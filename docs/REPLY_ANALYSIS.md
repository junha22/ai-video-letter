# 부모님 답장 분석

> 상태 (2026-11-16): **코드·자동 시험 완료. LLM 판단을 로컬 SEED 14B에서 CLOVA Studio HCX-007 API로 바꿨어요** (14절). 기능 스위치 `REPLY_ANALYSIS_ENABLED`는 기본 꺼짐이에요. 켜는 순서는 7절이에요.
> 규칙과 수치의 정답지는 저장소 밖 `reply-analysis-ref/reply_analysis_reference.py`예요 (`PROMPT_ID v2-6af325`). 판단 기준·JSON 틀·후처리·운율 규칙은 정답지와 같아요 (스크립트로 비교).

부모님(시니어)이 영상 편지를 보고 남긴 답장(음성·글)을 AI로 정리해서, **자녀 화면에만** "지금 알아야 할 일이 있는지" 보여 주는 기능이에요.
진단이 아니라 정리예요. 카드마다 "AI가 정리한 내용이에요. 진단이 아니니 음성을 함께 들어 보세요"를 붙여요.

## 1. 한눈에 보기

```
[시니어 /w/<token>]  말로 답하기(녹음 → 다시 듣기 → 보내기)  또는  글로 쓰기
        │ POST /api/watch/<token>/voice-replies (16kHz 모노 WAV로 바꿔 저장)
        ▼
[API] senior_replies 저장 → (기능 켜짐 + 지금 문구로 받은 자녀·시니어 동의) reply_analyses(queued) + jobs(reply_analysis)
        ▼
[워커 1개] 작업을 하나씩 처리 (영상 생성을 먼저)
   음성:  GPU PC /stt ──불확실──▶ stt_uncertain (끝)
            │ 받아쓰기 → senior_replies.text 채움 (자동 받아쓰기)
            ▼
          GPU PC /prosody → 같은 대상자의 지난 운율과 비교 (백엔드 규칙)
            ▼
   글·음성: mask_pii + 이름·이메일 가림 → CLOVA Studio HCX-007 (형식 강제 JSON) → 후처리(백엔드 규칙) → 저장 → 알림
        │                                     ▲
        │ 받아쓰기·운율만                       │ 워커가 바로 부른다 (Azure에서도 GPU PC를 거치지 않음)
        ▼                                     │ 보내는 것: 판단 기준, 자녀 편지, 최근 기록 3개, 가린 답장 글
[GPU PC] reply_analysis_server.py :8400        │ 안 보내는 것: 음성 파일, 목소리 값, 사용자·대상자 ID, 이메일, 이름
   /stt     받아쓰기 자식 프로세스: BuzzASR 올림 → 받아쓰기 → 프로세스 끝 (GPU 0으로)
   /prosody librosa (CPU)
        ▼
[자녀 /conversations/<id>] 답장 아래 분석 카드, 살펴보기 이상이면 알림, 바로 연락 필요는 화면 맨 위 빨간 띠
```

글 답장은 GPU PC가 꺼져 있어도 분석돼요 (받아쓰기·운율이 필요 없어서). GPU PC가 꺼져 있으면 음성 답장만 실패하고 '다시 정리하기'로 다시 할 수 있어요.

## 2. 코드를 바꾸기 전에 확인한 사실

| 확인한 것 | 결과 |
|---|---|
| 시니어 답장은 글뿐 | 맞았어요. `SeniorReply.text`(NOT NULL), `POST /api/watch/{token}/replies` |
| 게이트웨이 경로 | `/tts` `/video` `/train` 외에 `/comfy`(어린 시절 모드)도 있어요 |
| 답장 하나씩 지우기 | 이미 있었어요. 음성 파일·분석·그 답장의 알림도 같이 지우게 고쳤어요 |
| 다음 영상 대본 | 직전 편지 이후 답장 글을 CLOVA(HCX-003 v1)로 보내요. 받아쓰기도 넣기로 정했어요 (14절 5번) |
| 브라우저 알림 | 알림 벨이 이미 브라우저 알림(허용했고 탭이 열려 있을 때)을 띄워요 |
| 작업 큐 | 같은 `(type, user_id, message_id)`의 대기 작업을 취소해서, 답장 분석은 `replace=False`로 넣어요 |
| 동의 버전 | 예전에는 버전을 보지 않아서 버전을 올려도 다시 묻지 않았어요 → 지금 버전으로 받은 동의만 인정하게 고쳤어요 (2026-11-16) |
| 개발한 PC | Intel 노트북(GPU 없음). 코드·자동 시험은 여기서, GPU PC 시험은 GPU PC에서 직접 해요 |

## 3. 데이터 구조

`init_db()` 방식 그대로예요. 새 표는 `create_all`이, 새 칸은 `_add_missing_columns`가 붙여요. 반복 실행해도 되고 기존 ID·토큰·경로는 그대로예요. CLOVA로 바꾸면서 새 칸은 없어요.

### `senior_replies`에 더한 칸

| 칸 | 형식 | 뜻 |
|---|---|---|
| `kind` | String(10), 기본 `'text'` | `text` / `voice`. 기존 행은 DEFAULT로 `text`가 돼요 |
| `audio_path` | String(500) | `users/<uid>/replies/<reply_id>.wav` (16kHz 모노 PCM, 소리 크기는 그대로) |
| `audio_seconds` | Float | 녹음 길이 |
| `audio_sha256` | String(64) | 같은 `client_id` 재시도가 같은 녹음인지 |

음성 답장의 `text`는 처음엔 `""`이고, 받아쓰기가 확실하면 받아쓰기로 채워요. **`kind='voice'`이면 `text`는 자동 받아쓰기**예요. 불확실하면 채우지 않아요.

### 새 표 `reply_analyses` (답장 1개에 1행)

