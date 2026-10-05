/**
 * 치수 규격 관리 (pages/Specs.jsx)   [기능 F07 · 담당 B]
 *
 * 품목별 기준값 ± 공차 표. 관리자는 추가/수정/삭제 가능, 작업자는 보기만.
 * 저장하면 그 다음 들어오는 3D 치수검사부터 새 기준으로 판정된다 (지난 결과는 그대로).
 */
import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

// [필드 앞부분, 화면 이름] → width_nominal / width_tol 처럼 이름을 만들어 쓴다
const FIELDS = [
  ["width", "폭 W"],
  ["length", "길이 L"],
  ["height", "높이 H"],
];
// "규격 추가" 를 눌렀을 때 빈 입력 폼
const EMPTY = { item: "", width_nominal: "", width_tol: "", length_nominal: "", length_tol: "", height_nominal: "", height_tol: "" };

/** 품목별 치수 규격: 3D 치수검사 결과를 서버가 이 기준으로 OK/NG 판정 */
export default function Specs() {
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";
  const [specs, setSpecs] = useState([]);
  const [form, setForm] = useState(null); // 편집 중인 규격 (null 이면 닫힘)
  const [isNew, setIsNew] = useState(false); // true: 추가, false: 수정 (수정 땐 품목명 변경 불가)
  const [error, setError] = useState("");

  const load = () => api.specs().then(setSpecs).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const save = async (e) => {
    e.preventDefault();
    // 입력칸 값은 문자열이라 숫자로 바꿔서 보냄
    const body = {};
    for (const [k] of FIELDS) {
      body[`${k}_nominal`] = Number(form[`${k}_nominal`]);
      body[`${k}_tol`] = Number(form[`${k}_tol`]);
    }
    try {
      await api.saveSpec(form.item.trim(), body);
      setForm(null);
      setError("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const remove = async (item) => {
    if (!confirm(`${item} 규격을 삭제할까요?\n삭제 후에는 검사 PC가 보낸 판정을 그대로 사용합니다.`)) return;
    try {
      await api.deleteSpec(item);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <>
      <div className="page-head">
        <h2>치수 규격</h2>
        {isAdmin && <button className="primary" onClick={() => { setForm({ ...EMPTY }); setIsNew(true); }}>규격 추가</button>}
      </div>
      <p className="muted small">
        3D 치수검사 결과가 들어오면 <b>기준값 ± 공차</b> 안에 있는지 서버가 판정합니다. 규격이 없는 품목은 검사 PC가 보낸 판정을 그대로 씁니다.
        {!isAdmin && " (수정은 관리자만 가능)"}
      </p>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>품목</th>
              {FIELDS.map(([k, label]) => <th key={k} className="num">{label} (mm)</th>)}
              <th>수정일</th>
              {isAdmin && <th />}
            </tr>
          </thead>
          <tbody>
            {specs.map((s) => (
              <tr key={s.item}>
                <td><b>{s.item}</b></td>
                {FIELDS.map(([k]) => (
                  <td key={k} className="num">{s[`${k}_nominal`]} <span className="muted">± {s[`${k}_tol`]}</span></td>
                ))}
                <td className="small muted">{s.updated_at?.slice(0, 10)}</td>
                {isAdmin && (
                  <td className="row-gap">
                    <button className="ghost" onClick={() => { setForm({ ...s }); setIsNew(false); }}>수정</button>
                    <button className="ghost danger-text" onClick={() => remove(s.item)}>삭제</button>
                  </td>
                )}
              </tr>
            ))}
            {specs.length === 0 && <tr><td colSpan={6} className="center muted">등록된 규격이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>

      {form && (
        <div className="modal-bg" onClick={() => setForm(null)}>
          <form className="modal form-modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
            <div className="modal-head"><b>{isNew ? "규격 추가" : `${form.item} 규격 수정`}</b></div>
            <div className="form-body">
              <label>
                품목 (영문/숫자/_)
                <input value={form.item} disabled={!isNew} pattern="[A-Za-z0-9_]{1,50}" required
                  onChange={(e) => setForm({ ...form, item: e.target.value })} />
              </label>
              {FIELDS.map(([k, label]) => (
                <div className="form-row" key={k}>
                  <label>
                    {label} 기준값 (mm)
                    <input type="number" step="0.001" min="0.001" required value={form[`${k}_nominal`]}
                      onChange={(e) => setForm({ ...form, [`${k}_nominal`]: e.target.value })} />
                  </label>
                  <label>
                    공차 ± (mm)
                    <input type="number" step="0.001" min="0" required value={form[`${k}_tol`]}
                      onChange={(e) => setForm({ ...form, [`${k}_tol`]: e.target.value })} />
                  </label>
                </div>
              ))}
            </div>
            <div className="modal-foot">
              <button type="button" className="ghost" onClick={() => setForm(null)}>취소</button>
              <button className="primary">저장</button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
