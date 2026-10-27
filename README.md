# 온기 (we-meet)

자녀가 한 줄을 쓰면 자녀의 목소리와 얼굴로 만든 영상 편지가 부모님께 가는 서비스.

지금 구현된 서비스 경로:

```
가입·동의 → 목소리 녹음·사진 등록 → 대화 대상자 선택 → AI 영상 편지 생성·승인 → 링크 공유
  → 시니어가 로그인 없이 영상 시청·답글 → 사용자가 확인 후 새 영상 편지 → 날짜별 보관 → 월별 대화 포트폴리오
```

## 이메일 회원가입과 로그인

실제 첫 화면(`/`)에서 이메일·비밀번호로 가입하거나 로그인합니다. 테스트 단계의 비밀번호 조건은 4자 이상이며 문자 조합과 최대 길이 제한은 없습니다. 회원가입에는 이름, 이메일, 비밀번호가 필요하고, 가입 후에는 동의·대상자·목소리·사진 준비 단계로 연결됩니다. 로그인 화면과 설정 화면에서 비밀번호 표시 여부를 바꿀 수 있습니다. 시니어의 `/w/<token>` 공유 대화방에는 회원가입이나 로그인이 필요하지 않습니다.

설정(`/settings`)에서 비밀번호를 변경하거나 기존 개발용 계정에 이메일과 비밀번호를 연결할 수 있습니다. 로그아웃한 세션은 서버에서도 폐기하며, 비밀번호를 변경하면 다른 기기의 기존 세션도 무효화합니다. 비밀번호는 해시로 저장하고 인증 쿠키는 HttpOnly로 발급합니다.

이름만 입력하는 개발용 로그인은 기본적으로 꺼져 있습니다. 기존 개발 계정의 데이터를 이어 쓰려면 로컬 `backend/.env`에 `DEV_LOGIN=true`를 명시하고 기존 이름으로 접속한 뒤 설정에서 이메일을 연결합니다. 이메일 연결이 끝난 계정은 이름만으로 다시 접속할 수 없습니다. 이후 `DEV_LOGIN=false`로 되돌려 주세요. 카카오 버튼은 실제 로그인 화면에서 제외했으며 이메일 로그인에는 카카오 키가 필요하지 않습니다.

이메일 주소 소유 확인과 이메일을 이용한 비밀번호 재설정은 메일 발송 서비스 연결이 필요하며 현재 제공하지 않습니다. 인증 API와 세션 운영 방식은 [로그인 기능 문서](docs/AUTHENTICATION.md)를 참고하세요.

## 대상자별 영상 편지함과 대화

`/letters`의 **영상 편지함**에서 대상자를 등록하거나 선택합니다. 각 대상자의 `/conversations/<id>`에는 오늘의 영상·답글, 지난 날짜별 대화, 월별 포트폴리오가 모입니다. 영상 작성 화면에서도 대상자를 선택할 수 있습니다. 기존 온보딩의 부모님 정보는 기본 대상자로 자동 연결되며, 다른 대상자를 추가해도 기존 영상과 공유 링크는 유지됩니다.

공유한 `/w/<token>` 링크는 해당 대상자의 대화방으로 열립니다. 시니어는 별도의 회원가입이나 로그인 없이 승인된 영상을 보고 답글을 보낼 수 있으며, 같은 유효 링크에서 이후 승인된 영상도 볼 수 있습니다. 링크를 가진 사람이 작성하므로 답글 작성자의 신원은 인증하지 않습니다. 공개 화면에는 전화번호, 작성 중인 영상, 사용자의 메모, 월별 포트폴리오를 제공하지 않습니다.

대화 날짜는 기기의 시간대와 관계없이 **한국 시간(UTC+9)의 00시**에 바뀝니다. 영상은 승인한 날짜, 답글은 실제 서버에 저장된 날짜에 속합니다. 어제 영상을 보고 오늘 답글을 달면 오늘 대화에 저장되며 어제 대화는 날짜 목록에 남습니다. 날짜별 보관은 데이터를 옮기는 작업 없이 서버의 날짜 기준으로 조회합니다.

월별 포트폴리오는 한 달의 시니어 답글에서 주제별 빈도, 날짜별 답글 수, 대표 답글 원문과 다음 대화 제안을 정리합니다. 현재 구현은 `local_evidence_v1` 규칙 기반 분석이며 추가 LLM API 키가 필요하지 않습니다. 건강·감정·인지 상태를 진단하는 기능은 포함하지 않습니다. 현재 월은 화면에서 직접 작성·갱신하고, **지난달까지의 보고서는 작업 워커가 약 60초마다 자동 작성**합니다. 워커가 꺼져 있으면 자동 작성되지 않으며, 긴 영상 생성·음색 학습 중에는 해당 작업을 마친 뒤 처리합니다.

