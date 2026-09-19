// One transform for the background AND the object layer.
//
// The background is cover-fit to the viewport, except that the scene's "safe box"
// (the character plus every position an object can take) must stay in frame. On a
// wide window that is ordinary object-cover with a focal point. On a tall phone,
// plain cover would crop the shelves away, so the scale is capped at the one where
// the safe box spans the viewport width; the picture then sits in the upper part of
// the screen and the dialogue lives beneath it.

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
export function safeBox(scene: SceneView, aspect: number): Box {
  const a = scene.npc.anchor;
  const box: Box = { x0: a.x - 0.14, x1: a.x + 0.14, y0: a.y - 0.24, y1: a.y + 0.2 };
  for (const o of scene.objects) {
    for (const p of Object.values(o.positions)) {
      // Cutouts are roughly as wide as they are tall at most; h is a fraction of the
      // background HEIGHT, so convert to a width fraction through the aspect.
      const halfW = (p.h * 0.5) / aspect;
      box.x0 = Math.min(box.x0, p.x - halfW);
      box.x1 = Math.max(box.x1, p.x + halfW);
      box.y0 = Math.min(box.y0, p.y - p.h);
      box.y1 = Math.max(box.y1, p.y);
    }
  }
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
