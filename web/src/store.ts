// Game store: session, transcript, world, learning, mic state machine (PRD §20).

import { create } from "zustand";
import { api, ApiError } from "./lib/api";
import { clearSession, loadSession, saveSession } from "./lib/session";
import type {
  ActBody,
  CartridgeView,
  EvidenceEntry,
  HelpCue,
  LearningView,
  PlayerEntry,
  PublicState,
  Recap,
  SpokenLine,
  TranscriptEntry,
  Transcription,
  TurnResult,
  World,
} from "./lib/types";
import { mic } from "./audio/recorder";
import { linePlayer } from "./audio/linePlayer";

export const DEFAULT_CARTRIDGE = "broken-airship-ja";
export const MIN_RECORDING_MS = 250;
export const AUTO_SUBMIT_MS = 1200;
export const SLOW_RATE = 0.7;

export type Screen = "boot" | "start" | "play";
export type MicPhase =
  | "idle"
  | "listening"
  | "transcribing"
  | "preview"
  | "empty"
  | "waiting"
  | "error";

export interface Flight {
  id: number;
  objectId: string;
  to: "player" | "npc";
}

interface GameState {
  screen: Screen;
  bootError: string | null;
  starting: boolean;
  cartridgeId: string;
  cartridge: CartridgeView | null;
  sid: string | null;
  token: string | null;

  transcript: TranscriptEntry[];
  world: World | null;
  learning: LearningView | null;
  episodeComplete: boolean;
  recap: Recap | null;
  helpCue: HelpCue | null;
  helpBusy: boolean;

  mic: MicPhase;
  micDenied: boolean;
  preview: Transcription | null;
  previewDeadline: number | null;
  pending: PlayerEntry | null;
  notice: string | null;
  failedAct: ActBody | null;
  keyboard: boolean;

  speakingLineId: string | null;
  speakingRate: number;

  flights: Flight[];
  fixtureFlash: Record<string, number>;
  launchAt: number | null;
  focusPulseAt: number;
  showEnd: boolean;
  lastActivity: number;

  boot(): Promise<void>;
  begin(): Promise<void>;
  pressMic(): Promise<void>;
  releaseMic(): Promise<void>;
  confirmPreview(): Promise<void>;
  cancelPreview(): void;
  retryPreview(): void;
  retryFailed(): Promise<void>;
  sendText(text: string): Promise<void>;
  tapObject(objectId: string): Promise<void>;
  requestHelp(): Promise<void>;
  replay(line: SpokenLine, rate?: number): void;
  setKeyboard(on: boolean): void;
  touch(): void;
  resetGame(opts: { restart: boolean }): Promise<void>;
  dismissNotice(): void;
}

let flightSeq = 1;
let autoTimer: number | null = null;
let endTimer: number | null = null;
let recordingId = 0;

function clearAuto() {
  if (autoTimer != null) window.clearTimeout(autoTimer);
  autoTimer = null;
}

