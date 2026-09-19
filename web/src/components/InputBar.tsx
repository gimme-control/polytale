// The one input: a text field with the microphone inside it, at equal weight.
// Enter sends. Hold the mic (pointer or touch) or hold Space (when the field is not
// focused) to talk. While listening a live waveform takes the field's place; what
// was heard is shown inline with a short cancel window (Esc cancels, Enter sends).

import { useEffect, useRef, useState } from "react";
import { AUTO_SUBMIT_MS, useGame } from "../store";
import { mic } from "../audio/recorder";
import { inventoryOf, trayBox } from "./Scene";

export function InputBar() {
  const phase = useGame((s) => s.phase);
  const speaking = useGame((s) => !!s.speakingLineId || s.narrating);
  const audible = useGame((s) => s.audible);
  const preview = useGame((s) => s.preview);
  const deadline = useGame((s) => s.previewDeadline);
  const notice = useGame((s) => s.notice);
  const failed = useGame((s) => !!s.failedAct);
  const micDenied = useGame((s) => s.micDenied);
  const complete = useGame((s) => s.sceneComplete);
  const language = useGame((s) => s.language);
  const pressMic = useGame((s) => s.pressMic);
  const releaseMic = useGame((s) => s.releaseMic);
  const confirmPreview = useGame((s) => s.confirmPreview);
  const cancelPreview = useGame((s) => s.cancelPreview);
  const retryFailed = useGame((s) => s.retryFailed);
  const sendText = useGame((s) => s.sendText);
  const draft = useGame((s) => s.draft);
  const setPhraseOpen = useGame((s) => s.setPhraseOpen);
  const hasPhrasebook = useGame((s) => !!s.game);
  const slots = useGame((s) => (s.scene ? inventoryOf(s.scene, s.zones).length : 1));

  const [text, setText] = useState("");
  const [vw, setVw] = useState(() => window.innerWidth);
  const field = useRef<HTMLInputElement | null>(null);
  const spaceHeld = useRef(false);

  useEffect(() => {
    const onResize = () => setVw(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // "Use it" from the phrasebook lands here; the learner still sends it (or says it).
  useEffect(() => {
    if (!draft.nonce) return;
    setText(draft.text);
    window.setTimeout(() => field.current?.focus(), 0);
    // Consumed: a later remount (next scene) must not bring the phrase back.
    useGame.setState({ draft: { text: "", nonce: 0 } });
  }, [draft]);

  // Hold Space to talk (unless typing); Esc / Enter act on the "Heard" preview.
  useEffect(() => {
    const typing = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
    };
    const down = (e: KeyboardEvent) => {
      const st = useGame.getState();
      if (st.phase === "preview") {
        if (e.key === "Escape") {
          e.preventDefault();
          cancelPreview();
        } else if (e.key === "Enter") {
          e.preventDefault();
          void confirmPreview();
        }
        return;
      }
      if (e.code !== "Space" || e.repeat || typing(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement | null)?.tagName === "BUTTON") (e.target as HTMLElement).blur();
      e.preventDefault();
      spaceHeld.current = true;
      void pressMic();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || !spaceHeld.current) return;
      spaceHeld.current = false;
      e.preventDefault();
      void releaseMic();
    };
    const blur = () => {
      if (spaceHeld.current) {
        spaceHeld.current = false;
        void releaseMic();
      }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, [pressMic, releaseMic, confirmPreview, cancelPreview]);

  const busy = phase === "waiting" || phase === "transcribing";
  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (phase === "preview") return void confirmPreview();
    if (!text.trim() || busy) return;
    const sent = text;
    setText("");
    if (!(await sendText(sent))) setText(sent);
  };

  // The wallet tray lives bottom-left; the bar never sits on it.
  const tray = trayBox(vw, slots);
  const gutter = tray.left + tray.width + 10;
  const pad = vw < 640 ? { paddingLeft: gutter } : vw < 680 + gutter * 2 ? { paddingLeft: gutter, paddingRight: gutter, maxWidth: "none" } : undefined;
  const state = phase === "idle" && speaking ? "speaking" : phase;

  return (
    <div className="pointer-events-none mx-auto w-full max-w-[680px] px-3 pb-3 sm:px-0 sm:pb-6 [@media(max-height:520px)]:sm:pb-3" style={pad}>
      {hasPhrasebook && (
        <div className="flex justify-end pb-1 min-[1100px]:hidden">
          <button type="button" data-testid="phrasebook-open" onClick={() => setPhraseOpen(true)} className="over-art pointer-events-auto border-0 bg-transparent px-1 py-1 text-[13px] font-medium text-ink-2 underline decoration-hair-2 underline-offset-4 hover:text-ink">
            How do I say…?
          </button>
        </div>
      )}
      <div className="flex min-h-6 items-end justify-center pb-2">
        {notice && (
          <p data-testid="notice" role="status" className="fade-in over-art pointer-events-auto m-0 flex items-center gap-3 text-[13px] text-ink-2">
            <span>{notice}</span>
            {failed && (
              <button type="button" data-testid="retry-send" onClick={() => void retryFailed()} className="border-0 bg-transparent p-0 text-[13px] font-medium text-ink underline decoration-hair-2 underline-offset-4 hover:decoration-ink">
                Send again
              </button>
            )}
          </p>
        )}
      </div>

      <form
        onSubmit={submit}
        data-testid="input-bar"
        data-state={state}
        data-audible={audible ? "1" : "0"}
        className={`pointer-events-auto relative flex h-12 items-center overflow-hidden rounded-[10px] border bg-glass backdrop-blur-md transition-colors duration-200 sm:h-[52px] ${
          phase === "listening" ? "border-jade/70" : "border-hair focus-within:border-hair-2"
        }`}
      >
        <div className="flex h-full min-w-0 flex-1 items-center pl-4">
          {phase === "listening" ? (
            <Waveform />
          ) : phase === "transcribing" ? (
            <span data-testid="transcribing" className="text-[15px] text-ink-3">
              Listening back…
            </span>
          ) : phase === "preview" && preview ? (
            <p data-testid="preview" className="m-0 flex min-w-0 items-baseline gap-2 text-[15px]">
              <span className="shrink-0 text-ink-3">Heard</span>
              <span lang={language?.locale} className="target truncate text-[17px] font-normal text-ink">
                {preview.transcript}
              </span>
              {preview.romanized && preview.romanized.trim().toLowerCase() !== preview.transcript.trim().toLowerCase() && <span className="hidden truncate text-[13px] text-ink-3 sm:inline">{preview.romanized}</span>}
            </p>
          ) : (
            <input
              ref={field}
              data-testid="text-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={busy || complete}
              lang={language?.locale}
              placeholder={phase === "waiting" ? "" : "Say something…"}
              aria-label="Say something"
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="send"
              className="h-full w-full border-0 bg-transparent text-[16px] text-ink outline-none placeholder:text-ink-3 disabled:opacity-60"
            />
          )}
        </div>

        {phase === "preview" ? (
          <div className="flex shrink-0 items-center gap-1 pr-2">
            <BarButton testid="preview-cancel" onClick={cancelPreview} hint="Esc">
              Cancel
            </BarButton>
            <BarButton testid="preview-send" onClick={() => void confirmPreview()} hint="Enter" strong>
              Send
            </BarButton>
          </div>
        ) : text.trim() && phase !== "listening" ? (
          <button type="submit" data-testid="send-button" disabled={busy} aria-label="Send" className="mr-1.5 grid h-9 w-9 shrink-0 place-items-center rounded-[8px] border-0 bg-ink text-night transition-opacity duration-150 disabled:opacity-40 sm:h-10 sm:w-10">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" />
            </svg>
          </button>
        ) : (
          <MicButton phase={phase} speaking={speaking} denied={micDenied} disabled={busy || complete} onPress={pressMic} onRelease={releaseMic} />
        )}

        {phase === "preview" && deadline && (
          <span data-testid="countdown" className="countdown absolute inset-x-0 bottom-0 h-px bg-jade" style={{ animationDuration: `${AUTO_SUBMIT_MS}ms` }} />
        )}
      </form>

      <p className="m-0 hidden pt-2 text-center text-[12px] text-ink-3 sm:block [@media(max-height:520px)]:sm:hidden">
        {phase === "listening" ? "Let go to send" : "Enter to send · hold Space to talk · click things to use them"}
      </p>
    </div>
  );
}

function BarButton({ children, onClick, testid, hint, strong = false }: { children: React.ReactNode; onClick: () => void; testid: string; hint: string; strong?: boolean }) {
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={onClick}
      className={`flex h-9 items-center gap-1.5 rounded-[8px] border px-3 text-[13px] font-medium transition-colors duration-150 ${
        strong ? "border-transparent bg-ink text-night" : "border-hair bg-transparent text-ink-2 hover:text-ink"
      }`}
    >
      {children}
      <kbd className={`hidden font-ui text-[11px] font-normal sm:inline ${strong ? "text-night/55" : "text-ink-3"}`}>{hint}</kbd>
    </button>
  );
}

function MicButton({ phase, speaking, denied, disabled, onPress, onRelease }: { phase: string; speaking: boolean; denied: boolean; disabled: boolean; onPress: () => Promise<void>; onRelease: () => Promise<void> }) {
  const held = useRef(false);
  const listening = phase === "listening";
  return (
    <button
      type="button"
      data-testid="mic-button"
      data-phase={phase}
      data-speaking={speaking ? "1" : "0"}
      disabled={disabled}
      aria-label={denied ? "Microphone is off. Hold to try again" : "Hold to talk"}
      aria-pressed={listening}
      title={denied ? "The microphone is off" : "Hold to talk"}
      onPointerDown={(e) => {
        if (e.button !== 0 && e.pointerType === "mouse") return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        held.current = true;
        void onPress();
      }}
      onPointerUp={() => {
        if (!held.current) return;
        held.current = false;
        void onRelease();
      }}
      onPointerCancel={() => {
        if (!held.current) return;
        held.current = false;
        void onRelease();
      }}
      onContextMenu={(e) => e.preventDefault()}
      className={`mr-1.5 grid h-9 w-9 shrink-0 touch-none select-none place-items-center rounded-[8px] border transition-colors duration-150 disabled:opacity-40 sm:h-10 sm:w-10 ${
        listening ? "border-transparent bg-jade text-night" : "border-hair bg-transparent text-ink hover:border-hair-2"
      }`}
    >
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={denied ? "opacity-45" : ""}>
        <rect x="6.5" y="2" width="5" height="9" rx="2.5" />
        <path d="M3.75 8.75a5.25 5.25 0 0 0 10.5 0M9 14v2" />
        {denied && <path d="M3 3l12 12" />}
      </svg>
    </button>
  );
}

/** Live input level, drawn as a quiet centre-line waveform. */
function Waveform() {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    let raf = 0;
    const data = new Uint8Array(1024);
    const bars: number[] = [];
    const draw = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (el.width !== w * dpr) {
        el.width = w * dpr;
        el.height = h * dpr;
      }
      let level = 0;
      if (mic.analyser) {
        mic.analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (let i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i] - 128));
        level = Math.min(1, peak / 90);
      }
      bars.push(level);
      const step = 4;
      const max = Math.ceil(w / step);
      while (bars.length > max) bars.shift();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "rgb(159 195 177)";
      for (let i = 0; i < bars.length; i++) {
        const bh = Math.max(2, bars[i] * (h - 8));
        ctx.fillRect(w - (bars.length - i) * step, (h - bh) / 2, 2, bh);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={canvas} data-testid="waveform" aria-label="Listening" className="h-7 w-full pr-3" />;
}
