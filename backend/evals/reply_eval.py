"""답장 분석 채점 (docs/REPLY_ANALYSIS.md 17절): 정답을 단 시험 답장으로 CLOVA 판단이 얼마나 틀리는지 잰다.

CLOVA는 답장마다 한 번만 부르고, 같은 결과로 세 단계를 채점한다.
  ① CLOVA 그대로         CLOVA가 고른 수준
  ② + 코드 보정          postprocess (받아쓰기에 없는 근거 지우기, 신호가 있는데 '없음'이면 살펴보기로 올림)
  ③ + 코드 보정 + 운율   말·목소리 불일치면 살펴보기로 올림 (음성 답장만. 글 답장은 ②와 같다)
서비스와 다른 점: 최근 답장 기록(hist)을 넣지 않는다. 답장 하나하나의 판단만 잰다.

시험 세트 CSV (글: evals/reply_eval_text.csv, 음성: evals/reply_eval_voice_template.csv 형식)
  공통: id, case, letter, reply(글 답장)
  음성: speaker, order, audio(이 CSV 기준 wav 경로), reply_script(읽은 글), voice_intent(평소/처짐)
  정답: mood, health, mind, life, level (선택지 글자 그대로), confidence(확실/애매), check_1·check_2(정답을 확인한 사람)

  cd backend
  python -m evals.reply_eval --set evals/reply_eval_text.csv --out <결과 폴더>
  python -m evals.reply_eval --set <음성 세트.csv> --out <결과 폴더>   # 분석 서버(REPLY_ANALYSIS_URL)가 받아쓰기·운율을 한다
  ... --score-only   CLOVA·분석 서버를 다시 부르지 않고 저장한 결과로 채점만

CLOVA 결과·받아쓰기·운율은 <결과 폴더>/cache.jsonl에 저장해서, 다시 돌려도 같은 답장은 다시 부르지 않는다.
화면에는 답장 번호와 수준만 찍는다. 답장 글과 CLOVA 요약은 결과 폴더의 파일에만 쓴다.
주의: 실제 사용자 답장과 AI Hub 음성은 넣지 않는다. CLOVA(외부 서비스)로 보내도 되는, 직접 만든 답장만 쓴다.
"""

import argparse
import copy
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from app.services import reply_analysis as rules
from app.services import reply_gpu, reply_llm

OPTIONS = {"mood": rules.MOODS, "health": rules.HEALTH, "mind": rules.MIND, "life": rules.LIFE, "level": rules.LEVELS}
SIGNALS = ("health", "mind", "life")
RANK = {level: i for i, level in enumerate(rules.LEVELS)}
STAGE_NAMES = {"s1": "① CLOVA 그대로", "s2": "② + 코드 보정", "s3": "③ + 코드 보정 + 운율"}
SHORT = {"s1": "①", "s2": "②", "s3": "③"}
NAMES = {"mood": "기분", "health": "건강 신호", "mind": "마음 신호", "life": "생활·안전 신호"}


# ---------------------------------------------------------------- 시험 세트 ----
def _option(value: str | None, options: list[str]) -> str | None:
    """선택지 글자 그대로, 또는 앞부분만 쓴 경우(가라앉음 → 가라앉음(쓸쓸·우울))"""
    v = (value or "").strip()
    if v in options:
        return v
    hits = [o for o in options if v and o.startswith(v)]
    return hits[0] if len(hits) == 1 else None