API 계약, 공유 링크 권한, 답글 제한, 마이그레이션과 검증 방법은 [대화 기능 문서](docs/CONVERSATIONS.md)에 정리했습니다.

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
샘플 이메일 로그인·회원가입 화면은 안내만 표시하고 API 호출·로그인 세션 생성·실제 홈 이동을 하지 않습니다.
실제 `/`는 `/api/me`와 `/api/auth/config`를 확인하고 이메일 회원가입·로그인 요청을 처리합니다. 개발용 로그인은 `DEV_LOGIN=true`를 명시한 경우에만 추가로 표시합니다. 서버 연결 실패 시 다시 불러올 수 있습니다.
프리뷰는 디자인 확인용이며 실제 인증 동작은 API를 실행한 상태에서 확인합니다.

협업 시 `design-reference/gyeote-web-prototype.html`, `src/app/dev-preview/`의 모든 파일,
`src/app/home/FamilyIllustration.tsx`, `src/components/DashboardShell.tsx`, `src/components/LoginScreen.tsx`도 변경사항에 포함해야 합니다.
개발 설정 변경은 `next.config.mjs`, `tsconfig.json`, `.gitignore`와 함께 공유하세요.
개인 PC 절대경로나 로컬 가상환경 파일은 필요하지 않습니다.

### 실제 서비스의 PC·모바일 레이아웃

로그인 후 화면은 `AppShell`과 `DashboardShell`을 통해 같은 크림색 배경·사이드바·고정 헤더를 사용합니다.
PC에서는 기존 휴대폰 폭 제한을 제거하고, 음성 등록의 문장·녹음 조작, 사진 안내·업로드,
부모님 정보 입력, 동의 항목·안내, 메시지 작성·도움말, 대본·영상 미리보기, 설정을 넓은 2열로 배치합니다.
모바일에서는 한 열로 돌아가며 뒤로가기·알림·설정 경로는 유지합니다. 부모님 수신 링크의 큰 재생 버튼·자막 화면은 별도로 유지합니다.

화면 폭 변경은 표시 영역에만 적용됩니다. TTS 서버 연동, 음색 학습 상태와 갱신 주기,
녹음·업로드·생성·승인·공유 및 개발용 영상·음성 다운로드는 기존 로직을 사용합니다.
`src/components/StudioPanels.tsx`의 표시 전용 컴포넌트를 실제 화면과 프리뷰가 공유합니다.
밝은 읽기 카드·그린 녹음 패널, 정면 사진 가이드, 편지지·봉투 구성과 단계 표시를 함께 확인할 수 있습니다.
이 파일도 협업 시 Git 변경사항에 포함하세요. 일러스트는 코드로 작성되어 외부 이미지나 추가 설치가 필요하지 않습니다.
`/dev-preview`는 여전히 샘플 화면이며 실제 음성 등록 화면은 `/onboarding/voice`, 사진 등록 화면은 `/onboarding/photo`입니다.
실제 화면에서 데이터를 표시하고 조작하려면 백엔드가 필요합니다. 디자인 확인만으로 TTS·음색 학습이 검증된 것은 아닙니다.

## 실제 서비스 실행 (백엔드 필요)

처음 한 번 (conda 환경에 Python과 Node.js를 같이 설치한다):

```powershell
conda create -n ai-video-letter -c conda-forge python=3.11 nodejs=20 -y
conda activate ai-video-letter
npm install
python -m pip install -r backend/requirements.txt
copy backend\.env.example backend\.env                     # 이미 .env가 있으면 생략
```

그다음부터:

```powershell
conda activate ai-video-letter
npm run dev:all
```

`dev:all`은 활성화된 conda 환경의 python을 쓰고, 없으면 `backend/.venv`, 그것도 없으면 시스템 python을 쓴다.
다른 프로젝트가 3000/8000 포트를 쓰고 있으면 포트를 바꿔 띄운다: `$env:WEB_PORT=3001; $env:API_PORT=8001; npm run dev:all`

웹(3000), API(8000), 작업 워커가 한 번에 뜬다. 브라우저에서 http://localhost:3000 을 연다.
API 문서는 http://127.0.0.1:8000/docs 에서 볼 수 있다.

따로 띄우고 싶으면 터미널 3개에서:

