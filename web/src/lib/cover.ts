// How the scene painting is fitted to the viewport.
//
// The background is cover-fit, except that the scene's "safe box" (the character the
// learner is talking to, with room around them) must stay in frame. On a wide window
// that is ordinary object-cover with a focal point. On a tall phone, plain cover
// would push the character off the top, so the scale is capped at the one where the
// safe box still fits; the picture then sits in the upper part of the screen and the
// dialogue lives beneath it.

import type { SceneView } from "./types";

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Frame {
  left: number;
  top: number;
  width: number;
  height: number;
  /** the picture does not reach the bottom of the viewport */
  letterboxed: boolean;
  /** the picture does not reach the sides of the viewport */
  pillarboxed: boolean;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Everything that must stay visible, as fractions of the background. */
export function safeBox(scene: SceneView): Box {
  const a = scene.npc.anchor;
  // The anchor is the character's mouth: keep their head, shoulders and some room.
  const box: Box = { x0: a.x - 0.26, x1: a.x + 0.26, y0: a.y - 0.3, y1: a.y + 0.3 };
  const pad = 0.025;
  return {
    x0: clamp(box.x0 - pad, 0, 1),
    x1: clamp(box.x1 + pad, 0, 1),
    y0: clamp(box.y0 - pad, 0, 1),
    y1: clamp(box.y1 + pad, 0, 1),
  };
}

export function fitScene(
  vw: number,
  vh: number,
  bw: number,
  bh: number,
  safe: Box,
  insets: { top: number; bottom: number },
): Frame {
  if (vw <= 0 || vh <= 0 || bw <= 0 || bh <= 0) return { left: 0, top: 0, width: vw, height: vh, letterboxed: false, pillarboxed: false };
  const cover = Math.max(vw / bw, vh / bh);
  const safeW = Math.max(0.05, safe.x1 - safe.x0) * bw;
  const safeH = Math.max(0.05, safe.y1 - safe.y0) * bh;
  // Never larger than cover; smaller only as far as the safe box needs, and never
  // smaller than contain (an ultra-wide window pillarboxes rather than lose the counter).
  const contain = Math.min(vw / bw, vh / bh);
  const scale = Math.max(contain, Math.min(cover, vw / safeW, vh / safeH));
  const width = bw * scale;
  const height = bh * scale;

  const cx = ((safe.x0 + safe.x1) / 2) * width;
  const left = width <= vw ? (vw - width) / 2 : clamp(vw / 2 - cx, vw - width, 0);

  let top: number;
  const letterboxed = height < vh - 1;
  if (letterboxed) {
    // Sit below the top chrome when there is room to spare beneath for the dialogue.
    const free = vh - height;
    top = clamp(free - insets.bottom, 0, insets.top);
  } else {
    const cy = ((safe.y0 + safe.y1) / 2) * height;
    top = clamp(vh / 2 - cy, vh - height, 0);
  }
  return { left, top, width, height, letterboxed, pillarboxed: width < vw - 1 };
}
