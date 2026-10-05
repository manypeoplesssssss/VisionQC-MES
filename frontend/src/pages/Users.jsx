/**
 * 사용자 관리 (pages/Users.jsx) - 관리자만 들어올 수 있음 (App.jsx 의 RequireAuth admin)   [기능 F04 · 담당 A]
 *
 * 추가 / 권한 변경 / 사용 중지·재사용 / 비밀번호 초기화.
 * 삭제 대신 '사용 중지' 를 쓴다 (기록 보존). 자기 자신은 권한·중지 변경 불가 (백엔드도 막음).
 */
import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

const EMPTY = { username: "", name: "", password: "", role: "OPERATOR" };

/** 사용자 관리 (관리자 전용) */
export default function Users() {
  const { user: me } = useAuth(); // 지금 로그인한 관리자 본인
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
      await api.createUser(form);
      setForm(null);
      setError("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  /** 사용자 1명 일부 수정 (권한/사용여부/비밀번호) 후 목록 새로고침 */
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

  return (
    <>
      <div className="page-head">
        <h2>사용자 관리</h2>
        <button className="primary" onClick={() => setForm({ ...EMPTY })}>사용자 추가</button>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr><th>아이디</th><th>이름</th><th>권한</th><th>상태</th><th /></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "inactive"}>
                <td className="mono">{u.username}</td>
                <td>{u.name}</td>
                <td>
                  <select value={u.role} disabled={u.id === me.id} onChange={(e) => patch(u, { role: e.target.value })}>
                    <option value="ADMIN">관리자</option>
                    <option value="OPERATOR">작업자</option>
                  </select>
                </td>
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
            <div className="modal-head"><b>사용자 추가</b></div>
            <div className="form-body">
              <label>
                아이디 (영문/숫자/_/., 3자 이상)
                <input value={form.username} pattern="[A-Za-z0-9_.]{3,50}" required onChange={(e) => setForm({ ...form, username: e.target.value })} />
              </label>
              <label>
                이름
                <input value={form.name} required onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label>
                비밀번호 (6자 이상)
                <input type="password" minLength={6} value={form.password} required onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </label>
              <label>
                권한
                <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  <option value="OPERATOR">작업자 (조회)</option>
                  <option value="ADMIN">관리자 (규격·사용자·삭제)</option>
                </select>
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