```powershell
npm run dev                                                   # 웹
cd backend; python -m uvicorn app.main:app --reload --reload-dir app --port 8000   # API
cd backend; python -m app.worker                              # 워커
```

## 설정 (backend/.env)

이메일 로그인은 외부 API 키 없이 동작합니다. AI 대본·음성·영상 제공자는 아래 설정으로 선택합니다.

| 항목 | 비워 두면 | 채우면 |
|---|---|---|
| `KAKAO_REST_API_KEY` | 이메일 로그인 사용 | 기존 카카오 API 경로 사용 가능. 이메일 로그인 화면에는 버튼 없음 |
| `DEV_LOGIN` | `false`: 이메일·비밀번호 인증 | `true`: 로컬 개발용 이름 로그인 추가. 이메일 연결된 계정은 접속 불가 |
| `SESSION_SECRET` | 로컬 데이터 폴더에 서명 키 생성 | 배포 시 모든 API 프로세스에 같은 긴 임의 서명 키 지정 |
| `NAVER_API_KEY` | 메모를 그대로 쓰는 규칙 기반 대본 | HyperCLOVA X 대본 |
| `TTS_PROVIDER` | `local`: Windows 내장 한국어 음성 (내 목소리 아님) | `wemeet`: 우리가 학습한 한국어 TTS 서버로 내 목소리 (아래 'TTS 서버 연동'), `runpod`: RunPod의 Chatterbox |
| `VIDEO_PROVIDER` | `local`: 사진이 천천히 확대되는 영상 | `runpod`: FLOAT + 입 모양 LoRA로 립싱크 영상 |
| `PUBLIC_BASE_URL` | `http://localhost:3000` (이 PC에서만 열림) | 배포/터널 주소 → 부모님 휴대폰에서 열림 |
| `VOICE_TARGET_SECONDS` | 135초(2분 15초) | 목소리 사전 녹음의 완료 기준. S3Gen 음색 학습이 돌 수 있는 최소 길이 (비교 30초 + 검증 20초 + 학습 60초, 대본 단위로 나눠서 약 130초) |

카카오톡 공유 버튼은 프론트엔드 `.env.local`에 `NEXT_PUBLIC_KAKAO_JS_KEY`를 넣으면 켜진다 (`.env.local.example` 참고).
없으면 휴대폰 공유 창, 문자 보내기, 링크 복사로 보낸다.

부모님 휴대폰에서 시청 링크를 열어 보려면 터널을 쓴다:

```powershell
npx cloudflared tunnel --url http://localhost:3000   # 나온 https 주소를 PUBLIC_BASE_URL에 넣고 dev:all 재시작
```

## TTS 서버 연동 (`TTS_PROVIDER=wemeet`)

`C:\WE_MEET\tts_server`(Chatterbox Multilingual + 한국어 대화체 LoRA)를 HTTP로 부른다. API 명세는 그 폴더의 `README.md`에 있다.

```powershell
conda activate ai-video-letter
npm run dev:all
```

`backend/.env`가 `TTS_PROVIDER=wemeet`이면 `dev:all`이 TTS 서버(`C:\WE_MEET\tts_server\run_server.ps1`, 127.0.0.1:8100)도 같이 띄운다.
시작에 약 15초, VRAM 약 3.2GB를 쓰고, 워커는 TTS 서버가 준비된 뒤에 뜬다. `dev:all`을 끄면 TTS 서버도 같이 꺼진다.

- TTS 서버가 이미 떠 있으면 새로 띄우지 않고 그대로 쓴다. 코드를 자주 고치며 `dev:all`을 껐다 켤 때는 TTS 서버를 따로 띄워 두면 모델을 매번 다시 올리지 않는다:
  `powershell -ExecutionPolicy Bypass -File C:\WE_MEET\tts_server\run_server.ps1`
- `WEMEET_TTS_URL`이 다른 머신 주소면 띄우지 않는다. TTS 서버 폴더가 다른 곳에 있으면 `WEMEET_TTS_DIR`로 알려 준다.

워커 로그에 `TTS 서버 연결됨`이 찍히면 된다. `/api/health`의 `tts_server` 값(`ok` / `unreachable`)으로도 확인할 수 있다.

| 설정 (`backend/.env`) | 기본값 | 설명 |
|---|---|---|
| `WEMEET_TTS_URL` | `http://127.0.0.1:8100` | TTS 서버 주소 |
| `WEMEET_TTS_API_KEY` | (없음) | TTS 서버를 `WEMEET_API_KEY`로 띄웠을 때 같은 값. `X-API-Key` 헤더로 보낸다 |
| `WEMEET_TTS_TIMEOUT` | `300` | 요청 최대 대기(초). 음성 생성은 `30초 + 글자당 1초`를 기다리고 이 값을 넘지 않는다 |

