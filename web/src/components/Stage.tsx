// The stage: painted plate (crossfading variants), the engineer sprite at her
// authored feet position, the focused object floating near her raised hand, fixture
// hotspot flashes, give-flights into the inventory tray, and the launch moment.

import { useEffect, useMemo, useRef, useState } from "react";
import { useGame, type Flight } from "../store";
import { resolveArt, useElementSize } from "../lib/hooks";
import { ArtImage, KeyIcon, MapIcon, preloadImage, useImageStatus } from "./Art";
import type { CartridgeView, Focus } from "../lib/types";

const DEFAULT_ASPECT = 16 / 9;
const PLACEHOLDER_SPRITE_ASPECT = 200 / 420;
/**
 * Where a held object floats, as a fraction of the sprite box (origin top-left).
 * The authored engineer faces left with her hand raised palm-up at about (0.14, 0.17);
 * the placeholder silhouette's raised hand is at (0.18, 0.23). An authored
 * `stage.hand` (same units) overrides the real-art default.
 */
const HAND_REAL = { x: 0.14, y: 0.17 };
const HAND_PLACEHOLDER = { x: 0.18, y: 0.2 };

interface Layer {
  url: string | undefined;
  key: number;
}

/** The horizontal point of the plate kept centred when the frame crops its sides. */
const FOCAL_X = 0.56;

export function Stage({ compact = false, crop = 1.45, focalX = FOCAL_X }: { compact?: boolean; crop?: number; focalX?: number }) {
  const world = useGame((s) => s.world);
  const cartridge = useGame((s) => s.cartridge);
  const launchAt = useGame((s) => s.launchAt);
  const fixtureFlash = useGame((s) => s.fixtureFlash);
  const [containerRef, box] = useElementSize<HTMLDivElement>();
  const [aspect, setAspect] = useState(DEFAULT_ASPECT);
  const [sprites, setSprites] = useState<Record<string, number>>({});

  const plateUrl = resolveArt(world?.plate_url ?? cartridge?.location.plate_url);
  const [layers, setLayers] = useState<Layer[]>(() => [{ url: plateUrl, key: 0 }]);
  useEffect(() => {
    let live = true;
    // Load the new variant fully before crossfading, so the fade is image-to-image.
    void preloadImage(plateUrl).then(() => {
      if (!live) return;
      setLayers((ls) => {
        if (ls[ls.length - 1]?.url === plateUrl) return ls;
        return [...ls.slice(-1), { url: plateUrl, key: (ls[ls.length - 1]?.key ?? 0) + 1 }];
      });
    });
    return () => {
      live = false;
    };
  }, [plateUrl]);
  // Warm every authored variant up front (they're large paintings).
  useEffect(() => {
    if (!cartridge) return;
    for (const v of ["plate_panel_open", "plate_launched"]) {
      const base = cartridge.location.plate_url;
      if (base) void preloadImage(resolveArt(base.replace(/plate_[a-z_]+(\.\w+)$/, `${v}$1`)));
    }
  }, [cartridge]);
  useEffect(() => {
    if (layers.length < 2) return;
    const t = window.setTimeout(() => setLayers((ls) => ls.slice(-1)), 1600);
    return () => window.clearTimeout(t);
  }, [layers]);

  // Contain-fit the plate so authored fractional coordinates map exactly.
  const fit = useMemo(() => {
    const { w, h } = box;
    if (!w || !h) return { w: 0, h: 0, x: 0, y: 0 };
    let pw = w;
    let ph = w / aspect;
    if (ph > h) {
      ph = h;
      pw = h * aspect;
    }
    // Fill the frame (cover) up to a crop limit; beyond it, letterbox. When cropping
    // sideways, keep the window centred on the action (the engineer stands right of
    // centre), clamped to the plate edges so nothing outside the painting shows.
    const cover = Math.max(w / pw, h / ph);
    const k = Math.min(cover, crop);
    pw *= k;
    ph *= k;
    const x = pw > w ? Math.min(0, Math.max(w - pw, w / 2 - focalX * pw)) : (w - pw) / 2;
    const y = (h - ph) / 2;
    return { w: pw, h: ph, x, y };
  }, [box, aspect, crop, focalX]);

  const launched = launchAt != null || Object.values(world?.fixtures ?? {}).includes("launched");
  const now = performance.now();

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden bg-night" data-testid="stage">
      {/* Ambient backdrop: the same plate, blurred, fills the letterbox. */}
      <div className="absolute inset-0 scale-110 opacity-60 blur-2xl saturate-150">
        <ArtImage src={layers[layers.length - 1]?.url} kind="plate" alt="" className="h-full w-full object-cover" />
      </div>
      <div className="absolute inset-0 bg-gradient-to-b from-ink/50 via-transparent to-ink/70" />

      {fit.w > 0 && (
        <div
          className="absolute overflow-hidden rounded-[6px] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8)] ring-1 ring-white/5"
          style={{ left: fit.x, top: fit.y, width: fit.w, height: fit.h }}
          data-testid="plate-box"
        >
          <div
            className="absolute inset-0 origin-[45%_40%]"
            style={launched ? { animation: "camera-drift 11s cubic-bezier(0.25,0.6,0.2,1) forwards" } : undefined}
          >
            {layers.map((l, i) => (
              <div
                key={l.key}
                className="absolute inset-0"
                style={i > 0 || layers.length === 1 ? { animation: l.key === 0 ? undefined : "fade-in 1.4s ease both" } : undefined}
                data-plate-url={l.url}
              >
                <ArtImage
                  src={l.url}
                  kind="plate"
                  alt={cartridge?.location.name ?? "The airfield"}
                  className="h-full w-full object-cover"
                  onLoadSize={(w, h) => w && h && setAspect(w / h)}
                />
              </div>
            ))}

            {cartridge?.fixtures.map((fx) => {
              const at = fixtureFlash[fx.id];
              // The launch has its own moment; its hotspot moves with the ship.
              if (!at || now - at > 2600 || world?.fixtures[fx.id] === "launched") return null;
              const d = fx.hotspot.r * 2 * fit.h; // r is a fraction of plate height
              return (
                <div
                  key={`${fx.id}-${at}`}
                  className="pointer-events-none absolute rounded-full"
                  style={{
                    left: fx.hotspot.x * fit.w,
                    top: fx.hotspot.y * fit.h,
                    width: d,
                    height: d,
                    background: "radial-gradient(circle, rgba(255,214,150,0.55), rgba(255,214,150,0) 65%)",
                    boxShadow: "0 0 0 2px rgba(246,205,131,0.55)",
                    animation: "hotspot-flash 2.4s ease-out forwards",
                  }}
                  data-flash={fx.id}
                />
              );
            })}

            {cartridge?.npcs.map((npc) => (
              <NpcSprite
                key={npc.id}
                npc={npc}
                plateW={fit.w}
                plateH={fit.h}
                onAspect={(a) => setSprites((m) => (m[npc.id] === a ? m : { ...m, [npc.id]: a }))}
              />
            ))}

            {world?.focus && cartridge && (
              <FocusObject focus={world.focus} cartridge={cartridge} plateW={fit.w} plateH={fit.h} compact={compact} spriteAspects={sprites} />
            )}
          </div>

          {launched && <LaunchLight />}
          <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_120px_rgba(0,0,0,0.45)]" />
        </div>
      )}
      <Flights />
    </div>
  );
}

