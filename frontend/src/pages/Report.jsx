/**
 * 보고서 화면 (pages/Report.jsx)   — 일일 / 주간 / 월간 탭
 *
 *   일일 : 기준일 하루
 *   주간 : 기준일이 속한 주 (월~일)
 *   월간 : 기준일이 속한 달 (1일~말일)
 *   각 보고서는 기간 집계(앞 기간과 비교), 하루씩 추이(주간·월간), 코드별 불량 분석, AI 조치 요약, 그 기간 검사 CSV 를 보여 준다.
 *   모든 숫자와 문장은 DB 에서 온 값이다 (데이터가 없으면 0 으로 나온다).
 *   수율 = 정상 ÷ (정상 + 불량), 판정 전 검사는 수율 계산에서 뺀다.
 *   예전 Streamlit 보고서(daily_report_center.py)를 MES 화면 안으로 옮긴 것.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StackedBars } from "../components/Charts.jsx";
import { api, fmtTime, todayStr } from "../api/client.js";

const PERIODS = [
  { key: "day", label: "일일" },
  { key: "week", label: "주간" },
  { key: "month", label: "월간" },
];
const HINT = {
  day: "기준일 하루의 보고서입니다.",
  week: "고른 날짜가 속한 주(월요일~일요일)의 보고서입니다.",
  month: "고른 달(1일~말일)의 보고서입니다.",
};

export default function Report() {
  const [period, setPeriod] = useState("day");
  const [date, setDate] = useState(todayStr());
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setReport(await api.report(date, period));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, [date, period]);

  useEffect(() => {
    setReport(null);
    load();
  }, [load]);

  const exportCsv = () =>
    api.exportCsv({ date_from: report.date_from, date_to: report.date_to }).catch((e) => alert(e.message));
  // 월간은 달 선택 상자(YYYY-MM)라서, 고른 달의 1일(이번 달이면 오늘)을 기준일로 쓴다
  const pickMonth = (ym) => {
    if (!ym) return;
    const first = `${ym}-01`;
    setDate(first > todayStr() ? todayStr() : first);
  };

  return (
    <>
      <div className="page-head">
        <h2>보고서</h2>
        <div className="row-gap">
          {period === "month" ? (
            <input type="month" value={date.slice(0, 7)} max={todayStr().slice(0, 7)} onChange={(e) => pickMonth(e.target.value)} />
          ) : (
            <input type="date" value={date} max={todayStr()} onChange={(e) => setDate(e.target.value || todayStr())} />
          )}
          <button className="ghost" onClick={exportCsv} disabled={!report || report.current.total === 0}>
            이 기간 검사 CSV 다운로드
          </button>
        </div>
      </div>

      <div className="tabs" role="tablist">
        {PERIODS.map((p) => (
          <button key={p.key} role="tab" aria-selected={period === p.key} className={period === p.key ? "active" : ""} onClick={() => setPeriod(p.key)}>
            {p.label}
          </button>
        ))}
      </div>
      <p className="muted small">{HINT[period]} 수율 = 정상 ÷ (정상 + 불량), 판정 전 검사는 뺍니다.</p>

      {error && <div className="error">{error}</div>}
      {!report && !error && <div className="center muted">불러오는 중...</div>}

      {report && (
        <>
          <h3 style={{ marginBottom: 8 }}>{report.title}</h3>
          {report.date_to > todayStr() && (
            <p className="muted small" style={{ marginTop: 0 }}>
              아직 끝나지 않은 기간이라 오늘({todayStr()})까지만 집계됩니다. 앞 기간과 건수를 비교하면 적게 보일 수 있습니다.
            </p>
          )}
          <section className="kpis" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
            <Kpi label="검사" value={report.current.total} sub={vs(report.current.total, report.previous.total, "건", report.previous.label, false, true)} />
            <Kpi label="정상" value={report.current.normal} tone="ok" />
            <Kpi label="불량" value={report.current.defect} tone="ng" sub={vs(report.current.defect, report.previous.defect, "건", report.previous.label, true)} />
            <Kpi label="판정 전" value={report.current.pending} tone="wip" />
            <Kpi label="수율" value={`${report.current.yield_pct}%`} sub={vs(report.current.yield_pct, report.previous.yield_pct, "%p", report.previous.label)} />
            <Kpi label="불량률" value={`${report.current.defect_rate}%`} tone={report.current.defect_rate >= 5 ? "ng" : ""} />
          </section>

          {report.period !== "day" && (
            <section className="card">
              <h3>하루별 검사 추이</h3>
              {report.current.total === 0 ? (
                <p className="muted">이 기간에는 검사 이력이 없습니다.</p>
              ) : (
                <>
                  <StackedBars
                    data={report.days.map((d) => ({ label: d.label.slice(5), values: [d.total - d.defect, d.defect] }))}
                    series={[{ name: "불량 외", cls: "s-ok" }, { name: "불량", cls: "s-ng" }]}
                    tickEvery={report.days.length > 10 ? 3 : 1}
                  />
                  <table className="table" style={{ marginTop: 12 }}>
                    <thead>
                      <tr><th>날짜</th><th className="num">검사</th><th className="num">정상</th><th className="num">불량</th><th className="num">판정 전</th><th className="num">수율</th></tr>
                    </thead>
                    <tbody>
                      {[...report.days].reverse().map((d) => (
                        <tr key={d.label} className="clickable" title="누르면 그날의 일일 보고서" onClick={() => { setDate(d.label); setPeriod("day"); }}>
                          <td>{d.label}</td>
                          <td className="num">{d.total}</td>
                          <td className="num">{d.normal}</td>
                          <td className="num">{d.defect ? <b className="ng-text">{d.defect}</b> : 0}</td>
                          <td className="num">{d.pending}</td>
                          <td className="num">{d.total ? `${d.yield_pct}%` : "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </section>
          )}

          <section className="card">
            <h3>불량 분석</h3>
            {report.current.total === 0 ? (
              <p className="muted">이 기간에는 검사 이력이 없습니다.</p>
            ) : report.defects.length === 0 ? (
              <p className="ok-text">이 기간에는 검출된 결함이 없습니다.</p>
            ) : (
              <>
                <table className="table">
                  <thead>
                    <tr><th>불량 코드</th><th className="num">결함 수</th><th className="num">검사 수</th><th>검출 종류</th><th>원인 후보 (확정 아님)</th><th>권장 조치</th></tr>
                  </thead>
                  <tbody>
                    {report.defects.map((x) => (
                      <tr key={x.defect_code}>
                        <td>
                          <b>{x.defect_code}</b>
                          {x.defect_name && <div className="small">{x.defect_name}</div>}
                        </td>
                        <td className="num">{x.count}</td>
                        <td className="num">{x.inspections}</td>
                        <td className="small">{x.classes.join(", ") || "-"}</td>
                        <td className="small">{x.cause_candidates.length ? x.cause_candidates.join(", ") : <span className="muted">-</span>}</td>
                        <td className="small">{x.recommended_action || <span className="muted">-</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {report.defects.some((x) => x.defect_code === "미분류") && (
                  <p className="muted small">
                    미분류는 아직 불량 코드를 지정하지 않은 결함입니다. [검사 조회]에서 검사를 열어 코드를 지정하면 원인 후보와 권장 조치가 채워집니다.
                  </p>
                )}
              </>
            )}
          </section>

          <section className="card">
            <h3>AI 조치 요약</h3>
            {report.ai_reports.length === 0 ? (
              <p className="muted small">
                이 기간에 불량 코드를 지정한 검사가 없습니다. 검사 상세에서 불량 코드를 지정하면 그 검사의 조치 요약이 여기에 모입니다.
              </p>
            ) : (
              <>
                {report.ai_reports.map((a) => (
                  <div key={a.inspection_id} style={{ marginBottom: 14 }}>
                    <div className="small">
                      <Link to={`/inspections/${encodeURIComponent(a.inspection_id)}`}>{a.inspection_id}</Link>
                      {" · "}{a.defect_codes.join(", ")}{" · "}{fmtTime(a.created_at)}
                    </div>
                    <pre className="advice">{a.text}</pre>
                  </div>
                ))}
                <p className="muted small">최근 10건까지 보여 줍니다. 전체는 [검사 조회]에서 확인하세요.</p>
              </>
            )}
          </section>
        </>
      )}
    </>
  );
}

/** 앞 기간과 비교한 문구 ("이전 주간 대비 +3건"). lowerIsBetter 면 줄어든 게 좋은 것 */
function vs(now, before, unit, label, lowerIsBetter = false, neutral = false) {
  const diff = Math.round((now - before) * 100) / 100;
  if (diff === 0) return `${label}과 같음`;
  const good = lowerIsBetter ? diff < 0 : diff > 0;
  return (
    <span className={neutral ? "" : good ? "ok-text" : "ng-text"}>
      {label} 대비 {diff > 0 ? "+" : ""}{diff}{unit}
    </span>
  );
}

function Kpi({ label, value, tone = "", sub }) {
  return (
    <div className={`kpi ${tone}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value num">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
