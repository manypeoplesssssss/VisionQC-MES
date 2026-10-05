"""
DB 테이블 정의 (models.py) - SQLAlchemy ORM   [기능 F01 · 담당 A]

파이썬 클래스 1개 = DB 테이블 1개. 서버가 처음 뜰 때 main.py 의
`Base.metadata.create_all()` 이 여기 정의된 테이블 중 없는 것을 자동으로 만든다.

테이블 구조
  users              로그인 계정 (ADMIN / OPERATOR)
  item_specs         품목별 치수 규격 (기준값 ± 공차) → 서버에서 OK/NG 판정
  inspections        검사 1건 = 이미지 1장 (시계열 기준 테이블)
                     - serial_no 로 제품 1개가 3개 공정을 거친 이력을 추적
                     - image_filename = yyyy-mm-dd-품목-공정-시리얼.확장자
  dimension_results  3D 모델링 치수검사 결과 (inspection 1 : 1)
  defect_results     PatchCore / YOLO 결함 결과 (inspection 1 : N, 박스마다 1행)

관계 그림
  inspections ─┬─ 1:1 ─ dimension_results   (DIM3D 공정일 때만)
               └─ 1:N ─ defect_results      (PATCHCORE / YOLO 공정일 때)
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index,
                        Integer, String, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ---------------------------------------------------------------------------
# 코드값 (Enum). DB 에는 MySQL ENUM 컬럼으로 저장된다
# str 을 같이 상속해서 JSON 으로 내보낼 때 "DIM3D" 같은 문자열 그대로 나간다
# ---------------------------------------------------------------------------
class Process(str, enum.Enum):
    """검사 공정"""
    DIM3D = "DIM3D"          # 3D 모델링 치수검사
    PATCHCORE = "PATCHCORE"  # 1차 PatchCore 이상탐지
    YOLO = "YOLO"            # 2차 YOLO 결함검사


# 라인에서 제품이 지나가는 공정 순서 (제품 추적 화면/집계에서 이 순서로 정렬)
PROCESS_ORDER = [Process.DIM3D, Process.PATCHCORE, Process.YOLO]


class Judge(str, enum.Enum):
    """판정 결과"""
    OK = "OK"
    NG = "NG"


class Role(str, enum.Enum):
    """사용자 권한"""
    ADMIN = "ADMIN"        # 사용자/규격 관리, 데이터 삭제
    OPERATOR = "OPERATOR"  # 조회


# ---------------------------------------------------------------------------
# 테이블
# Mapped[타입] = 컬럼 타입, Optional[...] 이면 NULL 허용
# ---------------------------------------------------------------------------
class User(Base):
    """로그인 계정"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # 로그인 아이디 (중복 불가)
    password_hash: Mapped[str] = mapped_column(String(100))   # bcrypt 해시 (비밀번호 원문은 저장하지 않음)
    name: Mapped[str] = mapped_column(String(50))              # 화면에 보이는 이름
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.OPERATOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # False 면 로그인 불가 (퇴사자 등)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ItemSpec(Base):
    """품목별 치수 규격. 측정값이 기준값 ± 공차 안에 있으면 OK"""
    __tablename__ = "item_specs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item: Mapped[str] = mapped_column(String(50), unique=True)  # 품목명 (Redcar ...) - 품목당 1행
    width_nominal: Mapped[float] = mapped_column(Float)         # 폭 기준값 (mm)
    width_tol: Mapped[float] = mapped_column(Float)             # 폭 공차 ± (mm)
    length_nominal: Mapped[float] = mapped_column(Float)
    length_tol: Mapped[float] = mapped_column(Float)
    height_nominal: Mapped[float] = mapped_column(Float)
    height_tol: Mapped[float] = mapped_column(Float)
    # 수정할 때마다 자동으로 현재 시각으로 갱신
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Inspection(Base):
    """검사 1건 (이미지 1장). 모든 조회·집계의 기준이 되는 테이블"""
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_no: Mapped[str] = mapped_column(String(50), index=True)      # 제품 개체 ID (공정 간 추적 키)
    item: Mapped[str] = mapped_column(String(50))                       # Redcar, Bluecar ...
    process: Mapped[Process] = mapped_column(Enum(Process))
    inspected_at: Mapped[datetime] = mapped_column(DateTime)            # 시계열 기준 시각 (서버 로컬 시각)
    result: Mapped[Judge] = mapped_column(Enum(Judge))                  # 종합 판정
    model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 사용한 AI 모델 버전
    image_filename: Mapped[str] = mapped_column(String(255), unique=True)  # 파일명 (중복 불가 → 파일과 1:1)
    image_path: Mapped[str] = mapped_column(String(500))                # STORAGE_DIR 기준 상대경로
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())  # DB 에 들어온 시각

    # 연관 데이터. lazy="selectin" : 검사 여러 건을 불러올 때 치수/결함을 쿼리 1번으로 한꺼번에 가져온다
    # cascade="all, delete-orphan" : 검사를 지우면 딸린 치수/결함 행도 같이 지워진다
    dimension: Mapped[Optional["DimensionResult"]] = relationship(
        back_populates="inspection", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    defects: Mapped[list["DefectResult"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan", lazy="selectin")

    # 조회가 많은 조건 조합에 인덱스 (기간 조회가 기본이라 inspected_at 을 뒤에 붙임)
    __table_args__ = (
        Index("ix_insp_time", "inspected_at"),
        Index("ix_insp_process_time", "process", "inspected_at"),
        Index("ix_insp_item_time", "item", "inspected_at"),
        Index("ix_insp_result_time", "result", "inspected_at"),
    )


class DimensionResult(Base):
    """3D 모델링 치수검사 결과 (검사 1건당 1행)"""
    __tablename__ = "dimension_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), unique=True)  # unique → 검사 1건에 1행만
    width_mm: Mapped[float] = mapped_column(Float)
    length_mm: Mapped[float] = mapped_column(Float)
    height_mm: Mapped[float] = mapped_column(Float)
    status: Mapped[Judge] = mapped_column(Enum(Judge))                   # 최종 판정 (규격 있으면 서버 판정)
    reported_status: Mapped[Optional[Judge]] = mapped_column(Enum(Judge), nullable=True)  # 검사 PC가 보낸 판정

    inspection: Mapped[Inspection] = relationship(back_populates="dimension")


class DefectResult(Base):
    """PatchCore / YOLO 결함 결과. 결함 박스 1개당 1행, 결함이 없으면 defect_detected=False 1행"""
    __tablename__ = "defect_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), index=True)
    defect_detected: Mapped[bool] = mapped_column(Boolean)
    type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # scratch, dent ...
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0 ~ 1
    box: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)        # [x1, y1, x2, y2] px (원본 이미지 기준)

    inspection: Mapped[Inspection] = relationship(back_populates="defects")
