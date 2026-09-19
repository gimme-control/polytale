// Typed REST client for the Polytale server (SPEC.md "REST API").
// `?mock=1` swaps in an in-browser implementation of the same contract (mockApi.ts).

import type {
  ActBody,
  CartridgeSummary,
  CreateSessionResponse,
  HelpResponse,
  PublicState,
  Recap,
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
  health(): Promise<{ ok: boolean; speech_provider: string; tts_provider: string }>;
  cartridges(): Promise<CartridgeSummary[]>;
  /** Art URL for a cartridge-relative path like "art/cover.png" (no token needed). */
  artUrl(cartridgeId: string, path: string): string;
  createSession(cartridgeId: string): Promise<CreateSessionResponse>;
  getState(sid: string, token: string): Promise<PublicState>;
  start(sid: string, token: string): Promise<TurnResult>;
  transcribe(sid: string, token: string, audio: Blob, clientRecordingId: string): Promise<Transcription>;
  act(sid: string, token: string, body: ActBody): Promise<TurnResult>;
  help(sid: string, token: string): Promise<HelpResponse>;
  recap(sid: string, token: string): Promise<Recap>;
  reset(sid: string, token: string): Promise<PublicState>;
  /** Playable URL for a line's audio (appends `?token=`). */
  audioSrc(sid: string, token: string, audioUrl: string, lineId: string): Promise<string>;
  /** Any server URL that needs the session token as a query param (audio, art). */
  withToken(url: string, token: string): string;
}

function withToken(url: string, token: string): string {
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
  if (opts.token) headers["X-Session-Token"] = opts.token;
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

const s = (sid: string) => `/api/sessions/${encodeURIComponent(sid)}`;

export function createHttpApi(): Api {
  return {
    mock: false,
    health: () => request("GET", "/api/health"),
    cartridges: () => request("GET", "/api/cartridges"),
    // `path` is cartridge-relative (e.g. "art/cover.png"), matching core.views.art_url.
    artUrl: (id, path) => `/api/cartridges/${encodeURIComponent(id)}/art/${path}`,
    createSession: (cartridge_id) => request("POST", "/api/sessions", { json: { cartridge_id } }),
    getState: (sid, token) => request("GET", s(sid), { token }),
    start: (sid, token) => request("POST", `${s(sid)}/start`, { token, json: {} }),
    transcribe: (sid, token, audio, clientRecordingId) => {
      const form = new FormData();
      form.append("audio", audio, `${clientRecordingId}.wav`);
      form.append("client_recording_id", clientRecordingId);
      return request("POST", `${s(sid)}/transcribe`, { token, form, timeoutMs: 25_000 });
    },
    act: (sid, token, body) => request("POST", `${s(sid)}/act`, { token, json: body, timeoutMs: 90_000 }),
    help: (sid, token) => request("POST", `${s(sid)}/help`, { token, json: {} }),
    recap: (sid, token) => request("GET", `${s(sid)}/recap`, { token }),
    reset: (sid, token) => request("POST", `${s(sid)}/reset`, { token, json: {} }),
    audioSrc: async (sid, token, audioUrl, lineId) =>
      withToken(audioUrl || `${s(sid)}/lines/${encodeURIComponent(lineId)}/audio`, token),
    withToken,
  };
}

function isMock(): boolean {
  try {
    const q = new URLSearchParams(window.location.search);
    return q.get("mock") === "1" || q.get("mock") === "true";
  } catch {
    return false;
  }
}

export const api: Api = isMock() ? createMockApi() : createHttpApi();
