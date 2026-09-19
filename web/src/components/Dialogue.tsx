// Dialogue / transcript panel. NPC lines: portrait, native text LARGE, romanization
// directly beneath (never a tooltip), replay + slow replay, and a per-line
// "reveal meaning" (translation hidden by default). Narration: support language,
// small italic. Player entries show what was heard. Evidence: encouraging chips.

import { useEffect, useMemo, useRef, useState } from "react";
import { SLOW_RATE, useGame } from "../store";
import type { CartridgeView, EvidenceEntry, PlayerEntry, SpokenLine, TranscriptEntry } from "../lib/types";
import { resolveArt } from "../lib/hooks";
import { ArtImage } from "./Art";
import { IconCheck, IconEye, IconHand, IconPlay, IconSlow } from "./icons";
import { linePlayer } from "../audio/linePlayer";
import { HelpCard } from "./Help";

export function DialoguePanel({ mobile = false }: { mobile?: boolean }) {
  const transcript = useGame((s) => s.transcript);
  const pending = useGame((s) => s.pending);
  const mic = useGame((s) => s.mic);
  const cartridge = useGame((s) => s.cartridge);
  const helpCue = useGame((s) => s.helpCue);
  const speaking = useGame((s) => s.speakingLineId);
  const scroller = useRef<HTMLDivElement>(null);

  const lastNpcIdx = useMemo(() => {
    for (let i = transcript.length - 1; i >= 0; i--) if (transcript[i].kind === "npc") return i;
    return -1;
  }, [transcript]);
  // The newest turn's NPC lines are the "hero" lines, set larger.
  const heroTurn = lastNpcIdx >= 0 ? transcript[lastNpcIdx].turn : -1;

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [transcript.length, pending, helpCue]);

  const npc = cartridge?.npcs[0];

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Conversation">
      {!mobile && npc && (
        <header className="flex items-center gap-3 border-b border-line px-6 pb-4 pt-6">
          <div className={`relative h-12 w-12 overflow-hidden rounded-full ring-2 transition ${speaking ? "ring-brass/80" : "ring-white/10"}`}>
            <ArtImage src={resolveArt(npc.portrait_url)} kind="portrait" alt={npc.name} className="h-full w-full object-cover" />
          </div>
          <div className="min-w-0">
            <div className="font-display text-xl leading-tight text-text">{npc.name}</div>
            <div className="text-xs uppercase tracking-[0.16em] text-faint">{npc.role}</div>
          </div>
          <div className="ml-auto">{speaking ? <SpeakingBars /> : null}</div>
        </header>
      )}
      <div
        ref={scroller}
        className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6"
        style={{ maskImage: "linear-gradient(to bottom, transparent 0, #000 18px)", WebkitMaskImage: "linear-gradient(to bottom, transparent 0, #000 18px)" }}
        data-testid="transcript"
      >
        <ol className="flex flex-col gap-4">
          {transcript.map((e, i) => (
            <li key={i} className="rise-in">
              <Entry entry={e} cartridge={cartridge} hero={e.kind === "npc" && e.turn === heroTurn} />
            </li>
          ))}
          {pending && (
            <li className="rise-in">
              <PlayerBubble entry={pending} cartridge={cartridge} />
            </li>
          )}
          {mic === "waiting" && (
            <li className="rise-in flex items-center gap-2 pl-1 text-sm text-muted" data-testid="thinking">
              <span className="anim-dots text-brass text-lg leading-none">
                <span>•</span>
                <span>•</span>
                <span>•</span>
              </span>
              {npc?.name ?? "She"} is working out what you mean
            </li>
          )}
        </ol>
      </div>
      {helpCue && (
        <div className="border-t border-line px-4 pb-4 pt-3 sm:px-6">
          <HelpCard cue={helpCue} />
        </div>
      )}
    </section>
  );
}

