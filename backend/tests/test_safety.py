"""
장비 안전 (센터링 · 인터락) 테스트 (tests/test_safety.py)

실행: backend 폴더에서  pytest tests/test_safety.py -v
"""
from tests.conftest import KEY


def check(client, **body):
    r = client.post("/api/safety/check", headers=KEY, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_allowed_only_when_off_and_zero(client, mes):
    """센터링 OFF + 인터락 0 만 허용. 그 외는 알람 기록 (두 조건 모두 이상이면 각각)"""
    assert check(client, centering_state="OFF", interlock_state="0") == {"allowed": True, "alarms": []}
    r = check(client, centering_state="UNKNOWN", interlock_state="UNKNOWN")  # 미확인·센서 끊김도 금지
    assert r["allowed"] is False and {a["alarm_type"] for a in r["alarms"]} == {"CENTERING", "INTERLOCK"}
    assert all(a["inspection_id"] is None and a["inspection_stage"] == "PRECHECK" for a in r["alarms"])

    mes.start("S1")
    r = check(client, inspection_id="S1", stage="YOLO", centering_state="OFF", interlock_state="1")
    assert r["allowed"] is False and [a["alarm_type"] for a in r["alarms"]] == ["INTERLOCK"]
    # 같은 검사에서 같은 종류가 이미 발생 중이면 새 알람을 만들지 않음
    r = check(client, inspection_id="S1", stage="YOLO", centering_state="OFF", interlock_state="1")
    assert r["alarms"] == []


def test_states_recorded_on_inspection_and_dimension(client, mes, viewer):
    """검사 행·치수 행에 상태가 기록되고, 미확인 기본값은 UNKNOWN"""
    r = mes.start("S2")
    assert (r["centering_state"], r["interlock_state"]) == ("UNKNOWN", "UNKNOWN")
    r = mes.dimension("S2", centering_state="OFF", interlock_state="0")
    assert r["dimension"]["centering_state"] == "OFF" and r["dimension"]["interlock_state"] == "0"
    assert r["centering_state"] == "OFF" and r["alarms"] == []
    r = mes.dimension("S2")  # 상태를 안 보내면 미확인 → 알람 2개
    assert r["active_alarms"] == 2 and r["dimension"]["centering_state"] == "UNKNOWN"


def test_alarm_list_and_clear(client, mes, viewer, manager):
    """알람 조회, 해제는 관리자 또는 검사 PC 만. 검사를 지워도 알람 이력은 남음"""
    mes.start("S3")
    check(client, inspection_id="S3", stage="DIMENSION", centering_state="ON", interlock_state="0")
    page = client.get("/api/safety/alarms", headers=viewer, params={"status": "ACTIVE"}).json()
    assert page["total"] == 1
    aid = page["items"][0]["id"]
    assert client.post(f"/api/safety/alarms/{aid}/clear", headers=viewer).status_code == 403
    r = client.post(f"/api/safety/alarms/{aid}/clear", headers=manager).json()
    assert r["alarm_status"] == "CLEARED" and r["cleared_at"]
    assert client.get("/api/dashboard/summary", headers=viewer).json()["active_alarms"] == 0

    assert client.delete("/api/inspections/S3", headers=manager).status_code == 204
    left = client.get("/api/safety/alarms", headers=viewer).json()["items"]
    assert len(left) == 1 and left[0]["inspection_id"] is None
