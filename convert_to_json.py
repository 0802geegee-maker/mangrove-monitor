"""
convert_to_json.py
지금까지 Python으로 뽑은 텍스트 결과를 JSON 캐시 파일로 변환합니다.
GEE 재실행 없이 대시보드에 바로 데이터를 올릴 수 있어요.

실행: python convert_to_json.py
"""

import json
from pathlib import Path

CACHE_DIR = Path("static/data")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── 여기에 기존 결과 데이터를 붙여넣으세요 ──────────────────
# 형식: (plot_id, plant_year, plant_month, area_ha, centroid_lon, centroid_lat, vi_data)
# vi_data: [{"period":"2022 Q2","ndvi":..,"evi":..,"ndwi":..}, ...]

RESULTS = [
    {
        "plot_id": "VNVPBKA23R01",
        "plant_year": "2023", "plant_month": "March",
        "area_ha": "0.98316318375",
        "centroid": [107.5, -2.5],   # ← 실제 좌표로 교체하세요
        "vi_data": [
            {"period":"2022 Q2","ndvi":-0.2069,"evi": 0.0397,"ndwi": 0.2717,"count":38},
            {"period":"2023 Q2","ndvi":-0.2015,"evi":-3.1751,"ndwi": 0.2609,"count":38},
            {"period":"2024 Q2","ndvi":-0.2104,"evi": 4.6743,"ndwi": 0.3232,"count":38},
            {"period":"2025 Q2","ndvi":-0.2255,"evi": 0.8166,"ndwi": 0.2779,"count":38},
            {"period":"2026 Q2","ndvi":-0.1301,"evi":-1.2527,"ndwi": 0.2626,"count":38},
        ],
        "status": "analyzed",
    },
    {
        "plot_id": "VNVPBKA23R05",
        "plant_year": "2023", "plant_month": "March",
        "area_ha": "2.15956915465",
        "centroid": [107.52, -2.51],
        "vi_data": [
            {"period":"2022 Q2","ndvi":-0.2766,"evi":-0.8872,"ndwi": 0.2463,"count":38},
            {"period":"2023 Q2","ndvi":-0.0833,"evi":-0.4783,"ndwi": 0.0934,"count":38},
            {"period":"2024 Q2","ndvi": 0.0802,"evi": 1.6718,"ndwi": 0.0178,"count":38},
            {"period":"2025 Q2","ndvi": 0.0822,"evi": 0.0907,"ndwi":-0.0753,"count":38},
            {"period":"2026 Q2","ndvi": 0.1441,"evi": 0.3293,"ndwi":-0.1529,"count":38},
        ],
        "status": "analyzed",
    },
    {
        "plot_id": "VNVPBKA23R06",
        "plant_year": "2023", "plant_month": "May",
        "area_ha": "3.86820678343",
        "centroid": [107.54, -2.52],
        "vi_data": [
            {"period":"2022 Q2","ndvi": 0.0489,"evi":-1.9381,"ndwi": 0.0102,"count":38},
            {"period":"2023 Q2","ndvi": 0.1290,"evi": 0.0611,"ndwi":-0.0456,"count":38},
            {"period":"2024 Q2","ndvi": 0.1930,"evi": 0.5856,"ndwi":-0.0864,"count":38},
            {"period":"2025 Q2","ndvi": 0.2448,"evi": 5.1092,"ndwi":-0.1842,"count":38},
            {"period":"2026 Q2","ndvi": 0.3137,"evi":-0.2300,"ndwi":-0.2437,"count":38},
        ],
        "status": "analyzed",
    },
    # ── 나머지 사업지도 동일한 형식으로 추가하세요 ──
    # {
    #     "plot_id": "VNVPBKA23R07",
    #     ...
    # },
]


def save_all():
    for site in RESULTS:
        pid  = site["plot_id"].replace("/", "_")
        path = CACHE_DIR / f"{pid}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(site, f, ensure_ascii=False, indent=2)
        print(f"  저장: {path}")
    print(f"\n완료: {len(RESULTS)}개 사업지 JSON 저장됨 → {CACHE_DIR}/")
    print("대시보드 실행: python app.py")


if __name__ == "__main__":
    save_all()
