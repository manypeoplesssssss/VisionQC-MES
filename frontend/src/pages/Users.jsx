/**
 * 계정 관리 (pages/Users.jsx) - 최고관리자만 들어올 수 있음 (App.jsx 의 RequireAuth superAdmin)
 *
 * 추가 / 권한 변경 / 이메일 · 리포트 수신 / 사용 중지·재사용 / 비밀번호 초기화.
 * 삭제 대신 '사용 중지' 를 쓴다 (기록 보존). 자기 자신은 권한·중지 변경 불가 (백엔드도 막음).
 */
import { useEffect, useState } from "react";
import { api, fmtTime, ROLE_LABEL } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

const EMPTY = { username: "", name: "", email: "", password: "", role: "VIEWER", receive_defect_reports: false };

export default function Users() {
  const { user: me } = useAuth(); // 지금 로그인한 최고관리자 본인
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(null); // 추가 모달 입력값 (null 이면 닫힘)
  const [error, setError] = useState("");

  const load = () => api.users().then(setUsers).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const create = async (e) => {
    e.preventDefault();
    try {
      await api.createUser({ ...form, email: form.email.trim() || null });
      setForm(null);
      setError("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  /** 계정 1개 일부 수정 후 목록 새로고침 */
  const patch = async (u, body) => {
    try {
      await api.updateUser(u.id, body);
      setError("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const resetPw = (u) => {
    const pw = prompt(`${u.username} 의 새 비밀번호 (6자 이상)`);
    if (pw) patch(u, { password: pw });
  };

  const editEmail = (u) => {
    const email = prompt(`${u.username} 의 이메일 (비우면 삭제)`, u.email || "");
    if (email !== null) patch(u, { email: email.trim() });
  };

  return (
    <>
      <div className="page-head">
        <h2>계정 관리</h2>
        <button className="primary" onClick={() => setForm({ ...EMPTY })}>계정 추가</button>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr><th>아이디</th><th>이름</th><th>이메일</th><th>권한</th><th>불량 리포트</th><th>마지막 로그인</th><th>상태</th><th /></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "inactive"}>
                <td className="mono">{u.username}</td>
                <td>{u.name}</td>
                <td><button className="link" onClick={() => editEmail(u)}>{u.email || "등록"}</button></td>
                <td>
                  <select value={u.role} disabled={u.id === me.id} onChange={(e) => patch(u, { role: e.target.value })}>
                    {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td>
                  <label className="check small">
                    <input type="checkbox" checked={u.receive_defect_reports}
                      onChange={(e) => patch(u, { receive_defect_reports: e.target.checked })} /> 수신
                  </label>
                </td>
                <td className="small muted">{fmtTime(u.last_login_at) || "-"}</td>
                <td>{u.is_active ? "사용" : "중지"}</td>
                <td className="row-gap">
                  <button className="ghost" onClick={() => resetPw(u)}>비밀번호 초기화</button>
                  {u.id !== me.id && (
                    <button className="ghost" onClick={() => patch(u, { is_active: !u.is_active })}>
                      {u.is_active ? "사용 중지" : "다시 사용"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {form && (
        <div className="modal-bg" onClick={() => setForm(null)}>
          <form className="modal form-modal" onClick={(e) => e.stopPropagation()} onSubmit={create}>
            <div className="modal-head"><b>계정 추가</b></div>
            <div className="form-body">
              <label>
                아이디 (영문/숫자/_/., 3자 이상)
                <input value={form.username} pattern="[A-Za-z0-9_.]{3,50}" required onChange={(e) => setForm({ ...form, username: e.target.value })} />
              </label>
              <label>이름<input value={form.name} required onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
              <label>이메일 (리포트 수신 주소, 선택)<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
              <label>
                비밀번호 (6자 이상)
                <input type="password" minLength={6} value={form.password} required onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </label>
              <label>
                권한
                <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  <option value="VIEWER">조회 전용</option>
                  <option value="ADMIN">관리자 (불량 분류·불량 종류·삭제)</option>
                  <option value="SUPER_ADMIN">최고관리자 (계정 관리 포함)</option>
                </select>
              </label>
              <label className="check">
                <input type="checkbox" checked={form.receive_defect_reports}
                  onChange={(e) => setForm({ ...form, receive_defect_reports: e.target.checked })} /> 불량 리포트 수신
              </label>
            </div>
            <div className="modal-foot">
              <button type="button" className="ghost" onClick={() => setForm(null)}>취소</button>
              <button className="primary">추가</button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
