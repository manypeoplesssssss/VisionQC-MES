/**
 * 로그인 화면 (pages/Login.jsx)   [기능 F03 · 담당 A]
 * 아이디/비밀번호 → AuthContext 의 login() → 성공하면 대시보드로 이동
 */
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); // 요청 중에는 버튼 비활성화 (중복 클릭 방지)

  // 이미 로그인한 상태로 /login 에 오면 대시보드로
  if (user) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault(); // form 기본 동작(페이지 새로고침) 막기
    setBusy(true);
    setError("");
    try {
      await login(form.username, form.password);
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <h1>
          VisionQC <b>AI MES</b>
        </h1>
        <p className="muted">비전 검사 품질관리 시스템</p>
        <label>
          아이디
          <input
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            autoFocus
            required
          />
        </label>
        <label>
          비밀번호
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "로그인 중..." : "로그인"}
        </button>
      </form>
    </div>
  );
}