| 칸 | 내용 |
|---|---|
| `user_id`, `recipient_id`, `reply_id` | 소유자·대상자·답장 (`reply_id` 고유, 답장을 지우면 같이 지워짐) |
| `kind`, `status` | text/voice, `queued` / `running` / `done` / `failed` / `stt_uncertain` |
| `stt_text`, `stt` | 받아쓰기 원문(불확실해도 남김), `{duration, pieces, problems, seconds, load_seconds, gpu_peak_gb}` |
| `prosody`, `voice`, `voice_mismatch` | `measure_prosody` 결과, `compare_prosody` 결과, 말·목소리 불일치 |
| `llm_raw`, `result`, `level`, `mood` | CLOVA가 돌려준 JSON, 후처리 결과 전체, 조회용 수준·기분 |
| `reply_chars` | CLOVA에 보낸 답장 글(가린 뒤)의 글자 수 (다음 답장의 '평소보다 짧음' 비교) |
| `prompt_id`, `stt_model`, `llm_model` | `v2-6af325`, `BuzzASR/korean`, `HCX-007` (CLOVA 주소의 마지막 부분) |
| `timings` | `{stt, stt_load, prosody, llm, llm_attempts, prompt_tokens, completion_tokens, total}` |
| `error` | 실패 이유 (칸 이름·상태 코드만, 답장 내용·결과 값·키는 넣지 않음) |

- **평소 목소리**: 같은 대상자의 이전 음성 답장 중 `prosody.ok`인 것 (답장 시각 순, `compare_prosody`가 최근 10개를 씀).
- **최근 기록**: 같은 대상자, 이번 답장보다 앞선 `done` 분석 3개.

### 새 표 `reply_analysis_months` (월간 포트폴리오의 'AI가 정리한 한 달' 문장, 16절)

대상자·달마다 1행: CLOVA가 쓴 `summary`, 만들 때의 사실 `fingerprint`(사실이 바뀌면 낡은 것으로 표시), `model`, `created_at`. 분석을 끄거나, 그 달의 답장을 지우거나, 동의를 철회하면 같이 지워요.

### 새 표 `reply_analysis_consents`

철회해도 행을 지우지 않고 `withdrawn_at`만 남겨요. `party`는 `child`(자녀가 켬) / `senior`(시니어가 안내 확인). `version`은 동의할 때의 `REPLY_ANALYSIS_CONSENT_VERSION`이에요. **분석은 지금 버전으로 받은 동의만 인정해요.** 버전을 올리면 예전 동의는 남아 있어도 다시 물어요 (자녀 화면은 '꺼짐', 시니어 화면은 녹음 버튼이 없어지고, 자녀가 다시 켜면 시니어 안내도 다시 보여요).

### 그 밖

- `notifications.reply_id` (색인): 어떤 답장의 알림인지. 새 종류 `reply_check`(살펴보기), `reply_alert`(바로 연락 필요).
- `jobs.type = "reply_analysis"`, `payload = {"reply_id": ...}`, 최대 3번.

## 4. API

### 시니어 공개 대화방 (토큰)

| 메서드·경로 | 동작 |
|---|---|
| `GET /api/watch/{token}/conversation` | 기능이 켜져 있으면 `voice_reply: {available, notice_needed, notice, max_seconds}`를 더해요. 음성 답장 이벤트에는 `kind: "voice"`, `audio_url`, `audio_seconds`가 붙고 **`text`는 항상 `""`** 예요. `analysis`는 절대 넣지 않아요 |
| `POST /api/watch/{token}/voice-notice` | 시니어가 안내를 확인함. 확인 전에 온 답장(글·음성)은 분석하지 않아요 |
| `POST /api/watch/{token}/voice-replies` | multipart `file`, `client_id`(8~80자), `message_id?`. 글 답장과 같은 토큰 재검사·`lock_owner`·속도 제한(1분 10개, 하루 120개, 글·음성 합산)·재시도 규칙. 10MB, 1~180초. 기능 꺼짐 404, 자녀가 안 켠 대화방 403 |
| `GET /api/watch/{token}/replies/{reply_id}/audio` | 같은 대화방의 음성 답장 재생 (`audio/wav`, `no-store`) |

### 자녀 (로그인)

| 메서드·경로 | 동작 |
|---|---|
| `GET /api/conversations/{id}/feed`, `GET /api/conversations/{id}` | 답장 이벤트에 음성 필드와 `analysis`(기능이 켜져 있을 때만, 없으면 `null`) |
| `GET /api/recipients/{id}`, 목록 | 기능이 켜져 있으면 `reply_analysis: {enabled, senior_notice, consent_text, version}` |
| `GET`·`PUT /api/recipients/{id}/reply-analysis` | 켜기(`{enabled: true, agree: true}`, 동의 확인 없으면 400)·끄기(`{enabled: false}`). 기능 꺼짐 404 |
| `POST /api/recipients/{id}/replies/{reply_id}/analysis` | 실패한 분석 다시 정리하기 (`failed`만, 아니면 409) |
| `GET /api/recipients/{id}/replies/{reply_id}/audio` | 음성 답장 재생 |
| `DELETE /api/recipients/{id}/replies/{reply_id}` | 기존 + 음성 파일·분석·그 답장의 알림 |
| `POST /api/notifications/{id}/read` | 알림 하나 읽음 (맨 위 빨간 띠의 '확인했어요') |
| `GET`·`POST /api/recipients/{id}/portfolio` | 답장 살펴보기를 켠 대화방이면 기존 응답에 `analysis_trends`(16절)를 더해요. 보고서에는 저장하지 않고 볼 때마다 계산해요 |
| `POST /api/recipients/{id}/portfolio/analysis-summary?month=YYYY-MM` | 그 달의 사실을 CLOVA로 2~3문장 정리해 저장해요. 정리한 답장 3개 미만·분석 꺼짐 409, CLOVA 실패 503(다시 하면 될 수 있음)·502(키·형식·문장 검사), 기능 꺼짐 404 |
| `GET /api/health` | 기능이 켜져 있으면 `reply_analysis: ok / unreachable`(GPU PC 받아쓰기 서버), `reply_llm: HCX-007 / no_key`(키가 있는지만, CLOVA를 부르지는 않음) |

자녀 화면용 `analysis`는 화면에 그대로 쓰는 값만 보내요. 목소리 측정 숫자는 DB에만 두고 보내지 않아요.

```text
analysis: {
  status, kind, message, notice, can_retry, finished_at,
  level, level_label, summary, mood_text, unsure_text,
  voice_text, voice_down, mismatch_text,                     // 음성 답장만
  signals: [{area: "건강", value: "아픔"}], evidence: [...최대 3개], trend_alerts: [...]
}
```

## 5. 작업 흐름 (워커 `reply_analysis`, `services/replies.py`의 `run`)

