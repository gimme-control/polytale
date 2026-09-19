// The scene: a full-bleed background with the clickable cutouts composited over it.
// ONE frame (lib/cover.ts) positions both, so objects stay registered to the
// painting at every aspect ratio. Moods crossfade between preloaded backgrounds.
// Objects are things you DO something with: a click opens their verbs.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useGame } from "../store";
import { fitScene, safeBox, type Frame } from "../lib/cover";
import { useDismiss, useElementSize } from "../lib/hooks";
import { useLayout } from "../lib/layout";
import type { SceneObject, SceneView } from "../lib/types";

const HELD = new Set(["inventory", "wallet"]);

/** What the player carries: whatever is in the inventory zone, plus things that only exist there. */
export function inventoryOf(scene: SceneView, zones: Record<string, string>): SceneObject[] {
  return scene.objects.filter((o) => HELD.has(zones[o.id]) || !o.positions.display);
}

/** Where the inventory tray sits, by viewport width. The input bar leaves room for it. */
export function trayBox(vw: number, slots = 1) {
  const phone = vw < 640;
  const w = phone ? 50 : 70;
  return { left: phone ? 12 : 24, bottom: phone ? 12 : 24, w, h: phone ? 48 : 60, width: w * Math.max(1, slots) };
}

interface Placed {
  left: number;
  top: number;
  height: number;
  opacity: number;
  live: boolean;
  fadeDelay: number;
}

