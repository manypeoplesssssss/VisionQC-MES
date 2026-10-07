"""
검사 조회 · 사진 · 불량 코드 · CSV 테스트 (tests/test_inspections.py)

실행: backend 폴더에서  pytest tests/test_inspections.py -v
"""
from tests.helpers import SCRATCH, TODAY


def test_list_filters_and_paging(client, mes, viewer):
    """최종결과·식별번호·기간 필터와 페이지 크기"""
    for i in range(4):
        mes.start(f"L{i}", serial=f"RC-{i}")
        mes.dimension(f"L{i}")
        mes.patchcore(f"L{i}", 0.1)
    mes.start("L9")
    mes.dimension("L9", 50)  # 치수 불합격
    body = client.get("/api/inspections", headers=viewer, params={"date_from": TODAY, "size": 2}).json()
    assert body["total"] == 5 and len(body["items"]) == 2
    assert client.get("/api/inspections", headers=viewer, params={"final_result": "NORMAL"}).json()["total"] == 4
    assert client.get("/api/inspections", headers=viewer, params={"final_result": "DEFECT"}).json()["total"] == 1
    assert client.get("/api/inspections", headers=viewer, params={"serial": "RC-3"}).json()["total"] == 1
    assert client.get("/api/products", headers=viewer).json() == ["redcar"]


def test_signed_image_url(client, mes, viewer):
    """서명된 주소로만 사진이 열리고, 서명을 바꾸거나 경로를 조작하면 막힘"""
    mes.start("IMG1")
    mes.capture("IMG1", 1, [SCRATCH])
    item = client.get("/api/inspections", headers=viewer).json()["items"][0]
    assert client.get(item["thumbnail_url"]).status_code == 200
    assert client.get(item["thumbnail_url"].replace("sig=", "sig=0")).status_code == 403
    assert client.get("/api/images/../../etc/passwd?exp=9999999999&sig=x").status_code in (403, 404)


def test_defect_code_and_recommended_action(client, mes, manager):
    """결함에 불량 코드를 지정하면 원인 후보·권장 조치가 채워지고, 해제하면 비워진다"""
    mes.start("C1")
    mes.capture("C1", 1, [SCRATCH, SCRATCH])
    r = client.put("/api/inspections/C1/defects/1", headers=manager, json={"defect_code": "D05"}).json()
    assert r["defects"][1]["defect_code"] == "D05" and r["defects"][1]["defect_name"]
    assert "D05" in r["recommended_action"] and "원인 후보" in r["recommended_action"]
    assert client.put("/api/inspections/C1/defects/5", headers=manager, json={"defect_code": "D05"}).status_code == 404
    assert client.put("/api/inspections/C1/defects/0", headers=manager, json={"defect_code": "D99"}).status_code == 400
    r = client.put("/api/inspections/C1/defects/1", headers=manager, json={"defect_code": None}).json()
    assert r["recommended_action"] is None


def test_defect_types(client, viewer, manager):
    """불량 종류 5개 조회, 관리자는 수정 가능"""
    types = client.get("/api/defect-types", headers=viewer).json()
    assert [t["defect_code"] for t in types] == ["D01", "D02", "D03", "D04", "D05"]
    body = {**{k: types[0][k] for k in ("defect_name", "defect_category", "cause_candidates")},
            "recommended_action": "노즐 청소", "is_active": False}
    assert client.put("/api/defect-types/D01", headers=viewer, json=body).status_code == 403
    r = client.put("/api/defect-types/D01", headers=manager, json=body).json()
    assert r["recommended_action"] == "노즐 청소" and r["is_active"] is False


def test_export_csv(client, mes, viewer):
    """CSV 다운로드 (BOM 포함, 헤더와 데이터 확인)"""
    mes.start("CSV1", serial="RC-CSV")
    mes.dimension("CSV1")
    r = client.get("/api/inspections/export", headers=viewer)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("inspection_id,created_at,product_name")
    assert "CSV1" in text and "PATCHCORE_PENDING" in text
