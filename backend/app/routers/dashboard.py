"""
메인 페이지(대시보드)용 API (routers/dashboard.py)

GET /api/dashboard/summary?date=YYYY-MM-DD      그날 검사 수·정상·불량·대기·불량률, 최종 결과별, 단계별,
                                                 제품 모델별, YOLO 결함 종류, 불량 코드, 최근 불량
GET /api/dashboard/hourly?date=YYYY-MM-DD       시간대별 검사·불량 수 (하루)
GET /api/dashboard/daily?date_from=&date_to=    일별 검사·불량 수 (기간, 기본 최근 14일)
GET /api/dashboard/report?date=YYYY-MM-DD       일일 보고서: 일간·주간(7일)·월간(30일) 집계, 그날 불량 분석, AI 조치 요약

검사 1회 = product_inspection 1행. 시각은 created_at(검사 시작 시각) 기준.
불량 = 치수 불합격(DIMENSION_DEFECT) + PatchCore 불합격(YOLO_PENDING, PROCESS_DEFECT)
대기 = DIMENSION_PENDING + PATCHCORE_PENDING
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminUser, AlarmStatus, DefectType, EquipmentSafetyAlarm, FinalResult, ProductInspection
from ..schemas import (AiReportItem, DashboardSummary, DefectAnalysis, LabelCount, PeriodStat, ProductSummary,
                       ReportOut, StageCount, TrendPoint)
from ..security import get_current_user
from ..services.ai_report import assigned_codes
from ..services.query import DEFECT_RESULTS, PENDING_RESULTS, date_range, to_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _rows(db: Session, start, end) -> list[ProductInspection]:
    P = ProductInspection
    return db.scalars(select(P).where(P.created_at >= start, P.created_at < end)
                      .order_by(P.created_at.desc(), P.id.desc())).all()


def defect_rate(defect: int, normal: int) -> float:
    """불량률(%) = 불량 / (정상 + 불량). 대기 중인 검사는 아직 결과가 없으니 뺀다"""
    done = defect + normal
    return round(defect / done * 100, 2) if done else 0.0


def _v(x) -> str:
    return getattr(x, "value", x)


def _ai_items(rows: list[ProductInspection], limit: int = 5) -> list[AiReportItem]:
    """AI 조치 요약이 있는 검사 중 최근 것부터 (rows 는 최신순)"""
    return [AiReportItem(inspection_id=r.inspection_id, product_name=r.product_name,
                         defect_codes=assigned_codes(r), text=r.ai_report, created_at=r.created_at)
            for r in rows if r.ai_report][:limit]


@router.get("/summary", response_model=DashboardSummary)
def summary(
    d: date | None = Query(None, alias="date"),   # 쿼리스트링 이름은 date, 파이썬 변수는 d
    recent: int = Query(12, ge=1, le=50),          # 최근 불량 몇 건 보여줄지
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    d = d or date.today()
    start, end = date_range(d, d)
    rows = _rows(db, start, end)
    A = EquipmentSafetyAlarm
    active_alarms = db.scalar(select(func.count()).select_from(A).where(A.alarm_status == AlarmStatus.ACTIVE))
    alarms_today = db.scalar(select(func.count()).select_from(A).where(A.occurred_at >= start, A.occurred_at < end))

    by_final = {f.value: 0 for f in FinalResult}   # 0건인 결과도 나오게
    stages = {"DIMENSION": Counter(), "PATCHCORE": Counter(), "YOLO": Counter()}
    products: dict[str, Counter] = defaultdict(Counter)
    classes, codes = Counter(), Counter()
    for r in rows:
        by_final[r.final_result] += 1
        stages["DIMENSION"][_v(r.dimension_result)] += 1
        stages["PATCHCORE"][_v(r.patchcore_result)] += 1
        stages["YOLO"][_v(r.yolo_status)] += 1
        group = "defect" if r.final_result in DEFECT_RESULTS else "pending" if r.final_result in PENDING_RESULTS else "normal"
        products[r.product_name][group] += 1
        for x in r.yolo_defect_data or []:
            classes[x.get("defect_class") or "unknown"] += 1
            codes[x.get("defect_code") or "미분류"] += 1

    normal = by_final[FinalResult.NORMAL.value]
    defect = sum(by_final[k] for k in DEFECT_RESULTS)
    pending = sum(by_final[k] for k in PENDING_RESULTS)
    return DashboardSummary(
        date=d.isoformat(), total=len(rows), normal=normal, defect=defect, pending=pending,
        defect_rate=defect_rate(defect, normal),
        by_final=by_final,
        by_stage=[StageCount(stage=k, counts=dict(v)) for k, v in stages.items()],
        by_product=[ProductSummary(product_name=k, total=sum(v.values()), normal=v["normal"],
                                   defect=v["defect"], pending=v["pending"]) for k, v in sorted(products.items())],
        defect_classes=[LabelCount(label=k, count=n) for k, n in classes.most_common()],  # 많은 순
        defect_codes=[LabelCount(label=k, count=n) for k, n in sorted(codes.items())],
        recent_defects=[to_summary(r) for r in rows if r.final_result in DEFECT_RESULTS][:recent],
        active_alarms=active_alarms or 0, alarms_today=alarms_today or 0,
        daily_ai_reports=_ai_items(rows),
    )


@router.get("/hourly", response_model=list[TrendPoint])
def hourly(
    d: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    """시간대별 검사 수 / 불량 수 (00시~23시, 24칸)"""
    d = d or date.today()
    start, end = date_range(d, d)
    P = ProductInspection
    rows = db.execute(select(P.created_at, P.final_result)
                      .where(P.created_at >= start, P.created_at < end)).all()
    # 시(hour)별 [전체, 불량] 칸을 만들어 놓고 채운다 (DB 마다 시간 추출 함수가 달라서 파이썬에서 계산)
    buckets = {h: [0, 0] for h in range(24)}
    for ts, res in rows:
        buckets[ts.hour][0] += 1
        if res in DEFECT_RESULTS:
            buckets[ts.hour][1] += 1
    return [TrendPoint(label=f"{h:02d}", total=t, defect=n) for h, (t, n) in buckets.items()]


@router.get("/daily", response_model=list[TrendPoint])
def daily(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    """일별 검사 수와 불량 수"""
    date_to = date_to or date.today()
    date_from = date_from or (date_to - timedelta(days=13))  # 기본 14일 (종료일 포함)
    start, end = date_range(date_from, date_to)
    P = ProductInspection
    rows = db.execute(select(P.created_at, P.final_result)
                      .where(P.created_at >= start, P.created_at < end)).all()
    # 데이터가 없는 날도 0 으로 나오게 날짜 칸을 먼저 만든다
    days = {(date_from + timedelta(days=i)).isoformat(): [0, 0]
            for i in range((date_to - date_from).days + 1)}
    for ts, res in rows:
        k = ts.date().isoformat()
        if k in days:
            days[k][0] += 1
            if res in DEFECT_RESULTS:
                days[k][1] += 1
    return [TrendPoint(label=k, total=t, defect=n) for k, (t, n) in days.items()]


# -------------------------------------------------------------------------
# 일일 보고서 (일간 · 주간 7일 · 월간 30일 + 그날 불량 분석 + AI 조치 요약)
# -------------------------------------------------------------------------
def _period(db: Session, label: str, d_from: date, d_to: date) -> PeriodStat:
    """기간 안의 검사를 최종 결과별로 세어 정상·불량·판정 전·수율을 계산한다 (수율은 판정 끝난 검사 기준)"""
    P = ProductInspection
    start, end = date_range(d_from, d_to)
    counts = {_v(k): n for k, n in db.execute(
        select(P.final_result, func.count()).where(P.created_at >= start, P.created_at < end).group_by(P.final_result)).all()}
    normal = counts.get(FinalResult.NORMAL.value, 0)
    defect = sum(counts.get(k, 0) for k in DEFECT_RESULTS)
    pending = sum(counts.get(k, 0) for k in PENDING_RESULTS)
    done = normal + defect
    return PeriodStat(label=label, date_from=d_from.isoformat(), date_to=d_to.isoformat(),
                      total=sum(counts.values()), normal=normal, defect=defect, pending=pending,
                      yield_pct=round(normal / done * 100, 2) if done else 0.0, defect_rate=defect_rate(defect, normal))


def _defect_analysis(db: Session, rows: list[ProductInspection]) -> list[DefectAnalysis]:
    """그날 검출된 결함을 불량 코드별로 모은다. 원인 후보·권장 조치는 불량 종류 표(defect_type)에 적힌 내용 그대로"""
    groups: dict[str, dict] = {}
    for r in rows:
        for x in r.yolo_defect_data or []:
            g = groups.setdefault(x.get("defect_code") or "미분류", {"count": 0, "inspections": set(), "classes": set()})
            g["count"] += 1
            g["inspections"].add(r.inspection_id)
            if x.get("defect_class"):
                g["classes"].add(x["defect_class"])
    types = {t.defect_code: t for t in db.scalars(select(DefectType).where(DefectType.defect_code.in_(list(groups))))} if groups else {}
    out = []
    for code in sorted(groups, key=lambda c: (c == "미분류", c)):   # D01.. 순서, 미분류는 마지막
        g, t = groups[code], types.get(code)
        out.append(DefectAnalysis(defect_code=code, defect_name=t.defect_name if t else None, count=g["count"],
                                  inspections=len(g["inspections"]), classes=sorted(g["classes"]),
                                  cause_candidates=list(t.cause_candidates or []) if t else [],
                                  recommended_action=t.recommended_action if t else None))
    return out


@router.get("/report", response_model=ReportOut)
def report(
    d: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    d = d or date.today()
    start, end = date_range(d, d)
    rows = _rows(db, start, end)
    return ReportOut(
        date=d.isoformat(),
        daily=_period(db, "일간", d, d),
        weekly=_period(db, "주간 (7일)", d - timedelta(days=6), d),
        monthly=_period(db, "월간 (30일)", d - timedelta(days=29), d),
        defects=_defect_analysis(db, rows),
        ai_reports=_ai_items(rows),
    )