export function Scene({ scene }: { scene: SceneView }) {
  const zones = useGame((s) => s.zones);
  const mood = useGame((s) => s.mood);
  const hasHud = useGame((s) => !!s.game);
  const [rootRef, vp] = useElementSize<HTMLDivElement>();
  const [natural, setNatural] = useState({ w: 16, h: 9 });
  const [failed, setFailed] = useState<Record<string, true>>({});
  const [menuFor, setMenuFor] = useState<string | null>(null);

  const frame: Frame = useMemo(() => {
    const phone = vp.w < 640;
    return fitScene(vp.w, vp.h, natural.w, natural.h, safeBox(scene, natural.w / natural.h), {
      top: phone ? 74 + (hasHud ? 30 : 0) + scene.goals.length * 24 : 0,
      bottom: phone ? 300 : 0,
    });
  }, [vp.w, vp.h, natural.w, natural.h, scene, hasHud]);

  const setFrame = useLayout((s) => s.setFrame);
  useLayoutEffect(() => setFrame(frame, vp), [frame, vp, setFrame]);

  const layers = useMemo(() => {
    const urls = [scene.background_url, ...Object.values(scene.mood_urls)];
    return [...new Set(urls)].filter(Boolean);
  }, [scene]);
  const wanted = scene.mood_urls[mood] ?? scene.background_url;
  const active = failed[wanted] ? scene.background_url : wanted;
  const bgMissing = !!failed[scene.background_url];

  const held = inventoryOf(scene, zones);
  const tray = trayBox(vp.w, held.length);
  const closeMenu = useCallback(() => setMenuFor(null), []);

  return (
    <div ref={rootRef} className="absolute inset-0 isolate overflow-hidden bg-night" data-testid="scene" data-mood={mood}>
      {/* When the picture cannot fill the screen, a dimmed blur of itself does. */}
      {(frame.letterboxed || frame.pillarboxed) && !bgMissing && (
        <img src={active} alt="" aria-hidden className="absolute inset-0 h-full w-full scale-110 object-cover opacity-40 blur-3xl" />
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
        {layers.map((url) => (
          <img
            key={url}
            src={url}
            alt=""
            draggable={false}
            data-bg={url === active ? "active" : "idle"}
            onLoad={(e) => {
              if (url === scene.background_url) setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight });
            }}
            onError={() => setFailed((f) => ({ ...f, [url]: true }))}
            className="absolute inset-0 h-full w-full select-none transition-opacity duration-700 ease-out"
            style={{ opacity: url === active && !failed[url] ? 1 : 0 }}
          />
        ))}
      </div>

      {/* Scrims: the only gradients in the product. They keep type legible over any art. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-black/60 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[62%] bg-gradient-to-t from-[#080909] from-[8%] via-[#080909]/75 via-[45%] to-transparent" />

      {held.length > 0 && (
        <div
          data-testid="inventory-tray"
          aria-label="What you carry"
          className="absolute rounded-[10px] border border-hair bg-black/30"
          style={{ left: tray.left, bottom: tray.bottom, width: tray.width, height: tray.h }}
        />
      )}

      <div className="pointer-events-none absolute" style={{ left: frame.left, top: frame.top, width: frame.width, height: frame.height }} data-testid="object-layer">
        {scene.objects.map((o, i) => (
          <Cutout
            key={o.id}
            object={o}
            index={i}
            zone={zones[o.id]}
            frame={frame}
            vp={vp}
            slot={held.findIndex((w) => w.id === o.id)}
            slots={held.length}
            menuOpen={menuFor === o.id}
            onMenu={setMenuFor}
            onCloseMenu={closeMenu}
          />
        ))}
      </div>
    </div>
  );
}

function Cutout({
  object,
  index,
  zone,
  frame,
  vp,
  slot,
  slots,
  menuOpen,
  onMenu,
  onCloseMenu,
}: {
  object: SceneObject;
  index: number;
  zone: string | undefined;
  frame: Frame;
  vp: { w: number; h: number };
  slot: number;
  slots: number;
  menuOpen: boolean;
  onMenu: (id: string | null) => void;
  onCloseMenu: () => void;
}) {
  const phase = useGame((s) => s.phase);
  const complete = useGame((s) => s.sceneComplete);
  const tapObject = useGame((s) => s.tapObject);
  const symbol = useGame((s) => s.language?.currency_symbol ?? "");
  const price = useGame((s) => s.game?.prices[object.id] ?? object.price);
  const lit = useGame((s) => {
    if (s.helpGlow && s.help?.highlight_object_ids.includes(object.id)) return true;
    if (!s.speakingLineId) return false;
    for (let i = s.transcript.length - 1; i >= 0; i--) {
      const e = s.transcript[i];
      if (e.kind === "npc" && e.line.line_id === s.speakingLineId) return e.line.highlight_object_ids.includes(object.id);
    }
    return false;
  });
  const setRect = useLayout((s) => s.setRect);
  const [broken, setBroken] = useState(false);
  const [aspect, setAspect] = useState(0.75);
  const [arc, setArc] = useState(0);
  const last = useRef<Placed | null>(null);
  const prevZone = useRef(zone);
  const button = useRef<HTMLButtonElement | null>(null);

  // A price that changes (haggling) shows the old one struck through for a moment.
  const prevPrice = useRef(price);
  const [was, setWas] = useState<number | null>(null);
  useEffect(() => {
    if (prevPrice.current != null && price != null && prevPrice.current !== price) {
      setWas(prevPrice.current);
      const t = window.setTimeout(() => setWas(null), 4200);
      prevPrice.current = price;
      return () => window.clearTimeout(t);
    }
    prevPrice.current = price;
  }, [price]);

  useEffect(() => setBroken(false), [object.art_url]);
  useLayoutEffect(() => {
    if (prevZone.current !== zone) {
      prevZone.current = zone;
      setArc((n) => n + 1);
    }
  }, [zone]);

  const carried = slot >= 0 && (HELD.has(zone ?? "") || !object.positions[zone ?? ""]) && zone !== "npc" && zone !== "gone";
  const placed: Placed | null = (() => {
    const pos = zone ? object.positions[zone] : undefined;
    if (carried) {
      const t = trayBox(vp.w, slots);
      const pad = 9;
      return { left: t.left + t.w * slot + t.w / 2 - frame.left, top: vp.h - t.bottom - pad - frame.top, height: t.h - pad * 2, opacity: 1, live: true, fadeDelay: 0 };
    }
    if (pos) {
      const handed = zone === "npc";
      return { left: pos.x * frame.width, top: pos.y * frame.height, height: pos.h * frame.height, opacity: handed ? 0 : 1, live: !handed, fadeDelay: handed ? 620 : 0 };
    }
    // `gone`, or a zone this object has no position for: fade out where it stood.
    return last.current ? { ...last.current, opacity: 0, live: false, fadeDelay: 0 } : null;
  })();
  if (placed?.live) last.current = placed;

  // Tell the dialogue where this object will rest (its target, not its mid-slide spot).
  const live = !!placed?.live && !carried;
  const rectKey = live && placed ? `${placed.left + frame.left}|${placed.top + frame.top}|${placed.height}|${aspect}` : "";
  useLayoutEffect(() => {
    if (!rectKey) {
      setRect(object.id, null);
      return;
    }
    const [cx, bottom, h, a] = rectKey.split("|").map(Number);
    setRect(object.id, { left: cx - (h * a) / 2, right: cx + (h * a) / 2, top: bottom - h, bottom });
  }, [rectKey, object.id, setRect]);
  useEffect(() => () => setRect(object.id, null), [object.id, setRect]);

  if (!placed || frame.width <= 0) return null;

  const busy = phase === "waiting" || phase === "listening" || phase === "transcribing" || phase === "preview";
  const enabled = placed.live && !busy && !complete;
  const actions = object.actions ?? [];
  const onClick = () => {
    if (actions.length > 1) onMenu(menuOpen ? null : object.id);
    else void tapObject(object.id, actions[0]?.id);
  };
  const showPrice = price != null && !carried;

  return (
    <>
      <button
        ref={button}
        type="button"
        data-testid={`object-${object.id}`}
        data-object={object.id}
        data-zone={zone}
        data-carried={carried ? "1" : "0"}
        data-pos={zone && object.positions[zone] ? `${object.positions[zone].x},${object.positions[zone].y},${object.positions[zone].h}` : ""}
        data-lit={lit ? "1" : "0"}
        aria-label={`Object ${index + 1}`}
        aria-haspopup={actions.length > 1 ? "menu" : undefined}
        aria-expanded={actions.length > 1 ? menuOpen : undefined}
        disabled={!enabled}
        onClick={onClick}
        className={`cutout group absolute block -translate-x-1/2 -translate-y-full border-0 bg-transparent p-0 outline-offset-4 ${
          placed.live ? "pointer-events-auto" : "pointer-events-none"
        } ${lit ? "cutout-lit" : ""}`}
        style={{
          left: placed.left,
          top: placed.top,
          height: placed.height,
          opacity: placed.opacity,
          transitionDelay: placed.fadeDelay ? `0ms, 0ms, 0ms, ${placed.fadeDelay}ms` : undefined,
          zIndex: Math.round(placed.top),
        }}
      >
        <span key={arc} className={`block h-full ${arc > 0 ? "cutout-arc" : ""}`}>
          {broken ? (
            <span className="cutout-img block aspect-[3/4] h-full rounded-[6px] border border-hair-2 bg-[#2a2b2b]" />
          ) : (
            <img
              src={object.art_url}
              alt=""
              draggable={false}
              onLoad={(e) => setAspect(e.currentTarget.naturalWidth / Math.max(1, e.currentTarget.naturalHeight))}
              onError={() => setBroken(true)}
              className="cutout-img block h-full w-auto max-w-none select-none"
            />
          )}
        </span>
        {showPrice && (
          <span
            data-testid={`price-${object.id}`}
            data-changed={was != null ? "1" : "0"}
            className={`pointer-events-none absolute -top-2 left-full ml-1.5 flex items-baseline gap-1.5 whitespace-nowrap rounded-[5px] border border-hair-2 bg-glass px-1.5 py-0.5 text-[12px] font-medium tabular-nums text-ink backdrop-blur-sm transition-opacity duration-200 ${
              lit || was != null || menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"
            }`}
          >
            {was != null && (
              <s className="fade-in font-normal text-ink-3 decoration-ink-3">
                {symbol}
                {was}
              </s>
            )}
            <span key={price} className={was != null ? "rise-in text-jade" : ""}>
              {symbol}
              {price}
            </span>
          </span>
        )}
      </button>
      {menuOpen && enabled && (
        <VerbMenu
          object={object}
          x={placed.left}
          top={placed.top - placed.height}
          bottom={placed.top}
          frame={frame}
          vp={vp}
          onClose={() => {
            onCloseMenu();
            button.current?.focus();
          }}
        />
      )}
    </>
  );
}

/** The verbs of one object, anchored to it. Arrow keys move, Enter acts, Esc closes. */
function VerbMenu({ object, x, top, bottom, frame, vp, onClose }: { object: SceneObject; x: number; top: number; bottom: number; frame: Frame; vp: { w: number; h: number }; onClose: () => void }) {
  const tapObject = useGame((s) => s.tapObject);
  const ref = useDismiss(true, onClose);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    if (ref.current) setWidth(ref.current.offsetWidth);
  }, [ref]);
  // Focus once it is visible (a hidden element cannot take focus).
  useEffect(() => {
    if (width) ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [width, ref]);

  // Above the object when there is room, otherwise below; never off the screen.
  const above = top + frame.top > 120;
  const cx = Math.max(8 + width / 2 - frame.left, Math.min(vp.w - 8 - width / 2 - frame.left, x));
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
    items[(i + step + items.length) % items.length]?.focus();
  };

  return (
    <div
      ref={ref}
      role="menu"
      data-testid="verb-menu"
      data-for={object.id}
      onKeyDown={onKey}
      className="fade-in pointer-events-auto absolute flex items-center gap-0.5 rounded-[10px] border border-hair-2 bg-[#0e0f0f]/92 p-1 backdrop-blur-xl"
      style={{ left: cx, top: above ? top - 10 : bottom + 10, translate: `-50% ${above ? "-100%" : "0"}`, zIndex: 5000, visibility: width ? "visible" : "hidden" }}
    >
      {(object.actions ?? []).map((a) => (
        <button
          key={a.id}
          type="button"
          role="menuitem"
          data-testid={`verb-${a.id}`}
          onClick={() => {
            onClose();
            void tapObject(object.id, a.id);
          }}
          className="h-8 rounded-[7px] border-0 bg-transparent px-3 text-[13px] font-medium text-ink-2 transition-colors duration-150 hover:bg-white/[0.08] hover:text-ink focus-visible:bg-white/[0.08] focus-visible:text-ink"
        >
          {a.label}
        </button>
      ))}
    </div>
  );
}
