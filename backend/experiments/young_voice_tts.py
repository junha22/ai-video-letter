"""타임 슬립(어린 시절 모드) 목소리 시험: TTS가 처음부터 아이 목소리로 말하게 하면, 나중에 변환하는 것보다 자연스러운지 비교한다.

나중에 변환(지금 앱 방식)하면 낮은 목소리를 2배 넘게 올려야 해서 기계음·찌지직 소리가 났다 (docs/YOUNG_MODE.md '목소리 비교').
참조 음성을 먼저 어린 목소리로 바꿔 TTS 목소리를 따로 등록하면, TTS가 소리를 처음부터 새로 만들어서 그 잡음이 걸러질 수 있다.

GPU PC에서 TTS 서버를 띄운 뒤(npm run gpu 또는 run_server.ps1) backend 폴더에서 실행한다:
  .venv\\Scripts\\python.exe experiments\\young_voice_tts.py --user-id 3
  .venv\\Scripts\\python.exe experiments\\young_voice_tts.py --reference C:\\path\\my_voice.wav
  (praat-parselmouth가 없으면 먼저: .venv\\Scripts\\python.exe -m pip install -r requirements.txt)

같은 문장을 네 가지로 만든다 (모두 같은 seed):
  내 목소리        : 등록한 목소리 그대로 (비교 기준, 가리지 않음)
  나중에 변환      : 내 목소리 결과를 어린 목소리로 변환 (지금 앱 방식, audio.make_younger)
  아이 목소리 등록 : 참조 음성을 어린 목소리로 바꿔 TTS 목소리를 따로 등록하고 그 목소리로 만든다
  등록 + 높이 보정 : 위 결과의 높이만 목표로 맞춘다 (울림은 참조 음성에서 이미 바꿨다). TTS가 높이를 덜 따라올 때를 대비
결과: data/young_voice_tts_test/index.html (방법을 가린 청취 페이지), key.json, 숫자 표.
녹음과 결과는 이 PC에만 둔다 (data 폴더는 git에 올라가지 않는다). 시험용으로 등록한 TTS 목소리는 끝나면 지운다.
"""

import argparse
import html
import json
import random
import secrets
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import parselmouth  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import audio, wemeet_tts  # noqa: E402

SENTENCES = [
    "엄마, 오늘 저녁은 드셨어요? 이번 주말에 집에 갈게요.",
    "아빠, 생신 축하드려요! 항상 건강하세요.",
    "할머니, 날씨가 추워졌어요. 감기 조심하시고 따뜻하게 입으세요.",
]
METHODS = {"post": "나중에 변환 (지금 앱 방식)", "reg": "아이 목소리 등록", "fix": "등록 + 높이 보정"}


def pitch(path: Path) -> float:
    f0 = parselmouth.Sound(str(path)).to_pitch(pitch_floor=75, pitch_ceiling=600).selected_array["frequency"]
    return float(np.median(f0[f0 > 0])) if (f0 > 0).any() else 0.0


