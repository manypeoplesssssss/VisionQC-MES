"""
F04 사용자 관리 · 권한 테스트 (tests/test_users.py)   담당 A

실행: backend 폴더에서  pytest tests/test_users.py -v

test_operator_cannot_admin 은 여러 기능(F07 규격, F13 삭제)에 걸친 권한 테스트라
해당 기능이 다 만들어진 뒤에 통과한다.
"""
from tests.helpers import dim


def test_user_management(client, admin):
    """사용자 추가 → 사용 중지 → 로그인 불가, 관리자 본인은 중지 불가"""
    r = client.post("/api/users", headers=admin,
                    json={"username": "kim", "password": "pass1234", "name": "김", "role": "OPERATOR"})
    assert r.status_code == 201
    uid = r.json()["id"]
    assert client.patch(f"/api/users/{uid}", headers=admin, json={"is_active": False}).status_code == 200
    r = client.post("/api/auth/login", json={"username": "kim", "password": "pass1234"})
    assert r.status_code == 403
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"is_active": False}).status_code == 400


def test_operator_cannot_admin(client, upload, operator, admin):
    """작업자는 삭제/사용자/규격 수정 불가, 관리자는 가능. 삭제하면 이미지 파일도 사라짐"""
    r = upload(dim("DEL1"))
    assert client.delete(f"/api/inspections/{r['id']}", headers=operator).status_code == 403
    assert client.get("/api/users", headers=operator).status_code == 403
    spec = {"width_nominal": 1, "width_tol": 0.1, "length_nominal": 1, "length_tol": 0.1,
            "height_nominal": 1, "height_tol": 0.1}
    assert client.put("/api/specs/Newcar", headers=operator, json=spec).status_code == 403
    assert client.put("/api/specs/Newcar", headers=admin, json=spec).status_code == 200
    assert client.delete(f"/api/inspections/{r['id']}", headers=admin).status_code == 204
    assert client.get(r["image_url"]).status_code == 404  # 파일도 같이 삭제됨
