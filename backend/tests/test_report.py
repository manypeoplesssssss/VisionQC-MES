"""
일일 보고서 · AI 조치 요약 테스트 (tests/test_report.py)

실행: backend 폴더에서  pytest tests/test_report.py -v
"""
import time

from datetime import date, timedelta

from app.services import ai_report
from tests.helpers import SCRATCH, TODAY, WHITE_PAINT


def _defect_inspection(mes, iid, defects=(SCRATCH,)):
    mes.start(iid)
    mes.dimension(iid)
    mes.patchcore(iid, 0.9)
    mes.capture(iid, 1, list(defects))
    mes.complete(iid)


def test_report_day_numbers_and_empty_day(client, mes, viewer):
    """일일: 정상/불량/판정 전과 수율(판정 끝난 검사 기준), 앞 기간 비교, 데이터 없는 날은 0"""
    mes.start("N1"); mes.dimension("N1"); mes.patchcore("N1", 0.1)      # 정상
    mes.start("N2"); mes.dimension("N2"); mes.patchcore("N2", 0.1)      # 정상
    _defect_inspection(mes, "D1")                                       # 공정 불량
    mes.start("X1")                                                     # 판정 전
    r = client.get("/api/dashboard/report", headers=viewer, params={"date": TODAY}).json()
    day = r["current"]
    assert r["period"] == "day" and r["date_from"] == r["date_to"] == TODAY and r["days"] == []
    assert (day["total"], day["normal"], day["defect"], day["pending"]) == (4, 2, 1, 1)
    assert day["yield_pct"] == round(2 / 3 * 100, 2) and day["defect_rate"] == round(1 / 3 * 100, 2)
    assert r["previous"]["total"] == 0 and r["previous"]["label"].startswith("이전")      # 어제는 검사 없음
    # 데이터가 없는 날은 전부 0, 수율 0 (가짜 숫자가 나오지 않는다)
    empty = client.get("/api/dashboard/report", headers=viewer, params={"date": "2000-01-01"}).json()
    assert (empty["current"]["total"], empty["current"]["yield_pct"]) == (0, 0.0)
    assert empty["defects"] == [] and empty["ai_reports"] == []


def test_report_week_and_month_ranges(client, mes, viewer):
    """주간은 기준일이 속한 월~일, 월간은 그 달 1일~말일. 하루씩 추이는 오늘까지만"""
    mes.start("W1"); mes.dimension("W1"); mes.patchcore("W1", 0.1)
    _defect_inspection(mes, "W2")
    today = date.today()
    week = client.get("/api/dashboard/report", headers=viewer, params={"period": "week", "date": TODAY}).json()
    monday = today - timedelta(days=today.weekday())
    assert (week["date_from"], week["date_to"]) == (monday.isoformat(), (monday + timedelta(days=6)).isoformat())
    assert [x["label"] for x in week["days"]] == [(monday + timedelta(days=i)).isoformat() for i in range(today.weekday() + 1)]
    assert week["days"][-1]["total"] == 2 and week["days"][-1]["normal"] == 1 and week["days"][-1]["defect"] == 1
    assert week["current"]["total"] == 2 and week["title"].endswith("주간")
    month = client.get("/api/dashboard/report", headers=viewer, params={"period": "month", "date": TODAY}).json()
    first = today.replace(day=1)
    assert month["date_from"] == first.isoformat() and month["date_to"][:7] == TODAY[:7]
    assert len(month["days"]) == today.day and month["days"][0]["label"] == first.isoformat()
    assert month["current"]["total"] == 2 and month["title"] == f"{TODAY[:7]} 월간"
    # 지난달 기준일 → 그 달 전체가 보이고, 앞 기간은 그 전달
    old = client.get("/api/dashboard/report", headers=viewer, params={"period": "month", "date": "2026-02-15"}).json()
    assert (old["date_from"], old["date_to"]) == ("2026-02-01", "2026-02-28") and len(old["days"]) == 28
    assert (old["previous"]["date_from"], old["previous"]["date_to"]) == ("2026-01-01", "2026-01-31")
    assert client.get("/api/dashboard/report", headers=viewer, params={"period": "year"}).status_code == 422


