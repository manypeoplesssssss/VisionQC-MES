"""
DB 테이블 정의 (models.py) - SQLAlchemy ORM

파이썬 클래스 1개 = DB 테이블 1개. 서버가 처음 뜰 때 main.py 의
`Base.metadata.create_all()` 이 여기 정의된 테이블 중 없는 것을 자동으로 만든다.
(MySQL 에 직접 만들 때 쓰는 SQL 은 backend/sql/schema.sql - 이 파일과 같은 구조)

테이블 5개 (검사 1회 단위)
  product_inspection            전체 검사. 제품 한 개의 검사 1회 = 한 행
                                3D 치수 → PatchCore → YOLO 단계별 결과를 한 행에 모으고
                                final_result 는 단계별 결과에서 DB 가 자동 계산
  product_dimension_inspection  3D 치수 (전체 검사 1회당 0~1행). 축별·종합 합불은 DB 가 자동 계산
  defect_type                   불량 종류 D01~D05 + 원인 후보 + 권장 조치
  admin_user                    관리자 계정 (SUPER_ADMIN / ADMIN / VIEWER) + 리포트 수신 설정
  equipment_safety_alarm        장비 안전 알람 (센터링 · 인터락) 발생 / 해제 이력
검사 테이블 2개에는 장비 상태 컬럼(centering_state, interlock_state, 미확인 기본값 UNKNOWN)이 있다.
검사 허용: 센터링 OFF(정위치) AND 인터락 0(정상). ON / 1 / UNKNOWN / 센서 응답 끊김이면 검사 금지

관계
  product_inspection.inspection_id ─ 1 : 0..1 ─ product_dimension_inspection.inspection_id  (실제 외래키)
  product_inspection.yolo_defect_data[*].defect_code ··· defect_type.defect_code          (JSON 안 논리 참조)
  product_inspection.inspection_id ─ 1 : 0..N ─ equipment_safety_alarm.inspection_id       (실제 외래키, 시작 전 알람은 NULL)
  admin_user ··· 검사 결과 조회 · 리포트 수신                                                (논리 참조)

[자동] 컬럼은 MySQL/SQLite 의 생성 컬럼(GENERATED ... STORED)이라 애플리케이션이 값을 넣지 않는다.
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, Computed, DateTime, Double, Enum, ForeignKey,
                        Index, Integer, String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# 3D 치수 판정 한계 (mm, 축별). inspection/station_3d/config.py 의 판정 기준과 같은 값
#   |편차| <= 재검 한계(RECHECK)      → PASS    정상
#   재검 한계 < |편차| <= 불량 한계   → RECHECK 재검 (다시 스캔해서 재판정)
#   |편차| > 불량 한계(TOLERANCE)    → FAIL    불합격
# 한계값은 정상 차 5회 스캔 표준편차의 2배(재검)·3배(불량). length = 3D 코드의 depth(전폭)
# 아래 SQL 식(생성 컬럼)에 숫자로 들어가므로, 바꾸면 sql/schema.sql 도 같이 바꾸고 기존 DB 는 컬럼 식을 다시 정의해야 한다
DIM_TOLERANCE_MM = {"width": 10.0, "length": 6.0, "height": 6.0}  # 불량 한계 (2026-10-07: 가로 ±10.0, 길이·높이 ±6.0)
DIM_RECHECK_MM = {"width": 10.0, "length": 6.0, "height": 6.0}    # 정상 한계 (불량 한계와 같아서 재검 구간은 없다. 구간을 다시 두려면 이 값을 줄일 것)
AXES = ("width", "length", "height")
# 소수점 계산 오차로 경계값(예: 33.1 - 30.1 = 3.0000000000000036)이 한 단계 나쁘게 나오는 것 방지
_EPS = 1e-6


# ---------------------------------------------------------------------------
# 코드값. str 을 같이 상속해서 JSON 으로 내보낼 때 "PASS" 같은 문자열 그대로 나간다
# ---------------------------------------------------------------------------
class StageResult(str, enum.Enum):
    """치수 · PatchCore 단계 판정"""
    PENDING = "PENDING"  # 대기 (아직 측정/검사 안 됨)
    PASS = "PASS"        # 합격
    RECHECK = "RECHECK"  # 재검 (치수만: 정상 한계는 넘고 불량 한계 안쪽 → 다시 스캔)
    FAIL = "FAIL"        # 불합격


class YoloStatus(str, enum.Enum):
    """YOLO 진행 상태"""
    NOT_STARTED = "NOT_STARTED"  # 아직 시작 안 함
    IN_PROGRESS = "IN_PROGRESS"  # 검사 중 (결함 사진이 들어오는 중)
    COMPLETED = "COMPLETED"      # 분류 완료


class FinalResult(str, enum.Enum):
    """최종 검사 결과 (DB 자동 계산)"""
    DIMENSION_PENDING = "DIMENSION_PENDING"  # 치수 검사 대기
    DIMENSION_DEFECT = "DIMENSION_DEFECT"    # 치수 불합격
    PATCHCORE_PENDING = "PATCHCORE_PENDING"  # 치수 합격 후 PatchCore 검사 대기
    NORMAL = "NORMAL"                        # 치수와 PatchCore 모두 합격
    YOLO_PENDING = "YOLO_PENDING"            # PatchCore 불합격 후 YOLO 분류 대기
    PROCESS_DEFECT = "PROCESS_DEFECT"        # PatchCore 불합격 후 YOLO 분류 완료


class Role(str, enum.Enum):
    """관리자 권한"""
    SUPER_ADMIN = "SUPER_ADMIN"  # 최고관리자: 계정 관리 + 아래 전부
    ADMIN = "ADMIN"              # 관리자: 불량 분류·불량 종류 수정·검사 삭제
    VIEWER = "VIEWER"            # 조회 전용


# ---- 장비 안전 상태 (센터링 · 인터락) ----
# 검사 허용 조건: 센터링 OFF(정위치) AND 인터락 0(정상). 그 외(ON, 1, UNKNOWN, 센서 응답 끊김)는 검사 금지
class CenteringState(str, enum.Enum):
    """센터링 상태"""
    OFF = "OFF"          # 정위치 (정상)
    ON = "ON"            # 위치 이상
    UNKNOWN = "UNKNOWN"  # 미확인 / 센서 응답 없음


class InterlockState(str, enum.Enum):
    """인터락 상태"""
    NORMAL = "0"         # 정상
    ABNORMAL = "1"       # 비정상
    UNKNOWN = "UNKNOWN"  # 미확인 / 센서 응답 없음


class AlarmType(str, enum.Enum):
    CENTERING = "CENTERING"  # 센터링 이상 (ON 또는 미확인)
    INTERLOCK = "INTERLOCK"  # 인터락 이상 (1 또는 미확인)


class AlarmStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"    # 발생 중
    CLEARED = "CLEARED"  # 해제됨 (해제만으로 검사가 자동 재시작되지는 않음)


class InspectionStage(str, enum.Enum):
    """알람이 난 검사 단계"""
    PRECHECK = "PRECHECK"    # 사전 확인 (검사 시작 전)
    DIMENSION = "DIMENSION"  # 3D 치수
    PATCHCORE = "PATCHCORE"
    YOLO = "YOLO"


def safety_allowed(centering, interlock) -> bool:
    """검사 허용 여부: 센터링 OFF 그리고 인터락 0 일 때만 (Enum 이든 문자열이든 받음)"""
    c, i = getattr(centering, "value", centering), getattr(interlock, "value", interlock)
    return c == CenteringState.OFF.value and i == InterlockState.NORMAL.value


def _check(name: str, column: str, enum_cls, nullable: bool = False) -> CheckConstraint:
    """허용값 CHECK 제약 (MySQL 8.0.16+ 에서 실제로 검사됨). 이름은 스키마 안에서 고유해야 한다"""
    values = ",".join(f"'{e.value}'" for e in enum_cls)
    cond = f"{column} IN ({values})"
    return CheckConstraint(f"{column} IS NULL OR {cond}" if nullable else cond, name=name)


# ---------------------------------------------------------------------------
# 자동 계산 SQL 식 (MySQL 8.0.16+ / SQLite 3.31+ 둘 다 되는 표준 CASE 문)
# ---------------------------------------------------------------------------
def _dev(axis: str) -> str:
    return f"ABS({axis}_mm - standard_{axis}_mm)"


def _missing(axis: str) -> str:
    return f"({axis}_mm IS NULL OR standard_{axis}_mm IS NULL)"


def _over(axis: str, limits: dict) -> str:
    """측정값이 있고 |편차| 가 한계를 넘음"""
    return f"(NOT {_missing(axis)} AND {_dev(axis)} > {limits[axis] + _EPS})"


def _axis_result_sql(axis: str) -> str:
    """축 1개: 실측이나 기준이 없으면 PENDING, 불량 한계 초과 FAIL, 재검 한계 초과 RECHECK, 나머지 PASS"""
    return (f"CASE WHEN {_missing(axis)} THEN 'PENDING' "
            f"WHEN {_dev(axis)} > {DIM_TOLERANCE_MM[axis] + _EPS} THEN 'FAIL' "
            f"WHEN {_dev(axis)} > {DIM_RECHECK_MM[axis] + _EPS} THEN 'RECHECK' "
            f"ELSE 'PASS' END")


# 종합: 하나라도 FAIL → FAIL, (FAIL 없이) 하나라도 누락 → PENDING, 하나라도 RECHECK → RECHECK, 나머지 PASS
_DIMENSION_RESULT_SQL = (
    "CASE WHEN " + " OR ".join(_over(a, DIM_TOLERANCE_MM) for a in AXES) + " THEN 'FAIL' "
    "WHEN " + " OR ".join(_missing(a) for a in AXES) + " THEN 'PENDING' "
    "WHEN " + " OR ".join(_over(a, DIM_RECHECK_MM) for a in AXES) + " THEN 'RECHECK' "
    "ELSE 'PASS' END"
)

# 최종 결과: 치수 → PatchCore → YOLO 순서로 내려가며 판단 (치수 재검은 다시 스캔할 때까지 '치수 검사 대기')
_FINAL_RESULT_SQL = (
    "CASE "
    "WHEN dimension_result IS NULL OR dimension_result IN ('PENDING', 'RECHECK') THEN 'DIMENSION_PENDING' "
    "WHEN dimension_result = 'FAIL' THEN 'DIMENSION_DEFECT' "
    "WHEN patchcore_result IS NULL OR patchcore_result = 'PENDING' THEN 'PATCHCORE_PENDING' "
    "WHEN patchcore_result = 'PASS' THEN 'NORMAL' "
    "WHEN yolo_status = 'COMPLETED' THEN 'PROCESS_DEFECT' "
    "ELSE 'YOLO_PENDING' END"
)


# ---------------------------------------------------------------------------
# 테이블
# Mapped[타입] = 컬럼 타입, Optional[...] 이면 NULL 허용
# ---------------------------------------------------------------------------
class ProductInspection(Base):
    """전체 검사. 제품 한 개의 검사 1회 = 한 행 (같은 제품을 재검사하면 새 inspection_id)"""
    __tablename__ = "product_inspection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)                 # 검사 행 식별번호
    inspection_id: Mapped[str] = mapped_column(String(64), unique=True)        # 검사 고유번호 (날짜 포함, 예: 20261006_inspection_143000_001)
    product_name: Mapped[str] = mapped_column(String(50))                      # 제품 모델명 (redcar)
    product_serial: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)  # 개별 제품 식별번호

    # ---- 장비 안전 상태 (마지막으로 확인한 값. 미확인 기본값 UNKNOWN)
    centering_state: Mapped[str] = mapped_column(
        Enum(CenteringState, native_enum=False, length=8), default=CenteringState.UNKNOWN)  # 센터링: OFF 정위치 / ON 위치 이상
    interlock_state: Mapped[str] = mapped_column(
        Enum(InterlockState, native_enum=False, length=8,
             values_callable=lambda e: [m.value for m in e]), default=InterlockState.UNKNOWN)  # 인터락: 0 정상 / 1 비정상

    # ---- 3D 치수 (치수 테이블 결과를 서버가 복사해 둠)
    dimension_result: Mapped[str] = mapped_column(
        Enum(StageResult, native_enum=False, length=16), default=StageResult.PENDING)  # 3D 치수 합불 판정
    dimension_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)        # 치수 상세 데이터 (JSON)
    scan_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 3D 스캔 파일 경로

    # ---- PatchCore
    patchcore_result: Mapped[str] = mapped_column(
        Enum(StageResult, native_enum=False, length=16), default=StageResult.PENDING)  # PatchCore 합불 판정
    patchcore_score: Mapped[Optional[float]] = mapped_column(Double, nullable=True)     # 이상 점수
    patchcore_threshold: Mapped[Optional[float]] = mapped_column(Double, nullable=True)  # 검사 당시 판정 기준
    patchcore_model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # ---- YOLO
    yolo_status: Mapped[str] = mapped_column(
        Enum(YoloStatus, native_enum=False, length=16), default=YoloStatus.NOT_STARTED)  # YOLO 검사 진행 상태
    # 불량별 검출 정보 배열. 원소: {capture_number, defect_class, confidence, box, angle_deg, defect_code}
    yolo_defect_data: Mapped[list] = mapped_column(JSON, default=list)
    yolo_model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # ---- 사진
    capture_folder: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 검사 PC 의 사진 폴더 경로
    # 이미지별 파일 경로 배열 (STORAGE_DIR 기준 상대경로)
    # 원소: {capture_number, original_path, annotated_path, metadata_path}
    image_files: Mapped[list] = mapped_column(JSON, default=list)

    # ---- 결과 · 리포트
    final_result: Mapped[str] = mapped_column(
        String(32), Computed(_FINAL_RESULT_SQL, persisted=True), index=True)        # [자동] 최종 검사 결과
    recommended_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # 원인 후보 및 권장 조치
    report_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)   # 생성한 리포트 파일 경로
    report_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 리포트 발송 성공 시각

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), index=True)  # 검사 행 생성 시각
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), onupdate=datetime.now)

    # 치수 행 (0~1개). lazy="selectin" : 목록 조회 시 한 번에 같이 불러옴
    dimension: Mapped[Optional["ProductDimensionInspection"]] = relationship(
        back_populates="inspection", uselist=False, cascade="all, delete-orphan", lazy="selectin")

    # 알람 이력 (0~N개). 검사를 지워도 알람 이력은 남긴다 (inspection_id 만 NULL 이 됨)
    alarms: Mapped[list["EquipmentSafetyAlarm"]] = relationship(
        back_populates="inspection", passive_deletes=True, order_by="EquipmentSafetyAlarm.occurred_at")

    __table_args__ = (
        Index("ix_pi_product_created", "product_name", "created_at"),
        _check("ck_pi_dimension_result", "dimension_result", StageResult),
        _check("ck_pi_patchcore_result", "patchcore_result", StageResult),
        _check("ck_pi_yolo_status", "yolo_status", YoloStatus),
        _check("ck_pi_centering_state", "centering_state", CenteringState),
        _check("ck_pi_interlock_state", "interlock_state", InterlockState),
    )


class ProductDimensionInspection(Base):
    """3D 치수 검사. 전체 검사 1회당 최대 1행. 기준 치수는 검사 당시 값으로 보관"""
    __tablename__ = "product_dimension_inspection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("product_inspection.inspection_id", ondelete="CASCADE", onupdate="CASCADE"),
        unique=True)                                                              # 전체 검사와 연결하는 검사번호
    # 치수 측정 시점의 장비 상태 (검사 프로그램이 같이 기록, 미확인 기본값 UNKNOWN)
    centering_state: Mapped[str] = mapped_column(
        Enum(CenteringState, native_enum=False, length=8), default=CenteringState.UNKNOWN)
    interlock_state: Mapped[str] = mapped_column(
        Enum(InterlockState, native_enum=False, length=8,
             values_callable=lambda e: [m.value for m in e]), default=InterlockState.UNKNOWN)
    width_mm: Mapped[Optional[float]] = mapped_column(Double, nullable=True)       # 실측 가로
    length_mm: Mapped[Optional[float]] = mapped_column(Double, nullable=True)      # 실측 길이
    height_mm: Mapped[Optional[float]] = mapped_column(Double, nullable=True)      # 실측 높이
    standard_width_mm: Mapped[Optional[float]] = mapped_column(Double, nullable=True)   # 기준 가로
    standard_length_mm: Mapped[Optional[float]] = mapped_column(Double, nullable=True)  # 기준 길이
    standard_height_mm: Mapped[Optional[float]] = mapped_column(Double, nullable=True)  # 기준 높이
    width_result: Mapped[str] = mapped_column(String(16), Computed(_axis_result_sql("width"), persisted=True))    # [자동]
    length_result: Mapped[str] = mapped_column(String(16), Computed(_axis_result_sql("length"), persisted=True))  # [자동]
    height_result: Mapped[str] = mapped_column(String(16), Computed(_axis_result_sql("height"), persisted=True))  # [자동]
    dimension_result: Mapped[str] = mapped_column(String(16), Computed(_DIMENSION_RESULT_SQL, persisted=True))   # [자동] 종합
    scan_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 3D 스캔 원본 경로
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), onupdate=datetime.now)

    inspection: Mapped[ProductInspection] = relationship(back_populates="dimension")

    __table_args__ = (
        _check("ck_pdi_centering_state", "centering_state", CenteringState),
        _check("ck_pdi_interlock_state", "interlock_state", InterlockState),
    )


class EquipmentSafetyAlarm(Base):
    """장비 안전 알람 (센터링 · 인터락) 발생 / 해제 이력.
    한 검사에 여러 알람 가능. 두 조건이 모두 이상이면 각각 1행씩 기록. 정지 후 이력을 저장하며,
    알람 해제만으로 검사가 자동으로 다시 시작되지는 않는다"""
    __tablename__ = "equipment_safety_alarm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)                      # 알람 식별번호
    inspection_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("product_inspection.inspection_id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True, index=True)                                                  # 관련 검사번호 (시작 전이면 NULL)
    alarm_type: Mapped[str] = mapped_column(Enum(AlarmType, native_enum=False, length=16))      # CENTERING / INTERLOCK
    alarm_status: Mapped[str] = mapped_column(
        Enum(AlarmStatus, native_enum=False, length=16), default=AlarmStatus.ACTIVE)           # ACTIVE 발생 중 / CLEARED 해제됨
    centering_state: Mapped[str] = mapped_column(Enum(CenteringState, native_enum=False, length=8))  # 알람 시점 센터링 상태
    interlock_state: Mapped[str] = mapped_column(
        Enum(InterlockState, native_enum=False, length=8, values_callable=lambda e: [m.value for m in e]))  # 알람 시점 인터락 상태
    inspection_stage: Mapped[str] = mapped_column(Enum(InspectionStage, native_enum=False, length=16))  # 사전 확인 / 치수 / PatchCore / YOLO
    alarm_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # 알람 상세 내용
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), index=True)  # 발생 시각
    cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 해제 확인 시각

    inspection: Mapped[Optional[ProductInspection]] = relationship(back_populates="alarms")

    __table_args__ = (
        Index("ix_alarm_status_time", "alarm_status", "occurred_at"),
        _check("ck_alarm_type", "alarm_type", AlarmType),
        _check("ck_alarm_status", "alarm_status", AlarmStatus),
        _check("ck_alarm_centering_state", "centering_state", CenteringState),
        _check("ck_alarm_interlock_state", "interlock_state", InterlockState),
        _check("ck_alarm_stage", "inspection_stage", InspectionStage),
    )


class DefectType(Base):
    """불량 종류 (D01~D05). 원인은 확정 원인이 아닌 '후보'로 관리"""
    __tablename__ = "defect_type"

    defect_code: Mapped[str] = mapped_column(String(10), primary_key=True)        # 불량 코드 (D01~D05)
    defect_name: Mapped[str] = mapped_column(String(100))                         # 불량 이름
    defect_category: Mapped[str] = mapped_column(String(50))                      # 도장 부족 / 스크래치
    defect_location: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 불량 발생 위치
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # 불량 상세 설명
    cause_candidates: Mapped[list] = mapped_column(JSON, default=list)            # 원인 후보 배열
    recommended_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 권장 점검 및 조치
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)                # 분류 사용 여부
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), onupdate=datetime.now)


class AdminUser(Base):
    """관리자 계정. 비밀번호는 평문으로 저장하지 않는다 (bcrypt 해시)"""
    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # 로그인 아이디
    password_hash: Mapped[str] = mapped_column(String(100))                     # 비밀번호 해시값
    name: Mapped[str] = mapped_column(String(50))                               # 관리자 이름
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)  # 이메일 및 리포트 수신 주소
    role: Mapped[str] = mapped_column(Enum(Role, native_enum=False, length=16), default=Role.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)              # 계정 활성 여부
    receive_defect_reports: Mapped[bool] = mapped_column(Boolean, default=False)  # 불량 리포트 수신 여부
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 마지막 로그인 성공 시각
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), onupdate=datetime.now)

    __table_args__ = (_check("ck_admin_role", "role", Role),)
