"""답장 받아쓰기 프로세스: BuzzASR/korean 올림 → 받아쓰기(+품질 검사) → 결과 JSON → 내림 → 끝 (docs/REPLY_ANALYSIS.md 6절).

분석 서버(reply_analysis_server.py)가 요청마다 하나씩 띄운다. 프로세스가 끝나야 CUDA 컨텍스트까지 GPU 메모리가 모두 돌아와서,
바로 다음 영상 작업이 메모리 부족으로 실패하지 않는다.
  python gpu_worker/reply_stt.py <16kHz 모노 wav> <결과 json>
받아쓰기 내용은 결과 파일에만 쓰고 화면(로그)에는 걸린 시간·조각 수만 남긴다.
"""

import gc
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reply_audio  # noqa: E402

MODEL = os.environ.get("REPLY_STT_MODEL", "BuzzASR/korean")


def main() -> None:
    wav_path, out_path = sys.argv[1], sys.argv[2]
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    started = time.monotonic()
    proc = WhisperProcessor.from_pretrained(MODEL)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL, torch_dtype=dtype).to(device).eval()
    loaded = time.monotonic()

    def transcribe_chunk(x, beams=1):
        feats = proc(x, sampling_rate=reply_audio.SR, return_tensors="pt").input_features.to(device, dtype)
        with torch.no_grad():
            ids = model.generate(feats, num_beams=beams, no_repeat_ngram_size=3,
                                 repetition_penalty=1.2, max_new_tokens=400)   # 모델 카드 권장 설정
        return proc.batch_decode(ids, skip_special_tokens=True)[0].strip()

    out = reply_audio.run_stt(wav_path, transcribe_chunk)
    out.update(model=MODEL, device=device, load_seconds=round(loaded - started, 1),
               seconds=round(time.monotonic() - loaded, 1))
    if device == "cuda":
        out["gpu_peak_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"[stt] {device} 모델 올리기 {out['load_seconds']}초, 받아쓰기 {out['seconds']}초 "
          f"({out['duration']}초 음성, 조각 {out['pieces']}개, 문제 {len(out['problems'])}개)", file=sys.stderr)


if __name__ == "__main__":
    main()
