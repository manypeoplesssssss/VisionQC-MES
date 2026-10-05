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
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
