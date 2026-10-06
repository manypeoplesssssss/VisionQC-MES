"""
관리자 계정 · 권한 테스트 (tests/test_users.py)

실행: backend 폴더에서  pytest tests/test_users.py -v
"""
from tests.helpers import SCRATCH


def test_user_management(client, admin):
    """계정 추가 → 사용 중지 → 로그인 불가, 최고관리자 본인은 중지 불가, 이메일 중복 불가"""
    r = client.post("/api/users", headers=admin,
                    json={"username": "kim", "password": "pass1234", "name": "김", "role": "VIEWER",
                          "email": "kim@example.com", "receive_defect_reports": True})
    assert r.status_code == 201
    assert r.json()["receive_defect_reports"] is True
    uid = r.json()["id"]
    dup = client.post("/api/users", headers=admin,
                      json={"username": "lee", "password": "pass1234", "name": "이", "email": "kim@example.com"})
    assert dup.status_code == 409
    assert client.patch(f"/api/users/{uid}", headers=admin, json={"is_active": False}).status_code == 200
    r = client.post("/api/auth/login", json={"username": "kim", "password": "pass1234"})
    assert r.status_code == 403
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"is_active": False}).status_code == 400


def test_role_permissions(client, mes, admin, manager, viewer):
    """조회 전용: 조회만 / 관리자: 불량 분류·삭제 / 최고관리자: 계정 관리까지"""
    mes.start("P1")
    mes.capture("P1", 1, [SCRATCH])
    assert client.get("/api/inspections/P1", headers=viewer).status_code == 200
    assert client.put("/api/inspections/P1/defects/0", headers=viewer, json={"defect_code": "D04"}).status_code == 403
    assert client.delete("/api/inspections/P1", headers=viewer).status_code == 403
    assert client.get("/api/users", headers=manager).status_code == 403
    assert client.get("/api/users", headers=admin).status_code == 200
    assert client.put("/api/inspections/P1/defects/0", headers=manager, json={"defect_code": "D04"}).status_code == 200

    images = client.get("/api/inspections/P1", headers=viewer).json()["images"]
    assert client.delete("/api/inspections/P1", headers=manager).status_code == 204
    assert client.get(images[0]["original_url"]).status_code == 404  # 사진 파일도 같이 삭제됨
