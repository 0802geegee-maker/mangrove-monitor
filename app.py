"""
app.py  —  맹그로브 모니터링 Flask 서버 v2
실행: python app.py
접속: http://localhost:5000
"""

import os, ssl, json, urllib.request
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, render_template, request

# .env 파일 자동 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── 프록시 / SSL 완전 우회 (회사 방화벽 대응) ─────────────────
proxy = os.environ.get("HTTP_PROXY", "http://168.219.61.252:8080")
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"):
    os.environ[k] = proxy

# SSL 검증 비활성화 — urllib, requests 모두 적용
os.environ['PYTHONHTTPSVERIFY'] = '0'
os.environ['CURL_CA_BUNDLE']    = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''

ssl._create_default_https_context = ssl._create_unverified_context

# urllib 프록시 설정
proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
urllib.request.install_opener(urllib.request.build_opener(proxy_handler))

# requests 라이브러리 SSL 검증 강제 비활성화
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    import requests as _req
    _orig_send = _req.Session.send
    def _patched_send(self, *args, **kwargs):
        kwargs['verify'] = False
        return _orig_send(self, *args, **kwargs)
    _req.Session.send = _patched_send
    print("[SSL] requests SSL 검증 비활성화 완료")
except Exception as _e:
    print(f"[SSL] requests 패치 실패 (무시): {_e}")

# ── GEE 초기화 ────────────────────────────────────────────────
try:
    import ee
    ee.Initialize(project="alaskawildfire")
    GEE_AVAILABLE = True
    print("[GEE] 초기화 성공")
except Exception as e:
    GEE_AVAILABLE = False
    print(f"[GEE] 초기화 실패: {e}")

# ── Flask ─────────────────────────────────────────────────────
app = Flask(__name__)
CACHE_DIR = Path("static/data")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 분석 진행 상황 전역 상태
_progress = {"total": 0, "done": 0, "current": "", "running": False, "log": []}

# KML 경로: 환경변수 → data/ 폴더 자동탐색 → 하드코딩 경로 순서로 탐색
def _find_kml():
    # 1. 환경변수
    env_path = os.environ.get("KML_PATH","")
    if env_path and Path(env_path).exists():
        return env_path
    # 2. 프로젝트 data/ 폴더 내 kml 파일 자동탐색
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    kml_files = list(data_dir.glob("*.kml"))
    if kml_files:
        print(f"[KML] data/ 폴더에서 자동 발견: {kml_files[0].name}")
        return str(kml_files[0])
    # 3. 하드코딩 경로 (기존)
    fallback = r"D:\예지\1. 외부감축사업\1 . (자발적) 외부감축사업\1. 모니터링\나라스페이스\공유 및 견적 요청\[인니 2023년도 식재 33개 추출].kml"
    if Path(fallback).exists():
        return fallback
    print(f"[KML] ⚠ KML 파일을 찾을 수 없음. data/ 폴더에 .kml 파일을 넣거나 .env에 KML_PATH를 설정하세요.")
    return fallback

KML_PATH = _find_kml()
PLANET_API_KEY = os.environ.get("PLANET_API_KEY", "")

# ── 분기 날짜 헬퍼 ───────────────────────────────────────────
QUARTER_DATES = {
    1: ("01-01","03-31"), 2: ("04-01","06-30"),
    3: ("07-01","09-30"), 4: ("10-01","12-31"),
}
def quarter_range(year, q):
    s, e = QUARTER_DATES[q]
    return f"{year}-{s}", f"{year}-{e}"

def get_min_valid_ratio(area_ha):
    try:
        a = float(area_ha or 0)
        return 0.70 if a<=1 else 0.60 if a<=2 else 0.50
    except: return 0.50

# ── GEE 분석 ─────────────────────────────────────────────────
def mask_s2(image):
    import ee
    qa = image.select("QA60")
    mask = qa.bitwiseAnd(1<<10).eq(0).And(qa.bitwiseAnd(1<<11).eq(0))
    return image.updateMask(mask).select(
        ["B2","B3","B4","B8","B11"]).divide(10000)

