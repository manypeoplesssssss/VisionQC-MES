"""
검사 결과 등록 · 자동 판정 테스트 (tests/test_ingest.py)

실행: backend 폴더에서  pytest tests/test_ingest.py -v
"""
import re

from tests.conftest import KEY
from tests.helpers import SCRATCH, WHITE_PAINT


def test_full_flow_normal(mes):
    """치수 합격 → PatchCore 합격 → 최종 NORMAL"""
    r = mes.start("I1", serial="RC-0001", capture_folder="captures/x")
    assert r["final_result"] == "DIMENSION_PENDING" and r["yolo_status"] == "NOT_STARTED"
    r = mes.dimension("I1", 42.0, 88.5, 31.0)
    assert r["dimension_result"] == "PASS"
    assert r["dimension"]["standard_width_mm"] == 40  # 서버 설정(PRODUCT_STANDARDS)의 기준
    assert r["final_result"] == "PATCHCORE_PENDING"
    r = mes.patchcore("I1", 0.3)
    assert r["patchcore_result"] == "PASS" and r["final_result"] == "NORMAL"


def test_dimension_rules(mes):
    """±3mm 이내 합격(경계 포함), 초과 불합격, 누락 대기. 기준값은 보낸 값이 우선"""
    mes.start("D1")
    r = mes.dimension("D1", 43.0, 93.1, 33.1, standard_length_mm=90.1, standard_height_mm=30.1)
    d = r["dimension"]
    assert (d["width_result"], d["length_result"], d["height_result"]) == ("PASS", "PASS", "PASS")
    mes.start("D2")
    r = mes.dimension("D2", 43.1, 90.0, None)
    assert r["dimension"]["width_result"] == "FAIL" and r["dimension"]["height_result"] == "PENDING"
    assert r["dimension_result"] == "FAIL" and r["final_result"] == "DIMENSION_DEFECT"
    mes.start("D3")
    r = mes.dimension("D3", 40.0, 90.0, None)
    assert r["dimension_result"] == "PENDING" and r["final_result"] == "DIMENSION_PENDING"


def test_patchcore_fail_then_yolo(mes):
    """PatchCore 불합격 → YOLO 대기 → 사진 등록 → 완료하면 PROCESS_DEFECT"""
    mes.start("Y1")
    mes.dimension("Y1")
    r = mes.patchcore("Y1", 0.6)  # 점수 >= 기준 → 불합격
    assert r["patchcore_result"] == "FAIL" and r["final_result"] == "YOLO_PENDING"
    r = mes.capture("Y1", 1, [SCRATCH, WHITE_PAINT])
    assert r["yolo_status"] == "IN_PROGRESS" and r["defect_count"] == 2 and r["capture_count"] == 1
    img = r["images"][0]
    # 파일명: 일자-제품-시각-공정-검사번호_c사진번호
    assert re.fullmatch(r"\d{4}-\d\d-\d\d/\d{4}-\d\d-\d\d-redcar-\d{6}-YOLO-Y1_c001\.png", img["original_path"])
    assert img["annotated_path"].endswith("Y1_c001_annotated.png")
    assert img["metadata_path"].endswith(".json")
    r = mes.capture("Y1", 2, [SCRATCH], annotated=False)
    assert r["capture_count"] == 2 and r["images"][1]["annotated_path"] is None
    mes.capture("Y1", 2, [SCRATCH], expect=409)  # 같은 사진 번호 중복
    r = mes.complete("Y1")
    assert r["yolo_status"] == "COMPLETED" and r["final_result"] == "PROCESS_DEFECT"


def test_stage_creates_inspection_with_product_query(client):
    """검사 행이 없을 때 단계 API 는 product_name 쿼리가 있으면 만들고, 없으면 404"""
    r = client.put("/api/inspections/N1/patchcore", headers=KEY, json={"score": 0.1, "threshold": 0.5})
    assert r.status_code == 404
    r = client.put("/api/inspections/N1/patchcore?product_name=redcar", headers=KEY,
                   json={"score": 0.1, "threshold": 0.5})
    assert r.status_code == 200 and r.json()["final_result"] == "DIMENSION_PENDING"


def test_bad_key_and_bad_ids(client, mes):
    """API Key 가 틀리면 401, 경로 조작 가능한 검사번호는 거부"""
    mes.start("K1")
    mes.capture("K1", 1, key={"X-API-Key": "wrong"}, expect=401)
    r = client.put("/api/inspections/bad..id", headers=KEY, json={"product_name": "redcar"})
    assert r.status_code == 422
