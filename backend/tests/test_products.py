"""
F09 제품 집계 로직 · 제품 API 테스트 (tests/test_products.py)   담당 C

실행: backend 폴더에서  pytest tests/test_products.py -v
"""
from tests.helpers import dim, defect


def test_product_status(client, upload, operator):
    """제품 상태: 3공정 OK=양품, 한 공정 NG=불량, 덜 끝남=진행중"""
    upload(dim("P_OK"))
    upload(defect("P_OK", "PATCHCORE"))
    upload(defect("P_OK", "YOLO"))
    upload(dim("P_NG", 45.0))
    upload(dim("P_WIP"))

    r = client.get("/api/products", headers=operator).json()
    status = {p["serial_no"]: p["status"] for p in r["items"]}
    assert status == {"P_OK": "OK", "P_NG": "NG", "P_WIP": "IN_PROGRESS"}

    r = client.get("/api/products", headers=operator, params={"status": "NG"}).json()
    assert [p["serial_no"] for p in r["items"]] == ["P_NG"]

    hist = client.get("/api/products/P_OK/history", headers=operator).json()
    assert [h["process"] for h in hist] == ["DIM3D", "PATCHCORE", "YOLO"]


def test_retest_uses_last_result(client, upload, operator):
    """재검사가 있으면 그 공정의 마지막 결과로 판단"""
    upload(dim("RT", 45.0))   # NG
    upload(dim("RT"))         # 재검사 OK
    upload(defect("RT", "PATCHCORE"))
    upload(defect("RT", "YOLO"))
    p = client.get("/api/products", headers=operator).json()["items"][0]
    assert p["status"] == "OK"
    assert p["steps"][0]["attempts"] == 2
