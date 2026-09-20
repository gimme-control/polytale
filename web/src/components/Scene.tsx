// The scene: one painting, full-bleed behind everything else. `lib/cover.ts` fits it
// so the character you are talking to is always in frame, and the insets keep them
// clear of the column of text the play view stacks over the lower part of the screen.
//
// The painting itself never changes. What changes is a handful of small cutouts laid
// over it — the character's face, and anything that visibly happened — each one
// positioned by a rectangle given in fractions of the painting. Because the rest of
// the picture is not redrawn, nothing in it can drift between turns. A new set of
// cutouts is only swapped in once every one of them has loaded, so the scene never
// flashes and never shows half a change.

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { fitScene, safeBox, type Frame } from "../lib/cover";
import { useElementSize } from "../lib/hooks";
import type { SceneView } from "../lib/types";
import { useGame } from "../store";

/** How much of a narrow screen the dialogue column needs beneath the painting. */
const PHONE_TEXT_SPACE = 300;

/** Long enough to read as a dissolve rather than a cut; matches `.slow-fade-in`. */
const CROSSFADE_MS = 700;

interface Patch {
  id: string;
  src: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Layers {
  key: string;
  patches: Patch[];
}

/** Settles once the image can be drawn — or has failed, which is also done waiting. */
function preload(src: string): Promise<void> {
  return new Promise((done) => {
    const img = new Image();
    img.onload = () => done();
    img.onerror = () => done();
    img.src = src;
  });
}

function Cutouts({ layers, className }: { layers: Layers; className?: string }) {
  return (
    <div className={`pointer-events-none absolute inset-0 ${className ?? ""}`} data-frame={layers.key} aria-hidden>
      {layers.patches.map((p) => (
        <img
          key={p.id}
          src={p.src}
          alt=""
          draggable={false}
          className="absolute select-none"
          style={{
            left: `${p.left * 100}%`,
            top: `${p.top * 100}%`,
            width: `${p.width * 100}%`,
            height: `${p.height * 100}%`,
          }}
        />
      ))}
    </div>
  );
}

export function Scene({ scene, topInset = 0 }: { scene: SceneView; topInset?: number }) {
  const [rootRef, vp] = useElementSize<HTMLDivElement>();
  const [natural, setNatural] = useState({ w: 16, h: 9 });
  const [failed, setFailed] = useState(false);

  const living = useGame((s) => s.frame);
  const journeyId = useGame((s) => s.journeyId);
  const token = useGame((s) => s.token);
  const shownRef = useRef<Layers | null>(null);
  const [shown, setShown] = useState<Layers | null>(null);
  const [leaving, setLeaving] = useState<Layers | null>(null);

  const frame: Frame = useMemo(() => {
    const phone = vp.w < 640;
    return fitScene(vp.w, vp.h, natural.w, natural.h, safeBox(scene), {
      top: phone ? topInset : 0,
      bottom: phone ? PHONE_TEXT_SPACE : 0,
    });
  }, [vp.w, vp.h, natural.w, natural.h, scene, topInset]);

  // Load every cutout of the new frame before showing any of it: a half-arrived change
  // would read as a glitch, and the previous one is still perfectly good to look at.
  useEffect(() => {
    if (!journeyId || !token) return;
    let cancelled = false;
    const key = living?.key ?? "";
    const patches: Patch[] = (living?.layers ?? []).map((l) => ({
      id: l.id,
      src: api.frameSrc(journeyId, token, l.id, l.url),
      left: l.left,
      top: l.top,
      width: l.width,
      height: l.height,
    }));
    void Promise.all(patches.map((p) => preload(p.src))).then(() => {
      if (cancelled || shownRef.current?.key === key) return;
      setLeaving(shownRef.current);
      shownRef.current = patches.length ? { key, patches } : null;
      setShown(shownRef.current);
    });
    return () => {
      cancelled = true;
    };
  }, [living, journeyId, token]);

  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(() => setLeaving(null), CROSSFADE_MS);
    return () => window.clearTimeout(timer);
  }, [leaving]);

  return (
    <div
      ref={rootRef}
      className="absolute inset-0 isolate overflow-hidden bg-night"
      data-testid="scene"
      data-expression={living?.expression ?? "neutral"}
    >
      {/* When the picture cannot fill the screen, a dimmed blur of itself does. */}
      {(frame.letterboxed || frame.pillarboxed) && !failed && (
        <img src={scene.background_url} alt="" aria-hidden className="absolute inset-0 h-full w-full scale-110 object-cover opacity-40 blur-3xl" />
      )}
      <div
        data-testid="scene-frame"
        data-anchor={`${scene.npc.anchor.x},${scene.npc.anchor.y}`}
        data-letterboxed={frame.letterboxed ? "1" : "0"}
        className="absolute bg-[#141515]"
        style={{
          left: frame.left,
          top: frame.top,
          width: frame.width,
          height: frame.height,
          maskImage: frame.letterboxed
            ? `linear-gradient(to bottom, ${frame.top > 0 ? "transparent, black 7%" : "black"}, black 86%, transparent)`
            : frame.pillarboxed
              ? "linear-gradient(to right, transparent, black 6%, black 94%, transparent)"
              : undefined,
        }}
      >
        <img
          src={scene.background_url}
          alt=""
          draggable={false}
          data-bg="active"
          onLoad={(e) => {
            setFailed(false);
            setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight });
          }}
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full select-none transition-opacity duration-700 ease-out"
          style={{ opacity: failed ? 0 : 1 }}
        />
        {!failed && leaving && <Cutouts layers={leaving} className={shown ? undefined : "frame-out"} />}
        {!failed && shown && <Cutouts key={shown.key} layers={shown} className="slow-fade-in" />}
      </div>

      {/* Scrims: the only gradients in the product. They keep type legible over any art. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-black/60 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[62%] bg-gradient-to-t from-[#080909] from-[8%] via-[#080909]/75 via-[45%] to-transparent" />
    </div>
  );
}
