// Vite 설정 (vite.config.js)
//   npm run dev     → 개발 서버 http://localhost:5173 (코드 저장하면 화면 자동 갱신)
//   npm run build   → dist/ 폴더에 배포용 정적 파일 생성 (Docker 에서는 nginx 가 이걸 서비스)
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중 /api 요청(이미지 포함)을 FastAPI(8000)로 넘김 → CORS 신경 안 써도 됨
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // IP 주소(192.168.x.x, 100.x.x.x)로 여는 건 항상 허용된다. 컴퓨터 "이름"으로 여는 경우(예: Tailscale 의
    // http://node:5173)는 여기에 이름을 적어야 한다. ".ts.net" 은 Tailscale 이 붙여 주는 전체 이름(node.xxx.ts.net)
    allowedHosts: ["node", ".ts.net"],
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
