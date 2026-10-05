"""
품목별 치수 규격 API (routers/specs.py)   [기능 F07 · 담당 B]

GET    /api/specs          전체 규격 (로그인 사용자)
PUT    /api/specs/{item}   규격 등록 또는 수정 (관리자) - 없으면 만들고 있으면 덮어씀
DELETE /api/specs/{item}   규격 삭제 (관리자) - 이후 그 품목은 검사 PC 판정을 그대로 사용

규격을 바꿔도 이미 저장된 검사 결과는 다시 판정하지 않는다 (그 당시 기준으로 남김).
"""
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ItemSpec, User
from ..schemas import NAME_PATTERN, SpecIn, SpecOut
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/specs", tags=["specs"])


@router.get("", response_model=list[SpecOut])
def list_specs(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(ItemSpec).order_by(ItemSpec.item).all()


@router.put("/{item}", response_model=SpecOut)
def upsert_spec(body: SpecIn, item: str = Path(pattern=NAME_PATTERN),
                db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    spec = db.query(ItemSpec).filter(ItemSpec.item == item).first()
    if spec is None:
        spec = ItemSpec(item=item)
        db.add(spec)
    # 받은 6개 값(기준값·공차)을 그대로 덮어쓰기
    for k, v in body.model_dump().items():
        setattr(spec, k, v)
    db.commit()
    db.refresh(spec)
    return spec


@router.delete("/{item}", status_code=204)
def delete_spec(item: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    spec = db.query(ItemSpec).filter(ItemSpec.item == item).first()
    if spec is None:
        raise HTTPException(404, "규격이 없습니다")
    db.delete(spec)
    db.commit()
