"""로컬 테스트용 시계열 데이터 100개를 생성합니다."""
import requests
from datetime import date, timedelta

api = "http://localhost:8000"
existing = requests.get(api + "/api/data", timeout=5).json()
remaining = max(0, 100 - len(existing))
start = date.today() - timedelta(days=remaining - 1)
for i in range(remaining):
    response = requests.post(api + "/api/data", json={
        "date": (start + timedelta(days=i)).isoformat(),
        "value": 100 + (len(existing) + i) * 0.8,
        "memo": "샘플 판매량",
    }, timeout=5)
    response.raise_for_status()
    print(f"{len(existing) + i + 1}/100")
print(f"현재 데이터 {len(existing) + remaining}개")
