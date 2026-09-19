// Heads-up pieces over the stage: objective chip, inventory tray, corner menu, wordmark.

import { useEffect, useRef, useState } from "react";
import { useGame } from "../store";
import { api } from "../lib/api";
import { linePlayer } from "../audio/linePlayer";
import { ObjectGlyph } from "./Stage";
import { IconMenu, IconVolume } from "./icons";

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 font-ui text-[12px] font-bold uppercase tracking-[0.34em] text-text/85 ${className}`}>
      <svg viewBox="0 0 64 64" className="h-4 w-4" aria-hidden>
        <path d="M10 40c7-12 17-18 31-18h11" stroke="#e9b45f" strokeWidth="6" fill="none" strokeLinecap="round" />
        <circle cx="52" cy="22" r="6" fill="#e9b45f" />
        <path d="M10 50h28" stroke="#8fc3c8" strokeWidth="5" strokeLinecap="round" />
      </svg>
      Relay
    </span>
  );
}

/** Practical intent + progress dots. Never shows the target sentence. */
export function ObjectiveChip({ className = "", compact = false }: { className?: string; compact?: boolean }) {
  const beat = useGame((s) => s.learning?.active_beat ?? null);
  const done = useGame((s) => s.episodeComplete);
  if (!beat && !done) return null;
  const total = beat?.total ?? 3;
  const index = done ? total : beat!.index;
  return (
    <div className={`glass inline-flex max-w-full items-center gap-3 rounded-2xl px-4 py-2.5 ${className}`} data-testid="objective">
      <div className="min-w-0">
        <div className="text-[10px] font-bold uppercase tracking-[0.24em] text-brass">{done ? "Complete" : "Your goal"}</div>
        <div key={beat?.id ?? "done"} className={`rise-in text-[14.5px] font-semibold text-text ${compact ? "line-clamp-2" : "truncate"}`} data-role="objective-text">
          {done ? "The airship is flying." : beat!.objective}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5" aria-label={`step ${Math.min(index + 1, total)} of ${total}`} data-testid="progress-dots">
        {Array.from({ length: total }, (_, i) => (
          <span
            key={i}
            className={`h-2 rounded-full transition-all duration-500 ${
              i < index ? "w-2 bg-brass" : i === index ? "w-5 bg-brass-strong shadow-[0_0_10px_rgba(246,205,131,0.7)]" : "w-2 bg-white/15"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

export function InventoryTray({ compact = false }: { compact?: boolean }) {
  const cartridge = useGame((s) => s.cartridge);
  const holders = useGame((s) => s.world?.holders ?? {});
  const flights = useGame((s) => s.flights);
  if (!cartridge) return null;
  const owned = cartridge.objects.filter((o) => holders[o.id] === "player");
  const slots = cartridge.objects.length;
  const size = compact ? 40 : 52;
  return (
    <div id="inventory-tray" className="glass flex items-center gap-2 rounded-2xl p-1.5 pr-2" data-testid="inventory" aria-label="Your items">
      <span className={`px-1.5 text-[10px] font-bold uppercase tracking-[0.22em] text-faint ${compact ? "hidden" : ""}`}>Pack</span>
      {Array.from({ length: slots }, (_, i) => {
        const o = owned[i];
        const inFlight = o && flights.some((f) => f.objectId === o.id && f.to === "player");
        return (
          <div
            key={o?.id ?? `empty-${i}`}
            data-inv-slot={o?.id ?? ""}
            className={`relative flex items-center gap-2 rounded-xl ${o ? "bg-white/[0.05] pr-3" : "border border-dashed border-white/10"}`}
            style={{ height: size, minWidth: size }}
          >
            {o && (
              <>
                <div
                  className="h-full p-1.5"
                  style={{ width: size, opacity: inFlight ? 0 : 1, animation: inFlight ? undefined : "inventory-land 0.5s cubic-bezier(0.2,0.8,0.2,1) both" }}
                >
                  <ObjectGlyph objectId={o.id} iconUrl={o.icon_url} />
                </div>
                <div className={`leading-tight ${inFlight ? "opacity-0" : "fade-in"}`}>
                  <div className="jp text-[16px] text-text">{o.native}</div>
                  <div className="text-[11.5px] text-romaji">{o.romanization}</div>
                </div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function CornerMenu() {
  const [open, setOpen] = useState(false);
  const [vol, setVol] = useState(linePlayer.volume);
  const [motion, setMotion] = useState<string>(() => document.documentElement.dataset.motion ?? "auto");
  const reset = useGame((s) => s.resetGame);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [open]);
  const setMotionPref = (m: string) => {
    setMotion(m);
    if (m === "auto") delete document.documentElement.dataset.motion;
    else document.documentElement.dataset.motion = m;
    try {
      localStorage.setItem("polytale.motion", m);
    } catch {
      /* ignore */
    }
  };
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="glass inline-flex h-9 w-9 items-center justify-center rounded-full text-muted hover:text-text"
        aria-label="Menu"
        aria-expanded={open}
        data-testid="menu-button"
      >
        <IconMenu className="h-4 w-4" />
      </button>
      {open && (
        <div className="glass rise-in absolute right-0 top-11 z-40 w-64 rounded-2xl p-3 shadow-2xl" data-testid="menu">
          <label className="flex items-center gap-3 px-1 py-2 text-[13px] text-muted">
            <IconVolume className="h-4 w-4 text-brass" />
            <span className="w-14">Voice</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={vol}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                setVol(v);
                linePlayer.setVolume(v);
              }}
              className="flex-1 accent-[#e9b45f]"
              aria-label="Voice volume"
            />
          </label>
          <div className="flex items-center gap-2 px-1 py-2 text-[13px] text-muted">
            <span className="flex-1">Motion</span>
            {(["auto", "reduced"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMotionPref(m)}
                className={`rounded-full px-2.5 py-1 text-[12px] ${motion === m ? "bg-white/10 text-text" : "text-faint hover:text-muted"}`}
              >
                {m === "auto" ? "Full" : "Reduced"}
              </button>
            ))}
          </div>
          <div className="my-1 h-px bg-line" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              void reset({ restart: false });
            }}
            className="w-full rounded-xl px-2 py-2 text-left text-[13px] text-muted hover:bg-white/5 hover:text-text"
            data-testid="reset-button"
          >
            Reset episode <span className="text-faint">(demo)</span>
          </button>
          {api.mock && <div className="px-2 pt-1 text-[11px] text-faint">Mock mode — scripted server</div>}
        </div>
      )}
    </div>
  );
}
