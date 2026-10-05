"""
판정 로직 (services/judge.py)   [기능 F07 · 담당 B]

OK/NG 판정 규칙은 반드시 여기 한 곳에서만 관리한다.
(API, 더미데이터 생성(seed.py) 이 모두 이 함수를 써서 규칙이 어긋나지 않게)

- DIM3D           : 품목 규격이 있으면 |측정값 - 기준값| <= 공차 로 서버 판정, 없으면 검사 PC 판정 사용
- PATCHCORE/YOLO  : 결함이 하나라도 있으면 NG
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import ItemSpec, Judge, Process
from ..schemas import DimensionIn, InspectionPayload

# 판정할 축 이름. DimensionIn 의 width_mm, ItemSpec 의 width_nominal / width_tol 처럼 이름을 맞춰둠
AXES = ("width", "length", "height")


def judge_dimension(dim: DimensionIn, spec: ItemSpec | None) -> Judge:
    """규격이 있으면 서버가 판정, 없으면 검사 PC가 보낸 status 사용"""
    if spec is not None:
        for axis in AXES:
            value = getattr(dim, f"{axis}_mm")
            nominal = getattr(spec, f"{axis}_nominal")
            tol = getattr(spec, f"{axis}_tol")
            # 1e-9 : 소수점 오차 때문에 딱 경계값(예: 40.5)이 NG 로 나오는 것 방지
            if abs(value - nominal) > tol + 1e-9:
                return Judge.NG
        return Judge.OK
    if dim.status is None:
        raise HTTPException(422, "이 품목은 서버에 규격이 없어서 dimension.status 를 같이 보내야 합니다")
    return dim.status


def judge_inspection(payload: InspectionPayload, db: Session) -> tuple[Judge, Judge | None]:
    """(종합 판정, 치수 판정) 반환. 치수 판정은 DIM3D 일 때만"""
    if payload.process == Process.DIM3D:
        spec = db.query(ItemSpec).filter(ItemSpec.item == payload.item).first()
        dim_status = judge_dimension(payload.dimension, spec)
        return dim_status, dim_status
    ng = any(d.defect_detected for d in payload.defects)
    return (Judge.NG if ng else Judge.OK), None