/* ------------------------------------------------------------------ NPC sprite */

type Npc = CartridgeView["npcs"][number];

function spriteBox(npc: Npc, plateW: number, plateH: number, aspect: number) {
  const h = npc.stage.height * plateH;
  const w = h * aspect;
  return { left: npc.stage.x * plateW, bottom: plateH - npc.stage.y * plateH, w, h };
}

function NpcSprite({ npc, plateW, plateH, onAspect }: { npc: Npc; plateW: number; plateH: number; onAspect: (a: number) => void }) {
  const speakingId = useGame((s) => s.speakingLineId);
  const transcript = useGame((s) => s.transcript);
  const src = resolveArt(npc.sprite_url);
  const status = useImageStatus(src);
  const [aspect, setAspect] = useState(PLACEHOLDER_SPRITE_ASPECT);
  const speaking = useMemo(() => {
    if (!speakingId) return false;
    for (let i = transcript.length - 1; i >= 0; i--) {
      const e = transcript[i];
      if (e.kind === "npc" && e.line.line_id === speakingId) return e.line.speaker === npc.id;
    }
    return true; // help replays aren't in the transcript; there's one speaker
  }, [speakingId, transcript, npc.id]);
  const b = spriteBox(npc, plateW, plateH, status === "ok" ? aspect : PLACEHOLDER_SPRITE_ASPECT);
  return (
    <div
      className="pointer-events-none absolute"
      style={{
        left: b.left,
        bottom: b.bottom,
        width: b.w,
        height: b.h,
        transform: "translate(-50%, 0)",
        animation: speaking ? "speak-bob 0.9s ease-in-out infinite" : undefined,
        filter: speaking
          ? "drop-shadow(0 0 18px rgba(246,205,131,0.45)) drop-shadow(0 12px 18px rgba(0,0,0,0.45))"
          : "drop-shadow(0 12px 18px rgba(0,0,0,0.5))",
        transition: "filter 0.4s ease",
      }}
      data-npc={npc.id}
      data-speaking={speaking ? "1" : "0"}
    >
      <ArtImage
        src={src}
        kind="sprite"
        alt={npc.name}
        className="h-full w-full object-contain object-bottom"
        onLoadSize={(w, h) => {
          if (!w || !h) return;
          setAspect(w / h);
          onAspect(w / h);
        }}
      />
      {/* Hand anchor: where held objects sit and where gives fly from. */}
      <div
        id={`hand-${npc.id}`}
        className="absolute"
        style={{ left: `${handOf(npc, status === "ok").x * 100}%`, top: `${handOf(npc, status === "ok").y * 100}%`, width: 1, height: 1 }}
      />
    </div>
  );
}

