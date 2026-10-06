/**
 * 화면 주소(라우트) 정의 (App.jsx)
 *
 *   /login                    로그인
 *   /                         대시보드
 *   /inspections              검사 조회 (검사 1회 = 한 줄)
 *   /inspections/:id          검사 상세 (치수 · PatchCore · YOLO 사진 · 불량 코드 지정)
 *   /defect-types             불량 종류 D01~D05
 *   /alarms                   안전 알람 (센터링 · 인터락 발생/해제 이력)
 *   /account                  내 계정 (비밀번호 변경)
 *   /users                    계정 관리 (최고관리자만)
 *
 * 로그인 화면을 뺀 나머지는 <Layout>(상단 메뉴) 안에 들어가고, 로그인해야만 보인다.
 */
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/AuthContext.jsx";
import Layout from "./components/Layout.jsx";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Inspections from "./pages/Inspections.jsx";
import InspectionDetail from "./pages/InspectionDetail.jsx";
import DefectTypes from "./pages/DefectTypes.jsx";
import Alarms from "./pages/Alarms.jsx";
import Users from "./pages/Users.jsx";
import Account from "./pages/Account.jsx";

/**
 * 로그인 확인 문지기.
 * 로그인 안 했으면 /login 으로, 최고관리자가 필요한데 아니면 / 로 보낸다.
 * (화면만 막는 것이고, 실제 권한 검사는 백엔드가 한다)
 */
function RequireAuth({ children, superAdmin = false }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center muted">불러오는 중...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (superAdmin && user.role !== "SUPER_ADMIN") return <Navigate to="/" replace />;
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
        <Route path="/inspections/:id" element={<InspectionDetail />} />
        <Route path="/defect-types" element={<DefectTypes />} />
        <Route path="/alarms" element={<Alarms />} />
        <Route path="/account" element={<Account />} />
        <Route
          path="/users"
          element={
            <RequireAuth superAdmin>
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
