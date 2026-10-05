/**
 * 프론트엔드 시작점 (main.jsx)   [기능 F00 · 담당 A]
 *
 * index.html 의 <div id="root"> 에 React 앱을 붙인다.
 * 감싸는 순서
 *   StrictMode    : 개발 중 잠재적 문제를 경고 (배포 빌드에는 영향 없음)
 *   BrowserRouter : 주소(URL)에 따라 화면 전환
 *   AuthProvider  : 로그인 상태를 앱 전체에 공유
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { AuthProvider } from "./context/AuthContext.jsx";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
