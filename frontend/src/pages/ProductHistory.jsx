/**
 * 제품 1개 이력 (pages/ProductHistory.jsx) - 주소: /products/:serial   [기능 F15 · 담당 D]
 *
 * 그 시리얼의 검사를 시간순으로 카드로 보여준다 (재검사도 각각 카드 1장).
 * 카드를 누르면 이미지 상세 모달. "제품 1개가 어느 공정에서 왜 불량이 됐나" 를 한눈에 보는 화면.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fmtTime, PROCESSES, processLabel } from "../api/client.js";
import ImageViewer from "../components/ImageViewer.jsx";
import ResultBadge from "../components/ResultBadge.jsx";

/** 제품 1개(시리얼)가 거친 전 공정 이력 (재검사 포함) */
export default function ProductHistory() {
  const { serial } = useParams(); // 주소의 :serial 부분
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  const load = () => api.history(serial).then(setRows).catch((e) => setError(e.message));
  useEffect(() => {
    setError("");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serial]);

  // 공정별 마지막 결과로 최종 상태 계산 (서버 규칙과 동일)
  const last = {};
  rows.forEach((r) => (last[r.process] = r.result));
  const status = Object.values(last).includes("NG")
    ? "NG"
    : PROCESSES.every((p) => last[p.code])
      ? "OK"
      : rows.length ? "IN_PROGRESS" : null;

  return (
    <>
      <div className="page-head">
        <h2>
          제품 이력 · <span className="mono">{serial}</span> {status && <ResultBadge value={status} long />}
        </h2>
        <Link to="/products">← 제품 목록</Link>
      </div>
      {error && <div className="error">{error}</div>}
      {rows[0] && (
        <p className="muted">
          품목 <b>{rows[0].item}</b> · 검사 {rows.length}건 · {fmtTime(rows[0].inspected_at)} ~ {fmtTime(rows[rows.length - 1].inspected_at)}
        </p>
      )}

      <div className="timeline">
        {rows.map((r, i) => {
          const found = r.defects.filter((d) => d.defect_detected);
          return (
            <button key={r.id} className={`step ${r.result === "NG" ? "step-ng" : ""}`} onClick={() => setSelected(r)}>
              <div className="step-no">{i + 1}</div>
              <img src={r.image_url} alt={r.image_filename} loading="lazy" />
              <div className="step-meta">
                <div className="row-gap"><b>{processLabel(r.process)}</b><ResultBadge value={r.result} /></div>
                {r.dimension && (
                  <span className="small num">
                    W {r.dimension.width_mm} · L {r.dimension.length_mm} · H {r.dimension.height_mm} mm
                  </span>
                )}
                {found.length > 0 && <span className="small">{found.map((d) => `${d.type} ${((d.confidence ?? 0) * 100).toFixed(0)}%`).join(", ")}</span>}
                <span className="muted small">{fmtTime(r.inspected_at)}</span>
                <span className="mono small muted">{r.image_filename}</span>
              </div>
            </button>
          );
        })}
      </div>

      <ImageViewer inspection={selected} onClose={() => setSelected(null)} onDeleted={load} />
    </>
  );
}