def player(label: str, file: str) -> str:
    return f'<div class="item"><b>{html.escape(label)}</b><audio controls preload="none" src="{file}"></audio></div>'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--user-id", type=int, help="앱에 목소리를 등록한 사용자 번호 (data/users/<번호>/voice/tts_reference.wav)")
    source.add_argument("--reference", type=Path, help="참조 음성 wav (내 목소리 10초 안팎)")
    parser.add_argument("--out", type=Path, default=settings.data_dir / "young_voice_tts_test")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--hz", type=float, default=settings.young_voice_hz or 270)
    parser.add_argument("--formant", type=float, default=settings.young_voice_formant)
    parser.add_argument("--range", type=float, default=settings.young_voice_range)
    args = parser.parse_args()

    reference = args.reference or settings.data_dir / "users" / str(args.user_id) / "voice" / "tts_reference.wav"
    if not reference.exists():
        sys.exit(f"참조 음성이 없습니다: {reference}\n앱에서 목소리를 등록한 사용자 번호를 주거나 --reference로 wav를 지정하세요.")
    if not wemeet_tts.health():
        sys.exit(f"TTS 서버({settings.wemeet_tts_url})에 연결할 수 없습니다. 먼저 npm run gpu 또는 run_server.ps1로 띄우세요.")

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    ref_adult, ref_young = out / "ref_original.wav", out / "ref_young.wav"
    shutil.copyfile(reference, ref_adult)
    shutil.copyfile(reference, ref_young)
    audio.make_younger(ref_young, args.hz, args.formant, args.range)

    tag = secrets.token_hex(4)
    adult_id, young_id = f"exp_young_{tag}_adult", f"exp_young_{tag}_young"
    rows, key, cards = [], {}, []
    rng = random.Random(args.seed)
    try:
        wemeet_tts.register_voice(adult_id, ref_adult)
        wemeet_tts.register_voice(young_id, ref_young)
        for i, text in enumerate(SENTENCES):
            base = out / f"s{i}_base.wav"
            base.write_bytes(wemeet_tts.synthesize(text, adult_id, args.seed).wav)
            files = {m: out / f"s{i}_{m}.wav" for m in METHODS}
            shutil.copyfile(base, files["post"])
            audio.make_younger(files["post"], args.hz, args.formant, args.range)
            files["reg"].write_bytes(wemeet_tts.synthesize(text, young_id, args.seed).wav)
            shutil.copyfile(files["reg"], files["fix"])
            audio.make_younger(files["fix"], args.hz, 1.0, 1.0)

            rows.append((i + 1, "내 목소리", pitch(base), audio.wav_duration(base)))
            for m, path in files.items():
                rows.append((i + 1, METHODS[m], pitch(path), audio.wav_duration(path)))
            order = list(METHODS)
            rng.shuffle(order)
            items = []
            for letter, m in zip("ABC", order):
                blind = out / f"s{i}_{letter}.wav"
                files[m].rename(blind)
                key[f"문장 {i + 1} {letter}"] = METHODS[m]
                items.append(player(letter, blind.name))
            answers = "".join(f"<li>{l}: {html.escape(key[f'문장 {i + 1} {l}'])}</li>" for l in "ABC")
            cards.append(
                f"<section><h2>문장 {i + 1}</h2><p class='text'>{html.escape(text)}</p>{player('내 목소리', base.name)}"
                f"{''.join(items)}<details><summary>정답 보기</summary><ul>{answers}</ul></details></section>"
            )
    finally:
        for voice_id in (adult_id, young_id):
            try:
                wemeet_tts.delete_voice(voice_id)
            except wemeet_tts.TTSError as e:
                print(f"시험용 목소리 {voice_id}를 지우지 못했습니다. TTS 서버에서 직접 지워 주세요: {e}")

    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"참조 음성 높이: 원래 {pitch(ref_adult):.0f}Hz → 아이로 바꾼 것 {pitch(ref_young):.0f}Hz (목표 {args.hz:.0f}Hz)\n")
    print(f"{'문장':<6}{'방법':<24}{'높이':>8}{'길이':>8}")
    for n, label, f0, dur in rows:
        print(f"{n:<6}{label:<24}{f0:>6.0f}Hz{dur:>7.1f}초")

    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>어린 목소리 TTS 비교</title><style>
body{{font-family:system-ui,sans-serif;max-width:720px;margin:24px auto;padding:0 16px;color:#222;background:#fffaf4}}
section{{background:#fff;border:1px solid #ead9cd;border-radius:14px;padding:12px 16px;margin:14px 0}}
.item{{display:flex;align-items:center;gap:12px;margin:6px 0}} .item b{{min-width:72px}} audio{{flex:1;max-width:100%}}
h2{{font-size:17px;margin:4px 0}} .text{{color:#666;margin:2px 0 8px}} details{{margin-top:8px;color:#555}}
</style></head><body><h1>어린 목소리 TTS 비교 (블라인드)</h1>
<p>문장마다 A~C를 듣고 ① 찌지직·기계음이 가장 적은 것 ② 가장 아이 같은 것 ③ 내 목소리를 닮은 것을 고른 뒤 정답을 열어 보세요.</p>
<section><h2>참조 음성</h2>{player('원래', ref_adult.name)}{player('아이로 바꾼 것', ref_young.name)}</section>
{''.join(cards)}</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"\n청취 페이지: {out / 'index.html'}")


if __name__ == "__main__":
    main()
