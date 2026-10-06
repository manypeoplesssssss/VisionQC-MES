"""
장비 안전 (센터링 · 인터락) 공통 로직 (services/safety.py)

검사 허용: 센터링 OFF(정위치) AND 인터락 0(정상). 그 외(ON, 1, UNKNOWN=미확인·센서 응답 끊김)는 검사 금지.
이상이면 조건마다 알람 1행 (두 조건 모두 이상이면 2행). 같은 검사·같은 단계에서 같은 종류·같은 상태의
'발생 중' 알람이 이미 있으면 새로 만들지 않는다 (검사 중 같은 상태를 여러 번 확인해도 알람이 쌓이지 않게).
DB 는 상태 기록용이다. 실제 장비 정지·재개는 검사 프로그램이 한다.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (AlarmStatus, AlarmType, CenteringState, EquipmentSafetyAlarm, InterlockState,
                      ProductInspection, safety_allowed)

_KO_CENTERING = {"OFF": "정위치", "ON": "위치 이상", "UNKNOWN": "미확인"}
_KO_INTERLOCK = {"0": "정상", "1": "비정상", "UNKNOWN": "미확인"}
_KO_STAGE = {"PRECHECK": "사전 확인", "DIMENSION": "3D 치수", "PATCHCORE": "PatchCore", "YOLO": "YOLO"}


def _v(x) -> str:
    return getattr(x, "value", x)


def record_safety(db: Session, insp: ProductInspection | None, stage, centering, interlock,
                  message: str | None = None) -> tuple[bool, list[EquipmentSafetyAlarm]]:
    """상태를 검사 행에 기록하고, 이상이면 알람을 만든다. (허용 여부, 새 알람 목록). commit 은 호출한 쪽에서"""
    c, i, st = _v(centering), _v(interlock), _v(stage)
    if insp is not None:
        insp.centering_state, insp.interlock_state = c, i
    allowed = safety_allowed(c, i)
    if allowed:
        return True, []

    problems = []
    if c != CenteringState.OFF.value:
        problems.append((AlarmType.CENTERING, f"센터링 {_KO_CENTERING.get(c, c)}"))
    if i != InterlockState.NORMAL.value:
        problems.append((AlarmType.INTERLOCK, f"인터락 {_KO_INTERLOCK.get(i, i)}"))

    active = set()
    if insp is not None:
        A = EquipmentSafetyAlarm
        rows = db.execute(select(A.alarm_type, A.inspection_stage, A.centering_state, A.interlock_state).where(
            A.inspection_id == insp.inspection_id, A.alarm_status == AlarmStatus.ACTIVE)).all()
        active = {tuple(_v(x) for x in r) for r in rows}

    created = []
    for kind, what in problems:
        if (kind.value, st, c, i) in active:
            continue
        text = f"[{_KO_STAGE.get(st, st)}] {what} → 검사 중단·보류"
        if message:
            text += f" ({message})"
        alarm = EquipmentSafetyAlarm(
            inspection_id=insp.inspection_id if insp is not None else None, alarm_type=kind,
            alarm_status=AlarmStatus.ACTIVE, centering_state=c, interlock_state=i,
            inspection_stage=st, alarm_message=text)
        db.add(alarm)
        created.append(alarm)
    db.flush()
    return False, created
