"""RunPod 서버리스 TTS 핸들러 (Chatterbox Multilingual, zero-shot).

아직 GPU에서 실행해 보지 않은 초안이다. 백엔드(app/services/tts.py)와 주고받는 형식만 맞춰 두었다.

입력:  {"text": str, "language": "ko", "reference_audio_b64": str(wav), "exaggeration"?: float, "cfg_weight"?: float}
출력:  {"audio_b64": str(wav), "sample_rate": int}

배포: pip install runpod chatterbox-tts torchaudio 후 이 파일을 RunPod 서버리스 이미지의 시작 스크립트로 지정한다.
사용자별 S3Gen 가중치·공통 T3 LoRA를 붙일 때는 모델을 불러온 뒤 가중치를 덮어쓰고,
입력에 user_id를 받아 해당 S3Gen 가중치를 고르도록 확장한다.
"""

import base64
import io
import os
import tempfile

import runpod
import torchaudio
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")


def handler(job):
    inp = job["input"]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(base64.b64decode(inp["reference_audio_b64"]))
        reference = f.name
    try:
        wav = model.generate(
            inp["text"],
            language_id=inp.get("language", "ko"),
            audio_prompt_path=reference,
            exaggeration=inp.get("exaggeration", 0.5),
            cfg_weight=inp.get("cfg_weight", 0.5),
        )
    finally:
        os.unlink(reference)
    buf = io.BytesIO()
    torchaudio.save(buf, wav, model.sr, format="wav")
    return {"audio_b64": base64.b64encode(buf.getvalue()).decode(), "sample_rate": model.sr}


runpod.serverless.start({"handler": handler})
