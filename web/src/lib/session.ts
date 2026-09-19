// {session_id, token} persistence so a refresh rebuilds the game from PublicState.

export interface SavedSession {
  session_id: string;
  token: string;
  cartridge_id: string;
}

function key(mock: boolean) {
  return mock ? "polytale.session.mock" : "polytale.session";
}

export function loadSession(mock: boolean): SavedSession | null {
  try {
    const raw = localStorage.getItem(key(mock));
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (typeof v?.session_id === "string" && typeof v?.token === "string") return v as SavedSession;
  } catch {
    /* storage blocked or corrupt */
  }
  return null;
}

export function saveSession(mock: boolean, s: SavedSession): void {
  try {
    localStorage.setItem(key(mock), JSON.stringify(s));
  } catch {
    /* storage blocked: session lives only in memory */
  }
}

export function clearSession(mock: boolean): void {
  try {
    localStorage.removeItem(key(mock));
  } catch {
    /* ignore */
  }
}
