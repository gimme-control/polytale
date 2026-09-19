// Game store: journey, scene state, subtitle reveal, and the input state machine.

import { create } from "zustand";
import { api, ApiError } from "./lib/api";
import { clearJourney, loadJourney, saveJourney } from "./lib/session";
import type {
  ActBody,
  Catalog,
  Clue,
  Difficulty,
  Ending,
  Entry,
  GameView,
  Help,
  JourneyScene,
  Language,
  LearnerEntry,
  Line,
  Persona,
  Phrase,
  Progress,
  PublicState,
  SceneCard,
  SceneView,
  Story,
  Summary,
  Transcription,
  TurnResult,
} from "./lib/types";
import { mic } from "./audio/recorder";
import { linePlayer, type QueueItem } from "./audio/linePlayer";

export const MIN_RECORDING_MS = 250;
export const AUTO_SUBMIT_MS = 1200;
export const SLOW_RATE = 0.75;
const SUMMARY_DELAY_MS = 1400;
const INTRO_MIN_MS = 2400;
const CLUE_TOAST_MS = 5200;

/** The narrator is read first; the character speaks once there has been time to read. */
function readingMs(text: string | null | undefined): number {
  if (!text) return 0;
  return Math.min(2600, 500 + text.split(/\s+/).length * 95);
}

export type Screen = "boot" | "start" | "intro" | "play" | "summary";
export type InputPhase = "idle" | "listening" | "transcribing" | "preview" | "waiting" | "error";

interface IntroCard {
  scene: SceneCard | null;
  error: string | null;
  body: { scene_id?: string; restart?: boolean };
}

interface GameState {
  screen: Screen;
  catalog: Catalog | null;
  startError: string | null;
  starting: boolean;
  chosenPersona: string | null;

  journeyId: string | null;
  token: string | null;
  language: Language | null;
  personas: Persona[];
  personaId: string | null;
  scene: SceneView | null;
  scenes: JourneyScene[];
  transcript: Entry[];
  zones: Record<string, string>;
  mood: string;
  progress: Progress | null;
  sceneComplete: boolean;
  summary: Summary | null;
  intro: IntroCard | null;
  story: Story | null;
  game: GameView | null;
  ending: Ending | null;
  chosenDifficulty: Difficulty;

  /** notebook: how many clues the learner has already looked at, and the newest arrival */
  cluesSeen: number;
  clueToast: Clue | null;

  /** "How do I say...?" */
  phrasebook: Phrase[];
  phraseOpen: boolean;
  phraseBusy: boolean;
  phraseError: string | null;
  phraseResult: Phrase | null;
  /** text handed to the input bar by "Use it" */
  draft: { text: string; nonce: number };

  /** npc lines of the current exchange not yet shown (they appear as they play) */
  hidden: Record<string, true>;
  speakingLineId: string | null;
  speakingRate: number;
  /** the narrator has the floor: the character's lines are about to start */
  narrating: boolean;
  /** a clip is sounding right now (speaking can also mean "line shown, audio loading") */
  audible: boolean;
  help: Help | null;
  helpBusy: boolean;
  helpGlow: boolean;

  phase: InputPhase;
  micDenied: boolean;
  preview: Transcription | null;
  previewDeadline: number | null;
  pending: LearnerEntry | null;
  learnerShownAt: number;
  notice: string | null;
  failedAct: ActBody | null;
  toast: string | null;

  boot(): Promise<void>;
  choosePersona(id: string): void;
  begin(): Promise<void>;
  enterScene(body: { scene_id?: string; restart?: boolean }, card: SceneCard | null): Promise<void>;
  retryIntro(): Promise<void>;
  pressMic(): Promise<void>;
  releaseMic(): Promise<void>;
  confirmPreview(): Promise<void>;
  cancelPreview(): void;
  retryFailed(): Promise<void>;
  sendText(text: string): Promise<boolean>;
  tapObject(objectId: string, actionId?: string): Promise<void>;
  chooseDifficulty(d: Difficulty): void;
  setDifficulty(d: Difficulty): Promise<void>;
  openNotebook(): void;
  setPhraseOpen(open: boolean): void;
  askPhrase(text: string): Promise<void>;
  showPhrase(p: Phrase): void;
  playPhrase(p: Phrase): void;
  usePhrase(p: Phrase): void;
  requestHelp(): Promise<void>;
  setPersona(id: string): Promise<void>;
  replay(line: Line, rate?: number): void;
  finishScene(): Promise<void>;
  continueJourney(): Promise<void>;
  restartScene(): Promise<void>;
  newJourney(): Promise<void>;
  dismissNotice(): void;
}

