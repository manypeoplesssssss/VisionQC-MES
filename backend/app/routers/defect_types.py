"""
불량 종류 API (routers/defect_types.py)

GET  /api/defect-types          전체 (로그인 사용자)
PUT  /api/defect-types/{code}   등록 또는 수정 (관리자) - 없으면 만들고 있으면 덮어씀

삭제 대신 is_active=False 로 '분류 사용 안 함' 처리한다 (이미 지정된 검사 기록을 보존).
원인 후보(cause_candidates)는 확정 원인이 아닌 '후보' 로 관리한다.
"""
from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminUser, DefectType
from ..schemas import DEFECT_CODE_PATTERN, DefectTypeIn, DefectTypeOut
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/defect-types", tags=["defect-types"])


@router.get("", response_model=list[DefectTypeOut])
def list_defect_types(db: Session = Depends(get_db), _user: AdminUser = Depends(get_current_user)):
    return db.query(DefectType).order_by(DefectType.defect_code).all()


@router.put("/{code}", response_model=DefectTypeOut)
def upsert_defect_type(body: DefectTypeIn, code: str = Path(pattern=DEFECT_CODE_PATTERN),
                       db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    t = db.get(DefectType, code)
    if t is None:
        t = DefectType(defect_code=code)
        db.add(t)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t
