"""부모님 답장 분석의 음성 쪽 규칙: 받아쓰기 자르기·품질 검사, 운율(목소리) 측정 (docs/REPLY_ANALYSIS.md).

GPU PC의 분석 서버(reply_analysis_server.py)와 받아쓰기 프로세스(reply_stt.py)가 쓴다.
정답지 reply_analysis_reference.py에서 그대로 옮겼다. 값과 동작을 바꾸지 않는다.
librosa는 함수 안에서 불러서, 자르기·품질 검사는 numpy만으로 시험할 수 있다 (backend/tests/test_reply_rules.py).
"""

import re
import zlib

import numpy as np

SR = 16000


def load_audio(path):
    import librosa
    wav, _ = librosa.load(path, sr=SR, mono=True)      # 16kHz 모노로 변환
    return wav.astype(np.float32)


def split_on_silence(wav, max_sec=25.0, min_sec=12.0):
    """Whisper는 30초까지만 들으므로, 25초를 넘으면 12~25초 사이에서 가장 조용한 곳을 잘라요"""
    frame = int(0.03 * SR)
    n = len(wav) // frame
    if len(wav) <= max_sec * SR or n < 2:
        return [(0, len(wav))]
    rms = np.sqrt(np.mean(wav[:n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    smooth = np.convolve(rms, np.ones(10) / 10, mode="same")          # 0.3초 평균
    cuts, start = [0], 0
    while len(wav) - start > max_sec * SR:
        f_lo = (start + int(min_sec * SR)) // frame
        f_hi = min((start + int(max_sec * SR)) // frame, n - 1)
        cut = (f_lo + int(np.argmin(smooth[f_lo:f_hi]))) * frame + frame // 2
        cuts.append(cut); start = cut
    cuts.append(len(wav))
    pieces = list(zip(cuts[:-1], cuts[1:]))
    if len(pieces) > 1 and (pieces[-1][1] - pieces[-1][0]) < 1.0 * SR:  # 1초도 안 되는 꼬리는 앞에 붙임
        pieces[-2:] = [(pieces[-2][0], pieces[-1][1])]
    return pieces


def is_silent(x, ref):
    """말소리가 거의 없는 조각은 받아쓰지 않음 (Whisper는 침묵에서 '시청해 주셔서 감사합니다'를 지어내곤 함)"""
    return np.percentile(np.abs(x), 95) < 0.1 * ref


def hangul_len(t):
    return len(re.findall(r"[가-힣]", t))


HALLUCINATIONS = ["시청해주셔서감사", "구독과좋아요", "구독좋아요", "자막제공", "다음영상에서"]


def check_text(t, dur):
    """받아쓰기 실패 신호: 빈 출력 / 같은 말 반복 / 길이에 비해 글자가 너무 많음 / 흔한 지어내기 문구"""
    t = t.strip()
    if hangul_len(t) < 2:
        return "빈 출력"
    if re.search(r"(.{2,15}?)(?:\s*\1){4,}", t):
        return "같은 말 반복"
    b = t.encode()
    if len(t) >= 50 and len(zlib.compress(b)) / len(b) < 1 / 2.4:
        return "같은 말 반복(압축률)"
    if hangul_len(t) / max(dur, 0.1) > 12:
        return "길이에 비해 글자가 너무 많음(지어내기 의심)"
    if any(h in t.replace(" ", "") for h in HALLUCINATIONS):
        return "지어내기 의심 문구"
    return None


def run_stt(path, transcribe_chunk):
    """transcribe_chunk(x, beams=1) = 조각 하나를 받아쓰는 함수 (reply_stt.py가 BuzzASR로 넘긴다)"""
    wav = load_audio(path)
    dur = len(wav) / SR
    ref = np.percentile(np.abs(wav), 95) + 1e-9
    pieces = split_on_silence(wav)
    texts, problems = [], []
    for s, e in pieces:
        x, d = wav[s:e], (e - s) / SR
        if is_silent(x, ref):
            continue
        t = transcribe_chunk(x)
        p = check_text(t, d)
        if p:                                     # 실패면 빔 서치로 한 번 더
            t2 = transcribe_chunk(x, beams=5)
            if check_text(t2, d) is None:
                t, p = t2, None
        texts.append(t)
        if p:
            problems.append(f"{s/SR:.0f}~{e/SR:.0f}초: {p}")
    text = " ".join(texts).strip()
    if not text:
        problems.append("말소리를 찾지 못함")
    return {"text": text, "duration": round(dur, 1), "pieces": len(pieces), "problems": problems}


# ---------------------------------------------------------------- 운율 (목소리) ----
def _runs(mask):
    """True/False가 이어지는 구간들: [(시작, 끝, 값), ...] (끝은 포함 안 함)"""
    if len(mask) == 0:
        return []
    change = np.flatnonzero(np.diff(mask.astype(np.int8))) + 1
    starts = np.r_[0, change]; ends = np.r_[change, len(mask)]
    return [(int(s), int(e), bool(mask[s])) for s, e in zip(starts, ends)]


def speech_mask(wav, hop=160, win=400):
    """10ms마다 말소리인지 표시 (소리 에너지 기준). 0.15초 미만 끊김은 말로 이어 붙이고, 0.1초 미만 소리는 잡음으로 지움"""
    import librosa
    rms = librosa.feature.rms(y=wav, frame_length=win, hop_length=hop, center=True)[0]
    db = 20 * np.log10(rms + 1e-10)
    thr = max(np.percentile(db, 10) + 10, db.max() - 40)
    m = db > thr
    for s, e, v in _runs(m):
        if not v and 0 < s and e < len(m) and (e - s) * hop / SR < 0.15:
            m[s:e] = True
    for s, e, v in _runs(m):
        if v and (e - s) * hop / SR < 0.10:
            m[s:e] = False
    return m, db, hop


def measure_prosody(path, text):
    """답장 1개의 운율 값. text는 받아쓰기(말 속도 계산용)"""
    wav = load_audio(path)
    m, db, hop = speech_mask(wav)
    t = hop / SR
    idx = np.flatnonzero(m)
    if len(idx) * t < 3:
        return {"ok": False, "reason": "말소리가 3초보다 짧아 운율을 재지 않음"}
    first, last = idx[0], idx[-1]
    span = (last - first + 1) * t                                  # 첫 말부터 마지막 말까지
    pauses = [(e - s) * t for s, e, v in _runs(m[first:last + 1]) if not v and (e - s) * t >= 0.3]
    talk = span - sum(pauses)                                      # 실제로 말한 시간
    syll = hangul_len(text)                                        # 한글 글자 수 = 대략 음절 수
    import librosa
    f0, voiced, _ = librosa.pyin(wav, fmin=60, fmax=400, sr=SR, frame_length=1024, hop_length=320)
    f0 = f0[voiced & ~np.isnan(f0)]
    out = {"ok": True, "duration": round(len(wav) / SR, 1), "speech_sec": round(talk, 1),
           "pause_ratio": round(sum(pauses) / span, 3), "pauses_per_min": round(len(pauses) / (span / 60), 1),
           "mean_pause_sec": round(float(np.mean(pauses)), 2) if pauses else 0.0,
           "rate": round(syll / talk, 2) if talk > 1 and syll >= 10 else None,     # 음절/초
           "loudness_db": round(float(np.median(db[m])), 1)}
    if len(f0) >= 50:                                              # 목소리(유성음) 0.5초 이상
        st = 12 * np.log2(f0 / 100.0)                             # 반음 단위 (100Hz 기준)
        out.update(pitch_hz=round(float(np.median(f0)), 1), pitch_st=round(float(np.median(st)), 2),
                   pitch_range_st=round(float(np.percentile(st, 90) - np.percentile(st, 10)), 2))
    else:
        out.update(pitch_hz=None, pitch_st=None, pitch_range_st=None)
    return {k: (float(x) if isinstance(x, np.floating) else x) for k, x in out.items()}
