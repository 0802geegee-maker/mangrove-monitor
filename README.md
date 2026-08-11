# 맹그로브 모니터링 대시보드 (Flask)

## 빠른 시작

### 1. 설치
```bash
pip install flask earthengine-api
```

### 2. GEE 없이 바로 실행하는 방법 (추천 첫 단계)

기존 Python 결과를 `convert_to_json.py`에 붙여넣고:
```bash
python convert_to_json.py   # JSON 캐시 생성
python app.py               # 서버 시작
```
브라우저에서 http://localhost:5000 접속

### 3. GEE 연동 실시간 분석

```bash
python app.py
# → 대시보드에서 "전체 분석 실행" 버튼 클릭
```

## API 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /` | 대시보드 메인 |
| `GET /api/sites` | 전체 사업지 목록 |
| `GET /api/analyze/<plot_id>` | 단일 사업지 분석 |
| `POST /api/analyze/all` | 전체 일괄 분석 (백그라운드) |
| `GET /api/status` | GEE 연결 상태 |
| `POST /api/load_json` | JSON 직접 업로드 |

## 파일 구조

```
mangrove-flask/
├── app.py                # Flask 서버 + GEE 호출
├── convert_to_json.py    # 기존 결과 → JSON 변환
├── requirements.txt
├── templates/
│   └── index.html        # 대시보드 UI
└── static/
    └── data/             # 분석 결과 JSON 캐시 (자동 생성)
```
