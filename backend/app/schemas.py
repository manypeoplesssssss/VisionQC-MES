"""
요청/응답 데이터 형식 (schemas.py) - Pydantic   [기능 F01 · 담당 A]

models.py 가 "DB 에 어떻게 저장하나" 라면, 이 파일은 "API 로 무엇을 주고받나" 를 정한다.
- ...In / ...Create / ...Update : 클라이언트 → 서버 (입력값 검증)
- ...Out                         : 서버 → 클라이언트 (응답 모양)
FastAPI 가 이 클래스들을 보고 자동으로 값 검증(틀리면 422 에러)과 /docs 문서를 만든다.

ConfigDict(from_attributes=True) : DB 객체(ORM)를 그대로 넣어도 속성을 읽어서 변환해준다.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Judge, Process, Role

# 파일명에 그대로 들어가는 값(품목)은 영문/숫자/_ 만 허용 → 경로 조작, 구분자('-') 섞임 방지
NAME_PATTERN = r"^[A-Za-z0-9_]{1,50}$"
# 시리얼은 '-' 도 허용 (파일명에 넣을 때 storage.py 에서 '_' 로 바꿈)
SERIAL_PATTERN = r"^[A-Za-z0-9_-]{1,50}$"


# =========================================================================
# 로그인 / 사용자
# =========================================================================
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str           # 이후 요청 헤더에 "Authorization: Bearer <토큰>" 으로 보냄
    token_type: str = "bearer"


class UserOut(BaseModel):
    """사용자 정보 응답 (password_hash 는 절대 내보내지 않는다)"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str
    role: Role
    is_active: bool


class UserCreate(BaseModel):
    """관리자가 사용자 추가할 때"""
    username: str = Field(pattern=r"^[A-Za-z0-9_.]{3,50}$")
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=50)
    role: Role = Role.OPERATOR


class UserUpdate(BaseModel):
    """관리자가 사용자 수정할 때. 보낸 값만 바뀐다 (None 이면 그대로)"""
    name: str | None = Field(default=None, min_length=1, max_length=50)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6)  # 비밀번호 초기화


class PasswordChange(BaseModel):
    """본인 비밀번호 변경"""
    current_password: str
    new_password: str = Field(min_length=6)


# =========================================================================
# 치수 규격
# =========================================================================
class SpecIn(BaseModel):
    """규격 등록/수정. 기준값은 0보다 커야 하고 공차는 0 이상"""
    width_nominal: float = Field(gt=0)
    width_tol: float = Field(ge=0)
    length_nominal: float = Field(gt=0)
    length_tol: float = Field(ge=0)
    height_nominal: float = Field(gt=0)
    height_tol: float = Field(ge=0)


class SpecOut(SpecIn):
    model_config = ConfigDict(from_attributes=True)
    item: str
    updated_at: datetime | None = None


# =========================================================================
# 검사 결과
# =========================================================================
class DimensionIn(BaseModel):
    """3D 치수검사 측정값 (검사 PC → 서버)"""
    width_mm: float
    length_mm: float
    height_mm: float
    status: Judge | None = None  # 검사 PC 판정. 서버에 규격이 있으면 서버가 다시 판정


class DimensionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    width_mm: float
    length_mm: float
    height_mm: float
    status: Judge                       # 최종 판정
    reported_status: Judge | None = None  # 검사 PC 가 보냈던 판정 (비교용)


class DefectIn(BaseModel):
    """결함 1건 (검사 PC → 서버). 결함이 없으면 defect_detected=false 만 보내면 된다"""
    defect_detected: bool
    type: str | None = Field(default=None, max_length=50)
    confidence: float | None = Field(default=None, ge=0, le=1)                 # 0 ~ 1
    box: list[float] | None = Field(default=None, min_length=4, max_length=4)  # [x1,y1,x2,y2]