1. **넣기**: 답장 저장과 같은 트랜잭션에서, 기능이 켜져 있고 지금 버전으로 받은 자녀·시니어 동의가 모두 있으면 `reply_analyses(queued)`와 작업을 넣어요.
2. **순서**: `jobs.claim`이 답장 분석을 음색 학습처럼 뒤로 미뤄요 (대기 중인 영상 생성·등록·삭제가 먼저). 분석 때문에 기다리는 영상 화면에는 "앞선 작업이 끝나길 기다리고 있어요 (약 N분)"이 보여요. 기준 `replies.EXPECTED_SECONDS` = 60초는 **잰 값이 아니라 추정**이에요 (받아쓰기 약 30초 + 운율 몇 초 + CLOVA 10~20초).
3. **처리**:
   - 답장·분석 행이 없거나 동의가 철회됐으면 그냥 끝. 긴 호출 뒤마다 다시 확인해서, 그사이 지웠거나 껐으면 결과를 버려요.
   - CLOVA 키가 없으면 받아쓰기도 하지 않고 바로 실패 ("CLOVA 키가 없어요").
   - **음성**: 저장된 16kHz WAV → GPU PC `/stt` → 문제 목록이 있으면 `stt_uncertain`으로 끝 (알림 없음) → `text` 채움 → `/prosody` → `compare_prosody(이번, 평소)`.
   - **가리기** (CLOVA Studio 약관상 개인정보를 넣지 않아요): `mask_pii`(전화번호·계좌번호) → 이메일은 `[이메일]`, DB에 있는 이름은 `[이름]`. 가리는 이름은 자녀 계정 이름(성까지 쓴 3~4자 이름은 이름만 쓴 뒤 2자도), 부모님이 자녀를 부르는 이름, 대상자 호칭이 이름일 때예요. '엄마'·'아버지'·'우리 딸' 같은 호칭은 그대로 둬요 (`reply_llm.HONORIFICS`). 편지·최근 기록에도 같은 가림을 해요.
   - **CLOVA 요청**: `POST https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-007`, 헤더 `Authorization: Bearer <키>`, `X-NCP-CLOVASTUDIO-REQUEST-ID: <요청마다 uuid>`.
     ```json
     {"messages": [{"role": "system", "content": "<SYSTEM>"},
                   {"role": "user", "content": "[자녀 편지]\n…\n\n[최근 답장 기록 (오래된 것부터)]\n…\n\n[이번 답장 받아쓰기]\n<가린 답장>"}],
      "responseFormat": {"type": "json", "schema": "<SCHEMA 그대로>"},
      "thinking": {"effort": "none"}, "maxCompletionTokens": 1024,
      "temperature": 0.2, "topP": 0.6, "topK": 0, "repetitionPenalty": 1.05, "seed": 1}
     ```
     형식 강제(Structured Outputs)는 HCX-007만 되고 추론과 같이 못 써서 `thinking.effort`는 `none`이에요. 값은 Kaggle 설정과 같아요 (`reply_analysis.CLOVA_PARAMS`).
   - **응답**: `status.code`가 `"20000"`일 때만 `result.message.content`를 `json.loads` → `check_output`. 토큰 수는 `result.usage`.
   - **후처리**: `voice_mismatch = voice_down and mood in MISMATCH_MOODS` → `postprocess(out, 가린 답장, 최근 기록, voice_mismatch)`. 근거 비교는 CLOVA가 본 글(가린 글)로 해요. 그래서 인용에 `[이름]`이 보일 수 있어요.
   - **알림**: 살펴보기 → `reply_check` "엄마님 답장에 살펴볼 내용이 있어요", 바로 연락 필요 → `reply_alert` "엄마님 답장을 확인하고 바로 연락해 보세요". 요약·받아쓰기는 알림 글에 넣지 않아요.
4. **CLOVA 오류** (`services/reply_llm.py`):

   | 상황 | 동작 |
   |---|---|
   | 연결 끊김·시간 초과(`REPLY_LLM_TIMEOUT` 60초)·429·5xx | 2초, 4초 쉬었다 다시 (모두 3번). 그래도 안 되면 재시도 가능 오류 → 작업 큐가 10초, 20초 뒤 다시 |
   | JSON이 깨짐·`check_output`에 걸림 | seed 2로 한 번만 더. 그래도 안 되면 다시 해도 같은 오류로 실패 |
   | 401·403 | 바로 실패 "CLOVA 키가 없거나 틀렸어요" |
   | 400 | 바로 실패 "CLOVA 요청 형식이 맞지 않아요" |
   | 그 밖의 4xx, 200인데 `status.code`가 20000이 아님 | 바로 실패 "CLOVA 요청이 실패했어요" |

   끝내 실패하면 `failed` → 자녀 화면에 "답장을 정리하지 못했어요"와 '다시 정리하기'.
5. **로그**: 요청 ID, 상태 코드, 걸린 시간, 토큰 수만 남겨요. 편지·답장·결과·키는 남기지 않아요.

## 6. GPU PC 분석 서버 (받아쓰기·운율)

| 파일 | 내용 |
|---|---|
| `backend/gpu_worker/reply_audio.py` | 정답지의 받아쓰기 자르기·품질 검사·운율 측정 그대로 |
| `backend/gpu_worker/reply_stt.py` | 받아쓰기 자식 프로세스: BuzzASR 올림 → `run_stt` → 결과 JSON → 내림 → 끝 |
| `backend/gpu_worker/reply_analysis_server.py` | FastAPI :8400 (`127.0.0.1`만). 요청은 잠금으로 하나씩. `--gpu-report` |
| `backend/gpu_worker/reply_demo_upload.py` | 시험용: 직접 녹음한 WAV를 공유 링크로 음성 답장처럼 차례로 보내기 |
| `backend/gpu_worker/requirements-reply.txt` | `Wemeet-reply` 환경 패키지 (LLM 관련 없음) |

| 경로 | 입력 → 출력 |
|---|---|
| `GET /health` | `{ok, stt_model, busy}` (LLM 파일이 없어도 정상) |
| `POST /stt` | 16kHz WAV → `{text, duration, pieces, problems, seconds, load_seconds, process_seconds, model}` |
| `POST /prosody` | WAV + 받아쓰기 → `measure_prosody` 결과 + `seconds` |

