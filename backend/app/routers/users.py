"""
관리자 계정 관리 API - 최고관리자 전용 (routers/users.py)

GET   /api/users        계정 목록
POST  /api/users        계정 추가
PATCH /api/users/{id}   이름/이메일/권한/사용여부/리포트 수신/비밀번호 수정

계정 삭제 기능은 일부러 없다. 기록과의 연결을 유지하려고 '사용 중지(is_active=False)' 로 처리.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminUser, Role
from ..schemas import UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_super_admin

router = APIRouter(prefix="/api/users", tags=["users"])


def _check_email(db: Session, email: str | None, me_id: int | None = None):
    """이메일은 계정마다 고유"""
    if email and db.query(AdminUser).filter(AdminUser.email == email, AdminUser.id != me_id).first():
        raise HTTPException(409, "이미 사용 중인 이메일입니다")


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: AdminUser = Depends(require_super_admin)):
    return db.query(AdminUser).order_by(AdminUser.id).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db),
                _admin: AdminUser = Depends(require_super_admin)):
    if db.query(AdminUser).filter(AdminUser.username == body.username).first():
        raise HTTPException(409, "이미 있는 아이디입니다")
    _check_email(db, body.email)
    user = AdminUser(username=body.username, password_hash=hash_password(body.password),
                     name=body.name, email=body.email or None, role=body.role, is_active=True,
                     receive_defect_reports=body.receive_defect_reports)
    db.add(user)
    db.commit()
    db.refresh(user)  # DB 가 채운 id, created_at 을 다시 읽어옴
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                admin: AdminUser = Depends(require_super_admin)):
    user = db.get(AdminUser, user_id)
    if user is None:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    # 최고관리자가 실수로 자기 자신을 막아서 아무도 계정을 관리할 수 없는 상황 방지
    if user.id == admin.id and (body.is_active is False or (body.role and body.role != Role.SUPER_ADMIN)):
        raise HTTPException(400, "자기 자신의 최고관리자 권한/활성 상태는 바꿀 수 없습니다")
    # 보낸 값만 반영
    if body.name is not None:
        user.name = body.name
    if body.email is not None:
        _check_email(db, body.email, user.id)
        user.email = body.email or None  # 빈 문자열 → 이메일 삭제
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.receive_defect_reports is not None:
        user.receive_defect_reports = body.receive_defect_reports
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return user