function handOf(npc: Npc, real: boolean) {
  return (real && npc.stage.hand) || (real ? HAND_REAL : HAND_PLACEHOLDER);
}

/* ---------------------------------------------------------------- focus object */

export function ObjectGlyph({ objectId, iconUrl }: { objectId: string; iconUrl?: string }) {
  const src = resolveArt(iconUrl);
  const status = useImageStatus(src);
  if (status === "ok" && src) return <img src={src} alt="" draggable={false} className="h-full w-full object-contain" />;
  return /map/i.test(objectId) ? <MapIcon /> : <KeyIcon />;
}

const GESTURE_ANIM: Record<string, string> = {
  hold_up: "hold-bob 2.8s ease-in-out infinite",
  point: "point-nudge 1.6s ease-in-out infinite",
  offer: "offer-reach 1.1s cubic-bezier(0.2,0.8,0.2,1) forwards",
  withhold: "withhold-pull 0.9s cubic-bezier(0.3,0.7,0.2,1) forwards",
};

function FocusObject({
  focus,
  cartridge,
  plateW,
  plateH,
  compact,
  spriteAspects,
}: {
  focus: Focus;
  cartridge: CartridgeView;
  plateW: number;
  plateH: number;
  compact: boolean;
  spriteAspects: Record<string, number>;
}) {
  const tapObject = useGame((s) => s.tapObject);
  const tapFallback = useGame((s) => s.learning?.tap_fallback ?? false);
  const pulseAt = useGame((s) => s.focusPulseAt);
  const holder = useGame((s) => s.world?.holders[focus.object_id]);
  if (focus.gesture === "put_away") return null;
  const obj = cartridge.objects.find((o) => o.id === focus.object_id);
  const npc = cartridge.npcs.find((n) => n.id === holder) ?? cartridge.npcs[0];
  if (!obj || !npc) return null;
  const real = spriteAspects[npc.id] != null;
  const spriteH = npc.stage.height * plateH;
  const spriteW = spriteH * (spriteAspects[npc.id] ?? PLACEHOLDER_SPRITE_ASPECT);
  const size = Math.max(compact ? 30 : 46, spriteH * 0.17);
  // Floating just above her raised palm.
  const hand = handOf(npc, real);
  const cx = npc.stage.x * plateW - spriteW / 2 + hand.x * spriteW;
  const cy = npc.stage.y * plateH - spriteH + hand.y * spriteH - size * 0.25;
  const withheld = focus.gesture === "withhold";
  return (
    <button
      type="button"
      onClick={() => void tapObject(obj.id)}
      className="group absolute rounded-full outline-none"
      style={{ left: cx - size / 2, top: cy - size / 2, width: size, height: size }}
      aria-label={`${obj.native} ${obj.romanization} — tap to point at it`}
      data-focus={obj.id}
      data-gesture={focus.gesture}
    >
      <div key={focus.gesture} className="relative h-full w-full" style={{ animation: GESTURE_ANIM[focus.gesture] }}>
        <div
          className="absolute -inset-[45%] rounded-full"
          style={{
            background: `radial-gradient(circle, rgba(255,210,140,${withheld ? 0.28 : 0.55}), rgba(255,210,140,0) 62%)`,
            animation: "glow-breathe 2.4s ease-in-out infinite",
          }}
        />
        <div className="relative h-full w-full drop-shadow-[0_6px_10px_rgba(0,0,0,0.6)] transition-transform group-hover:scale-110">
          <ObjectGlyph objectId={obj.id} iconUrl={obj.icon_url} />
        </div>
        {pulseAt > 0 && (
          <span
            key={pulseAt}
            className="pointer-events-none absolute inset-0 rounded-full border-2 border-brass-strong/80"
            style={{ animation: "ping-ring 1.3s ease-out 2 both" }}
          />
        )}
        {(tapFallback || focus.gesture === "point") && (
          <span
            className="pointer-events-none absolute inset-[-18%] rounded-full border border-dashed border-brass/70"
            style={{ animation: "spin 9s linear infinite" }}
          />
        )}
      </div>
    </button>
  );
}

