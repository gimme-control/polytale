// Character line playback: a sequential queue with replay and slow replay (pitch
// preserved) and a volume setting. The line is announced to listeners as soon as its
// turn in the queue begins, so text never waits on audio; when a clip fails (TTS
// down, 404) the line is simply held for a reading-length pause instead.

type Listener = (lineId: string | null, rate: number) => void;

export interface QueueItem {
  lineId: string;
  src: () => Promise<string>;
  /** how long to hold the line when its audio cannot play */
  fallbackMs: number;
}

const VOL_KEY = "polytale.volume";
const GAP_MS = 240;

function readVolume(): number {
  try {
    const v = parseFloat(localStorage.getItem(VOL_KEY) ?? "");
    return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0.9;
  } catch {
    return 0.9;
  }
}

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

class LinePlayer {
  private el: HTMLAudioElement | null = null;
  private gen = 0;
  private listeners = new Set<Listener>();
  volume = readVolume();
  current: string | null = null;
  /** true while a clip is actually sounding (not merely queued or loading) */
  audible = false;
  onAudible: ((on: boolean) => void) | null = null;

  private setAudible(on: boolean) {
    if (this.audible === on) return;
    this.audible = on;
    this.onAudible?.(on);
  }

  on(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(id: string | null, rate: number) {
    this.current = id;
    for (const l of this.listeners) l(id, rate);
  }

  setVolume(v: number) {
    this.volume = Math.max(0, Math.min(1, v));
    if (this.el) this.el.volume = this.volume;
    try {
      localStorage.setItem(VOL_KEY, String(this.volume));
    } catch {
      /* ignore */
    }
  }

  stop() {
    this.gen++;
    if (this.el) {
      this.el.pause();
      this.el.removeAttribute("src");
      this.el = null;
    }
    this.setAudible(false);
    if (this.current) this.emit(null, 1);
  }

  /** Play one clip; resolves true when it played through, false when it failed. */
  private playOne(src: string, rate: number, gen: number): Promise<boolean> {
    return new Promise((resolve) => {
      if (gen !== this.gen) return resolve(true);
      const el = new Audio();
      el.preload = "auto";
      el.volume = this.volume;
      el.playbackRate = rate;
      el.defaultPlaybackRate = rate;
      (el as HTMLAudioElement & { preservesPitch?: boolean }).preservesPitch = true;
      el.src = src;
      this.el = el;
      let done = false;
      const finish = (ok: boolean) => {
        if (done) return;
        done = true;
        window.clearTimeout(guard);
        if (this.el === el) this.el = null;
        this.setAudible(false);
        resolve(ok);
      };
      // A stuck clip must never wedge the queue.
      const guard = window.setTimeout(() => finish(true), 20_000);
      el.onplaying = () => {
        if (gen === this.gen && !done) this.setAudible(true);
      };
      el.onended = () => finish(true);
      el.onerror = () => finish(false);
      el.play().catch(() => finish(false));
    });
  }

  /** Play clips in order, replacing anything playing. Resolves when the queue drains. */
  async playSequence(items: QueueItem[], rate = 1): Promise<void> {
    this.stop();
    const gen = this.gen;
    for (const it of items) {
      if (gen !== this.gen) return;
      this.emit(it.lineId, rate);
      let ok = false;
      try {
        ok = await this.playOne(await it.src(), rate, gen);
      } catch {
        ok = false;
      }
      if (gen !== this.gen) return;
      if (!ok) await sleep(it.fallbackMs / rate);
      if (gen !== this.gen) return;
      await sleep(GAP_MS);
    }
    if (gen === this.gen) this.emit(null, 1);
  }

  /** A single clip outside the line queue (summary word audio). */
  async playClip(src: string): Promise<boolean> {
    this.stop();
    return this.playOne(src, 1, this.gen);
  }
}

export const linePlayer = new LinePlayer();
