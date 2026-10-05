/**
 * 화면 주소(라우트) 정의 (App.jsx)   [기능 F00 · 담당 A]
 *
 *   /login               로그인
 *   /                    대시보드
 *   /inspections         공정별 검사 조회
 *   /products            제품 추적 목록
 *   /products/:serial    제품 1개 이력
 *   /specs               치수 규격
 *   /account             내 계정 (비밀번호 변경)
 *   /users               사용자 관리 (관리자만)
 *
 * 로그인 화면을 뺀 나머지는 <Layout>(상단 메뉴) 안에 들어가고, 로그인해야만 보인다.
 */
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/AuthContext.jsx";
import Layout from "./components/Layout.jsx";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Inspections from "./pages/Inspections.jsx";
import Products from "./pages/Products.jsx";
import ProductHistory from "./pages/ProductHistory.jsx";
import Specs from "./pages/Specs.jsx";
import Users from "./pages/Users.jsx";
import Account from "./pages/Account.jsx";

/**
 * 로그인 확인 문지기.
 * 로그인 안 했으면 /login 으로, admin 이 필요한데 관리자가 아니면 / 로 보낸다.
 * (화면만 막는 것이고, 실제 권한 검사는 백엔드가 한다)
 */
function RequireAuth({ children, admin = false }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center muted">불러오는 중...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (admin && user.role !== "ADMIN") return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* path 없는 Route = 공통 틀(Layout). 안쪽 Route 들이 Layout 의 <Outlet/> 자리에 그려진다 */}
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/inspections" element={<Inspections />} />
        <Route path="/products" element={<Products />} />
        <Route path="/products/:serial" element={<ProductHistory />} />
        <Route path="/specs" element={<Specs />} />
        <Route path="/account" element={<Account />} />
        <Route
          path="/users"
          element={
            <RequireAuth admin>
              <Users />
            </RequireAuth>
          }
        />
      </Route>
      {/* 없는 주소는 대시보드로 */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