- 받아쓰기는 요청마다 **자식 프로세스**가 BuzzASR(약 3.1GB)를 올려 받아쓰고 끝나요. 프로세스가 끝나야 CUDA 컨텍스트까지 돌아와서, 바로 다음 영상 작업 자리가 남아요. TTS·영상 서버가 잡은 7GB 옆 남은 자리에 들어가요.
- 서버 프로세스는 CUDA를 쓰지 않아서 요청이 끝나면 분석 서버가 잡은 GPU 메모리는 0이에요. 운율은 CPU(librosa)이고, 서버가 켜질 때 한 번 미리 돌려 첫 호출 지연을 없애요.
- 음성·받아쓰기는 로그에 남기지 않고, 받은 음성은 요청이 끝나면 지워요.
- 파이썬 환경은 따로 써요 (`Wemeet-reply`): 영상 환경(Wemeet-float: torch 2.0.1, transformers 4.46.3 고정)·TTS 환경과 버전이 겹치지 않게.
- 로컬 LLM(llama.cpp 빌드, GGUF, `-ngl` 자동 계산, `--check-llm`·`--compare-full`·`--bench`)은 2026-11-16에 지웠어요.

## 7. 서비스에서 켜는 순서

1. **CLOVA 키 확인** (백엔드가 도는 곳에서. 가짜 답장 한 줄만 보내요):
   ```powershell
   cd backend
   python -m app.services.reply_llm --ping
   ```
   "성공: …초, 시도 1번, 토큰 …"과 가짜 답장의 판단이 나오면 키·주소·형식이 맞아요. "CLOVA 키가 없거나 틀렸어요"면 키를, "요청 형식이 맞지 않아요"면 HCX-007 사용 권한·주소를 확인해요.
2. **GPU PC** (음성 답장의 받아쓰기·운율):
   ```powershell
   conda create -n Wemeet-reply python=3.11 -y
   $py = "$env:USERPROFILE\miniconda3\envs\Wemeet-reply\python.exe"
   & $py -m pip install torch --index-url https://download.pytorch.org/whl/cu124
   & $py -m pip install -r backend/gpu_worker/requirements-reply.txt
   ```
   `backend/.env`에 `REPLY_ANALYSIS_PYTHON=<위 python 경로>`를 넣고 `npm run gpu` → 분석 서버(:8400)와 게이트웨이 `/analysis`가 같이 떠요. BuzzASR은 첫 받아쓰기 때 자동으로 받아요 (약 3GB). 이후 `tailscale serve --bg 8200`은 기존과 같아요.
3. **Azure** (`infra/params.local.json` → `.\infra\deploy.ps1`):
   - `replyAnalysisEnabled: true`
   - 키: `naverApiKey`(대본과 같은 키) 또는 따로 `replyLlmApiKey`
   - 게이트웨이 주소 `gpuGatewayUrl`은 기존 값 그대로 (`REPLY_ANALYSIS_URL=${gpuGatewayUrl}/analysis`, 토큰은 `gpu-token`)
   - CLOVA는 워커가 바로 불러요 (`NO_PROXY`에 `clovastudio.stream.ntruss.com`이 이미 있어요)
   - 로컬에서 띄울 때는 `backend/.env`에 `REPLY_ANALYSIS_ENABLED=true`와 `REPLY_LLM_API_KEY`(비우면 `NAVER_API_KEY`)
4. **자녀 화면**: 대화방 위쪽 **답장 살펴보기** → 동의 상자 체크 → 켜기. 시니어가 처음 답장할 때 안내를 확인하면 그때부터 분석해요.
5. **확인**: 글 답장 하나 → 카드가 '분석 중' → 완료. 음성 답장은 시니어 화면의 '말로 답하기'로. 미리 녹음한 파일로 시험할 때는 `reply_demo_upload.py` — **AI Hub 음성(reply-demo10)은 외부 서비스로 보내면 안 되는 조건이 있으니, CLOVA로 분석하는 시연에는 직접 녹음한 음성을 쓰세요** (스크립트도 실행할 때 이 경고를 보여 주고 확인을 받아요).

## 8. 화면

### 시니어 `/w/[token]` (큰 글씨, 단계 적게)

- 자녀가 답장 살펴보기를 켠 대화방에만 **말로 답하기** 큰 버튼이 생기고, 그 아래 "또는 글로 쓰기"로 지금 화면이 이어져요. 꺼진 대화방은 지금 화면 그대로예요.
- 처음 한 번 안내 + "알겠어요": "보내 주신 목소리와 답장은 ○○님께 전달돼요. 답장 글(음성은 받아쓴 글)을 네이버 클로바(CLOVA Studio) AI로 보내 정리하고, 정리한 내용은 ○○님께만 보여 드려요. 음성 파일은 보내지 않아요. 진단이 아니에요." 확인하지 않아도 글 답장은 보낼 수 있고, 분석만 하지 않아요.
- 말로 답하기: 눌러서 말하기 → 녹음 중(경과 시간 / 3:00, 소리 크기 막대, 큰 "다 했어요", 3분이면 저절로 멈춤) → "다시 듣기 / 다시 하기 / 보내기".
- 보낸 음성 답장은 "내가 남긴 음성 답장 · 0:42"와 큰 재생 버튼. **받아쓰기와 분석 결과는 어디에도 보이지 않아요.**

### 자녀 `/conversations/[id]`

- 위쪽 **답장 살펴보기 켜짐/꺼짐** 버튼 → 설명·동의 상자·켜기/끄기. 동의 상자 문구: "부모님이 보낸 답장을 AI가 정리해 나에게만 보여 주는 것을 부모님께 알리고 동의를 받았어요. 답장 글(음성 답장은 자동 받아쓰기 글)을 네이버 클로바(CLOVA Studio) AI로 보내 분석해요. 음성 파일과 목소리 값은 보내지 않고, 이름·전화번호는 가려서 보내요. 정리한 내용은 진단이 아니에요. 끄면 지금까지의 분석 결과를 지워요."
- 음성 답장 말풍선: 재생 버튼 + "자동 받아쓰기 · 틀린 글자가 있을 수 있어요" + 받아쓰기.
- 분석 카드: 분석 중 / 실패(+ 다시 정리하기) / 받아쓰기 불확실 / 완료(수준 배지 · 요약 · 기분 문구 · 목소리 한 줄 · 불일치 강조 · 확인해 볼 것 · 지난 답장과 비교 · 안내 문구).