def read_set(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    errors, seen = [], set()
    for r in rows:
        rid = (r.get("id") or "").strip()
        if not rid or rid in seen:
            errors.append(f"id가 비었거나 겹쳐요: {rid!r}")
        seen.add(rid)
        r["id"] = rid
        for key, options in OPTIONS.items():
            value = _option(r.get(key), options)
            if value is None:
                errors.append(f"{rid}: {key} = {r.get(key)!r} (선택지: {' / '.join(options)})")
            else:
                r[key] = value
        r["kind"] = "voice" if (r.get("audio") or "").strip() else "text"
        if r["kind"] == "text" and not (r.get("reply") or "").strip():
            errors.append(f"{rid}: 글 답장인데 reply가 비었어요")
        r["checked"] = bool((r.get("check_1") or "").strip() and (r.get("check_2") or "").strip())
        r["status"] = "pending"
    if errors:
        raise SystemExit("시험 세트를 고쳐 주세요:\n  " + "\n  ".join(errors))
    return rows


# ---------------------------------------------------------------- 저장 ----
class Cache:
    """CLOVA 결과·받아쓰기·운율을 한 줄에 하나씩 저장한다 (같은 입력이면 다시 부르지 않는다)"""

    def __init__(self, path: Path):
        self.path, self.data = path, {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.data[rec["key"]] = rec["value"]

    def get(self, key: str):
        return self.data.get(key)

    def put(self, key: str, value) -> None:
        self.data[key] = value
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")


def _sha(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


# ---------------------------------------------------------------- 음성: 받아쓰기 → 운율 ----
def _cer(ref: str, hyp: str) -> float | None:
    """한글·숫자만 비교한 글자 오류율 (띄어쓰기·문장부호 무시)"""
    a, b = re.sub(r"[^가-힣0-9]", "", ref), re.sub(r"[^가-힣0-9]", "", hyp)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(a)


def run_voice(rows: list[dict], base: Path, cache: Cache, score_only: bool) -> None:
    """화자마다 order 순서로: 받아쓰기 → (불확실하면 끝) → 운율 → 앞선 답장들(평소)과 비교. 서비스 run()과 같은 순서"""
    by_speaker = defaultdict(list)
    for r in rows:
        if r["kind"] == "voice":
            by_speaker[(r.get("speaker") or r["id"]).strip()].append(r)
    for items in by_speaker.values():
        items.sort(key=lambda r: float(r.get("order") or 0))
        past = []
        for r in items:
            wav = (base / r["audio"].strip()).resolve()
            if not wav.exists():
                r["status"], r["error"] = "error", f"음성 파일이 없어요: {r['audio']}"
                continue
            digest = hashlib.sha256(wav.read_bytes()).hexdigest()[:24]
            stt = cache.get(f"stt:{digest}")
            if stt is None and not score_only:
                stt = reply_gpu.stt(wav)
                stt = {k: stt.get(k) for k in ("text", "problems", "duration", "seconds")}
                cache.put(f"stt:{digest}", stt)
            if stt is None:
                r["status"] = "missing"
                continue
            r["stt_text"], r["stt_problems"] = stt.get("text") or "", stt.get("problems") or []
            if (r.get("reply_script") or "").strip():
                r["cer"] = _cer(r["reply_script"], r["stt_text"])
            if r["stt_problems"]:
                r["status"] = "stt_uncertain"  # 서비스도 CLOVA에 보내지 않고 운율도 재지 않는다
                continue
            key = f"prosody:{digest}:{_sha(r['stt_text'])}"
            pros = cache.get(key)
            if pros is None and not score_only:
                pros = reply_gpu.prosody(wav, r["stt_text"])
                cache.put(key, pros)
            if pros is None:
                r["status"] = "missing"
                continue
            r["voice"] = rules.compare_prosody(pros, past)
            past.append(pros)
            r["text"] = r["stt_text"]


# ---------------------------------------------------------------- CLOVA 판단 → 세 단계 ----
def judge(r: dict, cache: Cache, score_only: bool, usage: Counter) -> None:
    text = r.get("text") if r["kind"] == "voice" else r["reply"]
    masked = reply_llm.hide_names(rules.mask_pii(text), [])  # 서비스와 같은 가림 (시험 답장에는 DB 이름이 없다)
    user = rules.user_prompt(reply_llm.hide_names(r.get("letter") or "", []), [], masked)
    key = "clova:" + _sha(rules.PROMPT_ID, reply_llm.model_name(), rules.CLOVA_PARAMS, user)
    rec = cache.get(key)
    if rec is None:
        if score_only:
            r["status"] = "missing"
            return
        llm = reply_llm.analyze(rules.SYSTEM, user, rules.SCHEMA, rules.CLOVA_PARAMS)
        rec = {k: llm[k] for k in ("json", "attempts", "seconds", "prompt_tokens", "completion_tokens", "model")}
        cache.put(key, rec)
        usage.update(calls=1, attempts=rec["attempts"], prompt_tokens=rec["prompt_tokens"],
                     completion_tokens=rec["completion_tokens"])
        usage["seconds"] += rec["seconds"]
    raw = rec["json"]
    s2 = rules.postprocess(copy.deepcopy(raw), masked, [], voice_mismatch=False)
    voice = r.get("voice") or {}
    mismatch = bool(voice.get("voice_down") and raw["mood"] in rules.MISMATCH_MOODS)
    s3 = rules.postprocess(copy.deepcopy(raw), masked, [], voice_mismatch=mismatch)
    r.update(status="done", raw=raw, s1=raw["level"], s2=s2["level"], s3=s3["level"], mismatch=mismatch,
             evidence_dropped=s2["evidence_dropped"], warnings=s2["warnings"], pred_confidence=s2["confidence"],
             model=rec["model"])


# ---------------------------------------------------------------- 채점 ----
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """적은 수에서도 쓸 수 있는 95% 범위 (윌슨 구간)"""
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def pct(k: int, n: int, ci: bool = True) -> str:
    if not n:
        return "-"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% ({k}/{n}" + (f", 95% 범위 {100 * lo:.0f}~{100 * hi:.0f}%)" if ci else ")")


def level_metrics(rows: list[dict], stage: str) -> dict:
    pairs = [(r["level"], r[stage]) for r in rows]
    pos = [(g, p) for g, p in pairs if g != "없음"]
    neg = [(g, p) for g, p in pairs if g == "없음"]
    urgent = [(g, p) for g, p in pairs if g == "바로 연락 필요"]
    return {
        "수준이 틀린 비율": (sum(g != p for g, p in pairs), len(pairs)),
        "놓친 비율 (정답 살펴보기 이상 → '없음')": (sum(p == "없음" for _, p in pos), len(pos)),
        "괜한 알림 비율 (정답 없음 → 살펴보기 이상)": (sum(p != "없음" for _, p in neg), len(neg)),
        "'바로 연락 필요'를 낮게 본 비율": (sum(p != "바로 연락 필요" for _, p in urgent), len(urgent)),
        "정답보다 낮게 본 답장": (sum(RANK[p] < RANK[g] for g, p in pairs), len(pairs)),
        "정답보다 높게 본 답장": (sum(RANK[p] > RANK[g] for g, p in pairs), len(pairs)),
    }


def metrics_table(rows: list[dict], stages: list[str]) -> list[str]:
    ms = {s: level_metrics(rows, s) for s in stages}
    out = ["| | " + " | ".join(STAGE_NAMES[s] for s in stages) + " |", "|---|" + "---|" * len(stages)]
    for name in ms[stages[0]]:
        out.append(f"| {name} | " + " | ".join(pct(*ms[s][name]) for s in stages) + " |")
    return out


def confusion(rows: list[dict], stage: str) -> list[str]:
    out = [f"| 정답 \\ {STAGE_NAMES[stage]} | " + " | ".join(rules.LEVELS) + " |", "|---|" + "---|" * len(rules.LEVELS)]
    for g in rules.LEVELS:
        out.append(f"| {g} | " + " | ".join(str(sum(r['level'] == g and r[stage] == p for r in rows)) for p in rules.LEVELS) + " |")
    return out


def report(rows: list[dict], set_path: Path, usage: Counter) -> str:
    done = [r for r in rows if r["status"] == "done"]
    voice_rows = [r for r in rows if r["kind"] == "voice"]
    stages = ["s1", "s2"] + (["s3"] if any(r["kind"] == "voice" for r in done) else [])
    model = next((r["model"] for r in done), reply_llm.model_name())
    L = [f"# 답장 분석 채점 ({datetime.now():%Y-%m-%d %H:%M})", "",
         f"- 시험 세트: `{set_path.name}` · 답장 {len(rows)}개 (글 {len(rows) - len(voice_rows)} · 음성 {len(voice_rows)})",
         f"- 판단 기준 `{rules.PROMPT_ID}` · 모델 {model} · 최근 답장 기록 없이 답장마다 따로 판단",
         f"- 채점한 답장 {len(done)}개 · 상태별 {dict(Counter(r['status'] for r in rows))}"]
    unchecked = sum(not r["checked"] for r in done)
    if unchecked:
        L.append(f"- **주의: 팀이 정답을 확인하지 않은 답장이 {unchecked}개예요. 이 결과는 초안 정답 기준이에요** "
                 "(check_1·check_2를 채우면 사라져요)")
    if not done:
        return "\n".join(L + ["", "채점할 답장이 없어요."])
    L += ["", "## 수준 (없음 / 살펴보기 / 바로 연락 필요)", ""] + metrics_table(done, stages)
    sure = [r for r in done if (r.get("confidence") or "").strip() == "확실"]
    if sure and len(sure) < len(done):
        L += ["", f"정답이 '확실'인 답장만 ({len(sure)}개)", ""] + metrics_table(sure, stages)
    L += ["", "### 혼동표", ""] + confusion(done, stages[-1])

    L += ["", "## 칸별로 정답과 같은 비율 (① CLOVA 그대로)", "", "| 칸 | 같음 | 신호 있음/없음만 같음 |", "|---|---|---|"]
    for key, name in NAMES.items():
        same = sum(r["raw"][key] == r[key] for r in done)
        if key in SIGNALS:
            yes_no = sum((r["raw"][key] != "없음") == (r[key] != "없음") for r in done)
            L.append(f"| {name} | {pct(same, len(done), False)} | {pct(yes_no, len(done), False)} |")
        else:
            L.append(f"| {name} | {pct(same, len(done), False)} | |")
    dropped = sum(1 for r in done if r["evidence_dropped"])
    no_evidence = sum(1 for r in done if any("근거" in w for w in r["warnings"]))
    L += ["", f"- 받아쓰기·답장에 없는 근거 문장을 만든 답장: {pct(dropped, len(done), False)} (코드 보정에서 지움)",
          f"- 신호를 골랐는데 근거가 하나도 없는 답장: {pct(no_evidence, len(done), False)}",
          f"- CLOVA가 확신도를 '애매'로 낸 답장: {pct(sum(r['raw']['confidence'] == '애매' for r in done), len(done), False)}"]

    if voice_rows:
        vd = [r for r in voice_rows if r["status"] == "done"]
        unsure = [r for r in voice_rows if r["status"] == "stt_uncertain"]
        L += ["", "## 음성 답장", ""]
        if vd:
            L += metrics_table(vd, ["s1", "s2", "s3"]) + [""]
        cers = [r["cer"] for r in voice_rows if r.get("cer") is not None]
        L.append(f"- 받아쓰기 불확실(분석하지 않음): {pct(len(unsure), len(voice_rows), False)}, "
                 f"그중 정답이 살펴보기 이상 {sum(r['level'] != '없음' for r in unsure)}개")
        if cers:
            L.append(f"- 받아쓰기 글자 오류율(읽은 글과 비교, 가운데 값): {100 * sorted(cers)[len(cers) // 2]:.1f}% ({len(cers)}개)")
        compared = [r for r in vd if (r.get("voice") or {}).get("status") == "비교"]
        down = [r for r in compared if (r.get("voice_intent") or "").strip() == "처짐"]
        usual = [r for r in compared if (r.get("voice_intent") or "").strip() == "평소"]
        L.append(f"- 평소 목소리와 비교한 답장 {len(compared)}개 (나머지는 '기록 중'이거나 운율을 못 잼)")
        L.append(f"- 처진 목소리로 녹음한 답장을 '목소리 처짐'으로 잡은 비율: {pct(sum(r['voice']['voice_down'] for r in down), len(down))}")
        L.append(f"- 평소 목소리 답장을 '목소리 처짐'으로 잘못 잡은 비율: {pct(sum(r['voice']['voice_down'] for r in usual), len(usual))}")
        L.append(f"- 말·목소리 불일치로 판정: {sum(r['mismatch'] for r in vd)}개")

    L += ["", "## 분류별 (마지막 단계 기준)", "", "| 분류 | 답장 | 맞음 | 틀린 답장 |", "|---|---|---|---|"]
    by_case = defaultdict(list)
    for r in done:
        by_case[(r.get("case") or "").strip() or "-"].append(r)
    last = stages[-1]
    for case, rs in by_case.items():
        wrong = [f"{r['id']}({r[last]})" for r in rs if r[last] != r["level"]]
        L.append(f"| {case} | {len(rs)} | {len(rs) - len(wrong)} | {', '.join(wrong)} |")

    wrong = [r for r in done if any(r[s] != r["level"] for s in stages)]
    L += ["", "## 수준이 틀린 답장", "", "| id | 분류 | 정답 | " + " | ".join(SHORT[s] for s in stages) +
          " | CLOVA 기분·신호 | CLOVA 요약 |", "|---|---|---|" + "---|" * len(stages) + "---|---|"]
    for r in wrong:
        sig = ", ".join(f"{NAMES[k].split()[0]} {r['raw'][k]}" for k in SIGNALS if r["raw"][k] != "없음") or "신호 없음"
        L.append(f"| {r['id']} | {r.get('case', '')} | {r['level']} | " + " | ".join(r[s] for s in stages) +
                 f" | {r['raw']['mood']} · {sig} | {r['raw']['summary'].replace('|', '/')} |")
    if usage["calls"]:
        L += ["", f"이번 실행의 CLOVA 호출 {usage['calls']}번 (시도 {usage['attempts']}번), 평균 {usage['seconds'] / usage['calls']:.1f}초, "
              f"토큰 {usage['prompt_tokens']}→{usage['completion_tokens']}"]
    return "\n".join(L) + "\n"


def write_results(rows: list[dict], path: Path) -> None:
    keys = ["id", "case", "kind", "status", "checked", "confidence", "level", "s1", "s2", "s3", "mood", "pred_mood",
            "health", "pred_health", "mind", "pred_mind", "life", "pred_life", "pred_confidence", "evidence_dropped",
            "voice_intent", "voice_status", "voice_down", "voice_text", "mismatch", "cer", "stt_problems", "error", "summary"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            raw, voice = r.get("raw") or {}, r.get("voice") or {}
            w.writerow({**r, **{f"pred_{k}": raw.get(k, "") for k in ("mood", "health", "mind", "life")},
                        "voice_status": voice.get("status", ""), "voice_down": voice.get("voice_down", ""),
                        "voice_text": voice.get("text", ""), "summary": raw.get("summary", ""),
                        "stt_problems": " / ".join(r.get("stt_problems") or [])})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="답장 분석 채점 (CLOVA 오답률)")
    ap.add_argument("--set", type=Path, required=True, help="시험 세트 CSV")
    ap.add_argument("--out", type=Path, required=True, help="결과 폴더 (cache.jsonl, results.csv, report.md)")
    ap.add_argument("--score-only", action="store_true", help="CLOVA·분석 서버를 부르지 않고 저장한 결과로 채점만")
    ap.add_argument("--checked-only", action="store_true", help="팀이 정답을 확인한 답장(check_1·check_2)만 채점")
    ap.add_argument("--ids", help="이 답장들만 (쉼표로 구분)")
    ap.add_argument("--limit", type=int, help="앞에서 몇 개만 (시험 삼아 돌릴 때)")
    args = ap.parse_args(argv)

    rows = read_set(args.set)
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        rows = [r for r in rows if r["id"] in wanted]
    if args.checked_only:
        rows = [r for r in rows if r["checked"]]
    rows = rows[: args.limit] if args.limit else rows
    if not args.score_only and not reply_llm.api_key():
        raise SystemExit("CLOVA 키가 없어요 (backend/.env의 REPLY_LLM_API_KEY 또는 NAVER_API_KEY). 저장한 결과로만 채점하려면 --score-only")
    args.out.mkdir(parents=True, exist_ok=True)
    cache = Cache(args.out / "cache.jsonl")
    usage = Counter()

    if any(r["kind"] == "voice" for r in rows):
        if not args.score_only and not reply_gpu.health():
            raise SystemExit("분석 서버에 연결하지 못했어요 (REPLY_ANALYSIS_URL). GPU PC에서 reply_analysis_server를 켜 주세요")
        run_voice(rows, args.set.parent, cache, args.score_only)

    failures = 0
    for n, r in enumerate(rows, 1):
        if r["status"] != "pending":  # 음성: 받아쓰기 불확실·파일 없음 등은 CLOVA에 보내지 않는다
            print(f"[{n}/{len(rows)}] {r['id']} {r['status']}", flush=True)
            continue
        try:
            judge(r, cache, args.score_only, usage)
            failures = 0
        except reply_gpu.AnalysisError as e:  # 메시지에 답장 내용은 없다
            r["status"], r["error"] = "error", str(e)
            failures += 1
            if failures >= 3:
                print(f"연달아 {failures}번 실패해서 멈춰요: {e}")
                break
        print(f"[{n}/{len(rows)}] {r['id']} 정답 {r['level']} → " +
              (" ".join(f"{SHORT[s]} {r[s]}" for s in ("s1", "s2", "s3") if s in r) if r["status"] == "done" else r["status"]),
              flush=True)

    write_results(rows, args.out / "results.csv")
    text = report(rows, args.set, usage)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"결과: {args.out / 'report.md'}, {args.out / 'results.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
