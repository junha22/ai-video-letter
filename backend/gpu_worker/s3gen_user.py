"""사용자별 S3Gen 음색 어댑터 학습의 GPU 단계. 웹 백엔드 워커(app/services/s3gen.py)가 Wemeet-cb 환경 python으로 실행한다.

  prepare  녹음 문장들 -> 화자 일관성 검사 -> 참조·평가·검증·학습 분할 -> S3Gen 특징값
           출력 형식이 연구 코드(s3gen_data, enroll)와 같아서 chatterbox_lora.s3gen_train을 그대로 돌릴 수 있다
  score    기본 목소리와 어댑터 목소리로 같은 문장·seed로 만든 음성을, 학습에 안 쓴 실제 녹음과 비교해 화자 유사도를 낸다

학습·평가 코드는 WEMEET_LORA_CODE_DIR(C:\\WE_MEET\\AI_test)의 chatterbox_lora를 쓴다.
결과는 마지막 줄에 JSON 한 줄로 출력한다. 녹음 문장 텍스트는 받지도 출력하지도 않는다.

  python s3gen_user.py prepare --spec <work>/spec.json --work <work>
  python s3gen_user.py score --work <work> --pairs <work>/pairs.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.environ.get("WEMEET_LORA_CODE_DIR", r"C:\WE_MEET\AI_test"))

import torch  # noqa: E402

from chatterbox_lora.common import checkpoint_dir, resolve_device, safe_console  # noqa: E402

SPEAKER = "user"
SUBSET = "user"


def _load16(path: str) -> np.ndarray:
    import librosa

    return librosa.load(path, sr=16000)[0]


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def prepare(args) -> dict:
    """spec: {"ref": id, "clips": [{"id", "audio", "duration"}], "test_sec", "val_sec", "min_sim", "min_train_sec", "seed"}"""
    from chatterbox.models.voice_encoder import VoiceEncoder
    from chatterbox_lora.s3gen_data import featurize, load_s3gen

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    device = resolve_device("auto")
    clips = spec["clips"]
    ref_id = spec["ref"]

    # 다른 사람 목소리·웃음·잡음처럼 보이는 녹음은 녹음 전체의 중앙값 목소리와 멀어서 뺀다 (참조 문장은 남긴다)
    ve = VoiceEncoder()
    ve.load_state_dict(torch.load(checkpoint_dir() / "ve.pt", map_location="cpu", weights_only=True))
    ve.to(device).eval()
    with torch.no_grad():
        embs = {c["id"]: _unit(ve.embeds_from_wavs([_load16(c["audio"])], sample_rate=16000).mean(0)) for c in clips}
    median = _unit(np.median(np.stack(list(embs.values())), axis=0))
    for c in clips:
        c["sim"] = round(float(embs[c["id"]] @ median), 4)
    kept = [c for c in clips if c["id"] == ref_id or c["sim"] >= spec["min_sim"]]
    dropped = [{"id": c["id"], "sim": c["sim"]} for c in clips if c not in kept]
    del ve

    # 참조 = TTS 서버에 등록한 문장 (실제 생성 조건과 같게). 나머지에서 평가용·검증용을 먼저 떼고 남은 것으로 학습한다
    ref = next(c for c in kept if c["id"] == ref_id)
    rest = sorted((c for c in kept if c is not ref), key=lambda c: c["id"])
    random.Random(spec["seed"]).shuffle(rest)
    test, val, train, acc = [], [], [ref], {"test": 0.0, "val": 0.0}
    for c in rest:
        if acc["test"] < spec["test_sec"]:
            test.append(c)
            acc["test"] += c["duration"]
        elif acc["val"] < spec["val_sec"]:
            val.append(c)
            acc["val"] += c["duration"]
        else:
            train.append(c)
    train_sec = round(sum(c["duration"] for c in train), 1)
    summary = {
        "clips": len(clips),
        "kept": len(kept),
        "dropped": dropped,
        "train_clips": len(train),
        "train_sec": train_sec,
        "val_clips": len(val),
        "val_sec": round(acc["val"], 1),
        "test_clips": len(test),
        "test_sec": round(acc["test"], 1),
    }
    if train_sec < spec["min_train_sec"] or len(val) < 2 or len(test) < 2:
        return {"ok": False, "reason": "not_enough_audio", **summary}

    split = {
        "ref": ref_id,
        "test": [c["id"] for c in test],
        "val": [c["id"] for c in val],
        "subsets": {SUBSET: [c["id"] for c in train]},
        "subset_sec": {SUBSET: train_sec},
    }
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "splits.json").write_text(
        json.dumps({"speakers": {SPEAKER: split}, "clips": {c["id"]: c for c in kept}}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    s3gen = load_s3gen(device)
    feat_dir = args.work / "features"
    feat_dir.mkdir(exist_ok=True)
    for c in kept:
        torch.save(featurize(s3gen, Path(c["audio"])), feat_dir / f"{c['id']}.pt")
    return {"ok": True, **summary}


def score(args) -> dict:
    """pairs: {"pairs": [{"base": wav, "cand": wav}]}. 같은 문장·seed라 두 음성은 S3Gen 어댑터만 다르다."""
    from chatterbox_lora.s3gen_eval import Embedders

    device = resolve_device("auto")
    meta = json.loads((args.work / "splits.json").read_text(encoding="utf-8"))
    split = meta["speakers"][SPEAKER]
    pairs = json.loads(args.pairs.read_text(encoding="utf-8"))["pairs"]
    emb = Embedders(device)

    # 기준: 학습에 안 쓴 실제 녹음(평가용)의 평균 목소리
    test = [emb(_load16(meta["clips"][i]["audio"])) for i in split["test"]]
    real = {k: _unit(np.mean([t[k] for t in test], axis=0)) for k in ("ve", "sv")}
    sims = {"base": {"ve": [], "sv": []}, "cand": {"ve": [], "sv": []}}
    for p in pairs:
        for side in ("base", "cand"):
            e = emb(_load16(p[side]))
            for k in ("ve", "sv"):
                sims[side][k].append(float(e[k] @ real[k]))
    mean = {side: {k: round(float(np.mean(v)), 4) for k, v in d.items()} for side, d in sims.items()}
    return {
        "ok": True,
        "pairs": len(pairs),
        "test_clips": len(test),
        "base": mean["base"],
        "cand": mean["cand"],
        "gain": {k: round(mean["cand"][k] - mean["base"][k], 4) for k in ("ve", "sv")},
        "wins": {k: sum(c > b for b, c in zip(sims["base"][k], sims["cand"][k])) for k in ("ve", "sv")},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("prepare")
    pr.add_argument("--spec", type=Path, required=True)
    pr.add_argument("--work", type=Path, required=True)
    sc = sub.add_parser("score")
    sc.add_argument("--work", type=Path, required=True)
    sc.add_argument("--pairs", type=Path, required=True)
    args = p.parse_args(argv)
    safe_console()
    result = prepare(args) if args.command == "prepare" else score(args)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
