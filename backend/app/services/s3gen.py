"""사용자별 S3Gen 음색 어댑터 학습 (S3GEN_TRAINING=true, TTS_PROVIDER=wemeet).

연구 결과(3분 녹음, RTX 4070): zero-shot보다 화자 유사도가 조금 오르지만(VoiceEncoder 0.893 -> 0.908) 효과 없는 사람도 있다.
그래서 학습한 뒤 같은 문장·seed로 기본 목소리와 비교해서, 더 닮았을 때만 TTS 서버의 목소리에 어댑터를 붙인다.

  1. prepare  녹음을 참조·평가(30초)·검증(20초)·학습으로 나누고 S3Gen 특징값을 뽑는다
  2. train    chatterbox_lora.s3gen_train (연구 코드 그대로). 검증 손실이 가장 낮은 지점의 어댑터를 쓴다
  3. compare  임시 목소리(<voice_id>_cand)에 어댑터를 붙여 기본 목소리와 같은 문장·seed로 만든다
  4. score    두 음성을 학습에 안 쓴 실제 녹음과 비교해 화자 유사도(VoiceEncoder, WavLM)를 낸다

1·2·4는 torch가 있는 Wemeet-cb 환경 python으로 따로 실행한다(gpu_worker/s3gen_user.py). 웹 백엔드 환경에는 torch가 없다.
3은 TTS 서버를 부르므로 작업 워커에서 다른 TTS 요청과 겹치지 않게 순서대로 실행된다.
"""

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import BACKEND_DIR, log, settings
from . import wemeet_tts

GPU_SCRIPT = BACKEND_DIR / "gpu_worker" / "s3gen_user.py"
TEST_SECONDS = 30.0  # 학습에 안 쓰고 비교 기준으로 남기는 실제 녹음
VAL_SECONDS = 20.0  # 학습 중 가장 좋은 지점을 고르는 검증용
MIN_TRAIN_SECONDS = 60.0  # 연구에서 87초 학습은 효과가 없었다. 이보다 적으면 학습하지 않는다
MIN_SPEAKER_SIM = 0.75  # 녹음 전체의 중앙값 목소리와 이보다 멀면 다른 사람 목소리·잡음으로 보고 뺀다
SPLIT_SEED = 1247
PREPARE_TIMEOUT, TRAIN_TIMEOUT, SCORE_TIMEOUT = 600, 1800, 600
# 학습 작업 하나에 걸리는 시간 (RTX 4070, 1000 step 배치 4에서 4.3~4.6분). 기다리는 영상에 남은 시간을 보여 줄 때 쓴다
EXPECTED_SECONDS = 300

# 비교용 문장. 같은 seed면 T3 출력(말투·속도)이 같아서 두 음성은 S3Gen 어댑터만 다르다
EVAL_SENTENCES = [
    "엄마 오늘 비 오니까 우산 챙겨요.",
    "밥은 잘 챙겨 먹고 다니지? 끼니 거르지 마.",
    "날씨가 많이 추워졌는데 감기 조심하세요.",
    "이번 주말에 시간 되면 얼굴 한번 보자.",
    "별일 없지? 목소리 들으니까 좋다.",
    "창문을 열어 보니 시원한 바람이 들어와서 기분이 한결 좋아졌습니다.",
    "그 이야기를 들으니 마음이 아프네요. 지금은 잠시 쉬어도 괜찮아요.",
    "오늘 회의에서는 다음 주 일정과 준비할 자료를 함께 확인하겠습니다.",
]
EVAL_SEED = 1247


class TrainingError(Exception):
    """학습 단계 실패. 작업 큐가 다시 시도하고, 끝내 실패해도 사용자는 기본 목소리로 계속 쓴다."""

    user_message: str | None = None

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Outcome:
    applied: bool
    reason: str  # improved | no_gain | not_enough_audio | no_val_improvement | voice_changed
    report: dict = field(default_factory=dict)
    adapter: Path | None = None
    gpu_seconds: float = 0.0


