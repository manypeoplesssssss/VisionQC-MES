"""
요청/응답 데이터 형식 (schemas.py) - Pydantic

models.py 가 "DB 에 어떻게 저장하나" 라면, 이 파일은 "API 로 무엇을 주고받나" 를 정한다.
- ...In / ...Create / ...Update : 클라이언트 → 서버 (입력값 검증)
- ...Out                         : 서버 → 클라이언트 (응답 모양)
FastAPI 가 이 클래스들을 보고 자동으로 값 검증(틀리면 422 에러)과 /docs 문서를 만든다.

ConfigDict(from_attributes=True) : DB 객체(ORM)를 그대로 넣어도 속성을 읽어서 변환해준다.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import (AlarmStatus, AlarmType, CenteringState, FinalResult, InspectionStage, InterlockState,
                     Role, StageResult, YoloStatus)

# 파일명·주소에 그대로 들어가는 값은 영문/숫자/_/- 만 허용 → 경로 조작 방지
NAME_PATTERN = r"^[A-Za-z0-9_]{1,50}$"
ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
DEFECT_CODE_PATTERN = r"^[A-Z][0-9]{2,8}$"


# =========================================================================
# 로그인 / 관리자 계정 (admin_user)
# =========================================================================
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str           # 이후 요청 헤더에 "Authorization: Bearer <토큰>" 으로 보냄
    token_type: str = "bearer"


class UserOut(BaseModel):
    """관리자 정보 응답 (password_hash 는 절대 내보내지 않는다)"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str
    email: str | None = None
    role: Role
    is_active: bool
    receive_defect_reports: bool
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    """최고관리자가 계정 추가할 때"""
    username: str = Field(pattern=r"^[A-Za-z0-9_.]{3,50}$")
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    role: Role = Role.VIEWER
    receive_defect_reports: bool = False


class UserUpdate(BaseModel):
    """최고관리자가 계정 수정할 때. 보낸 값만 바뀐다 (None 이면 그대로)"""
    name: str | None = Field(default=None, min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=255, pattern=r"^[^@\s]*@?[^@\s]*$")  # 빈 문자열이면 삭제
    role: Role | None = None
    is_active: bool | None = None
    receive_defect_reports: bool | None = None
    password: str | None = Field(default=None, min_length=6)  # 비밀번호 초기화


class PasswordChange(BaseModel):
    """본인 비밀번호 변경"""
    current_password: str
    new_password: str = Field(min_length=6)


# =========================================================================
# 검사 PC → 서버 (단계별 결과 등록)
# =========================================================================
class InspectionUpsert(BaseModel):
    """전체 검사 1회 시작(또는 기본 정보 수정). inspection_id 는 주소에 넣는다"""
    product_name: str = Field(pattern=NAME_PATTERN)
    product_serial: str | None = Field(default=None, pattern=ID_PATTERN)
    capture_folder: str | None = Field(default=None, max_length=500)
    started_at: datetime | None = None  # 검사 시작 시각 (없으면 서버 현재 시각). created_at 으로 저장


class DimensionIn(BaseModel):
    """3D 치수 측정값. 기준 치수를 안 보내면 서버 설정(PRODUCT_STANDARDS)의 값을 쓴다"""
    width_mm: float | None = None
    length_mm: float | None = None
    height_mm: float | None = None
    standard_width_mm: float | None = Field(default=None, gt=0)
    standard_length_mm: float | None = Field(default=None, gt=0)
    standard_height_mm: float | None = Field(default=None, gt=0)
    scan_file_path: str | None = Field(default=None, max_length=500)
    # 측정 시점 장비 상태 (검사 프로그램이 같이 기록). 안 보내면 미확인(UNKNOWN)
    centering_state: CenteringState = CenteringState.UNKNOWN
    interlock_state: InterlockState = InterlockState.UNKNOWN


class PatchCoreIn(BaseModel):
    """PatchCore 결과. 이상 점수가 기준 이상이면 불합격 (서버 판정)"""
    score: float
    threshold: float
    model_version: str | None = Field(default=None, max_length=50)


