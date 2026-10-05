/**
 * 대시보드 (pages/Dashboard.jsx) - 메인 화면   [기능 F10·F11 · 담당 C]
 *
 * 화면 구성 (위 → 아래)
 *   KPI 5개          : 검사 제품 / 양품 / 불량 / 진행중 / 불량률   (제품 단위)
 *   공정 흐름        : 3D → PatchCore → YOLO 공정별 검사 건수와 OK/NG (검사 단위). 누르면 해당 공정 조회로 이동
 *   차트 2개         : 시간대별 검사 건수 / 최근 14일 제품 수
 *   품목별 표, 불량 유형 순위
 *   최근 불량 이미지 : 누르면 이미지 상세 모달
 *
 * 날짜가 오늘이면 30초마다 자동으로 새로고침 (현장 모니터에 띄워두는 용도)
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtTime, PROCESSES, processLabel, todayStr } from "../api/client.js";
import { HBars, StackedBars } from "../components/Charts.jsx";
import ImageViewer from "../components/ImageViewer.jsx";
import ResultBadge from "../components/ResultBadge.jsx";

const REFRESH_MS = 30_000; // 자동 새로고침 간격 (ms)

export default function Dashboard() {
  const [date, setDate] = useState(todayStr());
  const [summary, setSummary] = useState(null);
  const [hourly, setHourly] = useState([]);
  const [daily, setDaily] = useState([]);
  const [selected, setSelected] = useState(null); // 모달로 열린 검사 (null 이면 닫힘)
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);
  const isToday = date === todayStr();

  // API 3개를 동시에 호출 (Promise.all → 셋 다 끝날 때까지 기다림)
  // useCallback: date 가 바뀔 때만 함수를 새로 만듦 → 아래 useEffect 가 날짜 변경 때만 다시 실행됨
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
          <section className="kpis">
            {/* 제품 단위 숫자 (같은 시리얼의 3공정을 묶어 1개로 셈) */}
            <Kpi label="검사 제품" value={summary.products} sub={`검사 ${summary.inspections}건`} />
            <Kpi label="양품" value={summary.ok} tone="ok" sub="3공정 모두 OK" />
            <Kpi label="불량" value={summary.ng} tone="ng" sub="1공정 이상 NG" />
            <Kpi label="진행중" value={summary.in_progress} tone="wip" sub="공정 진행 중" />
            <Kpi
              label="불량률"
              value={`${summary.defect_rate}%`}
              tone={summary.defect_rate >= 5 ? "ng" : ""}
              sub="완료 제품 기준"
            />
          </section>

          <section className="card">
            <h3>공정 흐름</h3>
            <div className="flow">
              {summary.by_process.map((p, i) => (
                <div className="flow-step-wrap" key={p.process}>
                  <Link className="flow-step" to={`/inspections?process=${p.process}&date_from=${date}&date_to=${date}`}>
                    <div className="flow-name">{processLabel(p.process)}</div>
                    <div className="flow-total num">{p.total}<small>건</small></div>
                    <div className="flow-split">
                      <span className="ok-text">OK {p.ok}</span>
                      <span className={p.ng ? "ng-text" : "muted"}>NG {p.ng}</span>
                      <span className="muted">{p.total ? ((p.ng / p.total) * 100).toFixed(1) : "0.0"}%</span>
                    </div>
                  </Link>
                  {i < PROCESSES.length - 1 && <span className="flow-arrow">→</span>}
                </div>
              ))}
            </div>
          </section>

          <section className="grid-2">
            <div className="card">
              {/* OK 위에 NG 를 쌓아서 막대 전체 높이 = 그 시간 검사 건수 */}
              <h3>시간대별 검사 건수</h3>
              <StackedBars
                data={hours.map((h) => ({ label: h.label, values: [h.total - h.ng, h.ng] }))}
                series={[{ name: "OK", cls: "s-ok" }, { name: "NG", cls: "s-ng" }]}
                tickEvery={2}
              />
            </div>
            <div className="card">
              <h3>최근 14일 제품 수</h3>
              <StackedBars
                data={daily.map((d) => ({ label: d.label.slice(5), values: [d.total - d.ng, d.ng] }))}
                series={[{ name: "불량 외", cls: "s-ok" }, { name: "불량 제품", cls: "s-ng" }]}
                tickEvery={2}
                unit="개"
              />
            </div>
          </section>

          <section className="grid-2">
            <div className="card">
              <h3>품목별 현황</h3>
              <table className="table">
                <thead>
                  <tr><th>품목</th><th className="num">제품</th><th className="num">양품</th><th className="num">불량</th><th className="num">진행중</th><th className="num">불량률</th></tr>
                </thead>
                <tbody>
                  {summary.by_item.map((it) => {
                    const done = it.ok + it.ng;
                    return (
                      <tr key={it.item}>
                        <td><Link to={`/products?item=${it.item}&date_from=${date}&date_to=${date}`}>{it.item}</Link></td>
                        <td className="num">{it.products}</td>
                        <td className="num">{it.ok}</td>
                        <td className={`num ${it.ng ? "ng-text" : ""}`}>{it.ng}</td>
                        <td className="num">{it.in_progress}</td>
                        <td className="num">{done ? ((it.ng / done) * 100).toFixed(1) : "0.0"}%</td>
                      </tr>
                    );
                  })}
                  {summary.by_item.length === 0 && (
                    <tr><td colSpan={6} className="center muted">데이터 없음</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h3>불량 유형 (PatchCore · YOLO)</h3>
              <HBars data={summary.defect_types.map((d) => ({ label: d.type, value: d.count }))} empty="검출된 결함이 없습니다" />
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h3>최근 불량 (NG)</h3>
              <Link to={`/inspections?result=NG&date_from=${date}&date_to=${date}`}>전체 보기 →</Link>
            </div>
            {summary.recent_ng.length === 0 ? (
              <p className="muted">해당 날짜에 불량이 없습니다.</p>
            ) : (
              <div className="thumbs">
                {summary.recent_ng.map((r) => (
                  <button key={r.id} className="thumb" onClick={() => setSelected(r)}>
                    <img src={r.image_url} alt={r.image_filename} loading="lazy" />
                    <div className="thumb-meta">
                      <ResultBadge value={r.result} />
                      <b>{r.item}</b>
                      <span className="muted small">{processLabel(r.process)}</span>
                      <span className="muted small mono">{r.serial_no}</span>
                      <span className="muted small">{fmtTime(r.inspected_at).slice(11)}</span>
                      {r.defects.some((d) => d.defect_detected) && (
                        <span className="small">{r.defects.filter((d) => d.defect_detected).map((d) => d.type).join(", ")}</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <ImageViewer inspection={selected} onClose={() => setSelected(null)} onDeleted={load} />
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
