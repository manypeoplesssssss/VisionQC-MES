/**
 * 불량 종류 (pages/DefectTypes.jsx)
 *
 * 공정 불량 D01~D05 의 이름·분류·위치·원인 후보·권장 조치. 관리자는 추가/수정, 조회 전용은 보기만.
 * 원인은 확정 원인이 아닌 '후보' 로 관리한다.
 * 삭제 대신 '사용 안 함' 으로 끈다 (이미 지정된 검사 기록을 보존).
 */
import { useEffect, useState } from "react";
import { api, isAdmin } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

// "불량 종류 추가" 를 눌렀을 때 빈 입력 폼 (원인 후보는 줄바꿈으로 여러 개)
const EMPTY = { defect_code: "", defect_name: "", defect_category: "", defect_location: "", description: "",
  causes: "", recommended_action: "", is_active: true };

export default function DefectTypes() {
  const { user } = useAuth();
  const admin = isAdmin(user);
  const [types, setTypes] = useState([]);
  const [form, setForm] = useState(null); // 편집 중인 값 (null 이면 닫힘)
  const [isNew, setIsNew] = useState(false); // true: 추가, false: 수정 (수정 땐 코드 변경 불가)
  const [error, setError] = useState("");

  const load = () => api.defectTypes().then(setTypes).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const edit = (t) => {
    setForm({ ...t, causes: (t.cause_candidates || []).join("\n") });
    setIsNew(false);
  };

  const save = async (e) => {
    e.preventDefault();
    const body = {
      defect_name: form.defect_name.trim(),
      defect_category: form.defect_category.trim(),
      defect_location: form.defect_location?.trim() || null,
      description: form.description?.trim() || null,
      cause_candidates: form.causes.split("\n").map((s) => s.trim()).filter(Boolean),
      recommended_action: form.recommended_action?.trim() || null,
      is_active: form.is_active,
    };
    try {
      await api.saveDefectType(form.defect_code.trim().toUpperCase(), body);
      setForm(null);
      setError("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <>
      <div className="page-head">
        <h2>불량 종류</h2>
        {admin && <button className="primary" onClick={() => { setForm({ ...EMPTY }); setIsNew(true); }}>불량 종류 추가</button>}
      </div>
      <p className="muted small">
        검사 상세 화면에서 YOLO 결함에 불량 코드를 지정하면, 그 코드의 <b>원인 후보</b>와 <b>권장 조치</b>가 검사 결과에 모입니다.
        원인은 확정 원인이 아닌 후보입니다.{!admin && " (수정은 관리자만 가능)"}
      </p>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table wrap">
          <thead>
            <tr><th>코드</th><th>불량 이름</th><th>분류</th><th>위치</th><th>원인 후보</th><th>권장 조치</th><th>사용</th>{admin && <th />}</tr>
          </thead>
          <tbody>
            {types.map((t) => (
              <tr key={t.defect_code} className={t.is_active ? "" : "inactive"}>
                <td className="mono"><b>{t.defect_code}</b></td>
                <td>{t.defect_name}</td>
                <td>{t.defect_category}</td>
                <td>{t.defect_location || "-"}</td>
                <td>{(t.cause_candidates || []).join(", ") || "-"}</td>
                <td>{t.recommended_action || "-"}</td>
                <td>{t.is_active ? "사용" : "사용 안 함"}</td>
                {admin && <td><button className="ghost" onClick={() => edit(t)}>수정</button></td>}
              </tr>
            ))}
            {types.length === 0 && <tr><td colSpan={8} className="center muted">등록된 불량 종류가 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>

      {form && (
        <div className="modal-bg" onClick={() => setForm(null)}>
          <form className="modal form-modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
            <div className="modal-head"><b>{isNew ? "불량 종류 추가" : `${form.defect_code} 수정`}</b></div>
            <div className="form-body">
              <div className="form-row">
                <label>
                  코드 (예: D06)
                  <input value={form.defect_code} disabled={!isNew} pattern="[A-Za-z][0-9]{2,8}" required
                    onChange={(e) => setForm({ ...form, defect_code: e.target.value })} />
                </label>
                <label>
                  분류
                  <input value={form.defect_category} required placeholder="도장 부족 / 스크래치"
                    onChange={(e) => setForm({ ...form, defect_category: e.target.value })} />
                </label>
              </div>
              <label>불량 이름<input value={form.defect_name} required onChange={(e) => setForm({ ...form, defect_name: e.target.value })} /></label>
              <label>발생 위치<input value={form.defect_location || ""} onChange={(e) => setForm({ ...form, defect_location: e.target.value })} /></label>
              <label>상세 설명<textarea rows={2} value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
              <label>원인 후보 (한 줄에 하나)<textarea rows={3} value={form.causes} onChange={(e) => setForm({ ...form, causes: e.target.value })} /></label>
              <label>권장 점검 및 조치<textarea rows={2} value={form.recommended_action || ""} onChange={(e) => setForm({ ...form, recommended_action: e.target.value })} /></label>
              <label className="check">
                <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> 분류에 사용
              </label>
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
