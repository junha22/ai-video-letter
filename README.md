# 온기 (we-meet)

자녀가 한 줄을 쓰면 자녀의 목소리와 얼굴로 만든 영상 편지가 부모님께 가는 서비스.

지금 구현된 MVP 최소 경로:

```
가입·동의 → 목소리 녹음·사진 등록 → 한 줄 입력 → AI 대본 → 영상 미리보기·승인 → 링크 공유 → 부모님 시청 → 자녀에게 시청 알림
```

## 실행

처음 한 번:

```powershell
npm install
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
copy .env.example .env                                     # 이미 .env가 있으면 생략
cd ..
```

그다음부터:

```powershell
npm run dev:all
```

웹(3000), API(8000), 작업 워커가 한 번에 뜬다. 브라우저에서 http://localhost:3000 을 연다.
API 문서는 http://127.0.0.1:8000/docs 에서 볼 수 있다.

따로 띄우고 싶으면 터미널 3개에서:

```powershell
npm run dev                                                   # 웹
cd backend; .venv\Scripts\python -m uvicorn app.main:app --reload --reload-dir app --port 8000   # API
cd backend; .venv\Scripts\python -m app.worker                # 워커
```

## 설정 (backend/.env)

키가 없어도 끝까지 동작하도록 개발용 대체 기능이 들어 있다. 키를 넣으면 실제 서비스로 바뀐다.

| 항목 | 비워 두면 | 채우면 |
|---|---|---|
| `KAKAO_REST_API_KEY` | 이름만 입력하는 개발용 로그인 | 카카오 로그인 |
| `NAVER_API_KEY` | 메모를 그대로 쓰는 규칙 기반 대본 | HyperCLOVA X 대본 |
| `TTS_PROVIDER` | `local`: Windows 내장 한국어 음성 (내 목소리 아님) | `runpod`: Chatterbox로 내 목소리 |
| `VIDEO_PROVIDER` | `local`: 사진이 천천히 확대되는 영상 | `runpod`: 선정한 립싱크 모델 |
| `PUBLIC_BASE_URL` | `http://localhost:3000` (이 PC에서만 열림) | 배포/터널 주소 → 부모님 휴대폰에서 열림 |
| `VOICE_TARGET_SECONDS` | 180초 | 테스트할 때는 30 정도로 |

카카오톡 공유 버튼은 프론트엔드 `.env.local`에 `NEXT_PUBLIC_KAKAO_JS_KEY`를 넣으면 켜진다 (`.env.local.example` 참고).
없으면 휴대폰 공유 창, 문자 보내기, 링크 복사로 보낸다.

부모님 휴대폰에서 시청 링크를 열어 보려면 터널을 쓴다:

```powershell
npx cloudflared tunnel --url http://localhost:3000   # 나온 https 주소를 PUBLIC_BASE_URL에 넣고 dev:all 재시작
```

## 구조

```
src/app/
  page.tsx                 첫 화면 (로그인)
  onboarding/consent       1. 동의 (목소리·얼굴·부모님 수신)
  onboarding/parent        2. 부모님 정보 (호칭, 전화번호, 말투 예시)
  onboarding/voice         3. 목소리 녹음 (무작위 문장, 실시간 음량, 문장별 품질 검사)
  onboarding/photo         4. 얼굴 사진 (정면·1명·해상도·밝기·흐림 검사)
  home                     준비 상태, 보낸 영상 목록
  messages/new             한 줄 입력 + 상황 템플릿 (안부·날씨·병원·생일·명절)
  messages/[id]            대본 수정 → 영상 생성 진행 상태 → 미리보기·승인 → 공유 → 시청 확인
  w/[token]                부모님 시청 페이지 (로그인 없음, 만료 토큰, 큰 재생 버튼·자막)
  settings                 동의 철회(전체 삭제), 로그아웃

backend/app/
  main.py                  FastAPI 앱
  worker.py                작업 워커 (python -m app.worker)
  models.py                DB 테이블 (SQLite, DATABASE_URL로 교체 가능)
  routers/                 auth, account(동의·부모님), voice, photo, messages, watch, notifications
  services/
    jobs.py                DB 기반 작업 큐 (재시도, 멈춘 작업 복구)
    script_llm.py          HyperCLOVA X 대본 생성 + JSON 파싱·길이·금칙어 검증
    audio.py               녹음 변환(24kHz WAV), 음량 정규화, 품질 분석
    face.py                OpenCV 얼굴 검사
    tts.py / video.py      local / runpod 구현, 'AI로 만든 영상' 표시 입히기
    runpod.py              RunPod 서버리스 호출, GPU 시간·비용 기록
backend/gpu_worker/        RunPod용 Chatterbox TTS 핸들러 초안 (GPU에서 아직 실행 안 해 봄)
```

## 설계 메모

- **작업 큐**: GPU 작업은 웹 서버가 아니라 워커가 처리한다. 지금은 DB 테이블(`jobs`)을 큐로 쓰는데, Windows에서 설치 없이 돌아가고 작업 상태·재시도·비용 기록을 한곳에 둘 수 있어서다. Linux 서버로 옮길 때 `services/jobs.py`의 enqueue/claim만 Celery+Redis로 바꾸면 된다.
- **악용 방지**: 녹음 문장은 사용자마다 무작위로 섞어 준다. 돈·계좌·인증번호·앱 설치를 요구하는 대본은 영상으로 만들 수 없다. 모든 영상에 'AI로 만든 영상' 표시가 들어가고, 누가 어떤 대본으로 만들었는지는 `messages` 테이블에 남는다.
- **동의 철회**: 녹음·참조 음성·사진·영상 파일을 지우고, 링크를 막고, `deletion_logs`에 기록한다. 대본 텍스트는 악용 추적용 생성 로그로 남는다.
- **대본 길이**: 공백 제외 60~90자(약 15초)를 목표로 하고 120자를 넘으면 영상을 만들지 않는다. 길이가 곧 생성 시간과 GPU 비용이다.

## 다음 단계

- RunPod에 TTS 핸들러 배포 → `TTS_PROVIDER=runpod`
- 영상 모델 선정 후 `{"image_b64", "audio_b64"} → {"video_b64"}` 형식의 핸들러 작성 → `VIDEO_PROVIDER=runpod`
- S3Gen 사용자별 학습 작업 (`worker.run_voice` 뒤에 연결), 유사도 검사
- 파일 저장소를 S3로 (`services/storage.py`), DB를 Postgres로 (`DATABASE_URL`)
- PoC A/B 설문, 운영자 화면(작업 큐·GPU 비용·삭제 기록)