### 흐름

| 시점 | 백엔드 | TTS 서버 |
|---|---|---|
| 목소리 등록 (`voice` 작업) | 녹음 중 문장 1개를 고른다 (6초 이상 → 차분한 문장 → 평서문 → 잡음 적은 순). 서버는 앞 10초에서 그대로 자르므로, 그보다 긴 대본은 4~9.5초 사이의 가장 늦은 쉼에서 미리 잘라 `voice/tts_reference.wav`로 올린다 (`audio.trim_reference`, 음색 학습도 같은 파일 사용). voice_id(`user_<내부ID>_<무작위 8자>`)와 등록 시각을 `voice_profiles`에 저장 | `PUT /voices/{id}` |
| 영상 생성 (`video` 작업 첫 단계) | 대본을 그대로 보내고 WAV는 `messages/<id>/audio.wav`, `X-Seed`는 `messages.tts_seed`에 저장 | `POST /tts` |
| 다시 녹음, 동의 철회 | `voice_delete` 작업을 넣는다 | `DELETE /voices/{id}` |

- **순서대로 보내기**: 등록·생성·삭제 모두 워커가 작업 큐에서 하나씩 처리하므로 TTS 서버에 동시에 요청이 가지 않는다. **워커는 1개만 띄운다.**
- **seed**: 사용자가 '영상 만들기'나 '다시 만들기'를 누르면 새 seed로, 작업이 자동으로 다시 돌 때(예: 영상 단계 실패)는 저장된 seed로 같은 음성을 만든다.
- **숫자 읽기**: TTS 서버가 숫자·날짜·금액을 한글로 바꾸므로 백엔드는 대본을 그대로 보낸다 (`local`, `runpod`는 기존처럼 백엔드가 바꾼다).
- **voice_id**: 다시 녹음할 때마다 새로 만든다. 예전 목소리 삭제 작업이 서버 장애로 늦게 실행돼도 새 목소리를 지우지 않게 하려는 것이다.
- **개인정보**: 로그에는 voice_id, 상태 코드, 걸린 시간만 남고 대본·음성 내용은 남지 않는다.
- `wemeet`로 바꾸기 전에 등록한 목소리는 첫 영상 생성 때 남아 있는 녹음으로 자동 등록된다.
- 새로 추가된 DB 칸(`tts_voice_id`, `tts_registered_at`, `tts_seed`, `jobs.payload`)은 서버가 시작할 때 자동으로 추가된다 (`db.py`의 `_add_missing_columns`).

### 실패할 때

| 상황 | 백엔드 동작 | 사용자에게 보이는 문구 |
|---|---|---|
| 서버 꺼짐·연결 실패 | 2초, 4초 뒤 다시 연결 → 그래도 안 되면 작업 큐가 10초, 20초 뒤 재시도 (총 3번) → 실패 | 음성 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요. |
| 응답 시간 초과, 5xx | 작업 큐 재시도. 서버가 아직 처리 중일 수 있어서 바로 다시 보내지 않는다 | 위와 같음 |
| 400 (참조 음성 말소리 부족 등) | 재시도 없이 바로 실패 | 녹음에서 목소리를 읽지 못했어요. 처음부터 다시 녹음해 주세요. |
| 401 (API 키 틀림) | 재시도 없이 바로 실패 | 일반 실패 문구 |
| 404 (서버에 목소리 없음) | 남아 있는 녹음으로 다시 등록하고 한 번 더 생성. 녹음이 없으면 실패 | (다시 등록에 성공하면 없음) |
| 삭제할 때 서버 꺼짐 | 10초부터 두 배씩 최대 10번(약 1시간 반) 재시도. 끝내 실패하면 워커 로그에 남는다 → TTS 서버 `voices/<id>` 폴더를 직접 지운다 | — |

실패한 작업은 `jobs` 테이블의 `status='failed'`, `last_error`에 남는다.

### S3Gen 음색 학습 (`S3GEN_TRAINING=true`)

목소리 등록이 끝나면 녹음으로 사용자별 S3Gen 음색 어댑터(LoRA rank 16)를 학습하고, **기본 목소리(zero-shot)보다 더 닮았을 때만** TTS 서버의 목소리에 붙인다.
연구 결과(3분 녹음)로는 유사도가 조금 오르지만(VoiceEncoder 0.893 → 0.908) 효과가 없는 사람도 있어서, 학습할 때마다 비교해서 정한다.