def compute_ndvi_ndwi(img):
    import ee
    ndvi = img.normalizedDifference(["B8","B4"]).rename("NDVI")
    # McFeeters NDWI: (Green-NIR)/(Green+NIR) — 수체 감지
    ndwi = img.normalizedDifference(["B3","B8"]).rename("NDWI")
    return ndvi, ndwi

def analyze_period(polygon, area_ha, year, quarter, cloud_pct=30):
    import ee
    start, end = quarter_range(year, quarter)
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(polygon).filterDate(start, end)
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
           .map(mask_s2))
    count = col.size().getInfo()
    if count == 0:
        return {"year":year,"quarter":quarter,"count":0,"ndvi":None,"ndwi":None,"valid_ratio":None}

    img = col.median()
    ndvi, ndwi = compute_ndvi_ndwi(img)

    total_px = max(int(float(area_ha)*10000/100), 1)
    valid_px = ndvi.mask().reduceRegion(
        ee.Reducer.sum(), polygon, 10, maxPixels=1e9
    ).getInfo().get("NDVI", 0) or 0
    ratio = valid_px / total_px

    if ratio < get_min_valid_ratio(area_ha) or valid_px < 50:
        return {"year":year,"quarter":quarter,"count":count,
                "ndvi":None,"ndwi":None,"valid_ratio":round(ratio,3),"skipped":True}

    ndvi_v = ndvi.reduceRegion(ee.Reducer.median(), polygon, 10).getInfo().get("NDVI")
    ndwi_v = ndwi.reduceRegion(ee.Reducer.median(), polygon, 10).getInfo().get("NDWI")
    return {
        "year":year, "quarter":quarter, "count":count,
        "ndvi": round(ndvi_v,4) if ndvi_v is not None else None,
        "ndwi": round(ndwi_v,4) if ndwi_v is not None else None,
        "valid_ratio": round(ratio,3), "skipped":False,
    }

# ── KML 파싱 ─────────────────────────────────────────────────
def _int(v):
    try: return int(float(v)) if v else 0
    except: return 0

def parse_kml(kml_path):
    tree = ET.parse(kml_path)
    root = tree.getroot()
    ns = {"kml":"http://www.opengis.net/kml/2.2"}
    sites = []
    for pm in root.findall(".//kml:Placemark", ns):
        coords_text = pm.findtext(
            ".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates","",ns)
        if not coords_text: continue
        coords = []
        for c in coords_text.strip().split():
            p = c.split(",")
            if len(p)>=2:
                try: coords.append([float(p[0]),float(p[1])])
                except: pass
        if not coords: continue

        fields = {}
        for f in pm.findall(".//{http://www.opengis.net/kml/2.2}SimpleData"):
            fields[f.get("name","")] = f.text or ""

        lons=[c[0] for c in coords]; lats=[c[1] for c in coords]

        # 종별 식재량 파싱
        species_map = {
            "R.stylosa":      _int(fields.get("R_stylosa","0")),
            "R.apiculata":    _int(fields.get("R_apiculat","0")),
            "R.mucronata":    _int(fields.get("R_mucronat","0")),
            "A.officinalis":  _int(fields.get("A_officina","0")),
            "A.alba":         _int(fields.get("A_alba","0")),
            "A.marina":       _int(fields.get("A_marina","0")),
            "S.caseolaris":   _int(fields.get("S_caseolar","0")),
            "S.alba":         _int(fields.get("S_alba","0")),
            "B.gymnorrhiza":  _int(fields.get("B_gymnorrh","0")),
            "B.sexangula":    _int(fields.get("B_sexangul","0")),
            "C.tagal":        _int(fields.get("C_tagal","0")),
            "Nypa fruticans": _int(fields.get("Nypa_fruti","0")),
        }
        # 0그루 제거
        species_map = {k:v for k,v in species_map.items() if v > 0}

        sites.append({
            "plot_id":    fields.get("plot_id",""),
            "plant_year": fields.get("p_year",""),
            "plant_month":fields.get("p_month",""),
            "area_ha":    fields.get("Area_ha","0"),
            "n_tree":     _int(fields.get("N_tree","0")) or None,
            "n_species":  fields.get("n_species",""),
            "species_map":species_map,
            "zone":       fields.get("Zone",""),
            "province":   fields.get("Province",""),
            "district":   fields.get("District",""),
            "village":    fields.get("Village",""),
            "land_type":  fields.get("Land_type_",""),
            "n_person":   _int(fields.get("n_person","0")),
            "coords":     coords,
            "centroid":   [sum(lons)/len(lons), sum(lats)/len(lats)],
        })
    return sites