function uidLocal() {
  return `rec_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

let noticeTimer: number | null = null;

export const useGame = create<GameState>((set, get) => {
  linePlayer.on((id, rate) => set({ speakingLineId: id, speakingRate: rate }));

  function hydrate(st: PublicState) {
    const cid = st.cartridge.id;
    set({
      cartridge: st.cartridge,
      cartridgeId: cid,
      transcript: st.transcript ?? [],
      world: st.world,
      learning: st.learning,
      episodeComplete: st.episode_complete,
      recap: st.recap,
      helpCue: st.help_cue,
      showEnd: st.episode_complete,
      launchAt: null,
      pending: null,
      preview: null,
      mic: "idle",
      notice: null,
      failedAct: null,
      flights: [],
    });
  }

  function lineItems(lines: SpokenLine[], rate = 1) {
    const { sid, token } = get();
    return lines.map((l) => ({
      lineId: l.line_id,
      src: () => api.audioSrc(sid!, token!, l.audio_url, l.line_id),
      rate,
    }));
  }

  function scheduleEnd() {
    if (endTimer != null) window.clearTimeout(endTimer);
    const check = () => {
      const s = get();
      const sinceLaunch = s.launchAt ? performance.now() - s.launchAt : Infinity;
      if (!s.speakingLineId && sinceLaunch > 4200) {
        set({ showEnd: true });
        endTimer = null;
      } else endTimer = window.setTimeout(check, 400);
    };
    endTimer = window.setTimeout(check, 1200);
  }

  function applyTurn(r: TurnResult, player: PlayerEntry | null) {
    const prev = get().world;
    const entries: TranscriptEntry[] = [];
    if (player) entries.push({ ...player, turn: r.turn });
    for (const e of r.evidence ?? []) entries.push({ ...e, kind: "evidence", turn: e.turn ?? r.turn } as EvidenceEntry);
    if (r.narration) entries.push({ kind: "narration", turn: r.turn, text: r.narration });
    for (const l of r.spoken_lines ?? []) entries.push({ kind: "npc", turn: r.turn, line: l });

    // World diff -> stage moments.
    const flights: Flight[] = [];
    const flash: Record<string, number> = { ...get().fixtureFlash };
    let launchAt = get().launchAt;
    const now = performance.now();
    if (prev) {
      for (const [obj, holder] of Object.entries(r.world.holders)) {
        if (prev.holders[obj] !== holder) {
          if (holder === "player") flights.push({ id: flightSeq++, objectId: obj, to: "player" });
          else if (prev.holders[obj] === "player") flights.push({ id: flightSeq++, objectId: obj, to: "npc" });
        }
      }
      for (const [fx, state] of Object.entries(r.world.fixtures)) {
        if (prev.fixtures[fx] !== state) {
          flash[fx] = now;
          if (state === "launched") launchAt = now;
        }
      }
    }
    set((s) => ({
      transcript: [...s.transcript, ...entries],
      world: r.world,
      learning: r.learning,
      episodeComplete: r.episode_complete,
      recap: r.recap ?? s.recap,
      helpCue: null,
      pending: null,
      mic: "idle",
      notice: null,
      failedAct: null,
      flights: [...s.flights, ...flights],
      fixtureFlash: flash,
      launchAt,
      focusPulseAt: r.world.focus ? now : s.focusPulseAt,
      lastActivity: Date.now(),
    }));
    // Text first; audio follows.
    if (r.spoken_lines?.length) void linePlayer.playSequence(lineItems(r.spoken_lines));
    if (r.episode_complete) {
      if (!r.recap) {
        const { sid, token } = get();
        api.recap(sid!, token!).then((recap) => set({ recap })).catch(() => {});
      }
      if (!launchAt) set({ launchAt: now });
      scheduleEnd();
    }
  }

  async function act(body: ActBody, player: PlayerEntry) {
    const { sid, token } = get();
    if (!sid || !token) return;
    clearAuto();
    set({ mic: "waiting", pending: player, preview: null, previewDeadline: null, notice: null, failedAct: null, lastActivity: Date.now() });
    try {
      const r = await api.act(sid, token, body);
      applyTurn(r, player);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        // Attempt already consumed (e.g. double submit): resync from the server.
        try {
          hydrate(await api.getState(sid, token));
        } catch {
          set({ mic: "idle", pending: null });
        }
        return;
      }
      if (err.status === 422 || err.status === 404) {
        // Nothing usable was heard / attempt unknown: not a story failure, just try again.
        set({ mic: "empty", pending: null, notice: "Didn't catch that — try again." });
        return;
      }
      set({
        mic: "error",
        pending: player,
        failedAct: body,
        notice: "The moment slipped — nothing was lost. Try sending it again.",
      });
    }
  }

  return {
    screen: "boot",
    bootError: null,
    starting: false,
    cartridgeId: DEFAULT_CARTRIDGE,
    cartridge: null,
    sid: null,
    token: null,
    transcript: [],
    world: null,
    learning: null,
    episodeComplete: false,
    recap: null,
    helpCue: null,
    helpBusy: false,
    mic: "idle",
    micDenied: false,
    preview: null,
    previewDeadline: null,
    pending: null,
    notice: null,
    failedAct: null,
    keyboard: false,
    speakingLineId: null,
    speakingRate: 1,
    flights: [],
    fixtureFlash: {},
    launchAt: null,
    focusPulseAt: 0,
    showEnd: false,
    lastActivity: Date.now(),

    async boot() {
      const saved = loadSession(api.mock);
      if (saved) {
        try {
          const st = await api.getState(saved.session_id, saved.token);
          set({ sid: saved.session_id, token: saved.token });
          hydrate(st);
          set({ screen: st.started ? "play" : "start" });
          return;
        } catch {
          clearSession(api.mock);
        }
      }
      try {
        const list = await api.cartridges();
        const pick = list.find((c) => c.id === DEFAULT_CARTRIDGE) ?? list[0];
        if (pick) set({ cartridgeId: pick.id });
      } catch {
        /* server down: start screen still renders; Start will surface the error */
      }
      set({ screen: "start" });
    },

    async begin() {
      if (get().starting) return;
      set({ starting: true, bootError: null });
      // The Start press is the moment to ask for the microphone (PRD §25).
      try {
        await mic.ensure();
        set({ micDenied: false });
      } catch {
        set({ micDenied: true, keyboard: true });
      }
      try {
        let { sid, token } = get();
        if (!sid || !token) {
          const created = await api.createSession(get().cartridgeId);
          sid = created.session_id;
          token = created.token;
          saveSession(api.mock, { session_id: sid, token, cartridge_id: get().cartridgeId });
          set({ sid, token });
          hydrate(created.state);
        }
        try {
          const r = await api.start(sid, token);
          set({ screen: "play" });
          applyTurn(r, null);
        } catch (e) {
          if ((e as ApiError).status === 409) {
            hydrate(await api.getState(sid, token));
            set({ screen: "play" });
          } else throw e;
        }
      } catch (e) {
        const err = e as ApiError;
        set({
          bootError:
            err.status === 0 || err.status >= 500
              ? "Can't reach the airfield right now. Is the server running?"
              : `Couldn't start: ${err.detail ?? err.message}`,
        });
      } finally {
        set({ starting: false });
      }
    },

    async pressMic() {
      const s = get();
      if (s.mic === "listening" || s.mic === "transcribing" || s.mic === "waiting" || s.episodeComplete) return;
      clearAuto();
      linePlayer.stop(); // barge-in: the learner talking takes the floor
      try {
        await mic.ensure();
      } catch {
        set({ micDenied: true, keyboard: true, notice: "Microphone is off. You can type instead." });
        return;
      }
      mic.start();
      recordingId++;
      set({ mic: "listening", preview: null, previewDeadline: null, notice: null, lastActivity: Date.now() });
    },

    async releaseMic() {
      if (get().mic !== "listening") return;
      const myId = recordingId;
      const rec = await mic.stop();
      if (rec.durationMs < MIN_RECORDING_MS) {
        set({ mic: "idle", notice: "Hold the button while you speak." });
        return;
      }
      const { sid, token } = get();
      set({ mic: "transcribing" });
      try {
        const tr = await api.transcribe(sid!, token!, rec.blob, uidLocal());
        if (myId !== recordingId) return;
        if (!tr.transcript?.trim()) {
          set({ mic: "empty", notice: null, preview: null });
          return;
        }
        const deadline = tr.requires_confirmation ? null : Date.now() + AUTO_SUBMIT_MS;
        set({ mic: "preview", preview: tr, previewDeadline: deadline, lastActivity: Date.now() });
        if (deadline) autoTimer = window.setTimeout(() => void get().confirmPreview(), AUTO_SUBMIT_MS);
      } catch {
        if (myId !== recordingId) return;
        set({ mic: "empty", notice: "That didn't come through clearly — try again." });
      }
    },

    async confirmPreview() {
      const p = get().preview;
      if (!p || get().mic !== "preview") return;
      clearAuto();
      await act(
        { attempt_id: p.attempt_id },
        {
          kind: "player",
          turn: 0,
          attempt_id: p.attempt_id,
          input_mode: "speech",
          transcript: p.transcript,
          romanized: p.romanized,
          tapped_object_id: null,
        },
      );
    },

    cancelPreview() {
      // "I meant something else": restore the idle state, nothing is spent.
      clearAuto();
      set({ mic: "idle", preview: null, previewDeadline: null, notice: null, lastActivity: Date.now() });
    },

    retryPreview() {
      clearAuto();
      set({ mic: "idle", preview: null, previewDeadline: null, notice: "Hold to speak again.", lastActivity: Date.now() });
    },

    async retryFailed() {
      const { failedAct, pending } = get();
      if (!failedAct || !pending) return;
      await act(failedAct, pending);
    },

    async sendText(text) {
      const t = text.trim();
      if (!t || get().mic === "waiting") return;
      linePlayer.stop();
      await act({ text: t }, { kind: "player", turn: 0, attempt_id: "", input_mode: "text", transcript: t, romanized: null, tapped_object_id: null });
    },

    async tapObject(objectId) {
      const m = get().mic;
      if (m === "waiting" || m === "listening" || m === "transcribing" || get().episodeComplete) return;
      linePlayer.stop();
      await act(
        { tap_object_id: objectId },
        { kind: "player", turn: 0, attempt_id: "", input_mode: "tap", transcript: "", romanized: null, tapped_object_id: objectId },
      );
    },

    async requestHelp() {
      const { sid, token, helpBusy } = get();
      if (!sid || !token || helpBusy) return;
      set({ helpBusy: true, lastActivity: Date.now() });
      try {
        const { cue, learning } = await api.help(sid, token);
        set({ helpCue: cue, learning, focusPulseAt: performance.now() });
        if (cue.kind === "replay_slow" && cue.line) {
          void linePlayer.playSequence(lineItems([cue.line]), SLOW_RATE);
        }
      } catch {
        set({ notice: "Help is catching its breath — try again in a moment." });
      } finally {
        set({ helpBusy: false });
      }
    },

    replay(line, rate = 1) {
      set({ lastActivity: Date.now() });
      if (line.speaker && get().world?.focus) set({ focusPulseAt: performance.now() });
      void linePlayer.playSequence(lineItems([line], rate), rate);
    },

    setKeyboard(on) {
      set({ keyboard: on, lastActivity: Date.now() });
    },

    touch() {
      set({ lastActivity: Date.now() });
    },

    async resetGame({ restart }) {
      const { sid, token } = get();
      linePlayer.stop();
      clearAuto();
      if (endTimer != null) window.clearTimeout(endTimer);
      if (!sid || !token) {
        set({ screen: "start" });
        return;
      }
      try {
        const st = await api.reset(sid, token);
        hydrate(st);
        set({ fixtureFlash: {}, launchAt: null, showEnd: false, helpCue: null });
        if (restart) {
          const r = await api.start(sid, token);
          set({ screen: "play" });
          applyTurn(r, null);
        } else set({ screen: "start" });
      } catch {
        // Session gone server-side: start from scratch.
        clearSession(api.mock);
        set({ sid: null, token: null, screen: "start", showEnd: false });
      }
    },

    dismissNotice() {
      set({ notice: null });
    },
  };
});

// Transient hints fade on their own; failures that need action (failedAct) persist.
useGame.subscribe((s, prev) => {
  if (!s.notice || s.notice === prev.notice || s.failedAct) return;
  if (noticeTimer != null) window.clearTimeout(noticeTimer);
  const shown = s.notice;
  noticeTimer = window.setTimeout(() => {
    const now = useGame.getState();
    if (now.notice === shown && !now.failedAct) useGame.setState({ notice: null });
  }, 4500);
});
