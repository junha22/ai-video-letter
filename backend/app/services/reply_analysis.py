"""부모님 답장 분석 규칙: 판단 기준·JSON 틀, 후처리, 운율 평소 비교, LLM 대화 형식, 자녀 화면 문구 (docs/REPLY_ANALYSIS.md).

정답지는 Kaggle 실험에서 확정한 reply_analysis_reference.py다. 값과 동작을 바꾸지 않는다.
예외 하나 (2026-11-27, 사용자 결정): postprocess에 "신호가 없는데 살펴보기면 없음으로 내림"을 더했다 (CLOVA HCX-007 대응).
프롬프트나 JSON 틀을 고치면 PROMPT_ID가 바뀐다 (backend/tests/test_reply_rules.py가 알려 준다).
받아쓰기·운율 측정·LLM 실행은 GPU PC의 분석 서버(gpu_worker/reply_analysis_server.py)가 하고, 여기서는 판단 규칙만 다룬다.
LLM에는 목소리 정보를 넣지 않는다. 목소리는 compare_prosody(코드 규칙)로만 판단한다.
"""

import hashlib
import json
import re

import numpy as np

# ---------------------------------------------------------------- 판단 기준 + JSON 틀 ----
MOODS  = ["밝음", "평온", "가라앉음(쓸쓸·우울)", "걱정·불안", "서운함·짜증", "판단 어려움"]
HEALTH = ["없음", "아픔", "넘어짐·다침", "병원·약", "식사·잠 문제", "기타 건강"]
MIND   = ["없음", "외로움", "의욕 없음", "짐이 된다는 말", "죽음·살기 싫다는 말", "기타 마음"]   # 라벨 시트의 따옴표 붙은 '짐이 된다 같은 말'과 같은 항목 (JSON 강제 때 따옴표는 실수 지점이라 뺌)
LIFE   = ["없음", "돈 문제", "사기 의심", "혼자 해결 못 하는 일", "기타 생활"]
LEVELS = ["없음", "살펴보기", "바로 연락 필요"]
CHANGES = ["이전 기록 없음", "비슷함", "나아짐", "나빠짐"]

