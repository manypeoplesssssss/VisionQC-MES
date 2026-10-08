/**
 * 대시보드 (pages/Dashboard.jsx) - 메인 화면
 *
 * 화면 구성 (위 → 아래)
 *   KPI 5개      : 검사 / 정상 / 불량 / 대기 / 불량률   (검사 1회 = product_inspection 1행)
 *   검사 흐름    : 3D 치수 → PatchCore → YOLO 단계별 상태 건수. 누르면 해당 최종 결과로 검사 조회
 *   차트 2개     : 시간대별 검사 수 / 최근 14일 검사 수 (불량 표시)
 *   최종 결과별 · 불량 코드(D01~D05) · YOLO 결함 종류
 *   최근 불량    : 누르면 검사 상세로 이동
 *
 * 날짜가 오늘이면 30초마다 자동으로 새로고침 (현장 모니터에 띄워두는 용도)
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, FINAL_RESULTS, fmtTime, STAGE_LABEL, todayStr, YOLO_LABEL } from "../api/client.js";
import { HBars, StackedBars } from "../components/Charts.jsx";
import { FinalBadge } from "../components/ResultBadge.jsx";

const REFRESH_MS = 30_000; // 자동 새로고침 간격 (ms)

// 검사 흐름 카드: 단계별로 보여줄 상태와 이름
const STAGES = [
  { stage: "DIMENSION", name: "3D 치수", keys: ["PASS", "RECHECK", "FAIL", "PENDING"], labels: STAGE_LABEL },
  { stage: "PATCHCORE", name: "PatchCore", keys: ["PASS", "FAIL", "PENDING"], labels: STAGE_LABEL },
  { stage: "YOLO", name: "YOLO 불량 분류", keys: ["COMPLETED", "IN_PROGRESS", "NOT_STARTED"], labels: YOLO_LABEL },
];
const TONE = { PASS: "ok-text", FAIL: "ng-text", COMPLETED: "ok-text" };

export default function Dashboard() {
  const [date, setDate] = useState(todayStr());
  const [summary, setSummary] = useState(null);
  const [hourly, setHourly] = useState([]);
  const [daily, setDaily] = useState([]);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);
  const isToday = date === todayStr();

  // API 3개를 동시에 호출 (Promise.all → 셋 다 끝날 때까지 기다림)
  const load = useCallback(async () => {
    try {
      const [s, h, d] = await Promise.all([api.summary(date), api.hourly(date), api.daily(undefined, date)]);
      setSummary(s);
      setHourly(h);
      setDaily(d);
      setError("");
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e.message);
    }
  }, [date]);

  useEffect(() => {
    load();
    if (!isToday) return;
    const id = setInterval(load, REFRESH_MS); // 오늘이면 현장 모니터용 자동 새로고침
    return () => clearInterval(id); // 화면을 떠나거나 날짜를 바꾸면 타이머 정리
  }, [load, isToday]);

  // 근무시간대(06~22시)만 보이게, 데이터가 그 밖에 있으면 전체
  const hours = hourly.some((h, i) => (i < 6 || i > 21) && h.total) ? hourly : hourly.slice(6, 22);
  const listLink = (final_result) => `/inspections?final_result=${final_result}&date_from=${date}&date_to=${date}`;

  return (
    <>
      <div className="page-head">
        <h2>대시보드</h2>
        <div className="row-gap">
          {updatedAt && (
            <span className="muted small">
              {isToday ? "30초마다 갱신 · " : ""}마지막 갱신 {updatedAt.toLocaleTimeString("ko-KR")}
            </span>
          )}
          <input type="date" value={date} max={todayStr()} onChange={(e) => setDate(e.target.value || todayStr())} />
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {!summary && !error && <div className="center muted">불러오는 중...</div>}

      {summary && (
        <>
          {summary.active_alarms > 0 && (
            <Link className="alarm-banner" to="/alarms?status=ACTIVE">
              <b>안전 알람 {summary.active_alarms}건 발생 중</b>
              <span>센터링·인터락 이상으로 검사가 보류된 상태입니다. 현장 확인 후 해제하세요 →</span>
            </Link>
          )}
          <section className="kpis">
            <Kpi label="검사" value={summary.total} sub="검사 1회 = 1건" />
            <Kpi label="정상" value={summary.normal} tone="ok" sub="치수·PatchCore 합격" />
            <Kpi label="불량" value={summary.defect} tone="ng" sub="치수 또는 PatchCore 불합격" />
            <Kpi label="대기" value={summary.pending} tone="wip" sub={`치수·PatchCore 검사 전 · 안전 알람 ${summary.alarms_today}건`} />
            <Kpi label="불량률" value={`${summary.defect_rate}%`} tone={summary.defect_rate >= 5 ? "ng" : ""} sub="판정 끝난 검사 기준" />
          </section>

          <section className="card">
            <h3>검사 흐름</h3>
            <div className="flow">
              {STAGES.map((s, i) => {
                const counts = summary.by_stage.find((x) => x.stage === s.stage)?.counts ?? {};
                return (
                  <div className="flow-step-wrap" key={s.stage}>
                    <div className="flow-step">
                      <div className="flow-name">{s.name}</div>
                      <div className="flow-split">
                        {s.keys.map((k) => (
                          <span key={k} className={counts[k] ? TONE[k] || "" : "muted"}>
                            {s.labels[k]} <b className="num">{counts[k] || 0}</b>
                          </span>
                        ))}
                      </div>
                    </div>
                    {i < STAGES.length - 1 && <span className="flow-arrow">→</span>}
                  </div>
                );
              })}
            </div>
            <div className="final-grid">
              {FINAL_RESULTS.map((f) => (
                <Link key={f.code} className="final-cell" to={listLink(f.code)}>
                  <FinalBadge value={f.code} />
                  <span className="num">{summary.by_final[f.code] ?? 0}</span>
                </Link>
              ))}
            </div>
          </section>

          <section className="grid-2">
            <div className="card">
              <h3>시간대별 검사 수</h3>
              <StackedBars
                data={hours.map((h) => ({ label: h.label, values: [h.total - h.defect, h.defect] }))}
                series={[{ name: "불량 외", cls: "s-ok" }, { name: "불량", cls: "s-ng" }]}
                tickEvery={2}
              />
            </div>
            <div className="card">
              <h3>최근 14일 검사 수</h3>
              <StackedBars
                data={daily.map((d) => ({ label: d.label.slice(5), values: [d.total - d.defect, d.defect] }))}
                series={[{ name: "불량 외", cls: "s-ok" }, { name: "불량", cls: "s-ng" }]}
                tickEvery={2}
              />
            </div>
          </section>

          <section className="card">
            <div className="page-head" style={{ marginBottom: 6 }}>
              <h3 style={{ margin: 0 }}>AI 조치 요약</h3>
              <Link to="/report" className="small">일일 보고서 보기 →</Link>
            </div>
            {summary.daily_ai_reports?.length ? (
              summary.daily_ai_reports.map((a) => (
                <div key={a.inspection_id} style={{ marginBottom: 10 }}>
                  <div className="small">
                    <Link to={`/inspections/${encodeURIComponent(a.inspection_id)}`}>{a.inspection_id}</Link> · {a.defect_codes.join(", ")}
                  </div>
                  <pre className="advice">{a.text}</pre>
                </div>
              ))
            ) : (
              <p className="muted small">이 날짜에 불량 코드를 지정한 검사가 없습니다. 검사 상세에서 코드를 지정하면 조치 요약이 여기에 나옵니다.</p>
            )}
          </section>

          <section className="grid-2">
            <div className="card">
              <h3>불량 코드 (작업자 분류)</h3>
              <HBars data={summary.defect_codes.map((d) => ({ label: d.label, value: d.count }))} empty="분류할 결함이 없습니다" />
              <p className="muted small">YOLO 결함에 D01~D05 를 지정하면 여기에 모입니다. 지정은 검사 상세 화면에서 합니다.</p>
            </div>
            <div className="card">
              <h3>YOLO 결함 종류</h3>
              <HBars data={summary.defect_classes.map((d) => ({ label: d.label, value: d.count }))} empty="검출된 결함이 없습니다" />
              {summary.by_product.length > 0 && (
                <table className="table" style={{ marginTop: 16 }}>
                  <thead>
                    <tr><th>제품 모델</th><th className="num">검사</th><th className="num">정상</th><th className="num">불량</th><th className="num">대기</th></tr>
                  </thead>
                  <tbody>
                    {summary.by_product.map((p) => (
                      <tr key={p.product_name}>
                        <td>{p.product_name}</td>
                        <td className="num">{p.total}</td>
                        <td className="num">{p.normal}</td>
                        <td className={`num ${p.defect ? "ng-text" : ""}`}>{p.defect}</td>
                        <td className="num">{p.pending}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h3>최근 불량</h3>
              <Link to={listLink("DEFECT")}>전체 보기 →</Link>
            </div>
            {summary.recent_defects.length === 0 ? (
              <p className="muted">해당 날짜에 불량이 없습니다.</p>
            ) : (
              <div className="thumbs">
                {summary.recent_defects.map((r) => (
                  <Link key={r.id} className="thumb" to={`/inspections/${encodeURIComponent(r.inspection_id)}`}>
                    {r.thumbnail_url ? <img src={r.thumbnail_url} alt="" loading="lazy" /> : <div className="no-img">사진 없음</div>}
                    <div className="thumb-meta">
                      <FinalBadge value={r.final_result} />
                      <b>{r.product_name}</b>
                      <span className="muted small mono">{r.product_serial || r.inspection_id}</span>
                      <span className="muted small">{fmtTime(r.created_at).slice(11)}</span>
                      {r.defect_count > 0 && <span className="small">{r.defect_classes.join(", ")} · {r.defect_count}건</span>}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

/** KPI 카드 1개. tone: "ok" | "ng" | "wip" 이면 숫자 색이 바뀜 */
function Kpi({ label, value, tone = "", sub }) {
  return (
    <div className={`kpi ${tone}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value num">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