```env
S3GEN_TRAINING=true
WEMEET_TRAIN_PYTHON=C:\Users\swlab\miniconda3\envs\Wemeet-cb\python.exe   # torch가 있는 환경
WEMEET_LORA_CODE_DIR=C:\WE_MEET\AI_test                                    # chatterbox_lora 연구 코드 (고치지 않고 그대로 부른다)
```

| 단계 | 하는 일 | 실행 위치 |
|---|---|---|
| 1. 분할 | 녹음 문장을 참조(TTS 서버에 등록한 그 문장), 평가 약 30초, 검증 약 20초, 나머지 학습으로 나눈다. 녹음 전체의 평균 목소리와 유사도 0.75 미만인 문장은 뺀다. 학습분이 60초 미만이면 학습하지 않는다 | `gpu_worker/s3gen_user.py prepare` |
| 2. 학습 | `chatterbox_lora.s3gen_train`, 배치 4 × 1000 step, 100 step마다 검증해서 가장 좋은 지점 | Wemeet-cb |
| 3. 비교 음성 | 임시 목소리 `<voice_id>_cand`에 어댑터를 붙이고, 기본 목소리와 같은 문장 8개·같은 seed로 만든다 (T3 출력이 같아서 어댑터 차이만 남는다) | TTS 서버 |
| 4. 판단 | 두 음성을 평가용 실제 녹음과 비교. VoiceEncoder 유사도가 `S3GEN_MIN_VE_GAIN`(0.005) 이상 오르고 WavLM이 떨어지지 않으면 적용 | `s3gen_user.py score` |

- **걸리는 시간 (RTX 4070)**: 분할·특징값 약 30초 + 학습 약 3.5분 + 비교 약 1~2분. 학습 중 GPU는 TTS 서버를 포함해 최대 약 9GB를 쓴다 (영상 서버까지 띄우면 11.9GB, 아래 '영상 모델'). 배치 8은 12GB 한계(11.8GB)에 닿아서 기본값을 4로 뒀다. 검증 손실은 배치 8 연구 결과와 거의 같았다(0.4146 vs 0.4118~0.4147).
- **순서**: 학습도 같은 워커가 처리한다. 대기 중인 영상 생성·등록·삭제를 먼저 처리하고(`jobs.claim`), 학습이 시작되면 끝날 때까지 약 5분 동안 다른 작업이 기다린다. 등록이 끝난 순간부터 기본 목소리로 영상을 만들 수 있다.
  학습 때문에 기다리는 영상은 진행 화면에 "목소리를 더 닮게 다듬는 중이라 조금 늦어져요 (약 N분)"(다른 사용자의 학습이면 "앞선 작업이 끝나길 기다리고 있어요")로 보인다 (`serialize.queue_wait`, 남은 시간은 `s3gen.EXPECTED_SECONDS` 기준 추정).
- **결과 기록**: `voice_profiles.s3gen_status`(`queued` → `training` → `applied` / `skipped` / `failed`), `s3gen_report`(분할, 최적 step, 유사도 변화). `GET /api/voice`의 `tuning_report`로 볼 수 있다. 화면에는 "다듬는 중 / 다듬었어요 / 기본 목소리" 한 줄만 보인다.
- **파일**: 적용한 어댑터(약 10MB)만 `users/<id>/voice/s3gen_adapter.safetensors`에 남기고, 특징값·비교 음성 등 중간 파일은 끝나면 지운다. TTS 서버에서 목소리가 없어져 다시 등록할 때 이 어댑터도 다시 붙인다.
- **다시 녹음·동의 철회**: 대기 중인 학습은 취소한다. 이미 학습 중이면 끝난 뒤 목소리가 바뀐 것을 확인하고 결과를 버린다. TTS 서버는 목소리 폴더째 지우므로 어댑터도 같이 지워진다.
- **실패**: 학습 프로세스 오류·시간 초과는 한 번 더 시도하고, 그래도 안 되면 `failed`로 두고 기본 목소리로 계속 쓴다 (사용자 알림 없음). 비교용 임시 목소리를 서버 장애로 못 지우면 `voice_delete` 작업으로 다시 지운다.
- 학습 프로세스에는 녹음 파일 경로와 길이만 넘기고 문장 텍스트는 넘기지 않는다. 모델은 받아 둔 캐시만 쓴다(`HF_HUB_OFFLINE=1`).

## 구조

