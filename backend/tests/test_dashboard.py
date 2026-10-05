"""
F10 대시보드 집계 · F11 대시보드 차트 테스트 (tests/test_dashboard.py)   담당 C

실행: backend 폴더에서  pytest tests/test_dashboard.py -v
"""
from tests.helpers import dim, defect


def test_dashboard(client, upload, operator):
    """대시보드 집계 값"""
    upload(dim("D1"))
    upload(defect("D1", "PATCHCORE", [{"type": "crack", "confidence": 0.8}]))
    upload(dim("D2"))
    s = client.get("/api/dashboard/summary", headers=operator).json()
    assert s["products"] == 2 and s["ng"] == 1 and s["in_progress"] == 1
    assert s["defect_rate"] == 100.0
    assert s["defect_types"] == [{"type": "crack", "count": 1}]
    assert len(s["recent_ng"]) == 1
    assert len(client.get("/api/dashboard/hourly", headers=operator).json()) == 24
    assert len(client.get("/api/dashboard/daily", headers=operator).json()) == 14
