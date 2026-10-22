/**
 * 브라우저 녹음 + 실시간 음량 측정.
 * 음성 합성 모델용 녹음이라 브라우저의 잡음 제거·자동 음량 조절은 끈다 (목소리 특징이 바뀌지 않도록).
 */

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

export type Take = { blob: Blob; url: string; duration: number; speechDb: number; clipRatio: number };

function toDb(rms: number) {
  return 20 * Math.log10(Math.max(rms, 1e-6));
}

export class VoiceRecorder {
  private analyser: AnalyserNode;
  private buffer: Float32Array<ArrayBuffer>;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private levels: number[] = [];
  private clipped = 0;
  private sampled = 0;
  private timer: number | null = null;
  private startedAt = 0;

  private constructor(
    private stream: MediaStream,
    private ctx: AudioContext,
  ) {
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.buffer = new Float32Array(this.analyser.fftSize);
    ctx.createMediaStreamSource(stream).connect(this.analyser);
  }

  static async open(): Promise<VoiceRecorder> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("이 브라우저에서는 녹음을 할 수 없어요. 크롬이나 사파리 최신 버전을 사용해 주세요.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    const ctx = new AudioContext();
    await ctx.resume();
    return new VoiceRecorder(stream, ctx);
  }

  /** 지금 들어오는 소리 크기 (dBFS, 대략 -60 ~ 0) */
  level(): number {
    this.analyser.getFloatTimeDomainData(this.buffer);
    let sum = 0;
    let clipped = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const v = this.buffer[i];
      sum += v * v;
      if (Math.abs(v) > 0.98) clipped++;
    }
    if (this.recorder?.state === "recording") {
      this.clipped += clipped;
      this.sampled += this.buffer.length;
    }
    return toDb(Math.sqrt(sum / this.buffer.length));
  }

  /** 아무 말 하지 않을 때의 주변 소음 크기 */
  async measureNoise(ms = 1500): Promise<number> {
    const values: number[] = [];
    const end = performance.now() + ms;
    while (performance.now() < end) {
      values.push(this.level());
      await new Promise((r) => setTimeout(r, 50));
    }
    values.sort((a, b) => a - b);
    return values[Math.floor(values.length / 2)];
  }

  start() {
    const mimeType = MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
    this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.chunks = [];
    this.levels = [];
    this.clipped = 0;
    this.sampled = 0;
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.recorder.start();
    this.startedAt = performance.now();
    this.timer = window.setInterval(() => this.levels.push(this.level()), 50);
  }

  stop(): Promise<Take> {
    return new Promise((resolve) => {
      const recorder = this.recorder!;
      recorder.onstop = () => {
        if (this.timer) window.clearInterval(this.timer);
        const blob = new Blob(this.chunks, { type: recorder.mimeType || "audio/webm" });
        const loud = [...this.levels].sort((a, b) => b - a).slice(0, Math.max(1, Math.floor(this.levels.length / 2)));
        resolve({
          blob,
          url: URL.createObjectURL(blob),
          duration: (performance.now() - this.startedAt) / 1000,
          speechDb: loud.reduce((a, b) => a + b, 0) / loud.length,
          clipRatio: this.sampled ? this.clipped / this.sampled : 0,
        });
      };
      recorder.stop();
    });
  }

  get recording() {
    return this.recorder?.state === "recording";
  }

  close() {
    if (this.timer) window.clearInterval(this.timer);
    if (this.recorder?.state === "recording") this.recorder.stop();
    this.stream.getTracks().forEach((t) => t.stop());
    this.ctx.close();
  }
}

/** 업로드 전에 바로 알려 줄 수 있는 문제. 정확한 판정은 서버가 한다. */
export function quickCheck(take: Take): string[] {
  const problems: string[] = [];
  if (take.duration < 1.5) problems.push("너무 짧게 녹음됐어요. 문장을 끝까지 읽어 주세요.");
  else if (take.speechDb < -45) problems.push("목소리가 거의 들리지 않아요. 마이크가 켜져 있는지 확인해 주세요.");
  if (take.clipRatio > 0.002) problems.push("소리가 너무 커서 찢어졌어요. 마이크에서 조금 떨어져 주세요.");
  return problems;
}