| 원래 값 | 화면 |
|---|---|
| 수준 없음 / 살펴보기 / 바로 연락 필요 | 평소와 같아요 / 살펴보기 / 바로 연락해 보세요 |
| 밝음 / 평온 / 가라앉음 / 걱정·불안 / 서운함·짜증 / 판단 어려움 | 밝아 보여요 / 평온해 보여요 / 기운이 없어 보여요 / 걱정이 있어 보여요 / 서운해 보여요 / 기분은 판단하기 어려워요 |
| 확신도 애매 | AI 판단이 확실하지 않아요 |
| 불일치 | 말은 괜찮다고 하시지만 목소리가 평소보다 처져 있어요. 한번 연락해 보세요. |
| 받아쓰기 불확실 | 말소리가 잘 들리지 않아 내용을 정리하지 못했어요. 직접 들어 보세요. |

### 알림

- 살펴보기 → `reply_check`, 바로 연락 필요 → `reply_alert` (벨·토스트·기존 브라우저 알림). `reply_alert`는 읽기 전까지 로그인 화면 맨 위 **빨간 띠**로 보여요. 외부 알림 서비스는 쓰지 않아요.

## 9. 동의·삭제·외부로 나가는 것

- **기능 스위치** `REPLY_ANALYSIS_ENABLED` (기본 false). 꺼져 있으면 녹음 버튼 없음, 음성 업로드·안내·켜기 경로 404, 분석 작업 없음, API 응답에 새 칸 없음 → 지금과 똑같아요 (시험으로 확인).
- **동의**: 자녀가 대상자별로 켤 때 + 시니어가 처음 답장할 때 안내 확인. 둘 다 **지금 문구 버전(`REPLY_ANALYSIS_CONSENT_VERSION`, 기본 `2026-11-clova`)으로** 받아야 분석해요. 2026-11-16에 CLOVA로 보낸다는 내용이 들어가면서 버전을 올려서, 그 전의 동의는 다시 받아요.
- **CLOVA로 보내는 것**: 판단 기준, 자녀 편지(영상 대본), 최근 분석 기록 3개(`history_text`: 날짜·기분·수준·신호·요약), 가린 답장 글. 월간 포트폴리오의 한 달 정리에는 답장 원문 없이 답장마다 AI가 만든 요약·분류와 센 숫자만 보내요(16절). **보내지 않는 것**: 음성 파일, 목소리 값, 사용자·대상자 ID, 이메일, DB에 있는 이름, 전화번호·계좌번호.
- **분석 끄기** (대상자별): 두 동의를 철회하고, 대기 중인 분석을 취소하고, 분석 결과·분석 알림을 지워요. 답장과 음성은 남겨요.
- **답장 하나 지우기**: 음성 파일 + 분석 + 그 답장의 알림.
- **동의 철회** `POST /api/consent/withdraw`: 기존 삭제에 더해 음성 답장 파일, `reply_analyses`, 분석 알림, 답장 분석 동의까지. 삭제 기록에 `reply_audio_files`, `reply_analyses`, `analysis_notifications` 건수를 남겨요. CLOVA 쪽에는 우리가 남기는 것이 없어요 (요청할 때만 보냄).
- **GPU PC**는 받은 음성을 요청이 끝나면 바로 지워요.
- **월별 포트폴리오**: 받아쓰기가 없는 음성 답장은 대표 답장에서 빼고, 음성 답장 인용에는 `voice: true`와 받아쓰기 오류 안내를 붙여요.
- **다음 영상 대본** (14절 5번): 확실한 받아쓰기는 글 답장처럼 대본 맥락에 들어가서 `NAVER_API_KEY`가 있으면 CLOVA(대본용 HCX-003)로 나가요. 분석 결과·목소리 값·음성 파일은 넣지 않아요.

## 10. 시험

```powershell
python -m unittest discover -s backend/tests -v      # 전체 128개 (이 PC에서 통과)
python -m compileall -q backend/app
npx.cmd --no-install tsc --noEmit; npm.cmd run lint; npm.cmd run build
```

| 파일 | 내용 |
|---|---|
| `backend/tests/test_reply_rules.py` (31개) | `PROMPT_ID == "v2-6af325"`, 대화 형식·프롬프트 칸, Kaggle 옵션·`CLOVA_PARAMS`·형식 강제가 지원하는 키워드만 쓰는지, 근거 지우기, 신호·불일치 → 살펴보기, 바로 연락 → 애매, 가라앉음 3번, 흐름 경고 4가지, 기록 중, 목소리 처짐 문장, 화면 문구, `check_output`, 받아쓰기 규칙, 이름·이메일 가림(호칭은 그대로), LLM 파일 없이 분석 서버 `/health` 정상 |
| `backend/tests/test_reply_analysis.py` (14개) | 가짜 분석 서버·가짜 CLOVA(httpx `MockTransport`)로: 기능 꺼짐이면 지금과 같음, 음성 답장 5개(기록 중 → 처짐·불일치, CLOVA에 목소리 정보·전화번호 없음, 공개 API에 분석·받아쓰기 없음), 받아쓰기 불확실, 글 답장 바로 연락, 접근 차단, 업로드 제한·재시도·속도 제한, 실패 재시도·다시 정리하기, 철회 삭제, 하나 지우기·분석 중 끄기, **CLOVA 요청 본문·헤더·이름 가림**, **깨진 JSON → seed 2, 429 → 다시, 401·400·20000 아님 → 바로 실패**, **GPU PC 없이 글 답장·키 없으면 받아쓰기 전에 실패**, **동의 버전을 올리면 다시 묻기**, **한 달의 변화(흐름·이어진 이야기·목소리·지난달 비교·안부) 계산, CLOVA 한 달 정리에 원문이 없는지, 낡음 표시, 진단 같은 말 거르기, 답장 지우기·분석 끄기·기능 꺼짐** |

자동 시험은 GPU·외부 서비스 없이 임시 DB·임시 미디어·고정 시계로 돌아요. 실제 CLOVA 호출은 7절 `--ping`으로 확인해요.

## 11. 환경 변수

