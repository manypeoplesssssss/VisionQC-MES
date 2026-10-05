/**
 * 내 계정 (pages/Account.jsx)   [기능 F04 · 담당 A]
 * 내 정보 확인 + 비밀번호 변경. 상단 메뉴 오른쪽의 이름을 누르면 들어온다.
 */
import { useState } from "react";
import { api } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

export default function Account() {
  const { user } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [msg, setMsg] = useState({ type: "", text: "" }); // type: "error" | "success" (CSS 클래스 이름으로 씀)

  const submit = async (e) => {
    e.preventDefault();
    // 새 비밀번호 확인은 화면에서 먼저 검사 (서버는 현재 비밀번호와 새 비밀번호만 받음)
    if (form.next !== form.confirm) {
      setMsg({ type: "error", text: "새 비밀번호가 서로 다릅니다" });
      return;
    }
    try {
      await api.changePassword(form.current, form.next);
      setForm({ current: "", next: "", confirm: "" });
      setMsg({ type: "success", text: "비밀번호를 바꿨습니다" });
    } catch (err) {
      setMsg({ type: "error", text: err.message });
    }
  };

  return (
    <>
      <div className="page-head"><h2>내 계정</h2></div>
      <div className="card narrow">
        <dl className="kv">
          <dt>아이디</dt><dd className="mono">{user.username}</dd>
          <dt>이름</dt><dd>{user.name}</dd>
          <dt>권한</dt><dd>{user.role === "ADMIN" ? "관리자" : "작업자"}</dd>
        </dl>
        <h3>비밀번호 변경</h3>
        <form className="form-body" onSubmit={submit}>
          <label>현재 비밀번호<input type="password" required value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} /></label>
          <label>새 비밀번호 (6자 이상)<input type="password" minLength={6} required value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} /></label>
          <label>새 비밀번호 확인<input type="password" minLength={6} required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></label>
          {msg.text && <div className={msg.type}>{msg.text}</div>}
          <button className="primary">변경</button>
        </form>
      </div>
    </>
  );
}