SYSTEM = """너는 자녀에게 부모님 음성 답장의 상태를 알려 주는 분석가다. 입력은 자녀가 보낸 편지(질문), 부모님의 최근 답장 기록, 이번 답장의 받아쓰기(STT) 결과다. 받아쓰기에는 사투리와 오타가 있을 수 있다.
[흐름으로 판단] 위험한 단어가 있는지가 아니라 답장 전체의 흐름으로 판단한다. 문장 하나하나는 평범해도 합치면 걱정되는 경우를 신호로 본다(예: 식사를 대충 함 + 하고 싶은 게 없음 + "엄마 신경 쓰지 마"). "괜찮아"라는 말이 있어도 내용에 문제가 있으면 신호를 지우지 않는다. 반대로 무서운 단어가 있어도 농담·옛날 일·가정이면 신호가 아니다.
[돌려 말하는 표현] 죽음이나 삶을 끝내는 뜻을 돌려 말하는 것도 "죽음·살기 싫다는 말"로 본다(예: "이제 다 정리해야지", "오래 살아서 뭐 해", "이제 너희 걱정 안 하게 해 줄게", "갈 때가 됐지").
[기분] 말하는 지금의 기분 하나: 밝음(즐겁고 신남) / 평온(담담함, 일상 이야기) / 가라앉음(쓸쓸·우울: "그냥 그렇지", 혼자) / 걱정·불안("어떻게 해야 될지") / 서운함·짜증(섭섭함, 탓하는 말) / 판단 어려움(너무 짧거나 정보만 있음). 옛날 힘든 일을 웃으며 말하면 밝음이나 평온. 두 기분이 섞이면 더 길게, 더 강하게 드러난 쪽 하나. 말이 충분히 길고 담담하면 판단 어려움이 아니라 평온.
[위험 신호] 지금 또는 최근(약 한 달) 일이고 아직 끝나지 않은 것만. 오래전에 끝난 일, "만약에" 같은 가정, 일반 상식, 질문 주제만으로는 신호가 아니다. 종류마다 가장 중요한 것 하나, 없으면 "없음".
- 건강(본인의 몸): 아픔("요즘 무릎이 아파서 못 걸어") / 넘어짐·다침("지난달에 넘어져서 깁스 했어", 예전에 다쳤어도 지금까지 불편하면 포함) / 병원·약(지금 치료를 받거나 약을 먹는 문제) / 식사·잠 문제("입맛이 없어서 잘 안 먹어", "밤에 자꾸 깨") / 기타 건강. 일반 상식("감기는 따뜻하게 하면 나아")은 제외.
- 마음(지금 힘든 마음): 고르는 뜻은 다음과 같다.
  외로움 = 혼자 지내 쓸쓸하거나 말할 사람·찾아오는 사람이 없음("하루 종일 말할 사람이 없어", "혼자 있으니 심심해")
  의욕 없음 = 하고 싶은 것이 없고 기운이 안 남("뭐가 하고 싶은 게 없어")
  짐이 된다는 말 = 자기가 가족에게 부담이나 폐가 된다고 여기는 말("너희한테 짐만 되지", "폐만 끼치지"). 혼자 산다는 말이나 외로움은 여기에 넣지 않는다.
  죽음·살기 싫다는 말 = 죽고 싶다·살기 싫다는 말과 위의 돌려 말하는 표현
  기타 마음 = 위에 없는 마음의 어려움(가족을 돌보는 부담 등)
  지금 힘든 말 없이 사실만 설명한 것("남편은 오래전에 죽었어")과 "웃겨 죽겠다" 같은 농담은 제외.
- 생활·안전: 돈 문제("돈이 없어서 고치지도 못해") / 사기 의심("어떤 사람이 계좌를 알려 달래") / 혼자 해결 못 하는 일("보일러가 고장 난 지 일주일째야", 집 고장·난방 등) / 기타 생활. "만약 고장 나면 전화하지" 같은 가정은 제외.
[수준] 신호가 없으면 없음. 신호가 있고 다음 중 하나면 바로 연락 필요: 죽음이나 "살기 싫다"는 말(돌려 말한 것 포함), 넘어지거나 아파서 못 움직임, 사기·돈 문제가 지금 진행 중, 혼자 해결 못 해 도움을 청함. 그 밖의 신호는 살펴보기. 살펴보기와 바로 연락 필요 사이에서 애매하면 바로 연락 필요 + 확신도 애매.
[최근 답장 기록] 예전 답장의 요약이다. 이번 답장에 없는 내용을 이번 신호로 만들지 않는다. 같은 문제가 이어지거나 나빠지는지 비교해 변화 칸에 적고(기록이 없으면 "이전 기록 없음"), 같은 문제가 계속되면 요약에 "지난번에 이어"처럼 밝힌다.
[근거] 판단한 부분을 이번 받아쓰기에서 글자 그대로 복사한다(고치거나 요약하지 않음). 흐름으로 판단했으면 그 흐름을 이루는 조각을 여러 개 따온다. 신호가 없고 평온이면 빈 목록.
[요약] 자녀에게 보여 줄 한 문장. 진단하듯 말하지 않는다.
[확신도] 다른 사람도 같게 판단할 것 같으면 확실, 고민했으면 애매.
[출력] JSON 하나만 쓴다. mood=기분, health=건강 신호, mind=마음 신호, life=생활·안전 신호, level=수준, change=최근 기록과 비교한 변화, evidence=근거 문장 목록, summary=자녀에게 보여 줄 한 문장, confidence=확신도. 선택지가 있는 칸은 선택지 글자 그대로 쓴다."""

