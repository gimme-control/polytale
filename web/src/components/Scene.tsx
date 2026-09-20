// The scene: one painting, full-bleed behind everything else. `lib/cover.ts` fits it
// so the character you are talking to is always in frame, and the insets keep them
// clear of the column of text the play view stacks over the lower part of the screen.

import { useMemo, useState } from "react";
import { fitScene, safeBox, type Frame } from "../lib/cover";
import { useElementSize } from "../lib/hooks";
import type { SceneView } from "../lib/types";

/** How much of a narrow screen the dialogue column needs beneath the painting. */
const PHONE_TEXT_SPACE = 300;

export function Scene({ scene, topInset = 0 }: { scene: SceneView; topInset?: number }) {
  const [rootRef, vp] = useElementSize<HTMLDivElement>();
  const [natural, setNatural] = useState({ w: 16, h: 9 });
  const [failed, setFailed] = useState(false);

  const frame: Frame = useMemo(() => {
    const phone = vp.w < 640;
    return fitScene(vp.w, vp.h, natural.w, natural.h, safeBox(scene), {
      top: phone ? topInset : 0,
      bottom: phone ? PHONE_TEXT_SPACE : 0,
    });
  }, [vp.w, vp.h, natural.w, natural.h, scene, topInset]);

  return (
    <div ref={rootRef} className="absolute inset-0 isolate overflow-hidden bg-night" data-testid="scene">
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
      </div>

      {/* Scrims: the only gradients in the product. They keep type legible over any art. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-black/60 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[62%] bg-gradient-to-t from-[#080909] from-[8%] via-[#080909]/75 via-[45%] to-transparent" />
    </div>
  );
}
