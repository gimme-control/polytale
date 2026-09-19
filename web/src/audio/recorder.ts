// Push-to-talk microphone capture: raw PCM via Web Audio (AudioWorklet, with a
// ScriptProcessor fallback), encoded client-side to 16 kHz mono 16-bit WAV.
//
// The mic stream stays open after the Start screen grants permission so a press
// captures from the first syllable; a ~200 ms pre-roll ring buffer covers the gap
// between the finger landing and the learner starting to speak.

import { downsample, encodeWav, TARGET_SAMPLE_RATE } from "../lib/wav";

const WORKLET = `
class PolytaleCapture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("polytale-capture", PolytaleCapture);
`;

export interface Recording {
  blob: Blob;
  durationMs: number;
  peak: number;
}

export class MicRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  /** Held so the capture node is never garbage-collected mid-session. */
  captureNode: AudioNode | null = null;
  private recording = false;
  private chunks: Float32Array[] = [];
  private preroll: Float32Array[] = [];
  private prerollLen = 0;
  private startedAt = 0;
  analyser: AnalyserNode | null = null;

  get ready(): boolean {
    return !!this.ctx && !!this.stream && this.stream.active;
  }

  /** Ask for the microphone (call from a user gesture). Throws on denial. */
  async ensure(): Promise<void> {
    if (this.ready) {
      if (this.ctx!.state === "suspended") await this.ctx!.resume();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Microphone not available in this browser.");
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctx();
    if (this.ctx.state === "suspended") await this.ctx.resume().catch(() => {});
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    src.connect(this.analyser);
    const sink = this.ctx.createGain();
    sink.gain.value = 0;
    sink.connect(this.ctx.destination);
    try {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      const node = new AudioWorkletNode(this.ctx, "polytale-capture", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
      node.port.onmessage = (e: MessageEvent<Float32Array>) => this.push(e.data);
      src.connect(node);
      node.connect(sink);
      this.captureNode = node;
    } catch {
      // ScriptProcessor fallback (deprecated but universally available).
      const sp = this.ctx.createScriptProcessor(4096, 1, 1);
      sp.onaudioprocess = (e) => this.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      src.connect(sp);
      sp.connect(sink);
      this.captureNode = sp;
    }
  }

  private push(chunk: Float32Array) {
    if (this.recording) {
      this.chunks.push(chunk);
      return;
    }
    const max = (this.ctx?.sampleRate ?? 48000) * 0.2;
    this.preroll.push(chunk);
    this.prerollLen += chunk.length;
    while (this.prerollLen - this.preroll[0].length > max) this.prerollLen -= this.preroll.shift()!.length;
  }

  start(): void {
    if (!this.ready) throw new Error("Microphone not ready.");
    void this.ctx!.resume();
    this.chunks = [...this.preroll];
    this.preroll = [];
    this.prerollLen = 0;
    this.recording = true;
    this.startedAt = performance.now();
  }

  get isRecording(): boolean {
    return this.recording;
  }

  /** Stop and encode. Duration excludes the pre-roll. */
  async stop(): Promise<Recording> {
    const durationMs = performance.now() - this.startedAt;
    // Let the last worklet frames arrive.
    await new Promise((r) => setTimeout(r, 60));
    this.recording = false;
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const pcm = new Float32Array(total);
    let off = 0;
    let peak = 0;
    for (const c of this.chunks) {
      pcm.set(c, off);
      off += c.length;
    }
    for (let i = 0; i < pcm.length; i++) peak = Math.max(peak, Math.abs(pcm[i]));
    this.chunks = [];
    const mono16k = downsample(pcm, this.ctx?.sampleRate ?? TARGET_SAMPLE_RATE, TARGET_SAMPLE_RATE);
    return { blob: encodeWav(mono16k, TARGET_SAMPLE_RATE), durationMs, peak };
  }

  cancel(): void {
    this.recording = false;
    this.chunks = [];
  }
}

export const mic = new MicRecorder();
