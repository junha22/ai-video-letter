# 온기 백엔드 이미지 (API와 작업 워커가 같이 쓴다). 저장소 루트에서 빌드한다 (shared/ 대본 파일이 필요하다):
#   docker build -f backend/Dockerfile -t ongi-backend .
# API:   기본 CMD (uvicorn, 8000)
# 워커:  python -m app.worker  (Container Apps에서 command로 바꿔 띄운다)
# GPU 작업(TTS·영상)은 이 이미지에 없다. 배포에서는 GPU PC의 게이트웨이(gpu_worker/gateway.py)를 부른다
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# fonts-nanum: 영상 배지 "AI로 만든 영상" 한글 글꼴 (services/video.py가 찾는 경로)
# libglib2.0-0: opencv-python-headless가 필요로 한다
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-nanum libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

# services/sentences.py가 저장소 루트의 shared/voice-sentences.json을 읽는다 (/app/shared)
COPY shared /app/shared
COPY backend/app ./app

# 녹음·사진·영상 저장 위치. 배포에서는 Azure Files를 여기에 연결한다 (DB는 DATABASE_URL의 PostgreSQL)
ENV DATA_DIR=/data
RUN useradd --create-home --uid 10001 ongi && mkdir -p /data && chown ongi /data
USER ongi

EXPOSE 8000
# Container Apps의 HTTPS 종료 프록시 뒤에서 돈다
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
