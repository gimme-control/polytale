// Primary action: push-to-talk. Press & hold (mouse, touch, or Space) to record,
// release to transcribe, see "Heard: …" with Cancel/Retry, auto-send after a short
// cancel window (unless the server asks for confirmation). Keyboard input is a
// small, visually secondary fallback.

import { useEffect, useRef, useState } from "react";
import { AUTO_SUBMIT_MS, useGame } from "../store";
import { mic as recorder } from "../audio/recorder";
import { HelpButton } from "./Help";
import { IconKeyboard, IconMic, IconRetry, IconSend, IconX } from "./icons";

export function MicDock({ compact = false }: { compact?: boolean }) {
  const keyboard = useGame((s) => s.keyboard);
  const setKeyboard = useGame((s) => s.setKeyboard);
  const done = useGame((s) => s.episodeComplete);

  return (
    <div className="relative flex w-full flex-col items-center gap-1 px-4 pb-3 pt-2" data-testid="mic-dock">
      <StatusLine />
      {keyboard && <TextInput />}
      <div className="grid w-full max-w-[720px] grid-cols-[1fr_auto_1fr] items-center gap-3">
        <div className="flex min-w-0 justify-start">
          <HelpButton compact={compact} />
        </div>
        <MicButton disabled={done} />
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => setKeyboard(!keyboard)}
            className={`inline-flex h-10 items-center gap-2 rounded-full border px-3 text-[12.5px] transition ${
              keyboard ? "border-sky/40 bg-sky/10 text-sky" : "border-line bg-transparent text-faint hover:text-muted"
            }`}
            aria-pressed={keyboard}
            aria-label="Type instead"
            data-testid="keyboard-toggle"
          >
            <IconKeyboard className="h-4 w-4" />
            <span className="hidden sm:inline">Type instead</span>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ mic button */

function MicButton({ disabled }: { disabled: boolean }) {
  const phase = useGame((s) => s.mic);
  const press = useGame((s) => s.pressMic);
  const release = useGame((s) => s.releaseMic);
  const deadline = useGame((s) => s.previewDeadline);
  const speaking = useGame((s) => s.speakingLineId);
  const holding = useRef(false);

  // Space bar push-to-talk (ignored while typing in a field).
  useEffect(() => {
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || typing(e.target)) return;
      e.preventDefault();
      if (e.repeat || holding.current || disabled) return;
      holding.current = true;
      void press();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || typing(e.target)) return;
      e.preventDefault();
      if (!holding.current) return;
      holding.current = false;
      void release();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [press, release, disabled]);

  const listening = phase === "listening";
  const busy = phase === "transcribing" || phase === "waiting";
  const size = 78;
  return (
    <div className="relative flex items-center justify-center" style={{ width: size + 24, height: size + 24 }}>
      {listening && (
        <>
          <span className="absolute inset-3 rounded-full bg-brass/40" style={{ animation: "mic-halo 1.4s ease-out infinite" }} />
          <span className="absolute inset-3 rounded-full bg-brass/30" style={{ animation: "mic-halo 1.4s 0.7s ease-out infinite" }} />
        </>
      )}
      {phase === "preview" && deadline && <CountdownRing size={size + 16} />}
      <button
        type="button"
        disabled={disabled || busy}
        onPointerDown={(e) => {
          if (e.button !== 0 || disabled) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          holding.current = true;
          void press();
        }}
        onPointerUp={() => {
          if (!holding.current) return;
          holding.current = false;
          void release();
        }}
        onPointerCancel={() => {
          if (!holding.current) return;
          holding.current = false;
          void release();
        }}
        onContextMenu={(e) => e.preventDefault()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.preventDefault();
        }}
        className={`relative z-10 flex touch-none select-none items-center justify-center rounded-full transition-all duration-200 ${
          listening
            ? "scale-110 bg-brass-strong text-ink shadow-[0_0_0_6px_rgba(246,205,131,0.25),0_18px_50px_-8px_rgba(233,180,95,0.85)]"
            : busy
              ? "bg-raised text-muted"
              : "bg-gradient-to-b from-brass-strong to-brass text-ink shadow-[0_14px_40px_-10px_rgba(233,180,95,0.75),inset_0_1px_0_rgba(255,255,255,0.5)] hover:brightness-105 active:scale-95"
        } disabled:cursor-default ${disabled ? "opacity-40" : ""}`}
        style={{ width: size, height: size, WebkitTouchCallout: "none" } as React.CSSProperties}
        aria-label="Hold to speak"
        data-testid="mic-button"
        data-phase={phase}
        data-speaking={speaking ? "1" : "0"}
      >
        {busy ? (
          <span className="h-7 w-7 rounded-full border-[3px] border-white/15 border-t-brass" style={{ animation: "spin 0.9s linear infinite" }} />
        ) : (
          <IconMic className="h-9 w-9" />
        )}
      </button>
    </div>
  );
}

