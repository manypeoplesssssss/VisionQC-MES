/**
 * 검사 조회 (pages/Inspections.jsx) - 검사 1회(product_inspection 1행) = 표 한 줄
 *
 * 필터 값을 화면 상태(state)가 아니라 주소창 쿼리스트링에 둔다.
 *   예) /inspections?final_result=DEFECT&date_from=2026-10-05
 * → 새로고침해도 필터가 유지되고, 대시보드에서 링크로 바로 원하는 조건을 열 수 있고, 주소를 공유할 수 있다.
 * 줄을 누르면 검사 상세(/inspections/:id)로 이동.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, FINAL_RESULTS, fmtTime, todayStr } from "../api/client.js";
import Pager from "../components/Pager.jsx";
import { FinalBadge, StageBadge, YoloBadge } from "../components/ResultBadge.jsx";

const SIZE = 20; // 한 페이지 행 수
// 탭: 전체 / 불량 묶음 / 대기 묶음 / 정상
const TABS = [
  { code: "", label: "전체" },
  { code: "DEFECT", label: "불량 전체" },
  { code: "PENDING", label: "판정 전" },
  { code: "NORMAL", label: "정상" },
];

export default function Inspections() {
  const navigate = useNavigate();
  // 주소창 쿼리스트링 → 필터 값 (없으면 기본값: 오늘, 전체)
  const [params, setParams] = useSearchParams();
  const finalResult = params.get("final_result") || "";
  const dateFrom = params.get("date_from") || todayStr();
  const dateTo = params.get("date_to") || dateFrom;
  const product = params.get("product_name") || "";
  const serial = params.get("serial") || "";
  const page = Number(params.get("page") || 1);

  const [data, setData] = useState({ total: 0, items: [] });
  const [products, setProducts] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [serialInput, setSerialInput] = useState(serial); // 입력 중인 검색어 (Enter 를 눌러야 검색)

  /** 필터 바꾸기: 주소창 쿼리스트링을 고친다 → 위의 값들이 바뀌고 → useEffect 가 다시 조회 */
  const update = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in patch)) next.delete("page"); // 필터 바꾸면 1페이지로
    setParams(next);
  };

  const query = { final_result: finalResult, product_name: product, serial, date_from: dateFrom, date_to: dateTo };

  const load = useCallback(() => {
    setLoading(true);
    api
      .inspections({ ...query, page, size: SIZE })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finalResult, product, serial, dateFrom, dateTo, page]);

  useEffect(() => {
    api.products().then(setProducts).catch(() => {});
  }, []);
  useEffect(load, [load]); // 필터나 페이지가 바뀔 때마다 조회
  useEffect(() => setSerialInput(serial), [serial]);

  // CSV 는 지금 보고 있는 필터 그대로 (페이지 구분 없이 전체)
  const exportCsv = () => api.exportCsv(query).catch((e) => alert(e.message));
  // 탭에 없는 개별 결과(예: PROCESS_DEFECT)로 들어왔으면 선택 상자에 표시
  const tabCodes = TABS.map((t) => t.code);

  return (
    <>
      <div className="page-head">
        <h2>검사 조회</h2>
        <button className="ghost" onClick={exportCsv} disabled={!data.total}>CSV 다운로드</button>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.code || "all"} className={t.code === finalResult ? "active" : ""} onClick={() => update({ final_result: t.code })}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="filters">
        <input type="date" value={dateFrom} max={dateTo} onChange={(e) => update({ date_from: e.target.value })} />
        <span className="muted">~</span>
        <input type="date" value={dateTo} min={dateFrom} onChange={(e) => update({ date_to: e.target.value })} />
        <select value={product} onChange={(e) => update({ product_name: e.target.value })}>
          <option value="">전체 제품</option>
          {products.map((p) => <option key={p}>{p}</option>)}
        </select>
        <select value={tabCodes.includes(finalResult) ? "" : finalResult} onChange={(e) => update({ final_result: e.target.value })}>
          <option value="">최종 결과 (6가지)</option>
          {FINAL_RESULTS.map((f) => <option key={f.code} value={f.code}>{f.label}</option>)}
        </select>
        <form onSubmit={(e) => { e.preventDefault(); update({ serial: serialInput.trim() }); }}>
          <input placeholder="제품번호·검사번호 검색 (Enter)" value={serialInput} onChange={(e) => setSerialInput(e.target.value)} />
        </form>
        <span className="muted small">총 {data.total.toLocaleString()}건 {loading && "· 조회 중..."}</span>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>사진</th>
              <th>검사시각</th>
              <th>검사번호</th>
              <th>제품</th>
              <th>제품번호</th>
              <th>3D 치수</th>
              <th>PatchCore</th>
              <th>YOLO</th>
              <th>결함</th>
              <th>안전</th>
              <th>최종 결과</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => navigate(`/inspections/${encodeURIComponent(r.inspection_id)}`)}>
                <td>{r.thumbnail_url ? <img className="row-thumb" src={r.thumbnail_url} alt="" loading="lazy" /> : <div className="row-thumb" />}</td>
                <td className="mono small">{fmtTime(r.created_at)}</td>
                <td className="mono small">{r.inspection_id}</td>
                <td>{r.product_name}</td>
                <td className="mono small">{r.product_serial || "-"}</td>
                <td><StageBadge value={r.dimension_result} /></td>
                <td><StageBadge value={r.patchcore_result} /></td>
                <td><YoloBadge value={r.yolo_status} /></td>
                <td className="small">{r.defect_count ? `${r.defect_classes.join(", ")} · ${r.defect_count}건` : "-"}</td>
                <td>
                  {r.active_alarms > 0 ? <span className="badge ng">알람 {r.active_alarms}</span>
                    : r.centering_state === "OFF" && r.interlock_state === "0" ? <span className="badge ok">정상</span>
                    : <span className="badge wip">미확인</span>}
                </td>
                <td><FinalBadge value={r.final_result} /></td>
              </tr>
            ))}
            {!loading && data.items.length === 0 && (
              <tr><td colSpan={11} className="center muted">조건에 맞는 검사가 없습니다.</td></tr>
            )}
          </tbody>
        </table>
        <Pager page={page} total={data.total} size={SIZE} onChange={(p) => update({ page: String(p) })} />
      </div>
    </>
  );
}
