/**
 * 공통 틀 (components/Layout.jsx)   [기능 F00 · 담당 A]
 * 위쪽 메뉴 바 + 아래 본문. 본문 자리(<Outlet/>)에 현재 주소의 페이지가 들어간다.
 */
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function Layout() {
  const { user, logout } = useAuth();
  const isAdmin = user?.role === "ADMIN";
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          VisionQC <b>AI MES</b>
        </div>
        {/* NavLink 는 현재 주소와 같으면 자동으로 class="active" 가 붙는다 (end: 정확히 같을 때만) */}
        <nav>
          <NavLink to="/" end>대시보드</NavLink>
          <NavLink to="/inspections">공정별 검사</NavLink>
          <NavLink to="/products">제품 추적</NavLink>
          <NavLink to="/specs">치수 규격</NavLink>
          {isAdmin && <NavLink to="/users">사용자</NavLink>}
        </nav>
        <div className="user">
          <NavLink to="/account" className="user-name">
            {user?.name} <span className="role">{isAdmin ? "관리자" : "작업자"}</span>
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
