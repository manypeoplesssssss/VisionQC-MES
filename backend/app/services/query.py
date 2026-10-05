"""
검사 조회 공통 (services/query.py)   [기능 F12 · 담당 D]

여러 API(목록, CSV, 대시보드, 제품)가 같이 쓰는 기능
- date_range()    : 날짜 → [시작시각, 끝시각) 범위
- apply_filters() : 공정/품목/판정/시리얼/기간 조건을 쿼리에 붙이기
- to_out()        : DB 객체 → API 응답 형식 (이미지 서명 주소 포함)
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import Select

from ..models import Inspection, Judge, Process
from ..schemas import DefectOut, DimensionOut, InspectionOut
from ..storage import image_url

# 한 번에 조회할 수 있는 최대 기간 (너무 긴 기간 조회로 서버가 느려지는 것 방지)
MAX_RANGE_DAYS = 366


def day_start(d: date) -> datetime:
    """날짜 → 그날 00:00:00"""
    return datetime.combine(d, datetime.min.time())


def date_range(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    """
    [시작, 끝) 범위. 끝은 '종료일 다음날 00시' 라서 종료일 하루 전체가 포함된다.
    둘 다 없으면 오늘 하루, 하나만 있으면 그 하루.
    """
    date_from = date_from or date_to or date.today()
    date_to = date_to or date_from
    if date_to < date_from:
        raise HTTPException(400, "종료일이 시작일보다 빠릅니다")
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"조회 기간은 최대 {MAX_RANGE_DAYS}일입니다")
    return day_start(date_from), day_start(date_to + timedelta(days=1))


def apply_filters(q: Select, *, process: Process | None = None, item: str | None = None,
                  result: Judge | None = None, serial_no: str | None = None,
                  start: datetime | None = None, end: datetime | None = None) -> Select:
    """값이 있는 조건만 WHERE 절로 붙인다"""
    if process:
        q = q.where(Inspection.process == process)
    if item:
        q = q.where(Inspection.item == item)
    if result:
        q = q.where(Inspection.result == result)
    if serial_no:
        # 부분 검색 (LIKE '%값%'). autoescape → 검색어 안의 % _ 를 문자 그대로 취급
        q = q.where(Inspection.serial_no.contains(serial_no, autoescape=True))
    if start:
        q = q.where(Inspection.inspected_at >= start)
    if end:
        q = q.where(Inspection.inspected_at < end)
    return q


def to_out(insp: Inspection) -> InspectionOut:
    """DB 검사 객체 → 응답. image_path 대신 서명된 image_url 을 넣어준다"""
    return InspectionOut(
        id=insp.id,
        serial_no=insp.serial_no,
        item=insp.item,
        process=insp.process,
        inspected_at=insp.inspected_at,
        result=insp.result,
        model_version=insp.model_version,
        image_filename=insp.image_filename,
        image_url=image_url(insp.image_path),
        dimension=DimensionOut.model_validate(insp.dimension) if insp.dimension else None,
        defects=[DefectOut.model_validate(d) for d in insp.defects],
    )