SCHEMA = {"type": "object", "properties": {
    "mood":       {"type": "string", "enum": MOODS},
    "health":     {"type": "string", "enum": HEALTH},
    "mind":       {"type": "string", "enum": MIND},
    "life":       {"type": "string", "enum": LIFE},
    "level":      {"type": "string", "enum": LEVELS},
    "change":     {"type": "string", "enum": CHANGES},
    "evidence":   {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    "summary":    {"type": "string"},
    "confidence": {"type": "string", "enum": ["확실", "애매"]}},
    "required": ["mood", "health", "mind", "life", "level", "change", "evidence", "summary", "confidence"]}
# 판단 기준 이름표: 프롬프트나 JSON 틀을 고치면 바뀜 → 결과에 같이 적어서, 다른 기준으로 낸 결과가 섞이지 않게 함
PROMPT_ID = "v2-" + hashlib.md5((SYSTEM + json.dumps(SCHEMA, ensure_ascii=False)).encode()).hexdigest()[:6]

# ---------------------------------------------------------------- 운율 (목소리) ----
BASELINE_MIN = 3      # 평소 값을 만들기 위한 최소 지난 답장 수
BASELINE_MAX = 10     # 평소 값에 쓰는 최근 답장 수
Z_CUT = 1.5           # 평소에서 이만큼(표준편차 배수) 벗어나면 '달라짐'
DOWN_MIN = 2          # 처지는 쪽으로 달라진 항목이 이 개수 이상이면 '목소리가 처짐'

# (키, 이름, 처지는 방향, 최소 흔들림, 처질 때 문장)
#   처지는 방향 -1 = 값이 작아지면 처짐, +1 = 커지면 처짐
#   최소 흔들림 = 평소 답장끼리 너무 비슷해서 작은 차이도 크게 보이는 걸 막는 바닥값
PROSODY_FEATS = [
    ("pitch_st",       "목소리 높이", -1, 1.0,  "목소리가 낮아요"),
    ("pitch_range_st", "높낮이 폭",   -1, 1.0,  "높낮이가 단조로워요"),
    ("loudness_db",    "목소리 크기", -1, 2.0,  "목소리가 작아요"),
    ("rate",           "말 속도",     -1, 0.3,  "말이 느려요"),
    ("pause_ratio",    "쉬는 시간",   +1, 0.04, "자주 멈춰요"),
]


def compare_prosody(cur, past):
    """이번 운율 값을 같은 부모님의 지난 값들(평소)과 비교"""
    past = [p for p in past if p.get("ok")][-BASELINE_MAX:]
    if not cur.get("ok"):
        return {"status": "측정 못 함", "text": cur.get("reason", "운율을 재지 못했어요"), "voice_down": False, "items": []}
    if len(past) < BASELINE_MIN:
        return {"status": "기록 중", "n_past": len(past),
                "text": f"평소 목소리를 기록하는 중이에요 ({len(past)}/{BASELINE_MIN})", "voice_down": False, "items": []}
    items, down = [], []
    for k, name, sign, floor, phrase in PROSODY_FEATS:
        vals = [p[k] for p in past if p.get(k) is not None]
        if cur.get(k) is None or len(vals) < BASELINE_MIN:
            continue
        base = float(np.median(vals))
        sd = max(1.4826 * float(np.median(np.abs(np.array(vals) - base))), floor)   # 튀는 값에 덜 흔들리는 표준편차
        z = (cur[k] - base) / sd
        state = "처짐" if z * sign >= Z_CUT else ("반대로 달라짐" if z * sign <= -Z_CUT else "비슷")
        items.append({"key": k, "name": name, "now": cur[k], "usual": round(base, 2), "z": round(z, 2), "state": state})
        if state == "처짐":
            down.append(phrase)
    voice_down = len(down) >= DOWN_MIN
    if voice_down:
        text = "평소보다 " + " · ".join(down)
    elif down:
        text = f"평소와 비슷해요 (조금 다른 점: {down[0]})"
    else:
        text = "평소와 비슷해요"
    return {"status": "비교", "n_past": len(past), "text": text, "voice_down": voice_down, "down": down, "items": items}


# ---------------------------------------------------------------- 후처리 ----
def hangul_len(t):
    return len(re.findall(r"[가-힣]", t))


def mask_pii(text):
    """전화번호·계좌번호처럼 보이는 숫자를 가림"""
    text = re.sub(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}", "[전화번호]", text)
    return re.sub(r"\d{2,6}(?:-\d{2,6}){2,}", "[번호]", text)


def history_text(hist):
    if not hist:
        return "없음 (첫 답장)"
    lines = []
    for h in hist:
        sig = ", ".join(f"{name} {h[k]}" for k, name in (("health", "건강"), ("mind", "마음"), ("life", "생활·안전"))
                        if h.get(k, "없음") != "없음") or "없음"
        lines.append(f"- {h['date']} | 기분 {h['mood']} | 수준 {h['level']} | 신호 {sig} | {h['summary']}")
    return "\n".join(lines)


def norm(s):  # 근거 비교용: 띄어쓰기·문장부호 무시
    return re.sub(r"[\s.,?!~…'\"]", "", s)


# 글 기분이 이 중 하나인데 목소리가 처지면 말·목소리 불일치 (판단 어려움 = 글로는 기분을 알 수 없을 때라 목소리가 더 중요한 단서)
MISMATCH_MOODS = ("밝음", "평온", "판단 어려움")


def postprocess(out, reply_text, hist, voice_mismatch=False):
    """LLM 결과를 코드 규칙으로 한 번 더 확인 (+ 운율에서 온 말·목소리 불일치)"""
    reasons = []
    real = [e for e in out["evidence"] if e.strip() and norm(e) in norm(reply_text)]
    out["evidence_dropped"] = len(out["evidence"]) - len(real)     # 받아쓰기에 없는(지어낸) 근거 수
    out["evidence"] = real
    has_signal = any(out[k] != "없음" for k in ("health", "mind", "life"))
    if has_signal and out["level"] == "없음":
        out["level"] = "살펴보기"; reasons.append("신호가 있는데 수준이 '없음'이라 올림")
    # 2026-11-27 정답지에 더한 규칙: 판단 기준의 [수준] "신호가 없으면 없음"을 코드로도 지킨다.
    # CLOVA HCX-007은 신호가 모두 '없음'인 평범한 답장도 '살펴보기'로 내는 일이 많았다(시연 답장 24개 중 평소 0개).
    # 아래의 말·목소리 불일치, 가라앉은 기분 3번 연속은 이 뒤에 다시 올린다. '바로 연락 필요'는 내리지 않고 애매로만 표시
    if not has_signal and out["level"] == "살펴보기":
        out["level"] = "없음"; reasons.append("신호가 없는데 수준이 '살펴보기'라 '없음'으로 내림 (판단 기준: 신호가 없으면 없음)")
    if not has_signal and out["level"] == "바로 연락 필요":
        out["confidence"] = "애매"; reasons.append("신호 없이 '바로 연락 필요'라 확신도를 애매로 표시")
    # 말·목소리 불일치: 글로는 밝음·평온·판단 어려움인데 목소리가 평소보다 처짐 → 말로 숨긴 신호일 수 있어 살펴보기 (기준서 규칙을 운율에 맞게 바꿈)
    out["voice_mismatch"] = bool(voice_mismatch)
    if voice_mismatch and out["level"] == "없음":
        out["level"] = "살펴보기"; reasons.append("말은 괜찮지만 목소리가 평소보다 처짐 (말·목소리 불일치)")
    # ---- 답장 사이의 흐름 ----
    alerts, prev = [], hist[-2:]
    if len(prev) == 2 and all(h["level"] != "없음" for h in prev) and out["level"] != "없음":
        alerts.append("살펴보기 이상이 3번 연속")
    if len(prev) == 2 and all(h["mood"].startswith("가라앉음") for h in prev) and out["mood"].startswith("가라앉음"):
        alerts.append("가라앉은 기분이 3번 연속")
        if out["level"] == "없음":
            out["level"] = "살펴보기"; reasons.append("가라앉은 기분이 3번 연속")
    for k, name in (("health", "건강"), ("mind", "마음"), ("life", "생활·안전")):
        if out[k] != "없음" and any(h.get(k) == out[k] for h in prev):
            alerts.append(f"같은 {name} 신호가 다시 나옴: {out[k]}")
    lens = [h["reply_chars"] for h in hist if h.get("reply_chars")]
    if len(lens) >= 2 and len(reply_text) < 0.4 * float(np.median(lens)):
        alerts.append("답장이 평소보다 많이 짧음")
    if out.get("change") == "나빠짐":
        alerts.append("LLM 판단: 지난 기록보다 나빠짐")
    warnings = []
    if hangul_len(out.get("summary", "")) < 5:
        warnings.append("요약이 한국어 문장이 아님 → LLM 출력 이상 의심")
    if has_signal and not out["evidence"]:
        warnings.append("위험 신호를 골랐는데 받아쓰기에 있는 근거가 하나도 없음")
    out["trend_alerts"], out["level_reasons"], out["warnings"] = alerts, reasons, warnings
    return out


def check_output(out) -> None:
    """GPU 서버가 돌려준 JSON이 틀(SCHEMA)에 맞는지 한 번 더 본다. 틀린 칸 이름만 알리고 값은 알리지 않는다 (로그에 남을 수 있어서)."""
    if not isinstance(out, dict):
        raise ValueError("LLM 결과가 JSON 객체가 아니에요")
    for key in SCHEMA["required"]:
        spec, value = SCHEMA["properties"][key], out.get(key)
        if spec["type"] == "array":
            ok = isinstance(value, list) and len(value) <= spec["maxItems"] and all(isinstance(v, str) for v in value)
        else:
            ok = isinstance(value, str) and ("enum" not in spec or value in spec["enum"])
        if not ok:
            raise ValueError(f"LLM 결과가 JSON 틀과 맞지 않아요 ({key})")


# ---------------------------------------------------------------- LLM 호출 형식 ----
N_HISTORY = 3   # 프롬프트에 넣는 최근 기록 수 (같은 대상자의 최근 분석)


def build_prompt(system, user, think):
    """HyperCLOVA X SEED Think 14B의 대화 형식 (모델 저장소의 chat_template.jinja와 같게)"""
    p = "<|im_start|>tool_list\n<|im_end|>\n"
    p += f"<|im_start|>system\n{system}<|im_end|>\n"
    p += f"<|im_start|>user\n{user}<|im_end|>\n"
    if think:
        p += "<|im_start|>assistant/think\n"                                   # 추론부터 시작
    else:
        p += "<|im_start|>assistant/think\n<|im_end|>\n<|im_start|>assistant\n"  # 빈 추론 → 바로 답
    return p


STOPS = ["<|im_end|>", "<|endofturn|>", "<|stop|>"]
# 참고: Kaggle에서 로컬 SEED 14B(llama-server /completion)를 돌린 옵션. 서비스는 2026-11-16부터 CLOVA_PARAMS를 쓴다
LLM_PARAMS = {"n_predict": 1024, "temperature": 0.2, "top_p": 0.6, "repeat_penalty": 1.05, "seed": 1,
              "stop": STOPS, "cache_prompt": True}
# 서비스: CLOVA Studio HCX-007 (Chat Completions v3) 옵션. 값은 위 Kaggle 설정과 같다 (reply_llm.py).
# 형식 강제(responseFormat)는 추론과 같이 못 써서 thinking.effort는 none. JSON이 깨지면 seed+1로 한 번 더 한다
CLOVA_PARAMS = {"thinking": {"effort": "none"}, "maxCompletionTokens": 1024, "temperature": 0.2, "topP": 0.6, "topK": 0,
                "repetitionPenalty": 1.05, "seed": 1}


def user_prompt(letter, hist, reply_text):
    """reply_text는 mask_pii를 거친 받아쓰기(글 답장은 답장 글). 칸 이름은 글 답장도 참고 파일 그대로 둔다"""
    return (f"[자녀 편지]\n{letter}\n\n[최근 답장 기록 (오래된 것부터)]\n{history_text(hist)}\n\n"
            f"[이번 답장 받아쓰기]\n{reply_text}")


# ---------------------------------------------------------------- 자녀 화면 문구 ----
# 진단처럼 들리지 않게 바꿔서 보여 줌
LEVEL_UI = {"없음": ("평소와 같아요", "#E4EEEC", "#255F5A"), "살펴보기": ("살펴보기", "#FBE9CC", "#7A4A00"),
            "바로 연락 필요": ("바로 연락해 보세요", "#A8321E", "#FFFFFF")}
MOOD_UI = {"밝음": "밝아 보여요", "평온": "평온해 보여요", "가라앉음(쓸쓸·우울)": "기운이 없어 보여요",
           "걱정·불안": "걱정이 있어 보여요", "서운함·짜증": "서운해 보여요", "판단 어려움": "기분은 판단하기 어려워요"}
UNSURE_TEXT = "AI 판단이 확실하지 않아요"
MISMATCH_TEXT = "말은 괜찮다고 하시지만 목소리가 평소보다 처져 있어요. 한번 연락해 보세요."
STT_UNCERTAIN_TEXT = "말소리가 잘 들리지 않아 내용을 정리하지 못했어요. 직접 들어 보세요."
PENDING_TEXT = "AI가 답장을 정리하고 있어요."
FAILED_TEXT = {"voice": "답장을 정리하지 못했어요. 음성을 직접 들어 보세요.",
               "text": "답장을 정리하지 못했어요. 답장을 직접 읽어 보세요."}
NOTICE_TEXT = {"voice": "AI가 정리한 내용이에요. 진단이 아니니 음성을 함께 들어 보세요.",
               "text": "AI가 정리한 내용이에요. 진단이 아니니 답장을 함께 읽어 보세요."}
SIG_NAMES = (("health", "건강"), ("mind", "마음"), ("life", "생활·안전"))
SHOW_EVIDENCE = 3


def display(status: str, kind: str, result: dict | None, voice: dict | None) -> dict:
    """자녀 화면에 그대로 쓰는 값. 목소리 측정 숫자는 넣지 않는다 (점수처럼 보이지 않게)"""
    kind = "voice" if kind == "voice" else "text"
    out = {"status": status, "kind": kind, "notice": NOTICE_TEXT[kind], "message": None}
    if status in ("queued", "running"):
        out["message"] = PENDING_TEXT
    elif status == "stt_uncertain":
        out["message"] = STT_UNCERTAIN_TEXT
    elif status != "done" or not result:
        out["status"] = "failed"
        out["message"] = FAILED_TEXT[kind]
    if out["message"]:
        return out
    level = result["level"]
    out.update({
        "level": level, "level_label": LEVEL_UI[level][0],
        "summary": result.get("summary", ""), "mood_text": MOOD_UI.get(result["mood"], result["mood"]),
        "unsure_text": UNSURE_TEXT if result.get("confidence") == "애매" else None,
        "signals": [{"area": name, "value": result[k]} for k, name in SIG_NAMES if result.get(k, "없음") != "없음"],
        "evidence": result.get("evidence", [])[:SHOW_EVIDENCE],
        "trend_alerts": result.get("trend_alerts", []),
        "voice_text": None, "voice_down": False, "mismatch_text": None,
    })
    if kind == "voice" and voice:
        out["voice_text"] = voice.get("text")
        out["voice_down"] = bool(voice.get("voice_down"))
    if result.get("voice_mismatch"):
        out["mismatch_text"] = MISMATCH_TEXT
    return out