function SpeakingBars() {
  return (
    <span className="flex h-5 items-end gap-[3px]" aria-label="speaking">
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className="w-[3px] rounded-full bg-brass"
          style={{ height: "100%", animation: `dots 0.9s ${i * 0.12}s ease-in-out infinite`, transformOrigin: "bottom" }}
        />
      ))}
    </span>
  );
}

function Entry({ entry, cartridge, hero }: { entry: TranscriptEntry; cartridge: CartridgeView | null; hero: boolean }) {
  switch (entry.kind) {
    case "narration":
      return (
        <p className="border-l border-brass/30 pl-3 font-display text-[15px] italic leading-relaxed text-muted" data-kind="narration">
          {entry.text}
        </p>
      );
    case "npc":
      return <NpcLine line={entry.line} cartridge={cartridge} hero={hero} />;
    case "player":
      return <PlayerBubble entry={entry} cartridge={cartridge} />;
    case "evidence":
      return <EvidenceChip entry={entry} cartridge={cartridge} />;
    default:
      return null;
  }
}

export function NpcLine({ line, cartridge, hero }: { line: SpokenLine; cartridge: CartridgeView | null; hero: boolean }) {
  const replay = useGame((s) => s.replay);
  const speakingId = useGame((s) => s.speakingLineId);
  const speakingRate = useGame((s) => s.speakingRate);
  const [revealed, setRevealed] = useState(false);
  const npc = cartridge?.npcs.find((n) => n.id === line.speaker);
  const active = speakingId === line.line_id;
  const audioFailed = linePlayer.hasFailed(line.line_id);
  const isTarget = !!line.romanization;
  return (
    <article
      className={`relative rounded-2xl border px-4 py-3.5 transition-colors duration-500 ${
        active ? "border-brass/50 bg-brass/[0.07] shadow-[0_0_0_1px_rgba(233,180,95,0.15),0_10px_40px_-12px_rgba(233,180,95,0.35)]" : "border-line bg-white/[0.025]"
      }`}
      data-kind="npc"
      data-line-id={line.line_id}
      data-active={active ? "1" : "0"}
    >
      <div className="flex items-start gap-3">
        <div className={`mt-1 h-9 w-9 shrink-0 overflow-hidden rounded-full ring-1 ${active ? "ring-brass/70" : "ring-white/10"}`}>
          <ArtImage src={resolveArt(npc?.portrait_url)} kind="portrait" alt={line.speaker_name} className="h-full w-full object-cover" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-faint">{line.speaker_name || npc?.name}</div>
          <p
            lang={line.language}
            className={`jp mt-0.5 font-medium leading-[1.25] text-text [overflow-wrap:anywhere] [word-break:keep-all] ${
              hero ? (line.text.length > 9 ? "text-[28px] sm:text-[32px]" : "text-[34px] sm:text-[40px]") : "text-[22px] sm:text-[24px]"
            }`}
            data-role="native"
          >
            {line.text}
          </p>
          {isTarget && (
            <p className={`mt-1 tracking-wide text-romaji ${hero ? "text-lg" : "text-[15px]"}`} data-role="romanization">
              {line.romanization}
            </p>
          )}
          {revealed && line.translation && (
            <p className="fade-in mt-2 text-sm text-muted" data-role="translation">
              “{line.translation}”
            </p>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <LineButton onClick={() => replay(line, 1)} active={active && speakingRate === 1} label="Replay">
              <IconPlay className="h-3.5 w-3.5" />
              Replay
            </LineButton>
            <LineButton onClick={() => replay(line, SLOW_RATE)} active={active && speakingRate !== 1} label="Replay slowly">
              <IconSlow className="h-4 w-4" />
              Slow
            </LineButton>
            {line.translation && (
              <LineButton onClick={() => setRevealed((v) => !v)} active={revealed} label={revealed ? "Hide meaning" : "Reveal meaning"}>
                <IconEye className="h-3.5 w-3.5" />
                {revealed ? "Hide meaning" : "Meaning"}
              </LineButton>
            )}
            {audioFailed && <span className="ml-1 text-[11px] text-faint">audio unavailable — text is all here</span>}
          </div>
        </div>
      </div>
    </article>
  );
}

function LineButton({ children, onClick, active, label }: { children: React.ReactNode; onClick: () => void; active: boolean; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] font-medium transition ${
        active ? "border-brass/60 bg-brass/15 text-brass-strong" : "border-line bg-white/[0.03] text-muted hover:border-line-strong hover:text-text"
      }`}
    >
      {children}
    </button>
  );
}

function PlayerBubble({ entry, cartridge }: { entry: PlayerEntry; cartridge: CartridgeView | null }) {
  const obj = entry.tapped_object_id ? cartridge?.objects.find((o) => o.id === entry.tapped_object_id) : null;
  const label = entry.input_mode === "speech" ? "Heard" : entry.input_mode === "text" ? "Typed" : "Tapped";
  return (
    <div className="flex justify-end" data-kind="player">
      <div className="max-w-[85%] rounded-2xl rounded-br-md border border-sky/20 bg-sky/[0.07] px-4 py-2.5 text-right">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-sky/80">{label}</div>
        {entry.input_mode === "tap" ? (
          <div className="mt-0.5 flex items-center justify-end gap-2 text-[15px] text-text">
            <IconHand className="h-4 w-4 text-sky" />
            {obj ? (
              <span>
                <span className="jp text-lg">{obj.native}</span> <span className="text-romaji">{obj.romanization}</span>
              </span>
            ) : (
              "the object"
            )}
          </div>
        ) : (
          <>
            <div className="jp mt-0.5 text-[20px] leading-snug text-text">{entry.transcript}</div>
            {entry.romanized && entry.romanized !== entry.transcript && (
              <div className="text-[14px] text-romaji">{entry.romanized}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const SUPPORT_WORDS = [
  "on your own",
  "after hearing it slowly",
  "with the word shown",
  "with a phrase frame",
  "with a meaning hint",
  "with the full answer",
];

export function supportPhrase(level: number, mode?: string) {
  if (mode === "tap") return "by tapping";
  return SUPPORT_WORDS[Math.max(0, Math.min(5, level))] ?? "with help";
}

function stageOf(e: EvidenceEntry): string | null {
  const s = e.stage_after as unknown;
  if (s && typeof s === "object") {
    const m = s as Record<string, string | null>;
    return e.concept_ids.map((c) => m[c]).find((v) => v != null) ?? null;
  }
  return typeof s === "string" ? s : null;
}

function EvidenceChip({ entry, cartridge }: { entry: EvidenceEntry; cartridge: CartridgeView | null }) {
  const obj = cartridge?.objects.find((o) => entry.concept_ids.includes(o.concept_id));
  if (entry.outcome === "not_understood") {
    return (
      <div className="flex justify-center" data-kind="evidence" data-outcome="not_understood">
        <span className="rounded-full border border-line px-3 py-1 text-[12px] text-faint">Keep going — she's listening</span>
      </div>
    );
  }
  const word = obj ? (
    <>
      <span className="jp text-[14px] text-text">{obj.native}</span> <span>{obj.romanization}</span>
    </>
  ) : null;
  let text: React.ReactNode;
  if (entry.evidence_type === "recognized") text = <>recognized {word}</>;
  else if (entry.evidence_type === "transferred")
    text = stageOf(entry) === "transferred" ? <>reused the request for {word} — on your own</> : <>asked for {word} {supportPhrase(entry.support_level, entry.input_mode)}</>;
  else text = <>understood — {supportPhrase(entry.support_level, entry.input_mode)}</>;
  return (
    <div className="flex justify-center" data-kind="evidence" data-outcome={entry.outcome}>
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-ok/25 bg-ok/[0.08] px-3 py-1 text-[12.5px] text-ok"
        style={{ animation: "chip-pop 0.4s cubic-bezier(0.2,0.8,0.2,1) both" }}
      >
        <IconCheck />
        {text}
      </span>
    </div>
  );
}
