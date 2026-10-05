"""
메인 페이지(대시보드)용 API (routers/dashboard.py)   [기능 F10·F11 · 담당 C]

GET /api/dashboard/summary?date=YYYY-MM-DD      제품 수·양품·불량·불량률, 공정별/품목별, 불량 유형, 최근 불량
GET /api/dashboard/hourly?date=YYYY-MM-DD       시간대별 검사·불량 수 (하루)
GET /api/dashboard/daily?date_from=&date_to=    일별 제품·불량 수 (기간, 기본 최근 14일)

두 가지 단위를 섞어 쓰니 주의:
  - 제품 단위  : 제품 수, 양품/불량/진행중, 불량률, 품목별, 일별   (services/products.py 로 시리얼별 집계)
  - 검사 단위  : 공정별 건수, 시간대별, 불량 유형, 최근 불량        (inspections 행 그대로 셈)
"""
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DefectResult, Inspection, Judge, Process, User
from ..schemas import DashboardSummary, DefectTypeCount, ItemSummary, ProcessSummary, TrendPoint
from ..security import get_current_user
from ..services.products import aggregate_products, count_status, defect_rate
from ..services.query import date_range, to_out

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(
    d: date | None = Query(None, alias="date"),   # 쿼리스트링 이름은 date, 파이썬 변수는 d
    recent: int = Query(12, ge=1, le=50),          # 최근 불량 몇 건 보여줄지
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    d = d or date.today()
    start, end = date_range(d, d)
    in_day = (Inspection.inspected_at >= start) & (Inspection.inspected_at < end)  # 그날 조건 (재사용)

    # ---- 제품 단위 ----
    products = aggregate_products(db, start, end)
    c = count_status(products)

    # 품목별 상태 개수
    by_item_acc: dict[str, dict[str, int]] = defaultdict(lambda: {"OK": 0, "NG": 0, "IN_PROGRESS": 0})
    for p in products:
        by_item_acc[p.item][p.status] += 1
    by_item = [ItemSummary(item=k, products=sum(v.values()), ok=v["OK"], ng=v["NG"], in_progress=v["IN_PROGRESS"])
               for k, v in sorted(by_item_acc.items())]

    # ---- 검사(이미지) 단위 - 공정별 ----
    # SELECT process, COUNT(*), SUM(CASE WHEN result='NG' THEN 1 ELSE 0 END) ... GROUP BY process
    rows = db.execute(
        select(Inspection.process, func.count(),
               func.sum(case((Inspection.result == Judge.NG, 1), else_=0)))
        .where(in_day).group_by(Inspection.process)
    ).all()
    counted = {p: (t, int(ng or 0)) for p, t, ng in rows}
    # 검사가 0건인 공정도 0 으로 나오게 모든 공정을 돈다
    by_process = [ProcessSummary(process=p, total=counted.get(p, (0, 0))[0],
                                 ok=counted.get(p, (0, 0))[0] - counted.get(p, (0, 0))[1],
                                 ng=counted.get(p, (0, 0))[1]) for p in Process]

    # ---- 불량 유형 (PatchCore / YOLO) ----
    type_rows = db.execute(
        select(DefectResult.type, func.count())
        .join(Inspection, DefectResult.inspection_id == Inspection.id)
        .where(in_day, DefectResult.defect_detected.is_(True))
        .group_by(DefectResult.type)
    ).all()
    defect_types = sorted([DefectTypeCount(type=t or "unknown", count=n) for t, n in type_rows],
                          key=lambda x: x.count, reverse=True)  # 많은 순

    # ---- 최근 불량 ----
    recent_ng = db.scalars(
        select(Inspection).where(in_day, Inspection.result == Judge.NG)
        .order_by(Inspection.inspected_at.desc(), Inspection.id.desc()).limit(recent)
    ).all()

    return DashboardSummary(
        date=d.isoformat(),
        products=len(products), ok=c["OK"], ng=c["NG"], in_progress=c["IN_PROGRESS"],
        defect_rate=defect_rate(c),
        inspections=sum(x.total for x in by_process),
        by_process=by_process, by_item=by_item, defect_types=defect_types,
        recent_ng=[to_out(r) for r in recent_ng],
    )


@router.get("/hourly", response_model=list[TrendPoint])
def hourly(
    d: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """시간대별 검사 건수 / NG 건수 (00시~23시, 24칸)"""
    d = d or date.today()
    start, end = date_range(d, d)
    rows = db.execute(
        select(Inspection.inspected_at, Inspection.result)
        .where(Inspection.inspected_at >= start, Inspection.inspected_at < end)
    ).all()
    # 시(hour)별 [전체, NG] 칸을 만들어 놓고 채운다 (DB 마다 시간 추출 함수가 달라서 파이썬에서 계산)
    buckets = {h: [0, 0] for h in range(24)}
    for ts, res in rows:
        buckets[ts.hour][0] += 1
        if res == Judge.NG:
            buckets[ts.hour][1] += 1
    return [TrendPoint(label=f"{h:02d}", total=t, ng=n) for h, (t, n) in buckets.items()]


@router.get("/daily", response_model=list[TrendPoint])
def daily(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """일별 '제품' 수와 NG 제품 수"""
    date_to = date_to or date.today()
    date_from = date_from or (date_to - timedelta(days=13))  # 기본 14일 (종료일 포함)
    start, end = date_range(date_from, date_to)
    products = aggregate_products(db, start, end)

    # 데이터가 없는 날도 0 으로 나오게 날짜 칸을 먼저 만든다
    days = {(date_from + timedelta(days=i)).isoformat(): [0, 0]
            for i in range((date_to - date_from).days + 1)}
    for p in products:
        k = p.first_at.date().isoformat()  # 제품은 '첫 검사한 날' 에 잡힌다
        if k in days:
            days[k][0] += 1
            if p.status == "NG":
                days[k][1] += 1
    return [TrendPoint(label=k, total=t, ng=n) for k, (t, n) in days.items()]
