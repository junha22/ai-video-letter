# 온기 (we-meet)

자녀가 한 줄을 쓰면 자녀의 목소리와 얼굴로 만든 영상 편지가 부모님께 가는 서비스.

지금 구현된 MVP 최소 경로:

```
가입·동의 → 목소리 녹음·사진 등록 → 한 줄 입력 → AI 대본 → 영상 미리보기·승인 → 링크 공유 → 부모님 시청 → 자녀에게 시청 알림
```

## 백엔드 없이 디자인 확인 (개발 프리뷰)

프로젝트 루트에서 프론트엔드만 실행합니다. 기존 의존성이 설치되어 있다면 추가 설치가 필요 없습니다.

처음 클론한 팀원은 Node.js와 npm을 준비하고 프로젝트 루트에서 `npm.cmd install`을 한 번 실행합니다.
프리뷰에는 Python, 백엔드 패키지, AI 모델, API 키가 필요하지 않습니다. macOS/Linux에서는 `npm.cmd` 대신 `npm`을 사용합니다.

```powershell
npm.cmd run dev
```

브라우저에서 **http://localhost:3000/dev-preview** 를 엽니다. `/`는 실제 로그인 화면이므로 백엔드가 필요합니다.
3000 포트가 사용 중이면 터미널에 출력된 포트의 `/dev-preview`로 접속하세요.

- 메인, 로그인 화면, 대시보드, 음성·사진 등록, 메시지 작성, 영상 미리보기, 부모님 시청 화면을 메뉴로 전환합니다.
- `design-reference/gyeote-web-prototype.html`의 디자인을 React와 Tailwind로 구성했습니다. 서비스 브랜드는 **온기**를 유지합니다.
- 모든 인물·편지·상태는 **샘플 데이터**입니다. 문구 입력, 등록 상태 전환, 샘플 자막과 반응은 React 메모리에서만 유지되며 새로고침하면 초기화됩니다.
- 실제 API 요청, 로그인, 데이터 저장, 마이크·카메라·파일 접근, AI 생성, 영상 재생 및 발송을 수행하지 않습니다. 백엔드·Python 패키지·AI 모델을 설치할 필요가 없습니다.
- 실제 인증이나 온보딩을 우회하지 않습니다. 프리뷰 전용 컴포넌트는 서비스 API·인증 훅과 분리되어 있습니다.
- 서버의 `NODE_ENV === "development"`인 경우에만 페이지를 제공합니다. `npm.cmd run build` 후 `npm.cmd run start`로 실행하는 프로덕션에서는 `/dev-preview`가 **404**를 반환합니다. 클라이언트 설정이나 쿼리로 활성화할 수 없습니다.
- 검사: `npx.cmd --no-install tsc --noEmit`, `npm.cmd run lint`, `npm.cmd run build`.

### CSS가 적용되지 않거나 메뉴가 기본 HTML처럼 보일 때

`src/app/layout.tsx`에서 `globals.css`를 불러오고, PostCSS가 Tailwind 클래스를 CSS로 생성합니다.
개발 HTML은 열리는데 `/_next/static/css/app/layout.css` 요청이 404이면 CSS 산출물 문제입니다.
개발 서버와 빌드가 같은 `.next`를 사용하면 실행 중인 개발 CSS/JS를 빌드가 덮어쓸 수 있습니다.

이 프로젝트는 `next.config.mjs`에서 개발 서버는 **`.next-dev`**, 프로덕션 빌드·실행은 **`.next`**를 사용하도록 분리합니다.
두 폴더는 자동 생성되며 Git에 올리지 않습니다. 별도 폴더에 소스를 복사해 검사할 필요가 없습니다.
설정 변경 후 이미 켜져 있던 개발 서버가 정상 재시작하지 않으면 `Ctrl+C` 후 `npm.cmd run dev`를 다시 실행하고 브라우저를 새로고침하세요.
스타일 문제를 해결하기 위해 `globals.css`의 Tailwind 지시문을 제거하거나 다른 CSS 라이브러리를 설치하지 마세요.

### 실제 서비스와 프리뷰의 범위

| 프론트엔드 단독으로 가능 | 백엔드 및 설정이 필요한 작업 |
|---|---|
| `/dev-preview`의 일곱 샘플 화면과 반응형 디자인 확인 | 실제 로그인·사용자 정보·동의 처리 |
| 샘플 문구 입력, 샘플 등록 상태·자막·반응 전환 | 음성 녹음 업로드·사진 등록·데이터 저장 |
| TypeScript·ESLint·프론트엔드 빌드 검사 | 실제 대본·음성·영상 생성, 승인·공유·시청 기록 |

`/home`은 실제 API와 기존 사용자·동의 조건을 사용합니다. 홈에서는 부모님 전화번호를 표시하지 않으며 기존 정보 수정 화면에서 확인합니다.
프리뷰는 실제 홈을 대체하지 않습니다. 실제 서비스의 동작 검증에는 별도 백엔드 연동 검사가 필요합니다.

### 로그인 화면 디자인 확인

실제 `/`는 크림색 배경, PC의 브랜드 소개·로그인 카드 2열 구성과 모바일 세로 구성의 온기 로그인 화면입니다.
공통 `src/components/LoginScreen.tsx`에서 정적 일러스트와 로그인 UI를 재사용합니다. 전역 CSS 변경이나 외부 이미지·패키지 설치는 필요하지 않습니다.

백엔드 없이 버튼까지 살펴보려면 **http://localhost:3000/dev-preview** 의 **로그인 화면** 메뉴를 선택합니다.
상단 샘플 상태에서 로그인 버튼 표시, 로그인 설정 확인 중, 서버 연결 실패를 전환할 수 있습니다.
샘플 카카오·개발용 로그인 버튼은 안내만 표시하고 API 호출·로그인 세션 생성·실제 홈 이동을 하지 않습니다.
실제 `/`에서는 기존 `/api/me` 확인, `/api/auth/config` 조회, 카카오 로그인 경로, 개발 로그인 요청과 오류 처리를 유지합니다.
개발 로그인 노출 여부도 기존 서버 응답의 `dev_login` 조건을 그대로 따릅니다. 서버 연결 실패 시 오류를 표시하며 로그인 버튼을 임의로 활성화하지 않습니다.
따라서 프리뷰가 보인다는 사실은 실제 카카오 인증이나 개발 로그인이 검증됐다는 뜻이 아닙니다.

협업 시 `design-reference/gyeote-web-prototype.html`, `src/app/dev-preview/`의 모든 파일,
`src/app/home/FamilyIllustration.tsx`, `src/components/DashboardShell.tsx`, `src/components/LoginScreen.tsx`도 변경사항에 포함해야 합니다.
개발 설정 변경은 `next.config.mjs`, `tsconfig.json`, `.gitignore`와 함께 공유하세요.
개인 PC 절대경로나 로컬 가상환경 파일은 필요하지 않습니다.

## 실제 서비스 실행 (백엔드 필요)

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
