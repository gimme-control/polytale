// Where things are on screen, shared between the scene and the dialogue so the
// subtitles can keep clear of the picture's clickable objects.

import { create } from "zustand";
import type { Frame } from "./cover";

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface LayoutState {
  frame: Frame | null;
  vp: { w: number; h: number };
  /** viewport rects of the cutouts the learner can currently click, by object id */
  rects: Record<string, Rect>;
  setFrame(frame: Frame, vp: { w: number; h: number }): void;
  setRect(id: string, rect: Rect | null): void;
}

export const useLayout = create<LayoutState>((set) => ({
  frame: null,
  vp: { w: 0, h: 0 },
  rects: {},
  setFrame: (frame, vp) => set({ frame, vp }),
  setRect: (id, rect) =>
    set((s) => {
      const cur = s.rects[id];
      if (!rect) {
        if (!cur) return s;
        const rects = { ...s.rects };
        delete rects[id];
        return { rects };
      }
      if (cur && Math.abs(cur.left - rect.left) < 0.5 && Math.abs(cur.top - rect.top) < 0.5 && Math.abs(cur.right - rect.right) < 0.5 && Math.abs(cur.bottom - rect.bottom) < 0.5) return s;
      return { rects: { ...s.rects, [id]: rect } };
    }),
}));

/**
 * The widest-enough horizontal span of a band that no object occupies, preferring
 * the one nearest the centre. Null means "nothing fits": the caller centres as usual.
 */
export function freeSpan(rects: Rect[], band: { top: number; bottom: number }, vw: number, minWidth: number, margin: number, wantWidth = minWidth): { centre: number; width: number } | null {
  const blocked = rects
    .filter((r) => r.bottom > band.top && r.top < band.bottom)
    .map((r) => [r.left - 16, r.right + 16] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  if (!blocked.length) return null;
  const spans: { left: number; right: number }[] = [];
  let cursor = margin;
  for (const [l, r] of blocked) {
    if (l > cursor) spans.push({ left: cursor, right: Math.min(l, vw - margin) });
    cursor = Math.max(cursor, r);
  }
  if (cursor < vw - margin) spans.push({ left: cursor, right: vw - margin });
  const centre = vw / 2;
  const fits = spans.filter((s) => s.right - s.left >= minWidth);
  if (!fits.length) return null;
  const dist = (s: { left: number; right: number }) => (centre >= s.left && centre <= s.right ? 0 : Math.min(Math.abs(s.left - centre), Math.abs(s.right - centre)));
  fits.sort((a, b) => dist(a) - dist(b) || b.right - b.left - (a.right - a.left));
  // Stay as close to the middle of the screen as the span allows.
  const best = fits[0];
  // Wide enough for prose when the span allows it, even if that means sitting off-centre.
  const width = Math.min(wantWidth, best.right - best.left);
  const c = Math.max(best.left + width / 2, Math.min(best.right - width / 2, centre));
  return { centre: c, width };
}