class DefectOut(DefectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class InspectionPayload(BaseModel):
    """
    검사 결과 업로드 내용.
    업로드는 이미지 파일과 함께 보내야 해서 multipart/form-data 를 쓰고,
    이 내용은 그 안의 'payload' 필드에 JSON 문자열로 넣는다.
    """
    serial_no: str = Field(pattern=SERIAL_PATTERN)
    item: str = Field(pattern=NAME_PATTERN)
    process: Process
    inspected_at: datetime | None = None  # 없으면 서버 현재시각. 시간대(+09:00) 포함 가능
    model_version: str | None = Field(default=None, max_length=50)
    dimension: DimensionIn | None = None  # DIM3D 공정일 때만
    defects: list[DefectIn] = []          # PATCHCORE / YOLO 공정일 때

    @model_validator(mode="after")
    def check_by_process(self):
        """공정과 데이터 종류가 맞는지 확인 (DIM3D 인데 치수가 없으면 에러 등)"""
        if self.process == Process.DIM3D and self.dimension is None:
            raise ValueError("DIM3D 공정은 dimension 값이 필요합니다")
        if self.process != Process.DIM3D and self.dimension is not None:
            raise ValueError("dimension 은 DIM3D 공정에서만 보낼 수 있습니다")
        return self


class InspectionOut(BaseModel):
    """검사 1건 응답. image_url 은 서명이 붙은 이미지 주소 (그대로 <img src> 에 넣으면 됨)"""
    id: int
    serial_no: str
    item: str
    process: Process
    inspected_at: datetime
    result: Judge
    model_version: str | None = None
    image_filename: str
    image_url: str
    dimension: DimensionOut | None = None
    defects: list[DefectOut] = []


class InspectionPage(BaseModel):
    """목록 + 페이징 정보"""
    total: int  # 조건에 맞는 전체 건수
    page: int
    size: int
    items: list[InspectionOut]


# =========================================================================
# 제품(시리얼) 단위
# =========================================================================
# 제품 상태: 양품 / 불량 / 아직 공정 진행 중
ProductStatus = Literal["OK", "NG", "IN_PROGRESS"]


class ProductStep(BaseModel):
    """제품이 거친 공정 1개의 요약 (그 공정의 마지막 검사 기준)"""
    process: Process
    result: Judge
    inspection_id: int
    inspected_at: datetime
    attempts: int  # 같은 공정 검사 횟수 (재검사 포함)


class ProductOut(BaseModel):
    serial_no: str
    item: str
    first_at: datetime  # 첫 검사 시각
    last_at: datetime   # 마지막 검사 시각
    status: ProductStatus
    steps: list[ProductStep]  # 공정 순서대로


class ProductPage(BaseModel):
    total: int
    page: int
    size: int
    items: list[ProductOut]


# =========================================================================
# 대시보드
# =========================================================================
class ProcessSummary(BaseModel):
    """공정별 검사 건수 (검사=이미지 단위)"""
    process: Process
    total: int
    ok: int
    ng: int


class ItemSummary(BaseModel):
    """품목별 제품 수 (제품 단위)"""
    item: str
    products: int
    ok: int
    ng: int
    in_progress: int


class DefectTypeCount(BaseModel):
    type: str
    count: int


class DashboardSummary(BaseModel):
    date: str
    products: int            # 검사 들어온 제품 수
    ok: int                  # 3공정 모두 OK
    ng: int                  # 한 공정이라도 NG
    in_progress: int         # 아직 3공정을 다 안 거친 제품
    defect_rate: float       # 완료 제품 중 NG 비율(%)
    inspections: int         # 검사(이미지) 건수
    by_process: list[ProcessSummary]
    by_item: list[ItemSummary]
    defect_types: list[DefectTypeCount]
    recent_ng: list[InspectionOut]


class TrendPoint(BaseModel):
    """차트 막대 1개 (label: 시간 '09' 또는 날짜 '2026-10-05')"""
    label: str
    total: int
    ng: int
