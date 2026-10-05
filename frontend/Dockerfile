# 프론트엔드 이미지 (2단계 빌드)
#  1단계(build): Node 로 React 를 빌드해서 dist/ 생성
#  2단계: 가벼운 nginx 에 dist/ 만 복사 (Node 는 최종 이미지에 안 들어감)
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# ---- 2단계: nginx 로 정적 파일 서비스 + /api 를 backend 로 전달 ----
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
