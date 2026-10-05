"""
사용자 관리 API - 관리자 전용 (routers/users.py)   [기능 F04 · 담당 A]

GET   /api/users        사용자 목록
POST  /api/users        사용자 추가
PATCH /api/users/{id}   이름/권한/사용여부/비밀번호 수정

사용자 삭제 기능은 일부러 없다. 검사 이력 등과의 연결을 유지하려고 '사용 중지(is_active=False)' 로 처리.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, User
from ..schemas import UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "이미 있는 아이디입니다")
    user = User(username=body.username, password_hash=hash_password(body.password),
                name=body.name, role=body.role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)  # DB 가 채운 id, created_at 을 다시 읽어옴
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다")
    # 관리자가 실수로 자기 자신을 막아서 아무도 관리자가 없는 상황 방지
    if user.id == admin.id and (body.is_active is False or (body.role and body.role != Role.ADMIN)):
        raise HTTPException(400, "자기 자신의 관리자 권한/활성 상태는 바꿀 수 없습니다")
    # 보낸 값만 반영
    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return user
