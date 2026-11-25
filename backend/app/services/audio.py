"""녹음 변환·품질 검사. ffmpeg는 imageio-ffmpeg에 포함된 실행 파일을 쓴다."""

import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import parselmouth
from parselmouth.praat import call

from ..config import log

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


def decode(data: bytes, rate: int = SAMPLE_RATE) -> np.ndarray:
    """webm/mp4/wav 등 어떤 형식이든 모노 float32로 디코딩한다 (기본 24kHz, 답장 분석은 16kHz)."""
    raw = run_ffmpeg(["-i", "pipe:0", "-ac", "1", "-ar", str(rate), "-f", "f32le", "pipe:1"], data)
    return np.frombuffer(raw, dtype=np.float32).copy()


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        sr = w.getframerate()
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if sr != SAMPLE_RATE:
        return decode(path.read_bytes())
    return samples


def write_wav(path: Path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def make_younger(path: Path, pitch_hz: float, formant: float, pitch_range: float) -> None:
    """어린 시절 모드: 목소리 높이를 pitch_hz로 맞추고, 울림(포먼트)은 formant배로 따로 올린다. 길이는 그대로 둔다.
    원래 목소리가 낮든(남성 약 120Hz) 높든(여성 약 200Hz) 같은 아이 목소리 높이가 된다. pitch_range배로 억양 폭을 넓힌다.
    Praat의 Change gender(PSOLA)를 쓴다. 예전 방식(높이·울림을 같은 배율로)은 낮은 목소리가 144~163Hz에 머물렀다 (docs/YOUNG_MODE.md)"""
    try:
        sound = parselmouth.Sound(str(path))
        younger = call(sound, "Change gender", 75, 600, formant, pitch_hz, pitch_range, 1.0)
        # PSOLA로 이어 붙이면 파형이 한쪽으로 치우칠 수 있다(DC). 단순한 소리일수록 크다 (사인파에서 -0.16)
        call(younger, "Subtract mean")
        younger.save(str(path), "WAV")
    except parselmouth.PraatError as e:
        # 목소리 높이를 못 찾는 짧은·조용한 음성 등. 예전 방식으로라도 바꾼다
        log.warning("Praat으로 목소리를 바꾸지 못해서 음높이·울림을 함께 올립니다: %s", e)
        shift_all(path, SIMPLE_YOUNG_FACTOR)


SIMPLE_YOUNG_FACTOR = 1.25  # 처음 방식 ('간단히 높이기' 선택지, Praat이 실패했을 때)


def shift_all(path: Path, factor: float) -> None:
    """음높이와 울림을 같이 factor배로 올린다 (처음 방식, 단순 신호 처리). 빠르게 재생했다가(둘 다 오른다) 원래 속도로 되돌려 길이는 그대로"""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
    tmp = path.with_name(path.stem + ".young.wav")
    run_ffmpeg(["-y", "-i", str(path), "-af", f"asetrate={round(rate * factor)},aresample={rate},atempo={1 / factor:.6f}",
                "-ac", "1", str(tmp)])
    tmp.replace(path)


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


def trim_reference(samples: np.ndarray, max_seconds: float = 9.5, min_seconds: float = 4.0) -> np.ndarray:
    """TTS 서버 참조 음성용. 서버는 첫 말소리부터 10초에서 그대로 잘라서 긴 대본은 말이 중간에 끊긴다.
    그래서 첫 말소리부터 min_seconds~max_seconds 사이의 가장 늦은 쉼에서 미리 자른다. 그보다 짧으면 그대로 둔다.
    쉼은 0.14초 평균 크기로 찾는다. 단어 안의 짧은 끊김(받침·파열음)은 앞뒤 말소리에 묻히고 문장·구절 사이만 낮게 남는다.
    말소리보다 18dB 이상 작은 쉼을 먼저, 없으면 12dB 이상 작은 쉼, 그것도 없으면 max_seconds에서 자른다."""
    db = _frame_db(samples)
    voiced = np.nonzero(db > db.max() - 35)[0]  # 서버(librosa top_db=35)와 같은 기준으로 첫 말소리를 찾는다
    if not len(voiced):
        return samples
    first, limit = voiced[0], voiced[0] + int(max_seconds * SAMPLE_RATE) // FRAME
    if len(db) <= limit:
        return samples

    smooth = 10 * np.log10(np.convolve(10 ** (db / 10), np.ones(7) / 7, mode="same") + 1e-12)
    speech = np.percentile(db, 90)
    earliest = first + int(min_seconds * SAMPLE_RATE) // FRAME
    window = smooth[earliest:limit]
    for drop in (18, 12):
        quiet = window <= speech - drop
        if quiet.any():
            end = int(np.nonzero(quiet)[0][-1])
            start = end
            while start > 0 and quiet[start - 1]:
                start -= 1
            cut = earliest + start + int(np.argmin(window[start : end + 1]))  # 가장 늦은 쉼에서 가장 조용한 곳
            return samples[: cut * FRAME]
    return samples[: limit * FRAME]


def concat(paths: list[Path], gap: float = 0.25) -> np.ndarray:
    silence = np.zeros(int(gap * SAMPLE_RATE), dtype=np.float32)
    parts: list[np.ndarray] = []
    for p in paths:
        parts.extend([read_wav(p), silence])
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
