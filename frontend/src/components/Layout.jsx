/**
 * 공통 틀 (components/Layout.jsx)
 * 위쪽 메뉴 바 + 아래 본문. 본문 자리(<Outlet/>)에 현재 주소의 페이지가 들어간다.
 */
import { NavLink, Outlet } from "react-router-dom";
import { ROLE_LABEL } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          VisionQC <b>AI MES</b>
        </div>
        {/* NavLink 는 현재 주소와 같으면 자동으로 class="active" 가 붙는다 (end: 정확히 같을 때만) */}
        <nav>
          <NavLink to="/" end>대시보드</NavLink>
          <NavLink to="/report">보고서</NavLink>
          <NavLink to="/inspections">검사 조회</NavLink>
          <NavLink to="/defect-types">불량 종류</NavLink>
          <NavLink to="/alarms">안전 알람</NavLink>
          {user?.role === "SUPER_ADMIN" && <NavLink to="/users">계정 관리</NavLink>}
        </nav>
        <div className="user">
          <NavLink to="/account" className="user-name">
            {user?.name} <span className="role">{ROLE_LABEL[user?.role] ?? user?.role}</span>
          </NavLink>
          <button className="ghost" onClick={logout}>로그아웃</button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
