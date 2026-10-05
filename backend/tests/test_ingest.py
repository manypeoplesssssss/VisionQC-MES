"""
F05 검사 결과 등록 API · F06 이미지 저장/파일명 테스트 (tests/test_ingest.py)   담당 B

실행: backend 폴더에서  pytest tests/test_ingest.py -v
"""
from tests.helpers import dim, defect


def test_ingest_wrong_key(client, upload):
    """API Key 가 틀리면 업로드 거부"""
    upload(dim("S1"), key="bad", expect=401)


def test_defect_judgement_and_validation(upload):
    """결함 있으면 NG, 공정과 데이터가 안 맞거나 확장자가 이상하면 거부"""
    assert upload(defect("SN0005", "PATCHCORE"))["result"] == "OK"
    r = upload(defect("SN0005", "YOLO", [{"type": "scratch", "confidence": 0.9, "box": [1, 2, 3, 4]}]))
    assert r["result"] == "NG"
    assert r["defects"][0]["box"] == [1, 2, 3, 4]
    upload({"serial_no": "SN0005", "item": "Redcar", "process": "YOLO",
            "dimension": {"width_mm": 1, "length_mm": 1, "height_mm": 1}}, expect=422)
    upload(defect("SN0005", "YOLO"), filename="x.gif", expect=400)


def test_timezone_aware_time_is_stored_local(upload):
    """시간대가 붙은 시각(+00:00)도 받아서 저장"""
    r = upload(dim("SN0006", at="2026-10-05T00:30:00+00:00"))
    assert r["image_filename"].startswith("2026-10-05") or r["image_filename"].startswith("2026-10-04")


def test_retest_gets_suffix(upload):
    """같은 제품·공정 재검사 → 파일명 뒤에 _r2 (덮어쓰기 없음)"""
    a = upload(dim("SN0003"))
    b = upload(dim("SN0003"))
    assert a["image_filename"] != b["image_filename"]
    assert b["image_filename"].endswith("_r2.png")