let autoTimer: number | null = null;
let summaryTimer: number | null = null;
let toastTimer: number | null = null;
let glowTimer: number | null = null;
let clueTimer: number | null = null;
let speakTimer: number | null = null;
let recordingId = 0;

function clearAuto() {
  if (autoTimer != null) window.clearTimeout(autoTimer);
  autoTimer = null;
}

/** Reading-length pause for a line whose audio cannot play. */
function holdMs(line: Line): number {
  const words = line.segments.filter((s) => s.r || s.t.trim().length > 1).length || line.segments.length;
  return Math.min(4200, 900 + words * 420);
}

export const useGame = create<GameState>((set, get) => {
  linePlayer.onAudible = (audible) => set({ audible });
  linePlayer.on((id, rate) => {
    set((s) => {
      if (!id || !s.hidden[id]) return { speakingLineId: id, speakingRate: rate };
      const hidden = { ...s.hidden };
      delete hidden[id];
      return { speakingLineId: id, speakingRate: rate, hidden };
    });
  });

  function queue(lines: Line[]): QueueItem[] {
    const { journeyId, token } = get();
    return lines.map((l) => ({
      lineId: l.line_id,
      src: () => api.lineAudio(journeyId!, token!, l.line_id, l.audio_url),
      fallbackMs: holdMs(l),
    }));
  }

  function hydrate(st: PublicState) {
    set({
      journeyId: st.journey_id,
      language: st.language,
      personas: st.personas,
      personaId: st.persona_id,
      scene: st.scene,
      scenes: st.scenes ?? [],
      transcript: st.transcript ?? [],
      zones: st.zones ?? {},
      mood: st.mood,
      progress: st.progress,
      sceneComplete: st.scene_complete,
      summary: st.summary,
      story: st.story ?? get().story,
      game: st.game ?? null,
      ending: st.ending ?? null,
      phrasebook: st.phrasebook ?? [],
      cluesSeen: st.game?.clues.length ?? 0,
      clueToast: null,
      hidden: {},
      help: null,
      helpGlow: false,
      pending: null,
      preview: null,
      previewDeadline: null,
      phase: "idle",
      notice: null,
      failedAct: null,
    });
  }

  function scheduleSummary() {
    if (summaryTimer != null) window.clearTimeout(summaryTimer);
    summaryTimer = window.setTimeout(() => {
      summaryTimer = null;
      if ((get().summary || get().ending) && get().screen === "play") set({ screen: "summary" });
    }, SUMMARY_DELAY_MS);
  }

  /** Speak an exchange: its lines stay hidden until their turn in the queue. */
  function speak(lines: Line[], complete: boolean, delayMs = 0) {
    if (speakTimer != null) window.clearTimeout(speakTimer);
    speakTimer = null;
    if (!lines.length) {
      if (complete) scheduleSummary();
      return;
    }
    const hidden: Record<string, true> = {};
    for (const l of lines) hidden[l.line_id] = true;
    set({ hidden });
    const start = () => {
      speakTimer = null;
      set({ narrating: false });
      void linePlayer.playSequence(queue(lines)).then(() => {
        // Interrupted playback (barge-in) must not leave lines unseen.
        set({ hidden: {} });
        if (complete) scheduleSummary();
      });
    };
    if (delayMs > 0) {
      set({ narrating: true });
      speakTimer = window.setTimeout(start, delayMs);
    } else start();
  }

  /** The learner acts before the character has started: show the lines, skip the wait. */
  function cutToLines() {
    if (speakTimer == null) return;
    window.clearTimeout(speakTimer);
    speakTimer = null;
    set({ hidden: {}, narrating: false });
  }

  function noteClues(game: GameView | null | undefined) {
    if (!game) return;
    const known = get().game?.clues.length ?? 0;
    if (game.clues.length <= known) return;
    const newest = game.clues[game.clues.length - 1];
    set({ clueToast: newest });
    if (clueTimer != null) window.clearTimeout(clueTimer);
    clueTimer = window.setTimeout(() => set({ clueToast: null }), CLUE_TOAST_MS);
  }

  function applyTurn(r: TurnResult, learner: LearnerEntry | null) {
    const entries: Entry[] = [];
    const events = r.events ?? [];
    // `events` may carry only scene events or the whole turn; never add an entry twice.
    const fromServer = events.find((e): e is LearnerEntry => e.kind === "learner");
    if (fromServer) entries.push(fromServer);
    else if (learner) entries.push({ ...learner, turn: r.turn });
    for (const e of events) if (e.kind === "scene" || e.kind === "clue") entries.push(e);
    if (r.narration) entries.push({ kind: "narration", turn: r.turn, text: r.narration });
    else if (r.stage_direction) entries.push({ kind: "direction", turn: r.turn, text: r.stage_direction });
    for (const l of r.lines ?? []) entries.push({ kind: "npc", turn: r.turn, line: l });

    noteClues(r.game);
    set((s) => ({
      transcript: [...s.transcript, ...entries],
      game: r.game ?? s.game,
      ending: r.ending ?? s.ending,
      zones: r.zones,
      mood: r.mood,
      progress: r.progress,
      sceneComplete: r.scene_complete,
      summary: r.summary ?? s.summary,
      help: null,
      helpGlow: false,
      pending: null,
      learnerShownAt: Date.now(),
      phase: "idle",
      notice: null,
      failedAct: null,
    }));
    speak(r.lines ?? [], r.scene_complete || !!r.ending, readingMs(r.narration));
  }

  async function act(body: ActBody, learner: LearnerEntry) {
    const { journeyId, token } = get();
    if (!journeyId || !token) return;
    clearAuto();
    cutToLines();
    linePlayer.stop();
    set({ phase: "waiting", pending: learner, preview: null, previewDeadline: null, notice: null, failedAct: null });
    try {
      applyTurn(await api.act(journeyId, token, body), learner);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        // Consumed or busy: the server is the truth, resync.
        try {
          hydrate(await api.getState(journeyId, token));
        } catch {
          set({ phase: "idle", pending: null });
        }
        return;
      }
      if (err.status === 404 || err.status === 422) {
        set({ phase: "idle", pending: null, notice: "That one got lost. Say it again, or type it." });
        return;
      }
      // Model failure: state is unchanged server-side and the attempt is reusable.
      set({ phase: "error", pending: learner, failedAct: body, notice: err.status === 402 ? err.detail : "Didn't go through." });
    }
  }

  async function runIntro() {
    const { journeyId, token, intro } = get();
    if (!journeyId || !token || !intro) return;
    const t0 = performance.now();
    set({ intro: { ...intro, error: null } });
    try {
      let r: TurnResult | null = null;
      try {
        r = await api.enterScene(journeyId, token, intro.body);
      } catch (e) {
        // Already inside a scene (double click, stale tab): just rejoin it.
        if ((e as ApiError).status !== 409) throw e;
      }
      const st = await api.getState(journeyId, token);
      const knewIntro = !!get().intro?.scene?.intro;
      if (st.scene) set({ intro: { ...get().intro!, scene: { ...st.scene, intro: st.scene.intro } } });
      const wait = Math.max(INTRO_MIN_MS - (performance.now() - t0), knewIntro ? 0 : 1800);
      if (wait > 0) await new Promise((res) => window.setTimeout(res, wait));
      hydrate(st);
      set({ screen: (st.scene_complete && st.summary) || st.ending ? "summary" : "play", intro: null });
      if (r) {
        set({ learnerShownAt: 0 });
        speak(r.lines ?? [], r.scene_complete, readingMs(r.narration));
      }
    } catch (e) {
      const err = e as ApiError;
      // 402: the provider account is unfunded; say so, because retrying cannot help.
      set({ intro: { ...get().intro!, error: err.status === 402 ? err.detail : "Couldn't set the scene." } });
    }
  }

  return {
    screen: "boot",
    catalog: null,
    startError: null,
    starting: false,
    chosenPersona: null,
    journeyId: null,
    token: null,
    language: null,
    personas: [],
    personaId: null,
    scene: null,
    scenes: [],
    transcript: [],
    zones: {},
    mood: "neutral",
    progress: null,
    sceneComplete: false,
    summary: null,
    intro: null,
    story: null,
    game: null,
    ending: null,
    chosenDifficulty: "story",
    cluesSeen: 0,
    clueToast: null,
    phrasebook: [],
    phraseOpen: false,
    phraseBusy: false,
    phraseError: null,
    phraseResult: null,
    draft: { text: "", nonce: 0 },
    hidden: {},
    speakingLineId: null,
    speakingRate: 1,
    narrating: false,
    audible: false,
    help: null,
    helpBusy: false,
    helpGlow: false,
    phase: "idle",
    micDenied: false,
    preview: null,
    previewDeadline: null,
    pending: null,
    learnerShownAt: 0,
    notice: null,
    failedAct: null,
    toast: null,

    async boot() {
      const saved = loadJourney(api.mock);
      if (saved) {
        try {
          const st = await api.getState(saved.journey_id, saved.token);
          set({ token: saved.token });
          hydrate(st);
          if (st.scene && st.started) {
            set({ screen: (st.scene_complete && st.summary) || st.ending ? "summary" : "play" });
            return;
          }
          if (st.summary || st.ending) {
            set({ screen: "summary" });
            return;
          }
        } catch {
          clearJourney(api.mock);
          set({ journeyId: null, token: null });
        }
      }
      try {
        const catalog = await api.catalog();
        set({ catalog, language: get().language ?? catalog.language, story: get().story ?? catalog.story ?? null });
      } catch {
        /* server down: the start screen still renders; Begin reports it */
      }
      set({ screen: "start" });
    },

    choosePersona(id) {
      set({ chosenPersona: id });
    },

    chooseDifficulty(d) {
      set({ chosenDifficulty: d });
    },

    async setDifficulty(d) {
      const { journeyId, token, game } = get();
      if (!journeyId || !token || !game || game.difficulty === d) return;
      set({ game: { ...game, difficulty: d } });
      try {
        const st = await api.difficulty(journeyId, token, d);
        if (st.game) set({ game: st.game });
        set({ toast: d === "story" ? "Story mode, from the next turn" : "Immersion, from the next turn" });
      } catch {
        set({ game, toast: "Couldn't switch just now" });
      }
      if (toastTimer != null) window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(() => set({ toast: null }), 2600);
    },

    openNotebook() {
      set({ cluesSeen: get().game?.clues.length ?? 0, clueToast: null });
    },

    setPhraseOpen(open) {
      set({ phraseOpen: open, phraseError: null });
    },

    async askPhrase(text) {
      const t = text.trim();
      const { journeyId, token, phraseBusy } = get();
      if (!t || !journeyId || !token || phraseBusy) return;
      set({ phraseBusy: true, phraseError: null });
      try {
        const p = await api.phrase(journeyId, token, t);
        set((s) => ({ phraseResult: p, phrasebook: [p, ...s.phrasebook.filter((x) => x.phrase_id !== p.phrase_id)] }));
      } catch (e) {
        const err = e as ApiError;
        set({
          phraseError:
            err.status === 422
              ? "I can only help with what YOU want to say. Type it in English."
              : err.status === 402
                ? err.detail
                : "That didn't come back. Try again.",
        });
      } finally {
        set({ phraseBusy: false });
      }
    },

    showPhrase(p) {
      set({ phraseResult: p, phraseError: null });
    },

    playPhrase(p) {
      const { journeyId, token } = get();
      if (!journeyId || !token) return;
      void api.phraseAudio(journeyId, token, p.phrase_id, p.audio_url).then((src) => linePlayer.playClip(src)).catch(() => {});
    },

    usePhrase(p) {
      set((s) => ({ draft: { text: p.text, nonce: s.draft.nonce + 1 }, phraseOpen: window.innerWidth >= 1100 ? s.phraseOpen : false }));
    },

    async begin() {
      if (get().starting) return;
      set({ starting: true, startError: null });
      // Begin is the user gesture that asks for the microphone. Declining is fine.
      try {
        await mic.ensure();
        set({ micDenied: false });
      } catch {
        set({ micDenied: true });
      }
      try {
        let { journeyId, token } = get();
        if (!journeyId || !token) {
          const persona = get().chosenPersona ?? get().catalog?.personas[0]?.id;
          const created = await api.createJourney(persona ? { persona_id: persona } : {});
          journeyId = created.journey_id;
          token = created.token;
          saveJourney(api.mock, { journey_id: journeyId, token });
          set({ token });
          hydrate(created.state);
          const want = get().chosenDifficulty;
          if (created.state.game && created.state.game.difficulty !== want) hydrate(await api.difficulty(journeyId, token, want));
        } else if (get().chosenPersona && get().chosenPersona !== get().personaId) {
          hydrate(await api.persona(journeyId, token, get().chosenPersona!));
        }
        const first = get().scenes.find((s) => s.status !== "done") ?? get().catalog?.scenes[0] ?? null;
        await get().enterScene({}, first);
      } catch (e) {
        const err = e as ApiError;
        set({
          startError:
            err.status === 0 || err.status >= 500
              ? "Can't reach the server. Check that it is running, then try again."
              : `Couldn't start: ${err.detail ?? err.message}`,
        });
      } finally {
        set({ starting: false });
      }
    },

    async enterScene(body, card) {
      linePlayer.stop();
      clearAuto();
      if (summaryTimer != null) window.clearTimeout(summaryTimer);
      set({ screen: "intro", intro: { scene: card, error: null, body } });
      await runIntro();
    },

    retryIntro: runIntro,

    async pressMic() {
      const s = get();
      if (s.phase === "listening" || s.phase === "transcribing" || s.phase === "waiting" || s.screen !== "play") return;
      clearAuto();
      linePlayer.stop(); // barge-in: the learner talking takes the floor
      try {
        await mic.ensure();
      } catch {
        set({ micDenied: true, phase: "idle", notice: "The microphone is off. You can type instead." });
        return;
      }
      mic.start();
      recordingId++;
      set({ phase: "listening", micDenied: false, preview: null, previewDeadline: null, notice: null, failedAct: null });
    },

    async releaseMic() {
      if (get().phase !== "listening") return;
      const myId = recordingId;
      const rec = await mic.stop();
      if (rec.durationMs < MIN_RECORDING_MS) {
        set({ phase: "idle", notice: "Hold while you speak, then let go." });
        return;
      }
      const { journeyId, token } = get();
      set({ phase: "transcribing" });
      try {
        const tr = await api.transcribe(journeyId!, token!, rec.blob);
        if (myId !== recordingId) return;
        if (!tr.transcript?.trim()) {
          set({ phase: "idle", preview: null, notice: "Didn't catch that. Try again, or type it." });
          return;
        }
        const deadline = tr.requires_confirmation ? null : Date.now() + AUTO_SUBMIT_MS;
        set({ phase: "preview", preview: tr, previewDeadline: deadline });
        if (deadline) autoTimer = window.setTimeout(() => void get().confirmPreview(), AUTO_SUBMIT_MS);
      } catch {
        if (myId !== recordingId) return;
        set({ phase: "idle", notice: "Couldn't hear that. Type it instead." });
      }
    },

    async confirmPreview() {
      const p = get().preview;
      if (!p || get().phase !== "preview") return;
      clearAuto();
      await act(
        { attempt_id: p.attempt_id },
        {
          kind: "learner",
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
      // "I meant something else": nothing is spent.
      clearAuto();
      set({ phase: "idle", preview: null, previewDeadline: null, notice: null });
    },

    async retryFailed() {
      const { failedAct, pending } = get();
      if (!failedAct || !pending) return;
      await act(failedAct, pending);
    },

    async sendText(text) {
      const t = text.trim();
      const s = get();
      if (!t || s.phase === "waiting" || s.phase === "listening" || s.phase === "transcribing") return false;
      await act(
        { text: t },
        { kind: "learner", turn: 0, attempt_id: "", input_mode: "text", transcript: t, romanized: null, tapped_object_id: null },
      );
      return true;
    },

    async tapObject(objectId, actionId) {
      const s = get();
      if (s.phase !== "idle" && s.phase !== "error") return;
      if (s.sceneComplete) return;
      await act(actionId ? { tap_object_id: objectId, action_id: actionId } : { tap_object_id: objectId }, {
        kind: "learner",
        turn: 0,
        attempt_id: "",
        input_mode: "tap",
        transcript: "",
        romanized: null,
        tapped_object_id: objectId,
        action_id: actionId ?? null,
      });
    },

    async requestHelp() {
      const { journeyId, token, helpBusy, progress } = get();
      if (!journeyId || !token || helpBusy || !progress?.next_help) return;
      set({ helpBusy: true });
      try {
        const { help, progress: next } = await api.help(journeyId, token);
        set({ help, progress: next });
        if (help.kind === "again") {
          const byId = new Map<string, Line>();
          for (const e of get().transcript) if (e.kind === "npc") byId.set(e.line.line_id, e.line);
          const lines = help.line_ids.map((id) => byId.get(id)).filter((l): l is Line => !!l);
          if (glowTimer != null) window.clearTimeout(glowTimer);
          set({ helpGlow: true, hidden: {} });
          void linePlayer.playSequence(queue(lines), SLOW_RATE).then(() => {
            glowTimer = window.setTimeout(() => set({ helpGlow: false }), 1800);
          });
        }
      } catch {
        set({ notice: "Help didn't load. Try once more." });
      } finally {
        set({ helpBusy: false });
      }
    },

    async setPersona(id) {
      const { journeyId, token, personaId, personas } = get();
      if (!journeyId || !token || id === personaId) return;
      const before = personaId;
      set({ personaId: id });
      try {
        const st = await api.persona(journeyId, token, id);
        const label = personas.find((p) => p.id === st.persona_id)?.label ?? "";
        set({ personaId: st.persona_id, toast: `${label}, from the next reply` });
      } catch {
        set({ personaId: before, toast: "Couldn't switch just now" });
      }
      if (toastTimer != null) window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(() => set({ toast: null }), 2600);
    },

    replay(line, rate = 1) {
      void linePlayer.playSequence(queue([line]), rate);
    },

    async finishScene() {
      const { journeyId, token } = get();
      if (!journeyId || !token) return;
      linePlayer.stop();
      clearAuto();
      try {
        const summary = await api.finish(journeyId, token);
        set({ summary, sceneComplete: true, screen: "summary", phase: "idle", pending: null, preview: null });
      } catch {
        set({ notice: "Couldn't finish the scene just now." });
      }
    },

    async continueJourney() {
      const { summary, scenes } = get();
      const next = summary?.next_scene;
      if (!next) return;
      const card = scenes.find((s) => s.id === next.id) ?? { ...next, cover_url: "" };
      await get().enterScene({ scene_id: next.id }, card);
    },

    async restartScene() {
      const { scene } = get();
      if (!scene) return;
      await get().enterScene({ scene_id: scene.id, restart: true }, scene);
    },

    async newJourney() {
      const { journeyId, token } = get();
      linePlayer.stop();
      clearAuto();
      if (summaryTimer != null) window.clearTimeout(summaryTimer);
      try {
        if (journeyId && token) hydrate(await api.reset(journeyId, token));
      } catch {
        // Journey gone server-side: start from scratch.
        clearJourney(api.mock);
        set({ journeyId: null, token: null });
      }
      try {
        if (!get().catalog) set({ catalog: await api.catalog() });
      } catch {
        /* start screen renders without the cover */
      }
      set({ screen: "start", summary: null, ending: null, scene: null, chosenPersona: get().personaId, phraseResult: null, phraseOpen: false });
    },

    dismissNotice() {
      set({ notice: null });
    },
  };
});

// Transient notices fade on their own; a failed send stays until it is resolved.
let noticeTimer: number | null = null;
useGame.subscribe((s, prev) => {
  if (!s.notice || s.notice === prev.notice || s.failedAct) return;
  if (noticeTimer != null) window.clearTimeout(noticeTimer);
  const shown = s.notice;
  noticeTimer = window.setTimeout(() => {
    const now = useGame.getState();
    if (now.notice === shown && !now.failedAct) useGame.setState({ notice: null });
  }, 5000);
});
