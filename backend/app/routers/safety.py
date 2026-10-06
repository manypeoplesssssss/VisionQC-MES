"""
장비 안전 API - 센터링 · 인터락 (routers/safety.py)

POST /api/safety/check                 검사 프로그램이 확인한 상태 기록 → 허용 여부 (이상이면 알람 기록)
GET  /api/safety/alarms                알람 이력 (상태·종류·기간·검사번호 필터, 페이징)
POST /api/safety/alarms/{id}/clear     알람 해제 확인 (관리자 또는 검사 PC). 해제만으로 검사가 다시 시작되지는 않음

검사 허용: 센터링 OFF(정위치) AND 인터락 0(정상). ON / 1 / UNKNOWN(센서 응답 끊김 포함)이면 검사 금지.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminUser, AlarmStatus, AlarmType, EquipmentSafetyAlarm, ProductInspection
from ..schemas import AlarmOut, AlarmPage, SafetyCheckIn, SafetyCheckOut
from ..security import bearer, get_current_user, require_admin, require_ingest_auth
from ..services.query import date_range
from ..services.safety import record_safety

router = APIRouter(prefix="/api/safety", tags=["safety"])


@router.post("/check", response_model=SafetyCheckOut)
def check(body: SafetyCheckIn, db: Session = Depends(get_db), _who: str = Depends(require_ingest_auth)):
    insp = None
    if body.inspection_id:
        insp = db.scalar(select(ProductInspection).where(ProductInspection.inspection_id == body.inspection_id))
        if insp is None and body.product_name:  # 검사 행이 아직 없으면 만든다 (단계 API 와 같은 방식)
            insp = ProductInspection(inspection_id=body.inspection_id, product_name=body.product_name,
                                     yolo_defect_data=[], image_files=[])
            db.add(insp)
            db.flush()
    allowed, alarms = record_safety(db, insp, body.stage, body.centering_state, body.interlock_state, body.message)
    db.commit()
    for a in alarms:
        db.refresh(a)
    return SafetyCheckOut(allowed=allowed, alarms=[AlarmOut.model_validate(a) for a in alarms])


@router.get("/alarms", response_model=AlarmPage)
def list_alarms(
    status: AlarmStatus | None = None,
    alarm_type: AlarmType | None = None,
    inspection_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    A = EquipmentSafetyAlarm
    q = select(A)
    if status:
        q = q.where(A.alarm_status == status)
    if alarm_type:
        q = q.where(A.alarm_type == alarm_type)
    if inspection_id:
        q = q.where(A.inspection_id == inspection_id)
    if date_from or date_to:
        start, end = date_range(date_from, date_to)
        q = q.where(A.occurred_at >= start, A.occurred_at < end)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(A.occurred_at.desc(), A.id.desc()).offset((page - 1) * size).limit(size)).all()
    return AlarmPage(total=total, page=page, size=size, items=[AlarmOut.model_validate(r) for r in rows])


def _clear_auth(x_api_key: str | None = Header(default=None),
                cred: HTTPAuthorizationCredentials | None = Depends(bearer),
                db: Session = Depends(get_db)) -> str:
    """해제는 검사 PC(API Key) 또는 관리자 이상만"""
    if x_api_key is not None:
        return require_ingest_auth(x_api_key, None, db)
    return require_admin(get_current_user(cred, db)).username


@router.post("/alarms/{alarm_id}/clear", response_model=AlarmOut)
def clear_alarm(alarm_id: int, db: Session = Depends(get_db), _who: str = Depends(_clear_auth)):
    alarm = db.get(EquipmentSafetyAlarm, alarm_id)
    if alarm is None:
        raise HTTPException(404, "알람을 찾을 수 없습니다")
    if alarm.alarm_status != AlarmStatus.CLEARED:
        alarm.alarm_status = AlarmStatus.CLEARED
        alarm.cleared_at = datetime.now().replace(microsecond=0)
        db.commit()
        db.refresh(alarm)
    return AlarmOut.model_validate(alarm)