```
src/app/
  page.tsx                 첫 화면 (로그인)
  onboarding/consent       1. 동의 (목소리·얼굴·부모님 수신)
  onboarding/parent        2. 부모님 정보 (호칭, 전화번호, 말투 예시)
  onboarding/voice         3. 목소리 녹음 (무작위 문장, 실시간 음량, 문장별 품질 검사)
  onboarding/photo         4. 얼굴 사진 (정면·1명·해상도·밝기·흐림 검사)
  home                     준비 상태, 영상 편지함·최근 영상으로 이동
  letters                  대상자별 영상 편지함, 대상자 추가
  conversations/[id]       오늘 대화, 날짜별 보관, 대상자 수정, 월별 포트폴리오
  messages/new             대상자 선택 + 한 줄 입력 + 상황 템플릿 (안부·날씨·병원·생일·명절)
  messages/[id]            대본 수정 → 영상 생성 진행 상태 → 미리보기·승인 → 공유 → 시청 확인
  w/[token]                시니어 공개 대화방 (로그인 없음, 만료 토큰, 영상·자막·답글·지난 대화)
  settings                 동의 철회(미디어·답글·포트폴리오 삭제 및 링크 차단), 로그아웃

backend/app/
  main.py                  FastAPI 앱
  worker.py                작업 워커 (python -m app.worker)
  models.py                DB 테이블 (SQLite, DATABASE_URL로 교체 가능)
  routers/                 auth, account(동의·기본 부모님), conversations(대상자·대화·포트폴리오), voice, photo, messages, watch, notifications
  services/
    conversations.py       기존 대상자 이관, KST 대화 날짜·페이지 조회, 근거 기반 월별 분석
    jobs.py                DB 기반 작업 큐 (재시도, 멈춘 작업 복구)
    script_llm.py          HyperCLOVA X 대본 생성 + JSON 파싱·길이·금칙어 검증
    audio.py               녹음 변환(24kHz WAV), 음량 정규화, 품질 분석
    face.py                OpenCV 얼굴 검사
    tts.py / video.py      local / wemeet / runpod 구현, 'AI로 만든 영상' 표시 입히기
    wemeet_tts.py          WE_MEET TTS 서버 클라이언트 (연결 재시도, 오류 구분)
    s3gen.py               S3Gen 음색 학습 흐름 (분할 → 학습 → 비교 → 적용 판단)
    runpod.py              RunPod 서버리스 호출, GPU 시간·비용 기록 (로컬 테스트 서버도 지원)
backend/tests/
  test_conversations.py    격리 SQLite·임시 미디어를 사용하는 대화 기능 통합 테스트 23개
docs/CONVERSATIONS.md      대화방·공유 링크·월별 포트폴리오 API 및 운영 문서
backend/gpu_worker/
  s3gen_user.py            음색 학습의 GPU 단계 (Wemeet-cb 환경에서 실행: 분할·특징값, 유사도)
  tts_handler.py           RunPod용 Chatterbox TTS 핸들러 초안 (GPU에서 아직 실행 안 해 봄)
  video_handler.py         RunPod용 영상 핸들러: FLOAT + 입 모양 LoRA
  weights/float_lora_best.pt   입 모양 LoRA 가중치 (rank 16, 8MB)
```

## 영상 모델 (FLOAT + 입 모양 LoRA)

