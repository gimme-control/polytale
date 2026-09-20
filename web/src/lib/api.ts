// Typed REST client mirroring SPEC.md "REST". `?mock=1` swaps in an in-browser
// implementation of the same contract (mockApi.ts).

import type {
  ActBody,
  Catalog,
  CreateJourneyResponse,
  Health,
  HelpResponse,
  Phrase,
  PublicState,
  SceneBody,
  Summary,
  Transcription,
  TurnResult,
} from "./types";
import { createMockApi } from "./mockApi";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`HTTP ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

export interface Api {
  readonly mock: boolean;
  health(): Promise<Health>;
  catalog(): Promise<Catalog>;
  /** The learner picks the language on the title screen; the story is the same one. */
  createJourney(body: { language?: string }): Promise<CreateJourneyResponse>;
  getState(jid: string, token: string): Promise<PublicState>;
  /** Enter the next (or named) scene and run the opening turn. */
  enterScene(jid: string, token: string, body: SceneBody): Promise<TurnResult>;
  transcribe(jid: string, token: string, audio: Blob): Promise<Transcription>;
  act(jid: string, token: string, body: ActBody): Promise<TurnResult>;
  help(jid: string, token: string): Promise<HelpResponse>;
  /** "How do I say...?": the learner's own support-language sentence, never a character line. */
  phrase(jid: string, token: string, text: string): Promise<Phrase>;
  phraseAudio(jid: string, token: string, phraseId: string, audioUrl?: string): Promise<string>;
  finish(jid: string, token: string): Promise<Summary>;
  reset(jid: string, token: string): Promise<PublicState>;
  /** Playable URL for a line's audio (`?token=` appended). */
  lineAudio(jid: string, token: string, lineId: string, audioUrl?: string): Promise<string>;
  /** Playable URL for a bare item's audio (summary screen only). */
  itemAudio(jid: string, token: string, itemId: string, audioUrl?: string): Promise<string>;
}

export function withToken(url: string, token: string): string {
  if (!url) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}token=${encodeURIComponent(token)}`;
}

async function request<T>(
  method: string,
  path: string,
  opts: { token?: string; json?: unknown; form?: FormData; timeoutMs?: number } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.token) headers["X-Journey-Token"] = opts.token;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 60_000);
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body, signal: ctrl.signal });
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : "network error");
  } finally {
    window.clearTimeout(timer);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j?.detail === "string" ? j.detail : JSON.stringify(j?.detail ?? j);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const j = (jid: string) => `/api/journeys/${encodeURIComponent(jid)}`;

export function createHttpApi(): Api {
  return {
    mock: false,
    health: () => request("GET", "/api/health"),
    catalog: () => request("GET", "/api/catalog"),
    createJourney: (body) => request("POST", "/api/journeys", { json: body }),
    getState: (jid, token) => request("GET", j(jid), { token }),
    enterScene: (jid, token, body) => request("POST", `${j(jid)}/scene`, { token, json: body, timeoutMs: 90_000 }),
    transcribe: (jid, token, audio) => {
      const form = new FormData();
      form.append("audio", audio, "attempt.wav");
      return request("POST", `${j(jid)}/transcribe`, { token, form, timeoutMs: 25_000 });
    },
    act: (jid, token, body) => request("POST", `${j(jid)}/act`, { token, json: body, timeoutMs: 90_000 }),
    help: (jid, token) => request("POST", `${j(jid)}/help`, { token, json: {} }),
    phrase: (jid, token, text) => request("POST", `${j(jid)}/phrase`, { token, json: { text }, timeoutMs: 20_000 }),
    phraseAudio: async (jid, token, phraseId, audioUrl) =>
      withToken(audioUrl || `${j(jid)}/phrases/${encodeURIComponent(phraseId)}/audio`, token),
    finish: (jid, token) => request("POST", `${j(jid)}/finish`, { token, json: {} }),
    reset: (jid, token) => request("POST", `${j(jid)}/reset`, { token, json: {} }),
    lineAudio: async (jid, token, lineId, audioUrl) =>
      withToken(audioUrl || `${j(jid)}/lines/${encodeURIComponent(lineId)}/audio`, token),
    itemAudio: async (jid, token, itemId, audioUrl) =>
      withToken(audioUrl || `${j(jid)}/items/${encodeURIComponent(itemId)}/audio`, token),
  };
}

export function isMock(): boolean {
  try {
    const q = new URLSearchParams(window.location.search);
    return q.get("mock") === "1" || q.get("mock") === "true";
  } catch {
    return false;
  }
}

export const api: Api = isMock() ? createMockApi() : createHttpApi();
