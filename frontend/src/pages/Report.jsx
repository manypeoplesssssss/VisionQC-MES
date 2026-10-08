/**
 * 일일 보고서 화면 (pages/Report.jsx)   — 예전 Streamlit 보고서(daily_report_center.py)를 MES 화면 안으로 옮긴 것
 *
 *   기준일을 고르면 그날의 일간 · 주간(7일) · 월간(30일) 생산 현황, 그날 검출된 불량의 코드별 분석,
 *   불량 코드를 지정해서 만들어진 AI 조치 요약, 그날 검사 CSV 내려받기를 보여 준다.
 *   모든 숫자와 문장은 DB 에서 온 값이다 (데이터가 없으면 0 으로 나온다).
 *   수율 = 정상 / (정상 + 불량), 판정 전 검사는 수율 계산에서 뺀다.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtTime, todayStr } from "../api/client.js";

export default function Report() {
  const [date, setDate] = useState(todayStr());
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setReport(await api.report(date));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, [date]);

  useEffect(() => {
    setReport(null);
    load();
  }, [load]);

  const exportCsv = () => api.exportCsv({ date_from: date, date_to: date }).catch((e) => alert(e.message));

  return (
    <>
      <div className="page-head">
        <h2>일일 보고서</h2>
        <div className="row-gap">
          <input type="date" value={date} max={todayStr()} onChange={(e) => setDate(e.target.value || todayStr())} />
          <button className="ghost" onClick={exportCsv} disabled={!report || report.daily.total === 0}>
            {date} 검사 CSV 다운로드
          </button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {!report && !error && <div className="center muted">불러오는 중...</div>}

      {report && (
        <>
          <section className="kpis" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <Period p={report.daily} />
            <Period p={report.weekly} />
            <Period p={report.monthly} />
          </section>
          <p className="muted small">
            주간은 {report.weekly.date_from} ~ {report.weekly.date_to}, 월간은 {report.monthly.date_from} ~ {report.monthly.date_to}
            (기준일 포함). 수율 = 정상 ÷ (정상 + 불량), 판정 전 검사는 뺍니다.
          </p>

          <section className="card">
            <h3>{report.date} 불량 분석</h3>
            {report.daily.total === 0 ? (
              <p className="muted">이 날짜에는 검사 이력이 없습니다.</p>
            ) : report.defects.length === 0 ? (
              <p className="ok-text">이 날짜에는 검출된 결함이 없습니다.</p>
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
                불량 코드를 지정한 검사가 아직 없습니다. 검사 상세에서 불량 코드를 지정하면 그 검사의 조치 요약이 여기에 모입니다.
              </p>
            ) : (
              report.ai_reports.map((a) => (
                <div key={a.inspection_id} style={{ marginBottom: 14 }}>
                  <div className="small">
                    <Link to={`/inspections/${encodeURIComponent(a.inspection_id)}`}>{a.inspection_id}</Link>
                    {" · "}{a.defect_codes.join(", ")}{" · "}{fmtTime(a.created_at)}
                  </div>
                  <pre className="advice">{a.text}</pre>
                </div>
              ))
            )}
          </section>
        </>
      )}
    </>
  );
}

/** 한 기간 카드: 총 검사 수 + 정상/불량/판정 전/수율 */
function Period({ p }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{p.label}</div>
      <div className="kpi-value num">{p.total}건</div>
      <div className="kpi-sub">
        정상 <b className="ok-text">{p.normal}</b> · 불량 <b className="ng-text">{p.defect}</b> · 판정 전 {p.pending}
        <br />
        수율 <b>{p.yield_pct}%</b> · 불량률 {p.defect_rate}%
      </div>
    </div>
  );
}
