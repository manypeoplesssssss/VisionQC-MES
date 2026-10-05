"""
F07 치수 규격 · 판정 테스트 (tests/test_specs.py)   담당 B

실행: backend 폴더에서  pytest tests/test_specs.py -v
"""
from tests.helpers import TODAY, dim


def test_filename_rule_and_spec_judgement(client, upload, admin):
    """파일명 규칙(시리얼의 - 는 _ 로) + 규격 기준 서버 재판정"""
    ok = upload(dim("SN-0001", 40.2, 90.1, 29.8, status="NG"))  # 규격 안 → 서버가 OK로 재판정
    assert ok["result"] == "OK"
    assert ok["dimension"]["reported_status"] == "NG"
    assert ok["image_filename"] == f"{TODAY}-Redcar-DIM3D-SN_0001.png"

    ng = upload(dim("SN0002", 41.0))  # 폭 공차 초과
    assert ng["result"] == "NG"


def test_no_spec_requires_status(upload):
    """규격이 없는 품목은 검사 PC 가 status 를 보내야 함"""
    upload(dim("SN0004", item="Bluecar"), expect=422)
    r = upload(dim("SN0004", item="Bluecar", status="OK"))
    assert r["result"] == "OK"
