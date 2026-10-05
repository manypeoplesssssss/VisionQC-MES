# 백엔드 이미지: Python 3.12 + FastAPI
# docker-compose.yml 에서 DATABASE_URL 등 환경변수를 넣어준다
FROM python:3.12-slim
WORKDIR /app
# .pyc 파일 안 만들기, 로그를 버퍼 없이 바로 출력
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# 패키지 설치를 소스 복사보다 먼저 → 소스만 바뀌면 설치 단계는 캐시 재사용 (빌드 빠름)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# 컨테이너 밖에서도 접속되게 0.0.0.0 으로 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
