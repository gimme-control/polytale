// NPC line playback: sequential queue, replay, slow replay (0.7x, pitch preserved),
// volume. Text is always shown first; audio failing (e.g. TTS 503) never blocks.

type Listener = (lineId: string | null, rate: number) => void;

const VOL_KEY = "polytale.volume";

function readVolume(): number {
  try {
    const v = parseFloat(localStorage.getItem(VOL_KEY) ?? "");
    return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0.9;
  } catch {
    return 0.9;
  }
}

class LinePlayer {
  private el: HTMLAudioElement | null = null;
  private gen = 0;
  private listeners = new Set<Listener>();
  private failed = new Set<string>();
  volume = readVolume();
  current: string | null = null;

  on(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(id: string | null, rate: number) {
    this.current = id;
    for (const l of this.listeners) l(id, rate);
  }

  hasFailed(lineId: string): boolean {
    return this.failed.has(lineId);
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
      this.el.src = "";
      this.el = null;
    }
    if (this.current) this.emit(null, 1);
  }

  /** Play one clip; resolves when it ends, fails, or is superseded. */
  private playOne(lineId: string, src: string, rate: number, gen: number): Promise<void> {
    return new Promise((resolve) => {
      if (gen !== this.gen) return resolve();
      const el = new Audio();
      el.preload = "auto";
      el.volume = this.volume;
      el.playbackRate = rate;
      el.defaultPlaybackRate = rate;
      (el as HTMLAudioElement & { preservesPitch?: boolean }).preservesPitch = true;
      el.src = src;
      this.el = el;
      let done = false;
      const finish = (failed: boolean) => {
        if (done) return;
        done = true;
        if (failed) this.failed.add(lineId);
        window.clearTimeout(guard);
        if (this.el === el) this.el = null;
        resolve();
      };
      // A stuck clip must never wedge the queue.
      const guard = window.setTimeout(() => finish(false), 20_000);
      el.onended = () => finish(false);
      el.onerror = () => finish(true);
      // "Speaking" means audible: mark it when playback actually starts, not while
      // the clip is still being synthesized/fetched.
      el.onplaying = () => {
        if (gen === this.gen && !done) this.emit(lineId, rate);
      };
      el.play().catch(() => finish(true));
    });
  }

  /** Play clips in order, replacing anything playing. */
  async playSequence(items: { lineId: string; src: () => Promise<string> }[], rate = 1): Promise<void> {
    this.stop();
    const gen = this.gen;
    for (const it of items) {
      if (gen !== this.gen) return;
      let src = "";
      try {
        src = await it.src();
      } catch {
        this.failed.add(it.lineId);
        continue;
      }
      await this.playOne(it.lineId, src, rate, gen);
      if (gen !== this.gen) return;
      // A breath between lines.
      await new Promise((r) => setTimeout(r, 260));
    }
    if (gen === this.gen) this.emit(null, 1);
  }
}

export const linePlayer = new LinePlayer();
