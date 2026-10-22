"""대본 -> 음성. runpod = Chatterbox(자녀 목소리), local = Windows 내장 한국어 음성(개발용 대체)."""

import base64
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from . import audio, runpod


@dataclass
class TTSResult:
    provider: str
    gpu_seconds: float = 0.0
    cost_usd: float = 0.0


def synthesize(text: str, reference_wav: Path, out_wav: Path) -> TTSResult:
    if settings.tts_provider == "runpod":
        return _runpod(text, reference_wav, out_wav)
    return _local(text, out_wav)


def _runpod(text: str, reference_wav: Path, out_wav: Path) -> TTSResult:
    # 입력·출력 계약은 backend/gpu_worker/tts_handler.py 참고
    output, gpu_seconds = runpod.run(
        settings.runpod_tts_endpoint_id,
        {
            "text": text,
            "language": "ko",
            "reference_audio_b64": base64.b64encode(reference_wav.read_bytes()).decode(),
        },
    )
    if "audio_b64" not in output:
        raise runpod.RunPodError(f"TTS 응답에 audio_b64가 없습니다: {list(output)}")
    # Chatterbox 출력에 들어 있는 워터마크가 지워지지 않도록 음량 조정 없이 형식만 맞춘다
    samples = audio.decode(base64.b64decode(output["audio_b64"]))
    audio.write_wav(out_wav, samples)
    return TTSResult("runpod", gpu_seconds, runpod.cost(gpu_seconds))


_SAPI_SCRIPT = r"""
param([string]$TextFile, [string]$OutFile)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$ko = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'ko-KR' } | Select-Object -First 1
if ($ko) { $s.SelectVoice($ko.VoiceInfo.Name) }
$s.Rate = -1
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($OutFile, $fmt)
$s.Speak([System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8))
$s.Dispose()
"""


def _local(text: str, out_wav: Path) -> TTSResult:
    if sys.platform != "win32":
        raise RuntimeError("local TTS는 Windows에서만 동작합니다. TTS_PROVIDER=runpod로 설정하세요.")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "tts.ps1"
        script.write_text(_SAPI_SCRIPT, encoding="utf-8-sig")
        text_file = Path(tmp) / "text.txt"
        text_file.write_text(text, encoding="utf-8")
        raw = Path(tmp) / "raw.wav"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(text_file), str(raw)],
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0 or not raw.exists():
            raise RuntimeError(f"Windows TTS 실패: {proc.stderr.decode('cp949', 'replace')[-300:]}")
        samples = audio.read_wav(raw)
    audio.write_wav(out_wav, audio.clean(samples))
    return TTSResult("local")