class YoloDefectIn(BaseModel):
    """YOLO 결함 1개"""
    defect_class: str = Field(max_length=50)                                    # scratch / white_paint ...
    confidence: float = Field(ge=0, le=1)
    box: list[float] | None = Field(default=None, min_length=4, max_length=4)  # [x1,y1,x2,y2] 원본 사진 픽셀


class YoloCaptureIn(BaseModel):
    """결함 사진 1장의 정보 (multipart 의 payload 필드에 JSON 문자열로)"""
    capture_number: int = Field(ge=1)
    angle_deg: float | None = None
    captured_at: datetime | None = None
    model_version: str | None = Field(default=None, max_length=50)
    defects: list[YoloDefectIn] = []


class YoloCompleteIn(BaseModel):
    model_version: str | None = Field(default=None, max_length=50)


class DefectCodeIn(BaseModel):
    """작업자/관리자가 결함 1개에 공정 불량 코드를 지정 (null 이면 지정 해제)"""
    defect_code: str | None = Field(default=None, pattern=DEFECT_CODE_PATTERN)


# =========================================================================
# 검사 조회 응답
# =========================================================================
class DimensionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    width_mm: float | None = None
    length_mm: float | None = None
    height_mm: float | None = None
    standard_width_mm: float | None = None
    standard_length_mm: float | None = None
    standard_height_mm: float | None = None
    width_result: StageResult
    length_result: StageResult
    height_result: StageResult
    dimension_result: StageResult
    scan_file_path: str | None = None
    centering_state: CenteringState
    interlock_state: InterlockState


class ImageFileOut(BaseModel):
    """사진 1장. *_url 은 서명이 붙은 이미지 주소 (그대로 <img src> 에 넣으면 됨)"""
    capture_number: int
    original_path: str
    annotated_path: str | None = None
    metadata_path: str | None = None
    original_url: str
    annotated_url: str | None = None


class YoloDefectOut(BaseModel):
    """yolo_defect_data 배열의 원소 1개 + 지정된 불량 종류 이름"""
    index: int                      # 배열 안 위치 (불량 코드 지정할 때 사용)
    capture_number: int
    defect_class: str
    confidence: float
    box: list[float] | None = None
    angle_deg: float | None = None
    defect_code: str | None = None
    defect_name: str | None = None


class InspectionSummaryOut(BaseModel):
    """검사 목록의 한 줄"""
    id: int
    inspection_id: str
    product_name: str
    product_serial: str | None = None
    dimension_result: StageResult
    patchcore_result: StageResult
    yolo_status: YoloStatus
    final_result: FinalResult
    centering_state: CenteringState   # 마지막으로 확인한 센터링 상태
    interlock_state: InterlockState   # 마지막으로 확인한 인터락 상태
    active_alarms: int = 0            # 해제 안 된 안전 알람 수
    defect_count: int                # YOLO 결함 개수
    defect_classes: list[str]        # 결함 종류 (중복 제거)
    capture_count: int               # 사진 장수
    thumbnail_url: str | None = None  # 첫 사진 (표시 사진 우선)
    created_at: datetime


class InspectionDetailOut(InspectionSummaryOut):
    """검사 상세"""
    dimension_data: dict | None = None
    scan_file_path: str | None = None
    patchcore_score: float | None = None
    patchcore_threshold: float | None = None
    patchcore_model_version: str | None = None
    yolo_model_version: str | None = None
    capture_folder: str | None = None
    recommended_action: str | None = None
    report_path: str | None = None
    report_sent_at: datetime | None = None
    updated_at: datetime | None = None
    dimension: DimensionOut | None = None
    defects: list[YoloDefectOut] = []
    images: list[ImageFileOut] = []
    alarms: list["AlarmOut"] = []     # 이 검사의 안전 알람 이력


