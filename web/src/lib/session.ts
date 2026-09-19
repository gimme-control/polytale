// {journey_id, token} persistence so a refresh rebuilds the game from PublicState.

export interface SavedJourney {
  journey_id: string;
  token: string;
}

function key(mock: boolean) {
  return mock ? "polytale.journey.mock" : "polytale.journey";
}

export function loadJourney(mock: boolean): SavedJourney | null {
  try {
    const raw = localStorage.getItem(key(mock));
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (typeof v?.journey_id === "string" && typeof v?.token === "string") return v as SavedJourney;
  } catch {
    /* storage blocked or corrupt */
  }
  return null;
}

export function saveJourney(mock: boolean, s: SavedJourney): void {
  try {
    localStorage.setItem(key(mock), JSON.stringify(s));
  } catch {
    /* storage blocked: the journey lives only in memory */
  }
}

export function clearJourney(mock: boolean): void {
  try {
    localStorage.removeItem(key(mock));
  } catch {
    /* ignore */
  }
}
