// One transform for the background AND the object layer.
//
// The scene frame is a fixed 16:9 box laid out by CSS. Inside it sits one "plane" that
// holds both the painting and the cutouts. The plane is the painting cover-fit to the
// frame, centred on the character; cutouts are placed in percentages of the plane, so
// they stay registered to the painting at every size with no pixel maths and no
// measuring. For 16:9 art (the authored size) the plane is simply the frame.

export const FRAME_ASPECT = 16 / 9;

export interface Plane {
  /** percentages of the frame */
  left: number;
  top: number;
  width: number;
  height: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function coverPlane(naturalAspect: number, anchor: { x: number; y: number }): Plane {
  const a = Number.isFinite(naturalAspect) && naturalAspect > 0 ? naturalAspect : FRAME_ASPECT;
  if (Math.abs(a - FRAME_ASPECT) < 0.005) return { left: 0, top: 0, width: 100, height: 100 };
  if (a > FRAME_ASPECT) {
    // Wider than the frame: full height, cropped at the sides around the character.
    const width = (a / FRAME_ASPECT) * 100;
    return { left: clamp(50 - anchor.x * width, 100 - width, 0), top: 0, width, height: 100 };
  }
  const height = (FRAME_ASPECT / a) * 100;
  return { left: 0, top: clamp(50 - anchor.y * height, 100 - height, 0), width: 100, height };
}
