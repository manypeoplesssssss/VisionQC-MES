"""
대시보드 집계 · 차트 테스트 (tests/test_dashboard.py)

실행: backend 폴더에서  pytest tests/test_dashboard.py -v
"""
from tests.helpers import SCRATCH


def test_dashboard(client, mes, viewer):
    """대시보드 집계 값: 정상 1, 불량 2(치수 1 + PatchCore 1), 대기 1"""
    mes.start("A")
    mes.dimension("A")
    mes.patchcore("A", 0.1)          # NORMAL
    mes.start("B")
    mes.dimension("B", 50)           # DIMENSION_DEFECT
    mes.start("C")
    mes.dimension("C")
    mes.patchcore("C", 0.9)
    mes.capture("C", 1, [SCRATCH])   # YOLO_PENDING (불량)
    mes.start("D")                   # DIMENSION_PENDING
    s = client.get("/api/dashboard/summary", headers=viewer).json()
    assert (s["total"], s["normal"], s["defect"], s["pending"]) == (4, 1, 2, 1)
    assert s["defect_rate"] == round(2 / 3 * 100, 2)
    assert s["by_final"]["YOLO_PENDING"] == 1 and s["by_final"]["PROCESS_DEFECT"] == 0
    assert s["defect_classes"] == [{"label": "scratch", "count": 1}]
    assert s["defect_codes"] == [{"label": "미분류", "count": 1}]
    assert {x["inspection_id"] for x in s["recent_defects"]} == {"B", "C"}
    assert s["by_product"][0]["product_name"] == "redcar"
    assert len(client.get("/api/dashboard/hourly", headers=viewer).json()) == 24
    assert len(client.get("/api/dashboard/daily", headers=viewer).json()) == 14
