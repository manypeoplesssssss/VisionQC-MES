/**
 * 로그인 상태 공유 (context/AuthContext.jsx)   [기능 F03 · 담당 A]
 *
 * 앱 전체를 <AuthProvider> 로 감싸면, 어느 컴포넌트에서든 useAuth() 로
 *   user    : 로그인한 사용자 { id, username, name, role, is_active } (없으면 null)
 *   loading : 처음 접속 시 토큰 확인 중이면 true
 *   login() / logout()
 * 을 꺼내 쓸 수 있다.
 */
import { createContext, useContext, useEffect, useState } from "react";
import { api, tokenStore } from "../api/client.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // 새로고침해도 토큰이 있으면 로그인 유지
  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    // 저장된 토큰이 아직 유효한지 서버에 물어봄 (만료됐으면 토큰 삭제)
    api.me().then(setUser).catch(() => tokenStore.clear()).finally(() => setLoading(false));
  }, []);

  /** 로그인: 토큰 받아서 저장 → 내 정보 불러오기 (실패하면 에러가 그대로 throw 됨) */
  const login = async (username, password) => {
    const { access_token } = await api.login(username, password);
    tokenStore.set(access_token);
    setUser(await api.me());
  };

  /** 로그아웃: 토큰만 지우면 끝 (JWT 는 서버에 세션이 없음) */
  const logout = () => {
    tokenStore.clear();
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

/** 컴포넌트에서 const { user } = useAuth(); 처럼 사용 */
export const useAuth = () => useContext(AuthContext);