def test_report_defect_analysis_uses_defect_type_table(client, mes, admin, viewer):
    """불량 분석: 코드별 개수, 지정 안 한 결함은 미분류, 원인·조치는 불량 종류 표의 내용"""
    _defect_inspection(mes, "A1", [SCRATCH, WHITE_PAINT])
    r = client.put("/api/inspections/A1/defects/0", headers=admin, json={"defect_code": "D04"})
    assert r.status_code == 200
    rep = client.get("/api/dashboard/report", headers=viewer, params={"date": TODAY}).json()
    by = {x["defect_code"]: x for x in rep["defects"]}
    assert set(by) == {"D04", "미분류"} and rep["defects"][-1]["defect_code"] == "미분류"   # 미분류는 마지막
    d04 = by["D04"]
    assert d04["count"] == 1 and d04["inspections"] == 1 and d04["classes"] == ["scratch"]
    types = {t["defect_code"]: t for t in client.get("/api/defect-types", headers=viewer).json()}
    assert d04["defect_name"] == types["D04"]["defect_name"]
    assert d04["cause_candidates"] == types["D04"]["cause_candidates"]
    assert d04["recommended_action"] == types["D04"]["recommended_action"]
    assert by["미분류"]["defect_name"] is None and by["미분류"]["cause_candidates"] == []


def test_ai_report_saved_immediately_without_ollama(client, mes, admin, viewer):
    """불량 코드를 지정하면 AI 요약(기본 요약)이 바로 저장되고, 응답·재조회·대시보드·보고서에 나온다. Ollama 는 필요 없다"""
    _defect_inspection(mes, "R1")
    t = time.time()
    r = client.put("/api/inspections/R1/defects/0", headers=admin, json={"defect_code": "D01"})
    assert time.time() - t < 2          # AI 를 기다리지 않는다
    body = r.json()
    assert body["ai_report"].startswith(ai_report.HEADER_AUTO) and "D01" in body["ai_report"]
    assert client.get("/api/inspections/R1", headers=viewer).json()["ai_report"] == body["ai_report"]   # 저장됨
    assert client.get("/api/dashboard/summary", headers=viewer).json()["daily_ai_reports"][0]["inspection_id"] == "R1"
    rep = client.get("/api/dashboard/report", headers=viewer, params={"date": TODAY}).json()
    assert rep["ai_reports"][0]["defect_codes"] == ["D01"] and rep["ai_reports"][0]["text"] == body["ai_report"]
    # 코드를 다시 미분류로 돌리면 요약도 비워진다
    cleared = client.put("/api/inspections/R1/defects/0", headers=admin, json={"defect_code": None}).json()
    assert cleared["ai_report"] is None


def test_ai_report_upgraded_by_ollama_in_background(client, mes, admin, monkeypatch):
    """Ollama 가 답하면 응답을 보낸 뒤 AI 요약으로 바뀐다. 실패하면 기본 요약이 그대로 남는다"""
    _defect_inspection(mes, "R2")
    monkeypatch.setattr(ai_report, "ask_ollama", lambda prompt: "도료 공급 압력과 노즐 상태를 점검하세요.")
    client.put("/api/inspections/R2/defects/0", headers=admin, json={"defect_code": "D02"})
    got = client.get("/api/inspections/R2", headers=admin).json()["ai_report"]
    assert got == f"{ai_report.HEADER_AI}\n도료 공급 압력과 노즐 상태를 점검하세요."
    monkeypatch.setattr(ai_report, "ask_ollama", lambda prompt: None)          # Ollama 꺼짐
    client.put("/api/inspections/R2/defects/0", headers=admin, json={"defect_code": "D03"})
    after = client.get("/api/inspections/R2", headers=admin).json()["ai_report"]
    assert after.startswith(ai_report.HEADER_AUTO) and "D03" in after


def test_report_requires_login(client):
    assert client.get("/api/dashboard/report").status_code == 401