function CountdownRing({ size }: { size: number }) {
  const ref = useRef<SVGCircleElement>(null);
  const r = size / 2 - 3;
  const c = 2 * Math.PI * r;
  useEffect(() => {
    const a = ref.current?.animate([{ strokeDashoffset: 0 }, { strokeDashoffset: c }], {
      duration: AUTO_SUBMIT_MS,
      easing: "linear",
      fill: "forwards",
    });
    return () => a?.cancel();
  }, [c]);
  return (
    <svg className="pointer-events-none absolute" width={size} height={size} style={{ transform: "rotate(-90deg)" }} data-testid="countdown">
      <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(255,255,255,0.08)" strokeWidth="3" fill="none" />
      <circle ref={ref} cx={size / 2} cy={size / 2} r={r} stroke="#8fc3c8" strokeWidth="3" fill="none" strokeLinecap="round" strokeDasharray={c} />
    </svg>
  );
}

/* ----------------------------------------------------------------- status line */

function StatusLine() {
  const phase = useGame((s) => s.mic);
  const preview = useGame((s) => s.preview);
  const notice = useGame((s) => s.notice);
  const speaking = useGame((s) => s.speakingLineId);
  const failed = useGame((s) => s.failedAct);
  const done = useGame((s) => s.episodeComplete);
  const npcName = useGame((s) => s.cartridge?.npcs[0]?.name ?? "She");
  const confirm = useGame((s) => s.confirmPreview);
  const cancel = useGame((s) => s.cancelPreview);
  const retry = useGame((s) => s.retryPreview);
  const retryFailed = useGame((s) => s.retryFailed);
  const micDenied = useGame((s) => s.micDenied);

  let body: React.ReactNode;
  if (phase === "listening") {
    body = (
      <div className="flex items-center gap-3" data-state="listening">
        <Waveform />
        <span className="text-[13px] font-semibold text-brass-strong">Listening — release to send</span>
      </div>
    );
  } else if (phase === "transcribing") {
    body = (
      <span className="flex items-center gap-2 text-[14px] text-muted" data-state="transcribing">
        <span className="h-3.5 w-3.5 rounded-full border-2 border-white/15 border-t-sky" style={{ animation: "spin 0.8s linear infinite" }} />
        Listening back…
      </span>
    );
  } else if (phase === "preview" && preview) {
    body = (
      <div
        className="rise-in flex w-full max-w-[560px] items-center gap-3 rounded-2xl border border-sky/30 bg-sky/[0.08] px-4 py-2"
        data-state="preview"
        data-testid="preview"
      >
        <div className="min-w-0 flex-1">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.2em] text-sky/80">
            {preview.requires_confirmation ? "Is this what you said?" : "Heard"}
          </div>
          <div className="jp truncate text-[20px] leading-tight text-text" data-role="heard">
            {preview.transcript}
          </div>
          {preview.romanized && preview.romanized !== preview.transcript && (
            <div className="truncate text-[13px] text-romaji">{preview.romanized}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <SmallButton onClick={cancel} label="Cancel" testid="preview-cancel">
            <IconX className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Cancel</span>
          </SmallButton>
          <SmallButton onClick={retry} label="Retry" testid="preview-retry">
            <IconRetry className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Retry</span>
          </SmallButton>
          <SmallButton onClick={() => void confirm()} label="Send" testid="preview-send" primary>
            <IconSend className="h-3.5 w-3.5" />
            Send
          </SmallButton>
        </div>
      </div>
    );
  } else if (phase === "empty") {
    body = (
      <span className="text-[14px] text-muted" data-state="empty">
        {notice ?? "Didn't catch that — try again."}
      </span>
    );
  } else if (phase === "waiting") {
    body = (
      <span className="flex items-center gap-2 text-[14px] text-muted" data-state="waiting">
        <span className="anim-dots text-brass">
          <span>•</span>
          <span>•</span>
          <span>•</span>
        </span>
        {npcName} is thinking…
      </span>
    );
  } else if (phase === "error" && failed) {
    body = (
      <span className="flex items-center gap-2 text-[14px] text-muted" data-state="error">
        {notice}
        <SmallButton onClick={() => void retryFailed()} label="Send again" testid="retry-failed" primary>
          <IconRetry className="h-3.5 w-3.5" /> Send again
        </SmallButton>
      </span>
    );
  } else if (done) {
    body = <span className="text-[14px] text-brass-strong">Airborne.</span>;
  } else if (speaking) {
    body = (
      <span className="text-[14px] text-muted" data-state="speaking">
        {npcName} is speaking… <span className="text-faint">hold to answer anytime</span>
      </span>
    );
  } else {
    body = (
      <span className="text-[14px] text-muted" data-state="idle">
        {notice ?? (micDenied ? "Microphone is off — type instead, or allow the mic and hold to speak." : "Hold to speak")}
        {!notice && !micDenied && (
          <span className="ml-2 hidden text-faint sm:inline">
            or hold <kbd className="rounded-md border border-line-strong bg-white/[0.04] px-1.5 py-0.5 text-[11px] font-semibold text-muted">Space</kbd>
          </span>
        )}
      </span>
    );
  }
  return (
    <div className="flex min-h-[56px] w-full items-center justify-center" aria-live="polite" data-testid="mic-status">
      {body}
    </div>
  );
}

function SmallButton({
  children,
  onClick,
  label,
  testid,
  primary,
}: {
  children: React.ReactNode;
  onClick: () => void;
  label: string;
  testid: string;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      data-testid={testid}
      className={`inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold transition ${
        primary ? "bg-sky text-ink hover:brightness-110" : "border border-line-strong text-muted hover:text-text"
      }`}
    >
      {children}
    </button>
  );
}

function Waveform() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    const an = recorder.analyser;
    if (!cv) return;
    const ctx = cv.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    cv.width = 180 * dpr;
    cv.height = 40 * dpr;
    ctx.scale(dpr, dpr);
    const data = new Uint8Array(an ? an.fftSize : 512);
    let raf = 0;
    const bars = 30;
    const levels = new Array(bars).fill(0);
    const draw = () => {
      let rms = 0;
      if (an) {
        an.getByteTimeDomainData(data);
        for (let i = 0; i < data.length; i++) {
          const v = (data[i] - 128) / 128;
          rms += v * v;
        }
        rms = Math.sqrt(rms / data.length);
      }
      levels.shift();
      levels.push(Math.min(1, rms * 4.5 + 0.04));
      ctx.clearRect(0, 0, 180, 40);
      for (let i = 0; i < bars; i++) {
        const h = Math.max(3, levels[i] * 36);
        const x = i * 6;
        ctx.fillStyle = `rgba(246, 205, 131, ${0.35 + (i / bars) * 0.65})`;
        ctx.beginPath();
        ctx.roundRect(x, 20 - h / 2, 3.2, h, 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={ref} style={{ width: 180, height: 40 }} data-testid="waveform" />;
}

/* ------------------------------------------------------------------ text input */

function TextInput() {
  const send = useGame((s) => s.sendText);
  const phase = useGame((s) => s.mic);
  const [text, setText] = useState("");
  return (
    <form
      className="rise-in flex w-full max-w-[560px] items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!text.trim()) return;
        void send(text);
        setText("");
      }}
      data-testid="text-input"
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Type what you'd say — Japanese, romaji, or a mix"
        className="h-10 min-w-0 flex-1 rounded-full border border-line-strong bg-ink/60 px-4 text-[14px] text-text placeholder:text-faint focus:border-sky/50 focus:outline-none"
        aria-label="Type what you'd say"
        lang="ja"
      />
      <button
        type="submit"
        disabled={!text.trim() || phase === "waiting"}
        className="inline-flex h-10 items-center gap-1.5 rounded-full bg-white/10 px-4 text-[13px] font-semibold text-text disabled:opacity-40"
      >
        <IconSend className="h-3.5 w-3.5" />
        Send
      </button>
    </form>
  );
}
