"""녹음 변환·품질 검사. ffmpeg는 imageio-ffmpeg에 포함된 실행 파일을 쓴다."""

import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import imageio_ffmpeg
import numpy as np

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SAMPLE_RATE = 24000  # Chatterbox S3Gen 출력과 같은 24kHz (요구사항 16kHz 이상)
FRAME = int(SAMPLE_RATE * 0.02)  # 20ms


def run_ffmpeg(args: list[str], input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", *args],
        input=input_bytes,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {proc.stderr.decode('utf-8', 'replace')[-500:]}")
    return proc.stdout


def decode(data: bytes) -> np.ndarray:
    """webm/mp4/wav 등 어떤 형식이든 24kHz 모노 float32로 디코딩한다."""
    raw = run_ffmpeg(["-i", "pipe:0", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"], data)
    return np.frombuffer(raw, dtype=np.float32).copy()


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        sr = w.getframerate()
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if sr != SAMPLE_RATE:
        return decode(path.read_bytes())
    return samples


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def _frame_db(samples: np.ndarray) -> np.ndarray:
    n = len(samples) // FRAME
    if n == 0:
        return np.array([-100.0])
    frames = samples[: n * FRAME].reshape(n, FRAME)
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    return 20 * np.log10(rms)


@dataclass
class Quality:
    duration: float
    speech_db: float
    noise_db: float
    snr_db: float
    clip_ratio: float
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def analyze(samples: np.ndarray) -> Quality:
    db = _frame_db(samples)
    noise = float(np.percentile(db, 10))
    threshold = max(noise + 12, -50)
    speech_frames = db[db > threshold]
    speech = float(np.mean(speech_frames)) if len(speech_frames) else -100.0
    speech_ratio = len(speech_frames) / len(db)
    clip_ratio = float(np.mean(np.abs(samples) > 0.98)) if len(samples) else 0.0
    q = Quality(
        duration=len(samples) / SAMPLE_RATE,
        speech_db=round(speech, 1),
        noise_db=round(noise, 1),
        snr_db=round(speech - noise, 1),
        clip_ratio=round(clip_ratio, 4),
    )

    # 첫 말소리와 마지막 말소리 사이에서 1.5초 넘게 쉬는 구간
    voiced = np.nonzero(db > threshold)[0]
    inner_pause = 0
    if len(voiced) > 1:
        inner = db[voiced[0] : voiced[-1]] > threshold
        run = 0
        for is_speech in inner:
            run = 0 if is_speech else run + 1
            inner_pause = max(inner_pause, run)

    if q.duration < 1.5 or speech_ratio * q.duration < 1.0:
        q.problems.append("말소리가 거의 녹음되지 않았어요. 문장을 끝까지 읽어 주세요.")
    elif speech < -38:
        q.problems.append("목소리가 너무 작아요. 마이크에 조금 더 가까이 대고 읽어 주세요.")
    if clip_ratio > 0.002:
        q.problems.append("소리가 너무 커서 찢어졌어요. 마이크에서 조금 떨어져 주세요.")
    if speech > -100 and q.snr_db < 15:
        q.problems.append("주변 소음이 커요. 조용한 곳에서 다시 읽어 주세요.")
    if inner_pause * 0.02 > 1.5:
        q.problems.append("중간에 쉬는 구간이 길어요. 한 번에 이어서 읽어 주세요.")
    return q


def clean(samples: np.ndarray) -> np.ndarray:
    """앞뒤 무음을 자르고(0.15초 여백) 말소리 기준 -20dBFS로 맞춘다. 피크는 -1dBFS로 제한."""
    db = _frame_db(samples)
    noise = float(np.percentile(db, 10))
    voiced = np.nonzero(db > max(noise + 12, -50))[0]
    if len(voiced):
        pad = int(0.15 * SAMPLE_RATE)
        start = max(voiced[0] * FRAME - pad, 0)
        end = min((voiced[-1] + 1) * FRAME + pad, len(samples))
        samples = samples[start:end]
    samples = samples - float(np.mean(samples))
    q = analyze(samples)
    gain = 10 ** ((-20 - q.speech_db) / 20) if q.speech_db > -100 else 1.0
    peak = float(np.max(np.abs(samples))) or 1.0
    gain = min(gain, 0.89 / peak)
    return (samples * gain).astype(np.float32)


def concat(paths: list[Path], gap: float = 0.25) -> np.ndarray:
    silence = np.zeros(int(gap * SAMPLE_RATE), dtype=np.float32)
    parts: list[np.ndarray] = []
    for p in paths:
        parts.extend([read_wav(p), silence])
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