[FLOAT](https://github.com/deepbrainai-research/float)(ICCV 2025)의 Flow Matching Transformer에 입 모양 LoRA를 붙여 쓴다.
검증 영상 기준으로 입 움직임 상관이 0.233 → 0.253으로 오르고, 과하게 벌어지던 입 크기 비율(실제 = 1)이 1.27 → 1.12로 줄었다.

- **흐름**: 워커가 저장된 사진(최대 1280px)·얼굴 위치·TTS 음성을 핸들러에 보낸다. 핸들러는 FLOAT 방식으로 얼굴을 512×512로 잘라 영상을 만든다. 백엔드는 그 영상을 4:5 화면 가운데에 놓고 위아래를 흐린 배경으로 채운 뒤, 원래 음성과 'AI로 만든 영상' 표시를 입힌다.
- **입출력 형식**: `backend/gpu_worker/video_handler.py` 맨 위 설명 참고. 기존 `{"image_b64", "audio_b64", "fps"} → {"video_b64"}`에 `face`와 선택 옵션(`seed`, `lora_strength`, `emo` …)이 더해졌다.
- **표정(감정)**: 사용자가 영상 만들기 화면에서 평온·기쁨·슬픔·놀람 중에 고른다(기본 평온). FLOAT의 음성 감정 추정은 영어 음성으로 학습돼 한국어에서 부정확해서 쓰지 않는다. 고른 값은 `messages.emotion`에 남는다.
- **옵션**: `backend/.env`의 `VIDEO_LORA_STRENGTH`(0 = 원본 FLOAT, 1 = LoRA), `VIDEO_E_CFG_SCALE`(표정 세기), `VIDEO_SEED` 등. 비우면 핸들러 기본값.
- **사진 충실도·눈 후처리**: Kaggle 노트북(`float_infer.ipynb`)에서 고른 기능을 `gpu_worker/float_tuning.py`로 옮겼다. `VIDEO_R_CFG_SCALE`(사진 충실도), `VIDEO_REF_MODE`(적용 범위), `VIDEO_EYE_STABLE`(시선 안정), `VIDEO_BLINK_GAP`(깜빡임 간격), `VIDEO_DEJUMP`(튀는 곳만 다듬기). 비우면 모두 꺼져서 FLOAT 원래 동작과 같다. 노트북 추천값은 `.env.example` 참고.
- **GPU 필요**: FLOAT 코드가 `.cuda()`를 직접 불러서 CPU로는 돌지 않는다. GPU 없이 웹을 개발할 때는 `VIDEO_PROVIDER=local` 그대로 둔다.
- **라이선스**: FLOAT는 비상업 라이선스(CC BY-NC)라 비상업 연구·PoC 용도로만 쓴다.

### 이 PC(Windows)에서 TTS·음색 학습과 같이 돌리기

WSL 없이 Windows에서 바로 돈다. 처음 한 번 (FLOAT 소스·체크포인트 약 2.4GB는 git에 넣지 않는다):

```powershell
conda create -n Wemeet-float python=3.10 -y
$py = "$env:USERPROFILE\miniconda3\envs\Wemeet-float\python.exe"
& $py -m pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
git clone https://github.com/deepbrainai-research/float.git backend/gpu_worker/float
git -C backend/gpu_worker/float checkout 3b5b2dfc3e65df26e7fbba17d9adb3f43747851c
& $py -m pip install -r backend/gpu_worker/float/requirements.txt "numpy<2" runpod gdown "huggingface_hub<0.26"
& $py -m gdown 1rvWuM12cyvNvBQNCLmG4Fr2L1rpjQBF0 -O backend/gpu_worker/float/checkpoints/float.pth
& $py -c "from huggingface_hub import snapshot_download as d; ck='backend/gpu_worker/float/checkpoints/'; [d(repo_id=r, local_dir=ck+n, allow_patterns=['*.json','pytorch_model.bin','*.txt']) for r,n in [('facebook/wav2vec2-base-960h','wav2vec2-base-960h'),('r-f/wav2vec-english-speech-emotion-recognition','wav2vec-english-speech-emotion-recognition')]]"
```

```ini
# backend/.env
VIDEO_PROVIDER=runpod
RUNPOD_VIDEO_ENDPOINT_ID=http://127.0.0.1:8010
WEMEET_FLOAT_PYTHON=C:\Users\swlab\miniconda3\envs\Wemeet-float\python.exe
```

이러면 `npm run dev:all`이 영상 서버(127.0.0.1:8010, 이 PC에서만 접속)도 같이 띄우고, TTS·영상 서버가 준비된 뒤에 워커를 띄운다.
처음 실행할 때는 얼굴 검출 가중치(약 90MB)를 받느라 약 1분, 그 뒤로는 약 5초 걸린다. 이미 떠 있으면 그대로 쓴다.

RTX 4070(12GB)에서 잰 값:

| | GPU 전체 사용량 | 비고 |
|---|---|---|
| TTS 서버 + 영상 서버 대기 | 7.0GB | 영상 서버만 약 2.7GB |
| 영상 생성 중 최고 | 11.8GB | 21초 음성 → GPU 약 18초 |
| 음색 학습(배치 4) 중 최고 | 11.9GB | 속도는 영상 서버 없을 때와 같음 (0.22초/step) |

- 워커가 1개라 영상 생성과 음색 학습은 동시에 돌지 않는다. 둘 다 12.3GB 안에 들어가지만 여유는 0.5GB 정도라, 다른 GPU 프로그램(게임, 다른 모델)을 같이 띄우지 않는다.
- 영상 서버는 영상 하나를 만들 때마다 생성에 쓴 메모리(약 4GB)를 돌려준다(`torch.cuda.empty_cache`). 돌려주지 않으면 대기 상태가 7.5GB로 남아서 음색 학습이 들어갈 자리가 없다.

RunPod에 배포하지 않고 GPU PC(Linux 또는 WSL)에서 웹과 연결해 보기:

```bash
# GPU PC에서 (준비 과정은 video_handler.py 맨 위 '준비' 참고)
python backend/gpu_worker/video_handler.py --rp_serve_api --rp_api_host 0.0.0.0 --rp_api_port 8010
```

```ini
# 웹을 띄우는 PC의 backend/.env
VIDEO_PROVIDER=runpod
RUNPOD_VIDEO_ENDPOINT_ID=http://<GPU PC 주소>:8010
```

엔드포인트 ID 자리에 `http://` 주소를 넣으면 RunPod 대신 그 로컬 서버를 부른다. RunPod에 배포한 뒤에는 실제 엔드포인트 ID로 바꾸기만 하면 된다.

## 설계 메모

- **작업 큐**: GPU 작업은 웹 서버가 아니라 워커가 처리한다. 지금은 DB 테이블(`jobs`)을 큐로 쓰는데, Windows에서 설치 없이 돌아가고 작업 상태·재시도·비용 기록을 한곳에 둘 수 있어서다. Linux 서버로 옮길 때 `services/jobs.py`의 enqueue/claim만 Celery+Redis로 바꾸면 된다.
- **악용 방지**: 녹음 문장은 사용자마다 무작위로 섞어 준다. 돈·계좌·인증번호·앱 설치를 요구하는 대본은 영상으로 만들 수 없다. 모든 영상에 'AI로 만든 영상' 표시가 들어가고, 누가 어떤 대본으로 만들었는지는 `messages` 테이블에 남는다.
- **동의 철회**: 녹음·참조 음성·사진·영상 파일, 시니어 답글, 월별 포트폴리오, 답글 내용을 담은 알림을 지우고 모든 공유 링크를 막는다. `deletion_logs`에는 삭제 건수를 기록한다. 대본 텍스트는 악용 추적용 생성 로그로 남으며 대상자 연락처도 유지한다.
- **대상자 호환성**: 기존 `parent_profiles`는 온보딩의 기본 연락처로 유지하고, `recipients`에서 여러 대화 대상자를 관리한다. 서버 시작 시 기존 영상에 대상자를 연결하므로 DB를 초기화할 필요가 없다.
- **공개 대화방**: 유효 공유 토큰은 해당 사용자·대상자의 승인된 영상과 답글을 조회하는 권한이다. 영상·포스터 요청마다 같은 토큰의 만료·철회를 다시 검사하고 공개 응답은 `no-store`로 보낸다.
- **대본 길이**: 공백 제외 60~90자(약 15초)를 목표로 하고 120자를 넘으면 영상을 만들지 않는다. 길이가 곧 생성 시간과 GPU 비용이다.

## 대화 기능 검증

백엔드 의존성이 설치된 Python 환경에서 프로젝트 루트 기준으로 실행합니다.

```powershell
python -m unittest discover -s backend/tests -v
```

현재 통합 테스트 23개는 기존 SQLite 스키마 이관, 계정·대상자 분리, 토큰 만료·철회, 답글 재시도·동시 요청, KST 자정·월 경계와 마이크로초 정렬, 포트폴리오 갱신, 자동 월별 작성, 동의 철회와 저장 요청의 경합을 검증합니다. 테스트는 별도 DB·임시 미디어·고정 시계를 사용하며 실제 `backend/data`와 외부 AI 서비스를 사용하지 않습니다. 프론트엔드는 `npx.cmd --no-install tsc --noEmit`, `npm.cmd run lint`, `npm.cmd run build`로 검사합니다.

## 다음 단계

- TTS 서버를 다른 머신에 둘 때: 서버를 `-HostAddr 0.0.0.0` + `WEMEET_API_KEY`로 띄우고 `WEMEET_TTS_URL`, `WEMEET_TTS_API_KEY` 설정
- S3Gen 음색 학습: 적용 기준값(`S3GEN_MIN_VE_GAIN` 등) 확정, 실제 사용자 폰 녹음으로 효과 확인, 청취 평가
- RunPod에 영상 핸들러(`gpu_worker/video_handler.py`, FLOAT + LoRA) 배포 → 엔드포인트 ID만 바꾸면 된다. 지금은 이 PC에서 TTS·음색 학습과 GPU를 나눠 쓴다 (위 '이 PC(Windows)에서 …')
- 표정별(평온·기쁨·슬픔·놀람) 자연스러움, LoRA 0/1 비교 (PoC A/B 설문에 활용)
- 파일 저장소를 S3로 (`services/storage.py`), DB를 Postgres로 (`DATABASE_URL`)
- PoC A/B 설문, 운영자 화면(작업 큐·GPU 비용·삭제 기록)