def unavailable_reason() -> str | None:
    """학습을 돌릴 수 없으면 이유를, 돌릴 수 있으면 None. GPU PC에 맡기면(S3GEN_REMOTE_URL) 그쪽이 확인한다."""
    if settings.s3gen_remote_url:
        return None
    if not settings.wemeet_train_python or not Path(settings.wemeet_train_python).is_file():
        return f"WEMEET_TRAIN_PYTHON이 없습니다 ({settings.wemeet_train_python or '설정 안 됨'})"
    if not (Path(settings.wemeet_lora_code_dir) / "chatterbox_lora" / "s3gen_train.py").is_file():
        return f"WEMEET_LORA_CODE_DIR에 chatterbox_lora가 없습니다 ({settings.wemeet_lora_code_dir})"
    return None


def _run(args: list[str], *, cwd: Path, timeout: float, label: str) -> str:
    # 모델은 이미 받아 둔 캐시만 쓴다 (학습 중 네트워크에 의존하지 않게)
    env = {
        **os.environ,
        "WEMEET_LORA_CODE_DIR": settings.wemeet_lora_code_dir,
        "HF_HUB_OFFLINE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [settings.wemeet_train_python, *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise TrainingError(f"S3Gen {label} 시간 초과 ({timeout:.0f}초)") from e
    if proc.returncode != 0:
        raise TrainingError(f"S3Gen {label} 실패 (종료 코드 {proc.returncode}): {proc.stderr.strip()[-1500:]}")
    log.info("S3Gen %s 완료 (%.0f초)", label, time.monotonic() - started)
    return proc.stdout


def _gpu_step(command: str, work: Path, *extra: str, timeout: float, label: str) -> dict:
    stdout = _run([str(GPU_SCRIPT), command, "--work", str(work), *extra], cwd=work, timeout=timeout, label=label)
    for line in reversed(stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise TrainingError(f"S3Gen {label} 결과를 읽지 못했습니다: {stdout[-300:]}")


def prepare(clips: list[dict], ref_id: str, work: Path) -> dict:
    """clips: [{"id", "audio"(절대 경로), "duration"}]. 녹음 문장 텍스트는 넘기지 않는다."""
    done = work / "prepare.json"
    if done.exists():  # 앞선 시도에서 끝냈으면 다시 하지 않는다
        return json.loads(done.read_text(encoding="utf-8"))
    work.mkdir(parents=True, exist_ok=True)
    spec = {
        "ref": ref_id,
        "clips": clips,
        "test_sec": TEST_SECONDS,
        "val_sec": VAL_SECONDS,
        "min_sim": MIN_SPEAKER_SIM,
        "min_train_sec": MIN_TRAIN_SECONDS,
        "seed": SPLIT_SEED,
    }
    (work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    result = _gpu_step("prepare", work, "--spec", str(work / "spec.json"), timeout=PREPARE_TIMEOUT, label="특징값 추출")
    done.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def train(work: Path) -> dict:
    """학습 결과 요약(summary.json). 검증 손실이 처음보다 나아진 적이 없으면 adapter_best가 없다."""
    run = work / "run"
    if not (run / "summary.json").exists():  # 앞선 시도에서 학습을 마쳤으면 다시 하지 않는다
        _run(
            [
                "-m", "chatterbox_lora.s3gen_train",
                "--exp-dir", str(work),
                "--speaker", "user",
                "--subset", "user",
                "--output-dir", str(run),
                "--batch-size", str(settings.s3gen_batch_size),
                "--max-steps", str(settings.s3gen_steps),
                "--eval-every", "100",
            ],
            cwd=Path(settings.wemeet_lora_code_dir),
            timeout=TRAIN_TIMEOUT,
            label="학습",
        )
    return json.loads((run / "summary.json").read_text(encoding="utf-8"))


def compare(work: Path, voice_id: str, reference_wav: Path, adapter: Path) -> tuple[list[dict], float]:
    """기본 목소리와 임시 어댑터 목소리로 비교 문장을 만든다.
    임시 목소리는 호출한 쪽이 성공·실패와 상관없이 delete_candidate로 지운다."""
    cand_id = f"{voice_id}_cand"
    out = work / "eval"
    out.mkdir(parents=True, exist_ok=True)
    pairs, tts_seconds = [], 0.0
    wemeet_tts.register_voice(cand_id, reference_wav)
    wemeet_tts.set_s3gen_adapter(cand_id, adapter)
    # 같은 목소리끼리 이어서 만들면 서버가 어댑터를 문장마다 바꿔 끼우지 않는다
    for side, vid in (("base", voice_id), ("cand", cand_id)):
        for i, text in enumerate(EVAL_SENTENCES):
            speech = wemeet_tts.synthesize(text, vid, seed=EVAL_SEED + i)
            path = out / f"{side}_{i:02d}.wav"
            path.write_bytes(speech.wav)
            tts_seconds += speech.elapsed
            if side == "base":
                pairs.append({"base": str(path)})
            else:
                pairs[i]["cand"] = str(path)
    return pairs, tts_seconds


def delete_candidate(voice_id: str) -> bool:
    """비교용 임시 목소리를 지운다. 서버에 연결되지 않으면 False (워커가 삭제 작업을 따로 넣는다)."""
    try:
        wemeet_tts.delete_voice(f"{voice_id}_cand")
        return True
    except wemeet_tts.TTSError as e:
        log.warning("비교용 임시 목소리 %s_cand를 지우지 못했습니다: %s", voice_id, e)
        return False


def score(work: Path, pairs: list[dict]) -> dict:
    (work / "pairs.json").write_text(json.dumps({"pairs": pairs}), encoding="utf-8")
    return _gpu_step("score", work, "--pairs", str(work / "pairs.json"), timeout=SCORE_TIMEOUT, label="유사도 비교")


def run(
    clips: list[dict], ref_id: str, reference_wav: Path, voice_id: str, work: Path, still_current: Callable[[], bool]
) -> Outcome:
    """학습부터 적용 판단까지. 어댑터를 실제 목소리에 붙이는 것과 임시 목소리 삭제는 호출한 쪽(워커)이 한다.
    still_current: 학습(몇 분)이 끝난 뒤 그사이 다시 녹음·동의 철회로 목소리가 바뀌지 않았는지 확인한다."""
    split = prepare(clips, ref_id, work)
    report = {"split": {k: v for k, v in split.items() if k != "ok"}}
    if not split["ok"]:
        return Outcome(False, split["reason"], report)

    summary = train(work)
    report["train"] = {
        k: summary.get(k) for k in ("best_step", "base_val", "best_val", "improvement_pct", "train_sec", "total_sec")
    } | {"steps": settings.s3gen_steps, "batch_size": settings.s3gen_batch_size}
    gpu_seconds = float(summary.get("total_sec") or 0.0)
    adapter = work / "run" / "adapter_best.safetensors"
    if not summary.get("best_step") or not adapter.exists():
        return Outcome(False, "no_val_improvement", report, gpu_seconds=gpu_seconds)
    if not still_current():
        return Outcome(False, "voice_changed", report, gpu_seconds=gpu_seconds)

    pairs, tts_seconds = compare(work, voice_id, reference_wav, adapter)
    scores = score(work, pairs)
    thresholds = {"ve": settings.s3gen_min_ve_gain, "sv": settings.s3gen_min_sv_gain}
    report["score"] = {k: v for k, v in scores.items() if k != "ok"} | {"thresholds": thresholds}
    applied = scores["gain"]["ve"] >= thresholds["ve"] and scores["gain"]["sv"] >= thresholds["sv"]
    return Outcome(
        applied,
        "improved" if applied else "no_gain",
        report,
        adapter=adapter if applied else None,
        gpu_seconds=gpu_seconds + tts_seconds,
    )