class InspectionPage(BaseModel):
    """목록 + 페이징 정보"""
    total: int  # 조건에 맞는 전체 건수
    page: int
    size: int
    items: list[InspectionSummaryOut]


# =========================================================================
# 불량 종류 (defect_type)
# =========================================================================
class DefectTypeIn(BaseModel):
    defect_name: str = Field(min_length=1, max_length=100)
    defect_category: str = Field(min_length=1, max_length=50)
    defect_location: str | None = Field(default=None, max_length=100)
    description: str | None = None
    cause_candidates: list[str] = []
    recommended_action: str | None = None
    is_active: bool = True


class DefectTypeOut(DefectTypeIn):
    model_config = ConfigDict(from_attributes=True)
    defect_code: str
    updated_at: datetime | None = None


# =========================================================================
# 장비 안전 (센터링 · 인터락)
# =========================================================================
class SafetyCheckIn(BaseModel):
    """검사 프로그램이 확인한 장비 상태. 이상이면 서버가 알람을 기록하고 allowed=false 를 돌려준다.
    센서 응답이 끊겼으면 UNKNOWN 으로 보낸다 (검사 금지)"""
    inspection_id: str | None = Field(default=None, pattern=ID_PATTERN)  # 시작 전 확인이면 없어도 됨
    product_name: str | None = Field(default=None, pattern=NAME_PATTERN)  # 검사 행이 없을 때 만들기용
    stage: InspectionStage = InspectionStage.PRECHECK
    centering_state: CenteringState = CenteringState.UNKNOWN
    interlock_state: InterlockState = InterlockState.UNKNOWN
    message: str | None = Field(default=None, max_length=500)


class AlarmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inspection_id: str | None = None
    alarm_type: AlarmType
    alarm_status: AlarmStatus
    centering_state: CenteringState
    interlock_state: InterlockState
    inspection_stage: InspectionStage
    alarm_message: str | None = None
    occurred_at: datetime
    cleared_at: datetime | None = None


class SafetyCheckOut(BaseModel):
    allowed: bool                 # 검사 허용 (센터링 OFF AND 인터락 0)
    alarms: list[AlarmOut] = []   # 이번에 새로 기록한 알람 (같은 검사·같은 종류의 발생 중 알람이 있으면 새로 안 만듦)


class AlarmPage(BaseModel):
    total: int
    page: int
    size: int
    items: list[AlarmOut]


# =========================================================================
# 대시보드
# =========================================================================
class StageCount(BaseModel):
    """단계 1개의 상태별 건수 (예: 치수 PASS 30 / FAIL 2 / PENDING 1)"""
    stage: str          # DIMENSION / YOLO
    counts: dict[str, int]


class ProductSummary(BaseModel):
    """제품 모델별 건수"""
    product_name: str
    total: int
    normal: int
    defect: int
    pending: int


class LabelCount(BaseModel):
    label: str
    count: int


class DashboardSummary(BaseModel):
    date: str
    total: int                       # 그날 검사 수
    normal: int                      # NORMAL
    defect: int                      # 치수 불합격 + YOLO 결함
    pending: int                     # 치수 대기 + YOLO 대기
    defect_rate: float               # 판정 끝난 검사 중 불량 비율(%)
    by_final: dict[str, int]         # 최종 결과 6가지별 건수
    by_stage: list[StageCount]
    by_product: list[ProductSummary]
    defect_classes: list[LabelCount]  # YOLO 결함 종류별 개수
    defect_codes: list[LabelCount]    # 지정된 불량 코드별 개수 (D01~D05, 미분류)
    recent_defects: list[InspectionSummaryOut]
    active_alarms: int = 0                 # 지금 발생 중(해제 안 된) 안전 알람 수 (날짜와 무관)
    alarms_today: int = 0                  # 그날 발생한 안전 알람 수


class TrendPoint(BaseModel):
    """차트 막대 1개 (label: 시간 '09' 또는 날짜 '2026-10-05')"""
    label: str
    total: int
    defect: int


InspectionDetailOut.model_rebuild()