| 변수 | 기본 | 어디 | 뜻 |
|---|---|---|---|
| `REPLY_ANALYSIS_ENABLED` | false | 백엔드 | 기능 스위치 (Azure: `replyAnalysisEnabled`) |
| `REPLY_ANALYSIS_URL` | http://127.0.0.1:8400 | 백엔드 | GPU PC 받아쓰기 서버 (Azure: 게이트웨이 `/analysis`) |
| `REPLY_ANALYSIS_API_KEY` | (없음) | 백엔드 | 게이트웨이를 거칠 때 `GPU_GATEWAY_TOKEN` |
| `REPLY_ANALYSIS_TIMEOUT` | 600 | 백엔드 | 받아쓰기 서버 응답 대기(초) |
| `REPLY_ANALYSIS_CONSENT_VERSION` | 2026-11-clova | 백엔드 | 동의·안내 문구 버전. 바꾸면 다시 묻는다 |
| `REPLY_LLM_ENDPOINT` | https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-007 | 백엔드 | CLOVA 주소 (대본용 `HCX_ENDPOINT` v1과 따로) |
| `REPLY_LLM_API_KEY` | (비우면 `NAVER_API_KEY`) | 백엔드 | CLOVA Studio 키 (Azure: `replyLlmApiKey` 또는 `naverApiKey`) |
| `REPLY_LLM_TIMEOUT` | 60 | 백엔드 | CLOVA 응답 대기(초) |
| `REPLY_ANALYSIS_PYTHON` | (없음) | GPU PC | `Wemeet-reply` 환경 python (`npm run gpu`·`dev:all`이 씀) |
| `REPLY_ANALYSIS_PORT` | 8400 | GPU PC | 분석 서버 포트 |
| `REPLY_STT_MODEL` | BuzzASR/korean | GPU PC | 받아쓰기 모델 |
| `REPLY_GPU_INDEX` | 0 | GPU PC | `--gpu-report`의 `nvidia-smi -i` |
| `GATEWAY_ANALYSIS_URL` | http://127.0.0.1:8400 | GPU PC | 게이트웨이 `/analysis` 대상 (`npm run gpu`가 넣음) |

2026-11-16에 지운 변수: `REPLY_LLAMA_SERVER`, `REPLY_LLM_GGUF`, `REPLY_LLM_NGL`, `REPLY_LLM_CTX`, `REPLY_LLM_THREADS`, `REPLY_LLM_GPU_MARGIN_GB`, `REPLY_LLM_PORT`, `REPLY_LLM_LOAD_TIMEOUT`.

## 12. 참고 파일과 달라진 점 (판단 기준·후처리·운율 규칙의 값은 그대로)

1. LLM: 로컬 SEED Think 14B(llama-server, `json_schema`) → CLOVA Studio HCX-007(Structured Outputs). 판단 기준(`SYSTEM`)과 JSON 틀(`SCHEMA`), temperature 0.2·topP 0.6·반복 1.05·seed 1은 그대로예요. 대화 형식은 `build_prompt`(SEED 전용 토큰) 대신 CLOVA의 `messages`(system 1개 + user 1개)예요.
2. CLOVA로 보내기 전에 이메일·DB에 있는 이름을 가려요 (참고 파일에는 `mask_pii`만 있음). 후처리의 근거 비교도 가린 글로 해요.
3. 받아쓰기가 불확실하면 운율도 재지 않고 끝내요 (노트북은 쟀어요).
4. 받아쓰기 모델을 요청마다 자식 프로세스에서 올리고 내려요.
5. 편지(질문)는 답장이 가리킨 영상 대본, 없으면 그 전 마지막 승인 영상 대본이에요.
6. 글 답장도 칸 이름 `[이번 답장 받아쓰기]`를 그대로 써요.
7. 답장 사이의 순서는 답장 저장 시각 기준이에요.

## 13. 잰 값 (서비스에서 채움)

| 항목 | 값 |
|---|---|
| CLOVA 응답 시간·토큰 수 (`--ping`, 실제 답장 몇 개) | |
| 음성 답장 1개 (받아쓰기 / 운율 / CLOVA / 합계) | |
| 받아쓰기 뒤 GPU 메모리가 돌아오는지 (`--gpu-report` 전·후), 바로 이은 영상 생성 결과 | |
| Wemeet-reply 주요 버전 (torch, transformers, librosa) | |

## 14. 정한 것

| 날짜 | # | 질문 | 정한 것 |
|---|---|---|---|
| 2026-11-12 | 1 | 동의를 어디서 받을지 | 둘 다: 자녀가 대상자별로 켤 때 + 시니어가 처음 답장할 때 안내 확인 |
| 2026-11-12 | 2 | 바로 연락 필요 알림 방식 | 앱 알림 + 맨 위 빨간 띠 (외부 알림 서비스 없음) |
| 2026-11-12 | 3 | 시니어 화면에 받아쓰기 글 | 보여 주지 않음 (재생만, 공개 API에도 없음) |
| 2026-11-12 | 4 | 글 답장도 분석 | 예 |
| 2026-11-12 | 5 | 받아쓰기를 다음 영상 대본(CLOVA)에 | 넣음 (확실한 받아쓰기만, 분석 결과는 넣지 않음) |
| 2026-11-12 | 6 | GPU PC 작업 | 코드·자동 시험은 개발 PC에서, GPU PC는 직접 |
| **2026-11-16** | 7 | LLM을 어디서 돌릴지 | **LLM을 HCX-007 API로 변경 (GPU 부족). 판단 기준·후처리는 그대로.** 받아쓰기·운율은 GPU PC에 그대로. 답장 글을 CLOVA로 보내게 돼서 동의 문구를 고치고 버전을 `2026-11-clova`로 올림 (예전 동의는 다시 받음). 이름·이메일·전화번호는 가려서 보냄 |

## 15. 남은 일

- 서비스에서 `--ping`과 실제 답장으로 CLOVA 응답 시간을 재고 13절 채우기, `EXPECTED_SECONDS`(지금 60초 추정) 고치기
- HCX-007의 판단이 Kaggle의 SEED 14B 결과와 얼마나 같은지 직접 녹음한 시험 답장으로 비교하기 (판단 기준은 같지만 모델이 달라요)
- 운율 기준값(`Z_CUT` 등)은 첫 버전 추정값이에요. 실제 부모님 답장이 쌓이면 다시 봐요
- 화면을 실제 브라우저·휴대폰(특히 iPhone Safari 녹음 mp4)으로 확인하기
- 이름 가림은 DB에 있는 이름만 가려요. 답장 속 다른 사람 이름(이웃·친구 등)은 가리지 못해요
- `infra/main.bicep`은 이 PC에 Azure CLI가 없어 `az bicep build`로 검사하지 못했어요. 배포 전에 한 번 돌려 주세요

## 16. 월간 포트폴리오: AI가 정리한 한 달의 변화 (2026-11-16, 2026-11-25·26 고침)