# ── 캐시 ─────────────────────────────────────────────────────
def cache_path(plot_id, year, quarter):
    safe = plot_id.replace("/","_")
    return CACHE_DIR / f"{safe}_{year}_Q{quarter}.json"

def load_cache(plot_id, year, quarter):
    p = cache_path(plot_id, year, quarter)
    if p.exists():
        with open(p, encoding="utf-8") as f: return json.load(f)
    return None

def save_cache(plot_id, year, quarter, data):
    with open(cache_path(plot_id, year, quarter),"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_vi_cache(plot_id):
    """사업지의 전체 분기 VI 데이터를 캐시에서 로드"""
    result = []
    for year in range(2022, 2027):
        for quarter in range(1, 5):
            p = cache_path(plot_id, year, quarter)
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    result.append(json.load(f))
    return result if result else None


def load_site_meta_cache():
    """KML 파싱 결과 캐시"""
    p = CACHE_DIR / "_sites_meta.json"
    if p.exists():
        with open(p, encoding="utf-8") as f: return json.load(f)
    return None

def save_site_meta_cache(sites):
    with open(CACHE_DIR/"_sites_meta.json","w",encoding="utf-8") as f:
        json.dump(sites, f, ensure_ascii=False, indent=2)

# ── Planet Labs ───────────────────────────────────────────────
def planet_search(coords, start_date, end_date, cloud_max=0.2):
    if not PLANET_API_KEY: return []
    import urllib.request, json as _json, base64
    geojson = {"type":"Polygon","coordinates":[coords]}
    payload = _json.dumps({
        "item_types":["PSScene"],
        "filter":{
            "type":"AndFilter","config":[
                {"type":"GeometryFilter","field_name":"geometry","config":geojson},
                {"type":"DateRangeFilter","field_name":"acquired","config":
                    {"gte":f"{start_date}T00:00:00Z","lte":f"{end_date}T23:59:59Z"}},
                {"type":"RangeFilter","field_name":"cloud_cover","config":{"lte":cloud_max}},
            ]
        }
    }).encode()
    token = base64.b64encode(f"{PLANET_API_KEY}:".encode()).decode()
    req = urllib.request.Request(
        "https://api.planet.com/data/v1/quick-search",
        data=payload,
        headers={"Content-Type":"application/json","Authorization":f"Basic {token}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = _json.loads(r.read())
        scenes = []
        for f in result.get("features",[])[:20]:
            p = f["properties"]
            scenes.append({
                "scene_id": f["id"],
                "acquired": p.get("acquired","")[:10],
                "cloud_cover": p.get("cloud_cover"),
                "resolution": p.get("pixel_resolution"),
                "thumbnail": f"https://api.planet.com/data/v1/item-types/PSScene/items/{f['id']}/thumb?api_key={PLANET_API_KEY}",
            })
        return sorted(scenes, key=lambda x: x.get("cloud_cover") or 1)
    except Exception as e:
        print(f"[Planet] 검색 실패: {e}")
        return []

# ── Flask 라우트 ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/sites")
def api_sites():
    """KML 파싱 결과 반환 — 항상 KML 재파싱, VI 캐시 병합"""
    try:
        sites = parse_kml(KML_PATH)
        save_site_meta_cache(sites)
    except Exception as e:
        print(f"[KML] 파싱 실패: {e}")
        sites = load_site_meta_cache() or []
        if not sites:
            return jsonify({"error": str(e), "sites": [], "total": 0})

    # VI 분석 캐시 병합
    for site in sites:
        vi = load_vi_cache(site["plot_id"])
        site["vi_data"] = vi
        site["status"]  = "analyzed" if vi else "pending"

    vi_count = sum(1 for s in sites if s["vi_data"])
    return jsonify({"sites": sites, "total": len(sites), "analyzed": vi_count})


@app.route("/api/cache/clear", methods=["POST"])
def api_cache_clear():
    """사이트 메타 캐시 삭제 (VI 결과는 유지)"""
    p = CACHE_DIR / "_sites_meta.json"
    if p.exists():
        p.unlink()
    return jsonify({"message": "캐시 삭제 완료"})

@app.route("/api/analyze")
def api_analyze():
    """단일 사업지 + 특정 연도/분기 분석"""
    plot_id = request.args.get("plot_id","")
    year    = int(request.args.get("year", 2024))
    quarter = int(request.args.get("quarter", 2))
    force   = request.args.get("force","false").lower()=="true"

    if not force:
        cached = load_cache(plot_id, year, quarter)
        if cached: return jsonify({"source":"cache","data":cached})

    if not GEE_AVAILABLE:
        return jsonify({"error":"GEE 연결 없음"}), 503

    sites = load_site_meta_cache() or parse_kml(KML_PATH)
    site  = next((s for s in sites if s["plot_id"]==plot_id), None)
    if not site: return jsonify({"error":f"{plot_id} 없음"}), 404

    import ee
    polygon = ee.Geometry.Polygon(site["coords"])
    result  = analyze_period(polygon, site["area_ha"], year, quarter)
    result.update({"plot_id":plot_id, "analyzed_at":datetime.now().isoformat()})
    save_cache(plot_id, year, quarter, result)
    return jsonify({"source":"gee","data":result})

@app.route("/api/analyze/batch", methods=["POST"])
def api_analyze_batch():
    """
    일괄 분석 모드:
    - all_years=true  → 2022~2026 Q2 전체 (기저값 포함 추이 분석용)
    - all_years=false → 선택된 연도/분기만
    """
    body      = request.get_json() or {}
    year      = int(body.get("year", 2026))
    quarter   = int(body.get("quarter", 2))
    all_years = body.get("all_years", False)

    # 분석할 연도/분기 목록 결정
    if all_years:
        # 2022~현재까지 Q2 전체 (기저값 포함)
        periods = [(y, 2) for y in range(2022, year + 1)]
        print(f"[배치] 전체 연도 모드: {[f'{y}Q2' for y,q in periods]}")
    else:
        periods = [(year, quarter)]

    import threading
    def run():
        global _progress
        sites = load_site_meta_cache() or parse_kml(KML_PATH)
        total = len(sites) * len(periods)
        done  = 0
        _progress = {"total": total, "done": 0, "current": "", "running": True, "log": []}

        for y, q in periods:
            for site in sites:
                pid = site["plot_id"]
                if load_cache(pid, y, q):
                    done += 1
                    _progress["done"] = done
                    continue
                try:
                    import ee
                    _progress["current"] = f"{pid} {y}Q{q}"
                    polygon = ee.Geometry.Polygon(site["coords"])
                    result  = analyze_period(polygon, site["area_ha"], y, q)
                    result.update({"plot_id": pid,
                                   "period": f"{y} Q{q}",
                                   "analyzed_at": datetime.now().isoformat()})
                    save_cache(pid, y, q, result)
                    done += 1
                    _progress["done"] = done
                    msg = f"✓ {pid} {y}Q{q} ({done}/{total})"
                    _progress["log"].append(msg)
                    if len(_progress["log"]) > 20:
                        _progress["log"] = _progress["log"][-20:]
                    print(f"[분석] {msg}")
                except Exception as e:
                    done += 1
                    _progress["done"] = done
                    _progress["log"].append(f"✗ {pid} {y}Q{q}: {str(e)[:40]}")
                    print(f"[분석] {pid} {y}Q{q} 실패: {e}")

        _progress["running"] = False
        _progress["current"] = "완료"
        print(f"[분석] 전체 완료 ({done}/{total})")

    threading.Thread(target=run, daemon=True).start()
    mode = f"2022~{year} Q2 전체" if all_years else f"{year} Q{quarter}"
    return jsonify({"message": f"{mode} 분석 시작 ({len(periods)}개 기간 × 33개 사업지)"})

@app.route("/api/results")
def api_results():
    """특정 연도/분기의 전체 캐시된 결과 반환"""
    year    = int(request.args.get("year", 2024))
    quarter = int(request.args.get("quarter", 2))
    sites   = load_site_meta_cache() or []
    results = []
    for site in sites:
        cached = load_cache(site["plot_id"], year, quarter)
        results.append({
            **site,
            "vi": cached,
            "analyzed": cached is not None,
        })
    return jsonify({"results":results,"year":year,"quarter":quarter})

@app.route("/api/planet/search")
def api_planet_search():
    """Planet 씬 검색"""
    plot_id = request.args.get("plot_id","")
    year    = int(request.args.get("year", 2024))
    quarter = int(request.args.get("quarter", 2))

    if not PLANET_API_KEY:
        return jsonify({"error":"PLANET_API_KEY 미설정","scenes":[]})

    sites = load_site_meta_cache() or []
    site  = next((s for s in sites if s["plot_id"]==plot_id), None)
    if not site: return jsonify({"error":"사업지 없음","scenes":[]})

    start, end = quarter_range(year, quarter)
    scenes = planet_search(site["coords"], start, end)
    return jsonify({"scenes":scenes,"count":len(scenes)})

@app.route("/api/progress")
def api_progress():
    """분석 진행 상황 반환"""
    return jsonify(_progress)

@app.route("/api/status")
def api_status():
    sites = load_site_meta_cache() or []
    cached_files = list(CACHE_DIR.glob("*.json"))
    vi_files = [f for f in cached_files if not f.name.startswith("_")]
    return jsonify({
        "gee_available":   GEE_AVAILABLE,
        "planet_available": bool(PLANET_API_KEY),
        "total_sites":     len(sites),
        "cached_analyses": len(vi_files),
    })

@app.route("/api/kml/<plot_id>")
def api_kml_geojson(plot_id):
    """사업지 폴리곤을 GeoJSON으로 반환 (Leaflet용)"""
    sites = load_site_meta_cache() or []
    site  = next((s for s in sites if s["plot_id"]==plot_id), None)
    if not site: return jsonify({"error":"없음"}), 404
    geojson = {
        "type":"FeatureCollection",
        "features":[{
            "type":"Feature",
            "geometry":{"type":"Polygon","coordinates":[site["coords"]]},
            "properties":{"plot_id":plot_id,"area_ha":site["area_ha"],
                          "plant_year":site["plant_year"],"plant_month":site["plant_month"]}
        }]
    }
    return jsonify(geojson)

# Vercel 서버리스 함수로 export
def handler(environ, start_response):
    from werkzeug.serving import WSGIRequestHandler
    return app(environ, start_response)

if __name__ == "__main__":
    import socket
    PORT = 5000
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8",80)); ip=s.getsockname()[0]; s.close(); return ip
        except: return "IP 감지 실패"
    local_ip = get_local_ip()
    print("\n"+"="*50)
    print("  🌿 맹그로브 모니터링 서버 v2")
    print("="*50)
    print(f"  내 PC:     http://localhost:{PORT}")
    print(f"  팀원 공유: http://{local_ip}:{PORT}")
    print("="*50+"\n")
    app.run(debug=True, host="0.0.0.0", port=PORT)
