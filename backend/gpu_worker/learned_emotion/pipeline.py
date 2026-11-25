"""Production inference with the released FLOAT emotion checkpoints."""
from pathlib import Path
from fractions import Fraction
import hashlib
import io
import math

import av
import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly

from .adapters import DecoderRepair, install
from .ending_motion import HORIZON, load_ending
from .happy_lips import render_happy
from .regional_sad import RegionalSadFlow, face_regions
from .sad_refinement import COMMON_FORMAT, MOUTH_FORMAT, CommonSad, SharedMouth, align_mouth, expression_controls


EMOTIONS = ("neutral", "happy", "sad")


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint(root, name, format_name):
    file = root / name
    if not file.is_file():
        raise FileNotFoundError(f"Final FLOAT emotion checkpoint is missing: {file}")
    saved = torch.load(file, map_location="cpu", weights_only=True)
    if saved["format"] != format_name:
        raise ValueError(f"Unexpected emotion checkpoint format: {file}")
    return saved


def load_audio(processor, path):
    samples, rate = sf.read(str(path), dtype="float32", always_2d=True)
    samples = samples.mean(1)
    target = int(processor.sampling_rate)
    if rate != target:
        factor = math.gcd(rate, target)
        samples = resample_poly(samples, target // factor, rate // factor).astype(np.float32)
    return processor.wav2vec_preprocessor(samples, sampling_rate=target, return_tensors="pt").input_values


def rgb(frames):
    return ((frames.float().clamp(-1, 1) + 1) * 127.5).byte().permute(0, 2, 3, 1).cpu().numpy()


def write_video(frames, destination, crf, *, size):
    """Encode a silent 25fps stream. The app will add the original TTS audio."""
    with av.open(destination, mode="w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=25, options={"crf": str(crf), "preset": "fast"})
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        for index, frame in enumerate(frames):
            if isinstance(frame, np.ndarray):
                frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
            else:
                # A delayed timeline can reuse its first decoded frame. Give each
                # encoded copy independent timestamps and packet metadata.
                frame = av.VideoFrame.from_ndarray(frame.to_ndarray(format="yuv420p"), format="yuv420p")
            frame.pts = index
            frame.time_base = Fraction(1, 25)
            frame.pict_type = av.video.frame.PictureType.NONE
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def codec_roundtrip(frames, crf, size, *, pixel_format="rgb24"):
    # Landmark control is calibrated on the decoded video used in the release.
    with io.BytesIO() as buffer:
        write_video(frames, buffer, crf, size=size)
        buffer.seek(0)
        with av.open(buffer) as source:
            if pixel_format is None:
                return list(source.decode(video=0))
            return [frame.to_ndarray(format=pixel_format) for frame in source.decode(video=0)]


def preserve_yuv(frame, original, corrected):
    if original is corrected:
        return frame
    base = frame.to_ndarray(format="yuv420p")
    prior = av.VideoFrame.from_ndarray(original, format="rgb24").to_ndarray(format="yuv420p")
    updated = av.VideoFrame.from_ndarray(corrected, format="rgb24").to_ndarray(format="yuv420p")
    samples = (base.astype(np.int16) + updated - prior).clip(0, 255).astype(np.uint8)
    return av.VideoFrame.from_ndarray(samples, format="yuv420p")


class FinalEmotionRenderer:
    def __init__(self, agent, weights_root, float_checkpoint, lip_checkpoint):
        self.agent = agent
        self.model = agent.G.eval().requires_grad_(False)
        self.decoder = self.model.motion_autoencoder.dec
        self.device = next(self.model.parameters()).device
        weights_root = Path(weights_root)
        joint = checkpoint(weights_root, "float_v19_joint_quality/checkpoints/latest.pt",
                           "float_generated_joint_quality_v1")
        sad = checkpoint(weights_root, "float_v45_sad_corners/runs/20261124_091345/candidate.pt",
                         "float_sad_outer_eye_lip_v1")
        base_digest = file_digest(Path(float_checkpoint))
        lip_digest = file_digest(Path(lip_checkpoint))
        base_inputs = joint["signature"]["base_inputs"]
        if (base_inputs["float_sha256"] != base_digest or sad["float_sha256"] != base_digest
                or base_inputs["lip_adapter_sha256"] != lip_digest or sad["base_lora_sha256"] != lip_digest):
            raise ValueError("The released emotion checkpoints require their matching FLOAT and lip LoRA")

        self.sad = RegionalSadFlow(self.decoder, sad["style"]["alpha_std"],
                                   strong=True, trajectory=True, detail=True,
                                   corner_residual=sad.get("corner_residual", False)).to(self.device)
        self.sad.load_state_dict(sad["style"])
        self.sad.eval().requires_grad_(False)

        mouth = checkpoint(weights_root, "float_sad_mouth_detail/runs/20261124_142450_shared/candidate.pt",
                           MOUTH_FORMAT)
        self.mouth = SharedMouth().eval().requires_grad_(False)
        self.mouth.load_state_dict(mouth["model"])
        self.mouth_fraction = mouth["fraction"]
        self.frame_delay = int(mouth["frame_delay"])
        if not 0 <= self.frame_delay < HORIZON:
            raise ValueError("Unexpected timing in the released mouth checkpoint")
        common = checkpoint(weights_root, "float_sad_transfer/runs/20261125_common_face1_level/candidate.pt",
                            COMMON_FORMAT)
        self.common = CommonSad().eval().requires_grad_(False)
        self.common.load_state_dict(common["model"])
        self.profile = common["profile"].numpy()
        self.gap_bins = common["gap_bins"].numpy()
        self.ending = load_ending(weights_root / "float_ending_motion/runs/20261124_174813/candidate.pt", self.device)

        self.emotion = install(self.model, joint["adapter"]["rank"])
        self.emotion.restore(joint["adapter"])
        self.repair = DecoderRepair(self.model, joint["repair"]["rank"])
        self.repair.restore(joint["repair"])
        self.emotion.eval().requires_grad_(False)
        self.repair.eval().requires_grad_(False)
        with torch.no_grad():
            self.directions = self.decoder.direction(None).float()

    def _sample(self, reference, audio, audio_path, emotion, seed, a_cfg_scale, e_cfg_scale):
        motion = self.model.sample({"r_s": reference, "a": audio}, emo=emotion, seed=seed,
                                   a_cfg_scale=a_cfg_scale, r_cfg_scale=1.0, e_cfg_scale=e_cfg_scale)
        return self.ending.continue_motion(motion, self.directions, audio_path)

    def _portrait(self, source):
        appearance, alpha, features = self.model.encode_image_into_latent(source)
        return appearance, self.decoder.direction(alpha), features

    def _decode(self, appearance, features, motions):
        count = len(motions)
        expanded = [part.expand(count, *part.shape[1:]).contiguous() for part in features]
        frames, _ = self.decoder(appearance + motions, alpha=None, feats=expanded)
        return frames

    def _neutral(self, appearance, features, motion):
        labels = torch.tensor([4], device=self.device)
        with self.emotion.renderer_condition(labels), self.repair.condition(labels):
            return torch.cat([self._decode(appearance, features, frame[None]).cpu() for frame in motion[0]])

    def _sad_frames(self, appearance, features, reference, motion):
        import mediapipe as mp

        offsets, = self.sad(motion[0].float() @ self.directions, reference.float() @ self.directions)
        speech, expressive = [], []
        with (self.emotion.teacher(), self.repair.disabled(),
              torch.backends.cudnn.flags(benchmark=False, deterministic=True, allow_tf32=False),
              mp.solutions.face_mesh.FaceMesh(static_image_mode=True, refine_landmarks=True, max_num_faces=1) as mesh):
            for start in range(0, motion.shape[1], 3):
                current = motion[0, start:start + 3]
                raw = self._decode(appearance, features, current)
                regions = face_regions(raw, mesh, strong=True, trajectory=True, detail=True)
                # Keep the native eyes during the decoder pass. The shared
                # expression controller handles the brows after lip alignment.
                regions[:, :4] = 0
                with self.sad.condition((offsets[start:start + len(current)],), regions=regions):
                    edited = self._decode(appearance, features, current)
                speech.append(rgb(raw))
                expressive.append(rgb(edited))
        return np.concatenate(expressive), np.concatenate(speech)

    @torch.no_grad()
    def render(self, crop, audio_path, destination, *, emotion, seed, a_cfg_scale, e_cfg_scale):
        processor = self.agent.data_processor
        source = processor.transform(image=crop)["image"][None].to(self.device)
        audio = load_audio(processor, audio_path).to(self.device)
        appearance, reference, features = self._portrait(source)
        size = (source.shape[-1], source.shape[-2])
        sample = lambda ref, name: self._sample(ref, audio, audio_path, name, seed, a_cfg_scale, e_cfg_scale)
        notes = []
        if emotion == "neutral":
            frames = rgb(self._neutral(appearance, features, sample(reference, "neutral")))
            write_video(frames, destination, 18, size=size)
        elif emotion == "happy":
            motion = sample(reference, "happy")
            with (torch.backends.cudnn.flags(benchmark=False, deterministic=True, allow_tf32=False),
                  self.emotion.teacher(), self.repair.disabled()):
                native, native_ref, native_features = self._portrait(source)
                speech = sample(native_ref, "happy")
            frames = rgb(render_happy(self.model, appearance, features, speech, motion, self.emotion, self.repair,
                                      speech_appearance=native, speech_features=native_features,
                                      preserve_corners=True))
            write_video(frames, destination, 18, size=size)
        elif emotion == "sad":
            neutral = rgb(self._neutral(appearance, features, sample(reference, "neutral")))
            with self.emotion.teacher(), self.repair.disabled():
                motion = sample(reference, "sad")
            expressive, speech = self._sad_frames(appearance, features, reference, motion)
            count = len(expressive)
            neutral = codec_roundtrip(neutral, 18, size, pixel_format=None)
            neutral_indices = np.clip(np.arange(count) - self.frame_delay, 0, len(neutral) - 1)
            neutral = codec_roundtrip((neutral[i] for i in neutral_indices), 14, size)
            frames, mouth_matched = align_mouth(codec_roundtrip(expressive, 18, size),
                                                codec_roundtrip(speech, 18, size),
                                                self.mouth, self.mouth_fraction, self.frame_delay)
            del expressive, speech
            decoded = codec_roundtrip(frames, 12, size, pixel_format=None)
            frames, expression_matched = expression_controls(neutral,
                [frame.to_ndarray(format="rgb24") for frame in decoded], self.common, self.profile, self.gap_bins)
            write_video((preserve_yuv(frame, original, corrected)
                         for frame, (original, corrected) in zip(decoded, frames, strict=True)),
                        destination, 4, size=size)
            if not mouth_matched or not expression_matched:
                notes.append("일부 Sad 얼굴 좌표를 읽기 어려워 기본 움직임을 사용했습니다")
        else:
            raise ValueError(f"Unsupported final emotion: {emotion}")
        return len(frames), *size, notes
