"""FLOAT 생성 조정: 사진 충실도(참조 가이던스)와 눈 후처리.

Kaggle 노트북 float_infer.ipynb에서 써 보고 고른 기능을 핸들러(video_handler.py)로 옮겼다.
모두 학습 없이 추론할 때만 적용한다. 요청에 값이 없으면 DEFAULTS를 쓰고, 끄려면 아래 '끔' 값을 보낸다.

  RefGuidance        사진 충실도. FMT의 가이던스에 '사진 있음 - 사진 없음' 차이를 더한다
  motion_directions  사진마다 움직임 방향 20개 중 눈·입을 움직이는 방향을 찾는다
  eye_postprocess    생성된 움직임에서 깜빡임 간격·시선 떨림을 손질하고, 갑자기 튀는 프레임을 다듬는다
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from scipy.ndimage import gaussian_filter1d

REF_MODES = ("free", "eye", "all")

# 기본값. 생성 영상에서 시선이 튀어서 시선 안정·사진 충실도를 노트북 추천값(0.4, 3)보다 올렸다 (2026-10-27).
# 끔: r_cfg_scale 1, eye_stable 0, blink_gap 0, dejump false
DEFAULTS = {"r_cfg_scale": 4.0, "ref_mode": "free", "eye_stable": 0.7, "blink_gap": 0.0, "dejump": True}


def options(inp: dict) -> dict:
    """요청 입력에서 생성 조정 값을 읽는다. 없거나 비어 있으면 DEFAULTS, 0·false처럼 끄는 값은 그대로 쓴다."""
    def get(key):
        value = inp.get(key)
        return DEFAULTS[key] if value is None or value == "" else value

    out = {
        "r_cfg_scale": float(get("r_cfg_scale")),
        "ref_mode": str(get("ref_mode")).strip().lower(),
        "eye_stable": float(get("eye_stable")),
        "blink_gap": float(get("blink_gap")),
        "dejump": str(get("dejump")).strip().lower() in ("1", "true", "yes", "on"),
    }
    if out["ref_mode"] not in REF_MODES:
        raise ValueError(f"ref_mode는 {', '.join(REF_MODES)} 중 하나여야 합니다 (요청 {out['ref_mode']})")
    if not 0.0 <= out["eye_stable"] <= 1.0:
        raise ValueError(f"eye_stable은 0~1이어야 합니다 (요청 {out['eye_stable']})")
    if out["blink_gap"] < 0:
        raise ValueError(f"blink_gap은 0 이상이어야 합니다 (요청 {out['blink_gap']})")
    return out


class RefGuidance:
    """FMT.forward_with_cfv를 바꿔 끼워 사진 충실도를 적용한다.

    FLOAT 공식 코드는 r_cfg_scale을 받기만 하고 계산에 쓰지 않는다. 학습 때 사진 조건을 10% 확률로 비웠기 때문에
    (ref_dropout_prob=0.1) 모델은 '사진 없음' 상태를 알고, 그 차이를 scale배로 키우면 시선·기본 표정이 사진에서 덜 벗어난다.
    scale = 1이면 원래 코드를 그대로 부른다. mode는 그 차이 중 어디까지 적용할지:
      free  입(음성)·감정이 움직이려는 방향과 겹치는 성분을 프레임마다 빼고 적용 → 시선은 잡고 입·감정은 유지
      eye   눈 방향(motion_directions)에만 적용
      all   전체 적용 → 표정까지 사진(보통 무표정) 쪽으로 당겨져 감정이 약해진다
    """

    def __init__(self, fmt: torch.nn.Module):
        self.scale = 1.0
        self.mode = "free"
        self.eye_q: torch.Tensor | None = None  # [512, k], mode == "eye"일 때
        self._fmt = fmt
        self._original = fmt.forward_with_cfv
        fmt.forward_with_cfv = self.forward_with_cfv  # FLOAT.sample이 self.fmt.forward_with_cfv(...)로 부른다

    def forward_with_cfv(self, t, x, wa, wr, we, prev_x, prev_wa, a_cfg_scale=1.0, r_cfg_scale=1.0, e_cfg_scale=1.0, **kwargs):
        if self.scale == 1.0:
            return self._original(t, x, wa, wr, we, prev_x, prev_wa, a_cfg_scale=a_cfg_scale,
                                  r_cfg_scale=r_cfg_scale, e_cfg_scale=e_cfg_scale, **kwargs)
        # 원래 코드의 3개(조건 없음 / 전체 / 음성만)에 '사진 없음'을 더해 한 번에 계산한다
        cat = lambda *v: torch.cat(v, dim=0)  # noqa: E731
        za, zr, ze = torch.zeros_like(wa), torch.zeros_like(wr), torch.zeros_like(we)
        out = self._fmt.forward(t, cat(x, x, x, x), cat(za, wa, wa, wa), cat(wr, wr, wr, zr), cat(ze, we, ze, we),
                                cat(prev_x, prev_x, prev_x, prev_x), cat(prev_wa, prev_wa, prev_wa, prev_wa), train=False)
        uncond, all_cond, audio_only, no_ref = torch.chunk(out, 4, dim=0)
        ref_term = all_cond - no_ref
        if self.mode == "eye" and self.eye_q is not None:
            ref_term = (ref_term @ self.eye_q) @ self.eye_q.t()
        elif self.mode == "free":
            basis = []
            for b in (audio_only - uncond, all_cond - audio_only):
                for q in basis:
                    b = b - (b * q).sum(-1, keepdim=True) * q
                basis.append(b / (b.norm(dim=-1, keepdim=True) + 1e-8))
            for q in basis:
                ref_term = ref_term - (ref_term * q).sum(-1, keepdim=True) * q
        return (uncond + a_cfg_scale * (audio_only - uncond) + e_cfg_scale * (all_cond - audio_only)
                + (self.scale - 1.0) * ref_term)


@dataclass
class Directions:
    eye: torch.Tensor  # [512, k] 눈(시선)을 가장 많이 움직이는 방향
    all: torch.Tensor  # [512, 20] 움직임 방향 전체 (정규 직교)
    eye_idx: list[int]
    mouth_idx: list[int]  # 입을 많이 움직이는 방향 (눈 방향 제외). 튀는 곳 다듬기에서 건드리지 않는다


@torch.no_grad()
def motion_directions(G, landmarks: np.ndarray, s_r, lam, feats, k_eye: int = 4, step: float = 1.5) -> Directions:
    """방향 20개를 하나씩 ±step만큼 움직여 렌더링하고, 얼굴 전체 대비 눈·입 주변이 많이 바뀌는 방향을 고른다.

    landmarks: 512 크롭 사진의 얼굴 랜드마크 68점. s_r, lam, feats: FLOAT.encode_image_into_latent 결과.
    """
    def box(pts, pad):
        return (max(int(pts[:, 0].min()) - pad, 0), max(int(pts[:, 1].min()) - pad, 0),
                int(pts[:, 0].max()) + pad, int(pts[:, 1].max()) + pad)

    eb, mb, fb = box(landmarks[36:48], 10), box(landmarks[48:68], 12), box(landmarks, 0)
    dec = G.motion_autoencoder.dec
    q_all = dec.direction(None)
    eye_share, mouth_share = [], []
    for i in range(q_all.shape[1]):
        outs = []
        for sign in (-1, 1):
            moved = lam.clone()
            moved[0, i] += sign * step
            img, _ = dec(s_r + dec.direction(moved), alpha=None, feats=feats)
            outs.append(((img[0].clamp(-1, 1) + 1) / 2).mean(0).cpu().numpy())
        diff = np.abs(outs[1] - outs[0])
        face = diff[fb[1]:fb[3], fb[0]:fb[2]].mean() + 1e-8
        eye_share.append(diff[eb[1]:eb[3], eb[0]:eb[2]].mean() / face)
        mouth_share.append(diff[mb[1]:mb[3], mb[0]:mb[2]].mean() / face)
    eye_idx = np.argsort(-np.array(eye_share))[:k_eye]
    mouth_idx = [int(i) for i in np.argsort(-np.array(mouth_share))[:6] if i not in eye_idx]
    return Directions(q_all[:, eye_idx].float(), q_all.float(), eye_idx.tolist(), mouth_idx)


def eye_postprocess(x: torch.Tensor, r_s: torch.Tensor, dirs: Directions, fps: float, *,
                    stable: float = 0.0, blink_gap: float = 0.0, dejump: bool = False) -> tuple[torch.Tensor, list[str]]:
    """생성된 움직임 x [B, T, 512]를 손질한다. 입 방향은 건드리지 않는다.

    stable     0~1. 천천히 흐르는 시선은 사진 속 시선 쪽으로 당기고 빠른 떨림은 부드럽게 (1 = 사진 시선에 고정)
    blink_gap  초. 이보다 가깝게 붙은 깜빡임은 지우고 앞뒤를 직선으로 잇는다
    dejump     입 외 움직임이 갑자기 크게 바뀌는 프레임의 앞뒤만 부드럽게 (FLOAT가 2초 단위로 이어 붙이는 이음새)
    반환: (손질한 x, 무엇을 했는지 기록)
    """
    notes: list[str] = []
    q_eye = dirs.eye
    c = (x @ q_eye).float().cpu().numpy()  # [B, T, k] 눈 방향 계수
    ref = (r_s @ q_eye).float().cpu().numpy()  # [B, k] 사진 속 눈 상태
    new = c.copy()
    for b in range(c.shape[0]):
        s = c[b].copy()
        T = len(s)
        # (1) 깜빡임: 짧고 급격한 변화를 찾아, 최소 간격보다 가까운 것은 지우고 앞뒤를 직선으로 잇는다
        if blink_gap > 0 and T > 20:
            hp = s - gaussian_filter1d(s, 5, axis=0, mode="nearest")
            e = np.linalg.norm(hp, axis=1)
            thr = e.mean() + 1.5 * e.std()
            peaks = [i for i in range(2, T - 2) if e[i] > thr and e[i] == e[max(0, i - 4):i + 5].max()]
            kept, last = [], -10 ** 9
            for i in peaks:
                if i - last >= blink_gap * fps:
                    kept.append(i)
                    last = i
                else:
                    lo, hi = max(0, i - 6), min(T - 1, i + 6)
                    w = np.linspace(0, 1, hi - lo + 1)[:, None]
                    s[lo:hi + 1] = (1 - w) * s[lo] + w * s[hi]
            notes.append(f"깜빡임 {len(peaks)}회 중 {len(kept)}회 남김")
        # (2) 시선 안정: 느린 성분은 사진 시선 쪽으로, 빠른 떨림은 부드럽게
        if stable > 0:
            low = gaussian_filter1d(s, 8, axis=0, mode="nearest")
            high = s - low
            low = ref[b] + (1 - stable) * (low - ref[b])
            high = gaussian_filter1d(high, 0.5 + 2.5 * stable, axis=0, mode="nearest")
            s = low + high
        new[b] = s
    x = x + torch.tensor(new - c, device=x.device, dtype=x.dtype) @ q_eye.t()

    # (3) 튀는 곳만 다듬기: 나머지 프레임은 원래 속도 그대로 둔다
    if dejump:
        q_all, keep = dirs.all, set(dirs.mouth_idx)
        non_mouth = [i for i in range(q_all.shape[1]) if i not in keep]
        ca = (x @ q_all).float().cpu().numpy()
        resid = (x - (x @ q_all) @ q_all.t()).float().cpu().numpy()  # 방향 밖 성분
        n_fix = 0
        for b in range(ca.shape[0]):
            T = ca.shape[1]
            v = np.linalg.norm(np.diff(ca[b][:, non_mouth], axis=0), axis=1)
            jumps = np.where(v > 2.5 * np.median(v) + 1e-6)[0]
            if len(jumps) == 0:
                continue
            w = np.zeros(T)
            for j in jumps:
                w[max(0, j - 3):min(T, j + 5)] = 1.0
            w = np.clip(gaussian_filter1d(w, 1.5) * 1.5, 0, 1)[:, None]
            smooth = gaussian_filter1d(ca[b], 2.0, axis=0, mode="nearest")
            ca[b][:, non_mouth] = (1 - w) * ca[b][:, non_mouth] + w * smooth[:, non_mouth]
            resid[b] = (1 - w) * resid[b] + w * gaussian_filter1d(resid[b], 2.0, axis=0, mode="nearest")
            n_fix += len(jumps)
        x = (torch.tensor(ca, device=x.device, dtype=x.dtype) @ q_all.t()
             + torch.tensor(resid, device=x.device, dtype=x.dtype))
        notes.append(f"튀는 곳 {n_fix}군데 다듬음")
    return x, notes