화면 순서: 한 달의 이야기(달 고르기·작성) → 월별 기록 → **포트폴리오 제목 카드**('엄마님의 2026-11 대화 포트폴리오', 요약·답글 수·대화한 날·내용 복사·파일로 저장) → AI가 정리한 한 달의 변화(답장 살펴보기를 켠 방) 또는 한 달 흐름 캘린더(꺼진 방) → 안내 문구.

2026-11-25: 키워드 포트폴리오의 '자주 나눈 이야기·날짜별 대화 흐름·기억하고 싶은 답글·다음 안부에는 이런 말을'을 지웠어요(다른 칸과 겹쳐서). 새 보고서는 `local_evidence_v2`(제목·요약·답글 수·대화한 날·안내만)이고, 예전에 저장한 v1 보고서의 그 칸은 화면이 쓰지 않아요.

'AI가 정리한 한 달의 변화'는 `services/reply_month.py`, 화면은 `MonthChanges.tsx`·`MonthCalendar.tsx`·`LevelDonut.tsx`예요.

| 칸 | 만드는 법 |
|---|---|
| AI 정리 문장 | 아래 사실만 CLOVA HCX-007에 보내 2~3문장으로. 사실이 바뀌면 "다시 정리하면 반영돼요". 포트폴리오를 열 때 없거나 낡았으면 화면이 한 번 자동으로 만들어요 |
| 한 달 흐름 (캘린더) | 날짜마다 그날 **해결되지 않은** 답장 중 가장 높은 수준의 색(평소와 같아요·살펴보기·바로 연락해 보세요, 정리 전은 회색). 그날 살펴볼 답장이 모두 해결 완료면 **해결 완료**(파랑, ✓). 칸 안 숫자는 그날 답장 수, 목소리가 처졌거나 말과 목소리가 달랐던 날은 🎤. **날짜를 누르면 아래에 그날 답장**(답장마다 단계·AI 한 줄 요약·갈래·음성 여부, 날짜 옆에 단계·답장 수는 안 씀)이 열리고 '그날 대화 보기'로 대화방에 가요. 처음에는 해결되지 않은 가장 높은 수준의 최근 날을 보여 줘요. 분석이 꺼진 방도 캘린더는 보여요(색 없이 답장 수만, 누르면 바로 대화방) |
| 이번 달 답장 상태 (원형 그래프) | 캘린더 옆. 정리한 답장의 평소와 같아요·살펴보기·바로 연락해 보세요·**해결 완료** 수와 비율, 정리 전 답장 수 (`levels`). 해결 완료된 답장은 원래 수준에서 빼서 해결 완료로 세요. 색은 캘린더와 같은 계열을 진하게 한 것이고(dataviz 팔레트 검사 통과), 옆 목록에 이름·수·비율을 늘 같이 써요 |
| 이번 달 나눈 이야기 | CLOVA가 정리 문장과 같은 요청에서 답장을 **다섯 갈래**(건강 · 마음·외로움 · 생활·안전 · 가족 · 일상, `CATEGORIES`)로 나누고, 갈래마다 **상태**(이어지는 중 · 나아지는 중 · 해결 완료 · 평소 이야기)와 **흐름 단계** 1~4개(답장 번호 + 2~10자 이름, 예: 무릎 통증 시작 → 정형외과·약 → 계단 오를 만큼)를 골라요. 카드에는 아이콘·갈래·답장 수·상태 배지·흐름 점(점 색은 그 답장의 단계)만 보여요(요약 문장·인용·다음 안부는 2026-11-26에 뺐어요). 지금 신경 쓸 이야기(이어지는 중 → 나아지는 중 → 해결 완료 → 평소 이야기)부터 보여요. 카드를 누르면 캘린더에서 그 갈래의 날만 진하게 보여요 |
| 지난달과 비교 | 살펴보기 이상, 바로 연락 필요 횟수, 지난달과의 차이(+3 등). 답장 수·음성 답장 수 줄과 '목소리 흐름' 칸은 2026-11-26에 뺐어요(캘린더·원형 그래프와 겹쳐서). CLOVA에 보내는 사실에는 답장 수·목소리 횟수가 그대로 들어가요. 두 달 중 평소 목소리와 비교한 음성 답장이 있으면 **목소리 줄**: 평소보다 처진 답장, 말과 목소리가 다른 답장, 운율 항목별(말이 느려진·목소리가 작아진·목소리가 낮아진·높낮이가 단조로워진·자주 멈춘 답장, 두 달 다 0이면 숨김). 기록 중·측정 못 함 답장은 세지 않아요. 답장 길이(가운데 값)가 0.7배 미만이면 "짧아졌어요", 1.3배 넘으면 "길어졌어요" (양쪽 2개 이상일 때만) |
| 이번 달 이야기로 건넬 안부 | 같은 신호 값마다 정한 안부 문장 (최대 3개, `STARTERS`). '죽음·살기 싫다는 말'에는 자살예방 상담전화 109 안내 |

