"""
F12 공정별 조회 · F13 이미지 보기 · F14 CSV 테스트 (tests/test_inspections.py)   담당 D

실행: backend 폴더에서  pytest tests/test_inspections.py -v
"""
from tests.helpers import TODAY, dim, defect


def test_list_filters_and_paging(client, upload, operator):
    """공정/판정/시리얼 필터와 페이지 크기"""
    for i in range(5):
        upload(dim(f"L{i}"))
    upload(defect("L0", "YOLO", [{"type": "dent", "confidence": 0.7}]))
    r = client.get("/api/inspections", headers=operator,
                   params={"process": "DIM3D", "date_from": TODAY, "size": 2})
    body = r.json()
    assert body["total"] == 5 and len(body["items"]) == 2
    r = client.get("/api/inspections", headers=operator, params={"result": "NG"})
    assert r.json()["total"] == 1
    r = client.get("/api/inspections", headers=operator, params={"serial_no": "L3"})
    assert r.json()["total"] == 1


def test_signed_image_url(client, upload, operator):
    """서명된 주소로만 이미지가 열리고, 서명을 바꾸거나 경로를 조작하면 막힘"""
    upload(dim("IMG1"))
    item = client.get("/api/inspections", headers=operator).json()["items"][0]
    assert client.get(item["image_url"]).status_code == 200
    tampered = item["image_url"].replace("sig=", "sig=0")
    assert client.get(tampered).status_code == 403
    assert client.get("/api/images/../../etc/passwd?exp=9999999999&sig=x").status_code in (403, 404)


def test_export_csv(client, upload, operator):
    """CSV 다운로드 (BOM 포함, 헤더와 데이터 확인)"""
    upload(dim("CSV1"))
    r = client.get("/api/inspections/export", headers=operator)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("id,inspected_at,serial_no")
    assert "CSV1" in text