/* --------------------------------------------------------------------- flights */

function Flights() {
  const flights = useGame((s) => s.flights);
  return (
    <>
      {flights.map((f) => (
        <FlightSprite key={f.id} flight={f} />
      ))}
    </>
  );
}

function FlightSprite({ flight }: { flight: Flight }) {
  const ref = useRef<HTMLDivElement>(null);
  const cartridge = useGame((s) => s.cartridge);
  const obj = cartridge?.objects.find((o) => o.id === flight.objectId);
  useEffect(() => {
    const el = ref.current;
    const done = () => useGame.setState((s) => ({ flights: s.flights.filter((x) => x.id !== flight.id) }));
    if (!el) return done();
    const hand = document.getElementById(`hand-${cartridge?.npcs[0]?.id}`)?.getBoundingClientRect();
    const slot = document.querySelector(`[data-inv-slot="${flight.objectId}"]`)?.getBoundingClientRect() ??
      document.getElementById("inventory-tray")?.getBoundingClientRect();
    if (!hand || !slot) return done();
    const from = flight.to === "player" ? { x: hand.left, y: hand.top } : { x: slot.left + slot.width / 2, y: slot.top + slot.height / 2 };
    const to = flight.to === "player" ? { x: slot.left + slot.width / 2, y: slot.top + slot.height / 2 } : { x: hand.left, y: hand.top };
    const mid = { x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - 120 };
    const reduce = document.documentElement.dataset.motion === "reduced" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const anim = el.animate(
      [
        { transform: `translate(${from.x}px, ${from.y}px) translate(-50%,-50%) scale(1.4) rotate(0deg)`, opacity: 0 },
        { transform: `translate(${from.x}px, ${from.y}px) translate(-50%,-50%) scale(1.6) rotate(-8deg)`, opacity: 1, offset: 0.12 },
        { transform: `translate(${mid.x}px, ${mid.y}px) translate(-50%,-50%) scale(1.3) rotate(10deg)`, opacity: 1, offset: 0.55 },
        { transform: `translate(${to.x}px, ${to.y}px) translate(-50%,-50%) scale(0.8) rotate(0deg)`, opacity: 1 },
      ],
      { duration: reduce ? 1 : 1250, easing: "cubic-bezier(0.45, 0, 0.2, 1)", fill: "forwards" },
    );
    anim.onfinish = done;
    return () => anim.cancel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div ref={ref} className="pointer-events-none fixed left-0 top-0 z-50 h-14 w-14" style={{ opacity: 0 }} data-flight={flight.objectId}>
      <div className="absolute -inset-4 rounded-full bg-[radial-gradient(circle,rgba(255,214,150,0.6),transparent_65%)]" />
      <div className="relative h-full w-full drop-shadow-[0_8px_14px_rgba(0,0,0,0.6)]">
        <ObjectGlyph objectId={flight.objectId} iconUrl={obj?.icon_url} />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- launch */

function LaunchLight() {
  const embers = useMemo(
    () =>
      Array.from({ length: 16 }, (_, i) => ({
        left: 8 + ((i * 53) % 84),
        bottom: 6 + ((i * 29) % 30),
        delay: (i % 8) * 0.45,
        size: 3 + (i % 3) * 2,
      })),
    [],
  );
  return (
    <div className="pointer-events-none absolute inset-0" data-testid="launch-light">
      {/* Cinematic letterbox slides in for the launch. */}
      <div className="absolute inset-x-0 top-0 bg-black/85" style={{ height: "7%", animation: "bar-in 1.6s cubic-bezier(0.2,0.7,0.2,1) both" }} />
      <div className="absolute inset-x-0 bottom-0 bg-black/85" style={{ height: "7%", animation: "bar-in-bottom 1.6s cubic-bezier(0.2,0.7,0.2,1) both" }} />
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 70% at 55% -10%, rgba(255,226,170,0.55), rgba(255,200,120,0.18) 40%, transparent 70%)",
          mixBlendMode: "screen",
          animation: "sky-light 5.5s ease-out forwards",
        }}
      />
      {embers.map((e, i) => (
        <span
          key={i}
          className="absolute rounded-full bg-brass-strong"
          style={{
            left: `${e.left}%`,
            bottom: `${e.bottom}%`,
            width: e.size,
            height: e.size,
            boxShadow: "0 0 10px rgba(246,205,131,0.9)",
            animation: `ember 3.6s ease-out ${e.delay}s infinite`,
          }}
        />
      ))}
    </div>
  );
}