- **API**: `GET /api/recipients/{id}/portfolio`의 `calendar`(답글이 있는 날의 답글 수, 모든 방)와 `analysis_trends.days`(날짜별 수준·`resolved`, 켠 방), `analysis_trends.levels`(원형 그래프, `resolved` 포함), `analysis_trends.replies`(그날 답장: 단계·AI 요약·갈래), `analysis_trends.compare.rows[].group`(`답장`/`목소리`). `analysis_trends.topics`는 갈래 묶음(`name, status, count, dates, steps: [{date, label, level, resolved}]`).
- **규칙**: 정리한 답장이 3개 미만이면 문장·주제 묶음은 만들지 않고 "아직 정리한 답장이 적어…"만 보여요. 화면 문구는 답장 카드와 같은 표예요.
- **CLOVA로 보내는 것**: 부르는 말(호칭이 이름이면 "부모님"), 달, 답장 수, 지난달 비교, 답장마다 번호·날짜·수준·기분·신호·목소리 상태·AI 요약, 같은 신호가 나온 횟수, 목소리 횟수. **답장 원문·인용은 보내지 않아요.** 이름은 `[이름]`으로 가려요.
- **JSON 틀**: `{summary, topics: [{name(다섯 갈래 enum), status(네 상태 enum), replies: [번호], steps: [{reply, label}]}], resolved: [{reply, by}]}` (갈래 최대 5개, 단계 최대 4개, `maxCompletionTokens` 1000). 번호는 서버가 답장 ID로 바꿔 저장해요(`reply_analysis_months.topics`, `resolved`는 해결된 답장 ID 목록).
- **해결 완료** (2026-11-27 고침): CLOVA가 답장 흐름(답장마다 AI 요약)을 읽고 '살펴보기' 이상이었던 답장(reply)과, 그 일이 끝났다고 알려 준 뒤 답장(by)을 짝으로 골라요. 코드가 한 번 더 봐요: reply는 살펴볼 일, by는 reply보다 뒤에 온 '평소와 같아요' 답장이어야 하고, by 뒤에 같은 신호(칸·값, 예: 건강 아픔)가 다시 살펴볼 일로 나오면 끝나지 않은 것으로 봐요. **갈래는 보지 않아요**("이제 괜찮아" 같은 답장은 신호가 없어 다른 갈래로 갈 수 있어서). 프롬프트에도 "신호가 없어도 앞 걱정의 뒷이야기면 그 일의 갈래에 넣는다"를 넣었어요. 갈래 상태도 맞춰요: 살펴볼 답장이 없으면 평소 이야기, 모두 해결이면 해결 완료, 남았는데 해결 완료라고 하면 나아지는 중, 남았는데 평소 이야기라고 하면 이어지는 중. 해결 완료는 한 달 정리를 만들 때 정해지므로, 해결을 알려 준 답장이 온 뒤 포트폴리오를 열면(낡은 정리를 자동으로 다시 만들 때) 반영돼요. 답장 카드·알림·맨 위 빨간 띠, '지난달과 비교'의 횟수는 처음 판단 그대로예요.
- **검사**: 정리 문장은 한글 10자 이상, 500자 이하, "진단·우울증·치매·점수·질환·장애"가 없어야 해요. 갈래는 없는 번호·이미 다른 갈래에 든 번호를 빼고, 다섯 갈래가 아닌 이름은 버리고, 같은 갈래가 두 번 오면 합쳐요. 흐름 단계는 그 갈래 답장만, 이름이 2~14자이고 금지어가 없는 것만 받아요. 답장이 많은 갈래부터 저장해요. 쓸 수 있는 갈래가 하나도 없거나 문장이 걸리면 seed 2로 한 번 더 하고, 그래도면 저장하지 않아요(502).
- **확인 명령**: 새 JSON 틀(주제 묶음)을 CLOVA가 받아 주는지는 실제로 불러 봐야 알아요. `cd backend; python -m app.services.reply_month --ping` (가짜 사실 몇 줄만 보내요).
- **저장과 삭제**: 사실은 저장하지 않고 볼 때마다 계산해요. 문장·주제 묶음만 `reply_analysis_months`(`summary`, `topics`)에 저장하고, 분석 끄기·그 달 답장 지우기·동의 철회 때 지워요(철회 기록 `analysis_month_summaries`). 이 기능 전에 만든 정리는 판단 기준이 바뀌어 낡은 것으로 보이고, 포트폴리오를 열면 주제 묶음까지 다시 만들어요.
- 포트폴리오의 텍스트 내려받기(내용 복사·파일로 저장)에는 넣지 않아요.


## 17. 얼마나 맞는지 재기 (2026-11-17)

실험 도구는 `backend/evals/`에 있어요. 서비스 이미지(`backend/app`)에는 들어가지 않아요.

### CLOVA 오답률 (`evals/reply_eval.py`)

CLOVA는 답장마다 한 번만 부르고, 같은 결과로 세 단계를 채점해요.

| 단계 | 수준을 정하는 것 |
|---|---|
| ① CLOVA 그대로 | CLOVA가 고른 수준 |
| ② + 코드 보정 | `postprocess` (없는 근거 지우기, 신호가 있는데 '없음'이면 살펴보기) |
| ③ + 코드 보정 + 운율 | 말·목소리 불일치면 살펴보기 (음성 답장만. 글 답장은 ②와 같아요) |

- **재는 값**: 수준이 틀린 비율, 놓친 비율(정답 살펴보기 이상인데 '없음'), 괜한 알림 비율(정답 없음인데 살펴보기 이상), '바로 연락 필요'를 낮게 본 비율, 칸별 일치율. 비율마다 95% 범위(윌슨 구간)를 같이 적어요. 답장이 적으면 범위가 넓어요.
- **서비스와 다른 점**: 최근 답장 기록을 넣지 않고 답장마다 따로 판단해요.
- **시험 세트**
  - 글: `evals/reply_eval_text.csv`. 직접 쓴 답장 80개예요 (없음 40 · 살펴보기 30 · 바로 연락 필요 10). 가정 질문, 농담, 끝난 일, 남의 이야기, 짧은 답, '괜찮아' 하면서 신호가 있는 답, 돌려 말한 죽음 표현을 넣었어요.
  - 정답은 Claude가 판단 기준서(SYSTEM)대로 단 **초안**이에요. 팀 두 명이 보고 고친 뒤 `check_1`·`check_2`에 이름을 적어요. 비어 있으면 보고서 맨 위에 "초안 정답 기준"이라고 나와요.
  - 음성: `evals/reply_eval_voice_template.csv` 형식이에요. 한 사람이 12개를 녹음해요. 1~4번은 평소 목소리를 쌓는 녹음이고, 나머지는 평소 목소리와 처진 목소리(작게·느리게·낮게·힘없이)를 섞어요. 같은 휴대폰, 같은 거리(입에서 한 뼘), 조용한 곳에서 wav로 녹음해요. 처진 목소리인데 말은 괜찮은 답장의 정답은 설계대로 '살펴보기'예요.
- **AI Hub 음성은 넣지 않아요** (외부 서비스 전송 금지 조건). CLOVA로 보내도 되는, 직접 만든 답장만 써요.
- **실행** (CLOVA 키가 있는 PC, backend 폴더):
  ```
  python -m evals.reply_eval --set evals/reply_eval_text.csv --out <결과 폴더>
  python -m evals.reply_eval --set <음성 세트.csv> --out <결과 폴더>   # 분석 서버(REPLY_ANALYSIS_URL)도 필요
  python -m evals.reply_eval --set ... --out ... --score-only          # 정답만 고친 뒤 다시 채점 (CLOVA 안 부름)
  ```
- 결과는 `report.md`, `results.csv`, `cache.jsonl`(CLOVA 결과·받아쓰기·운율)에 써요. 화면에는 답장 번호와 수준만 찍어요. 시험 `backend/tests/test_reply_eval.py`(가짜 CLOVA·가짜 분석 서버).
