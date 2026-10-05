/**
 * 공정별 검사 조회 (pages/Inspections.jsx)   [기능 F12·F14 · 담당 D]
 *
 * 필터 값을 화면 상태(state)가 아니라 주소창 쿼리스트링에 둔다.
 *   예) /inspections?process=YOLO&result=NG&date_from=2026-10-05
 * → 새로고침해도 필터가 유지되고, 대시보드에서 링크로 바로 원하는 조건을 열 수 있고, 주소를 공유할 수 있다.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, fmtTime, PROCESSES, processLabel, todayStr } from "../api/client.js";
import ImageViewer from "../components/ImageViewer.jsx";
import Pager from "../components/Pager.jsx";
import ResultBadge from "../components/ResultBadge.jsx";

const SIZE = 20; // 한 페이지 행 수
// 탭: "전체 공정"(code 빈 문자열) + 3개 공정
const TABS = [{ code: "", label: "전체 공정" }, ...PROCESSES];

/** 공정별 검사 조회: 공정 탭 + 필터 + 목록 + 이미지 보기 + CSV */
export default function Inspections() {
  // 주소창 쿼리스트링 → 필터 값 (없으면 기본값: 오늘, 전체)
  const [params, setParams] = useSearchParams();
  const process = params.get("process") || "";
  const dateFrom = params.get("date_from") || todayStr();
  const dateTo = params.get("date_to") || dateFrom;
  const item = params.get("item") || "";
  const result = params.get("result") || "";
  const serial = params.get("serial") || "";
  const page = Number(params.get("page") || 1);

  const [data, setData] = useState({ total: 0, items: [] });
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [serialInput, setSerialInput] = useState(serial); // 입력 중인 시리얼 (Enter 를 눌러야 검색)

  /** 필터 바꾸기: 주소창 쿼리스트링을 고친다 → 위의 값들이 바뀌고 → useEffect 가 다시 조회 */
  const update = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in patch)) next.delete("page"); // 필터 바꾸면 1페이지로
    setParams(next);
  };

  const query = { process, item, result, serial_no: serial, date_from: dateFrom, date_to: dateTo };

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
  }, [process, item, result, serial, dateFrom, dateTo, page]);

  useEffect(() => {
    api.items().then(setItems).catch(() => {});
  }, []);
  useEffect(load, [load]); // 필터나 페이지가 바뀔 때마다 조회
  useEffect(() => setSerialInput(serial), [serial]);

  // CSV 는 지금 보고 있는 필터 그대로 (페이지 구분 없이 전체)
  const exportCsv = () => api.exportCsv(query).catch((e) => alert(e.message));
  // 공정에 따라 표 컬럼이 다름: 3D 탭은 치수, PatchCore/YOLO 탭은 결함, 전체 탭은 공정 이름
  const showDim = process === "DIM3D";
  const showDefect = process === "PATCHCORE" || process === "YOLO";

  return (
    <>
      <div className="page-head">
        <h2>공정별 검사 조회</h2>
        <button className="ghost" onClick={exportCsv} disabled={!data.total}>CSV 다운로드</button>
      </div>

      <div className="tabs">
        {TABS.map((p) => (
          <button key={p.code || "all"} className={p.code === process ? "active" : ""} onClick={() => update({ process: p.code })}>
            {p.label}
          </button>
        ))}
      </div>

      <div className="filters">
        <input type="date" value={dateFrom} max={dateTo} onChange={(e) => update({ date_from: e.target.value })} />
        <span className="muted">~</span>
        <input type="date" value={dateTo} min={dateFrom} onChange={(e) => update({ date_to: e.target.value })} />
        <select value={item} onChange={(e) => update({ item: e.target.value })}>
          <option value="">전체 품목</option>
          {items.map((i) => <option key={i}>{i}</option>)}
        </select>
        <select value={result} onChange={(e) => update({ result: e.target.value })}>
          <option value="">전체 판정</option>
          <option value="OK">OK</option>
          <option value="NG">NG</option>
        </select>
        <form onSubmit={(e) => { e.preventDefault(); update({ serial: serialInput.trim() }); }}>
          <input placeholder="시리얼 검색 (Enter)" value={serialInput} onChange={(e) => setSerialInput(e.target.value)} />
        </form>
        <span className="muted small">총 {data.total.toLocaleString()}건 {loading && "· 조회 중..."}</span>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>이미지</th>
              <th>검사시각</th>
              {!process && <th>공정</th>}
              <th>시리얼</th>
              <th>품목</th>
              {showDim && (<><th className="num">W (mm)</th><th className="num">L (mm)</th><th className="num">H (mm)</th></>)}
              {showDefect && (<><th>결함 유형</th><th className="num">신뢰도</th></>)}
              <th>판정</th>
              <th>파일명</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) => {
              const found = r.defects.filter((d) => d.defect_detected);
              return (
                <tr key={r.id} className="clickable" onClick={() => setSelected(r)}>
                  <td><img className="row-thumb" src={r.image_url} alt="" loading="lazy" /></td>
                  <td className="mono small">{fmtTime(r.inspected_at)}</td>
                  {!process && <td>{processLabel(r.process)}</td>}
                  <td>
                    <Link to={`/products/${encodeURIComponent(r.serial_no)}`} onClick={(e) => e.stopPropagation()}>{r.serial_no}</Link>
                  </td>
                  <td>{r.item}</td>
                  {showDim && (
                    <>
                      <td className="num">{r.dimension?.width_mm}</td>
                      <td className="num">{r.dimension?.length_mm}</td>
                      <td className="num">{r.dimension?.height_mm}</td>
                    </>
                  )}
                  {showDefect && (
                    <>
                      <td>{found.map((d) => d.type).join(", ") || "-"}</td>
                      <td className="num">{found.length ? Math.max(...found.map((d) => d.confidence ?? 0)).toFixed(3) : "-"}</td>
                    </>
                  )}
                  <td><ResultBadge value={r.result} /></td>
                  <td className="mono small muted">{r.image_filename}</td>
                </tr>
              );
            })}
            {!loading && data.items.length === 0 && (
              <tr><td colSpan={10} className="center muted">조건에 맞는 검사 데이터가 없습니다.</td></tr>
            )}
          </tbody>
        </table>
        <Pager page={page} total={data.total} size={SIZE} onChange={(p) => update({ page: String(p) })} />
      </div>

      <ImageViewer inspection={selected} onClose={() => setSelected(null)} onDeleted={load} />
    </>
  );
}
