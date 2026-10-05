/**
 * 제품 추적 목록 (pages/Products.jsx)   [기능 F15 · 담당 D]
 *
 * 한 행 = 제품 1개(시리얼). 3개 공정 칸에 각 공정의 마지막 결과, 재검사가 있었으면 횟수 표시.
 * 최종 상태: 양품(3공정 OK) / 불량(한 공정이라도 NG) / 진행중(아직 공정이 남음)
 * 행을 누르면 그 제품의 이력 화면(/products/시리얼)으로 이동.
 * 필터는 Inspections.jsx 와 같은 방식(주소창 쿼리스트링).
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmtTime, PROCESSES, todayStr } from "../api/client.js";
import Pager from "../components/Pager.jsx";
import ResultBadge from "../components/ResultBadge.jsx";

const SIZE = 30; // 한 페이지 제품 수

/** 제품(시리얼) 단위 목록 - 각 제품이 3개 공정을 어디까지, 어떤 결과로 거쳤는지 */
export default function Products() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const dateFrom = params.get("date_from") || todayStr();
  const dateTo = params.get("date_to") || dateFrom;
  const item = params.get("item") || "";
  const status = params.get("status") || "";
  const serial = params.get("serial") || "";
  const page = Number(params.get("page") || 1);

  const [data, setData] = useState({ total: 0, items: [] });
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [serialInput, setSerialInput] = useState(serial);

  const update = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in patch)) next.delete("page");
    setParams(next);
  };

  useEffect(() => {
    api.items().then(setItems).catch(() => {});
  }, []);

  useEffect(() => {
    api
      .products({ date_from: dateFrom, date_to: dateTo, item, status, serial_no: serial, page, size: SIZE })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [dateFrom, dateTo, item, status, serial, page]);

  return (
    <>
      <div className="page-head">
        <h2>제품 추적</h2>
      </div>

      <div className="filters">
        <input type="date" value={dateFrom} max={dateTo} onChange={(e) => update({ date_from: e.target.value })} />
        <span className="muted">~</span>
        <input type="date" value={dateTo} min={dateFrom} onChange={(e) => update({ date_to: e.target.value })} />
        <select value={item} onChange={(e) => update({ item: e.target.value })}>
          <option value="">전체 품목</option>
          {items.map((i) => <option key={i}>{i}</option>)}
        </select>
        <select value={status} onChange={(e) => update({ status: e.target.value })}>
          <option value="">전체 상태</option>
          <option value="OK">양품</option>
          <option value="NG">불량</option>
          <option value="IN_PROGRESS">진행중</option>
        </select>
        <form onSubmit={(e) => { e.preventDefault(); update({ serial: serialInput.trim() }); }}>
          <input placeholder="시리얼 검색 (Enter)" value={serialInput} onChange={(e) => setSerialInput(e.target.value)} />
        </form>
        <span className="muted small">총 {data.total.toLocaleString()}개</span>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>시리얼</th>
              <th>품목</th>
              {PROCESSES.map((p) => <th key={p.code}>{p.label}</th>)}
              <th>최종</th>
              <th>첫 검사</th>
              <th>마지막 검사</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((p) => {
              // [{process, result...}, ...] → { DIM3D: {...}, YOLO: {...} } 로 바꿔서 공정 칸에 바로 꺼내 씀
              const steps = Object.fromEntries(p.steps.map((s) => [s.process, s]));
              return (
                <tr key={p.serial_no} className="clickable" onClick={() => navigate(`/products/${encodeURIComponent(p.serial_no)}`)}>
                  <td className="mono"><Link to={`/products/${encodeURIComponent(p.serial_no)}`}>{p.serial_no}</Link></td>
                  <td>{p.item}</td>
                  {PROCESSES.map((proc) => {
                    const s = steps[proc.code];
                    return (
                      <td key={proc.code}>
                        <ResultBadge value={s?.result} />
                        {s?.attempts > 1 && <span className="muted small"> 재검 {s.attempts - 1}</span>}
                      </td>
                    );
                  })}
                  <td><ResultBadge value={p.status} long /></td>
                  <td className="mono small">{fmtTime(p.first_at)}</td>
                  <td className="mono small">{fmtTime(p.last_at)}</td>
                </tr>
              );
            })}
            {data.items.length === 0 && (
              <tr><td colSpan={8} className="center muted">조건에 맞는 제품이 없습니다.</td></tr>
            )}
          </tbody>
        </table>
        <Pager page={page} total={data.total} size={SIZE} onChange={(p) => update({ page: String(p) })} />
      </div>
    </>
  );
}
