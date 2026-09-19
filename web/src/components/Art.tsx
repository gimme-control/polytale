// Art with painterly fallbacks: every image slot tries its real URL first
// (cartridge art served by the API, or /mock-art in mock mode) and falls back to a
// tasteful SVG placeholder while the generated art doesn't exist yet.

import { useEffect, useState, type CSSProperties } from "react";

type Kind = "plate" | "sprite" | "portrait" | "icon" | "cover";

const loaded = new Map<string, boolean>();

/** Resolve the first candidate URL that loads. Results are memoised per URL. */
export function useImage(src: string | string[] | undefined): { status: "loading" | "ok" | "error"; url?: string } {
  const list = (Array.isArray(src) ? src : src ? [src] : []).filter(Boolean);
  const key = list.join("|");
  const known = list.find((u) => loaded.get(u) === true);
  const allBad = list.length === 0 || list.every((u) => loaded.get(u) === false);
  const [state, setState] = useState<{ key: string; status: "loading" | "ok" | "error"; url?: string }>(() => ({
    key,
    status: known ? "ok" : allBad ? "error" : "loading",
    url: known,
  }));
  useEffect(() => {
    let live = true;
    const hit = list.find((u) => loaded.get(u) === true);
    if (hit) {
      setState({ key, status: "ok", url: hit });
      return;
    }
    if (list.length === 0) {
      setState({ key, status: "error" });
      return;
    }
    setState({ key, status: "loading" });
    const tryAt = (i: number) => {
      if (i >= list.length) return live && setState({ key, status: "error" });
      if (loaded.get(list[i]) === false) return tryAt(i + 1);
      const img = new Image();
      img.onload = () => {
        loaded.set(list[i], true);
        if (live) setState({ key, status: "ok", url: list[i] });
      };
      img.onerror = () => {
        loaded.set(list[i], false);
        tryAt(i + 1);
      };
      img.src = list[i];
    };
    tryAt(0);
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state.key === key ? state : { status: known ? "ok" : "loading", url: known };
}

export function useImageStatus(src: string | undefined): "loading" | "ok" | "error" {
  return useImage(src).status;
}

/** Warm the browser cache for a URL; resolves when loaded or failed. */
export function preloadImage(url: string | undefined): Promise<void> {
  return new Promise((resolve) => {
    if (!url || loaded.has(url)) return resolve();
    const img = new Image();
    img.onload = () => {
      loaded.set(url, true);
      resolve();
    };
    img.onerror = () => {
      loaded.set(url, false);
      resolve();
    };
    img.src = url;
  });
}

export function ArtImage({
  src,
  kind,
  alt,
  className,
  style,
  onLoadSize,
}: {
  src: string | string[] | undefined;
  kind: Kind;
  alt: string;
  className?: string;
  style?: CSSProperties;
  onLoadSize?: (w: number, h: number) => void;
}) {
  const { status, url } = useImage(src);
  if (status === "ok" && url) {
    return (
      <img
        src={url}
        alt={alt}
        draggable={false}
        className={`fade-in ${className ?? ""}`}
        style={style}
        onLoad={(e) => onLoadSize?.(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)}
      />
    );
  }
  const Placeholder = PLACEHOLDERS[kind];
  const first = Array.isArray(src) ? src[0] : src;
  return (
    <div role="img" aria-label={alt} className={className} style={style} data-placeholder={kind}>
      {/* Nothing while loading: a placeholder flash over real art reads as a glitch. */}
      {status === "error" ? <Placeholder src={first ?? ""} /> : null}
    </div>
  );
}

/* ---------------------------------------------------------------- placeholders */

function variantOf(src: string): "base" | "panel_open" | "launched" {
  if (/launch/i.test(src)) return "launched";
  if (/panel_open|open/i.test(src)) return "panel_open";
  return "base";
}

export function PlatePlaceholder({ src }: { src: string }) {
  const v = variantOf(src);
  const launched = v === "launched";
  const open = v !== "base";
  return (
    <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" className="block h-full w-full">
      <defs>
        <linearGradient id="pp-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={launched ? "#26395a" : "#1a2236"} />
          <stop offset="0.55" stopColor={launched ? "#6f7f99" : "#3a3f55"} />
          <stop offset="0.82" stopColor={launched ? "#f1c585" : "#c98a52"} />
          <stop offset="1" stopColor={launched ? "#ffe2ad" : "#e7a865"} />
        </linearGradient>
        <radialGradient id="pp-sun" cx="0.78" cy="0.7" r="0.5">
          <stop offset="0" stopColor="#ffd9a0" stopOpacity={launched ? 0.95 : 0.55} />
          <stop offset="1" stopColor="#ffd9a0" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="pp-env" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#c9b38c" />
          <stop offset="0.6" stopColor="#8a6e4b" />
          <stop offset="1" stopColor="#4c3a28" />
        </linearGradient>
        <linearGradient id="pp-ground" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3a3130" />
          <stop offset="1" stopColor="#141217" />
        </linearGradient>
        <radialGradient id="pp-panel" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#ffd28a" stopOpacity="0.9" />
          <stop offset="1" stopColor="#ffd28a" stopOpacity="0" />
        </radialGradient>
        <filter id="pp-soft" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="18" />
        </filter>
      </defs>
      <rect width="1600" height="900" fill="url(#pp-sky)" />
      <rect width="1600" height="900" fill="url(#pp-sun)" />
      {/* storm clouds */}
      <g fill={launched ? "#e9eef5" : "#2b3044"} opacity={launched ? 0.35 : 0.8} filter="url(#pp-soft)">
        <ellipse cx="260" cy="170" rx="360" ry="90" />
        <ellipse cx="900" cy="120" rx="420" ry="80" />
        <ellipse cx="1420" cy="210" rx="300" ry="70" />
      </g>
      {/* distant hills */}
      <path d="M0 640 C 220 590 380 620 560 600 C 760 575 980 615 1180 590 C 1360 570 1480 600 1600 585 L1600 900 L0 900Z" fill="#2c2733" opacity="0.85" />
      {/* hangar */}
      <path d="M1040 690 L1040 520 Q1180 430 1320 520 L1320 690Z" fill="#231f26" />
      <path d="M1080 690 L1080 560 L1280 560 L1280 690Z" fill="#17151a" />
      {/* airship */}
      <g transform={launched ? "translate(470 150) scale(0.62)" : "translate(640 400)"} style={{ transition: "transform 1.2s" }}>
        <ellipse cx="0" cy="0" rx="330" ry="120" fill="url(#pp-env)" />
        <path d="M-300 -20 Q0 -70 300 -20" stroke="#e7d4ad" strokeOpacity="0.35" strokeWidth="6" fill="none" />
        <path d="M-320 10 Q0 40 320 10" stroke="#3a2c1f" strokeOpacity="0.5" strokeWidth="5" fill="none" />
        <path d="M300 -10 L390 -70 L400 70 L300 20Z" fill="#6d5438" />
        <g stroke="#2c241c" strokeWidth="4">
          <line x1="-150" y1="100" x2="-110" y2="170" />
          <line x1="150" y1="100" x2="110" y2="170" />
        </g>
        <rect x="-150" y="165" width="300" height="70" rx="18" fill="#3c2f24" />
        <rect x="-120" y="180" width="60" height="28" rx="6" fill={launched ? "#ffd99c" : "#1e1915"} />
        <rect x="-40" y="180" width="60" height="28" rx="6" fill={launched ? "#ffd99c" : "#1e1915"} />
      </g>
      {/* ground */}
      <path d="M0 700 C 400 670 1200 680 1600 700 L1600 900 L0 900Z" fill="url(#pp-ground)" />
      {!launched && (
        <g stroke="#1a1618" strokeWidth="10">
          <line x1="420" y1="700" x2="470" y2="520" />
          <line x1="860" y1="700" x2="820" y2="520" />
        </g>
      )}
      {/* engine panel at hotspot (0.32, 0.55) */}
      <g transform="translate(512 495)">
        <rect x="-62" y="-50" width="124" height="100" rx="10" fill="#2a241f" stroke="#6b5334" strokeWidth="4" />
        {open ? (
          <>
            <circle r="80" fill="url(#pp-panel)" />
            <rect x="-38" y="-26" width="76" height="52" rx="6" fill="#ffcf85" opacity="0.9" />
          </>
        ) : (
          <>
            <circle cx="0" cy="0" r="14" fill="#5a4630" />
            <rect x="-4" y="-2" width="8" height="18" fill="#1b1612" />
          </>
        )}
      </g>
      <rect width="1600" height="900" fill="url(#pp-sun)" opacity="0.3" />
    </svg>
  );
}

export function SpritePlaceholder() {
  return (
    <svg viewBox="0 0 200 420" className="block h-full w-full" preserveAspectRatio="xMidYMax meet">
      <defs>
        <linearGradient id="sp-coat" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4b5d6e" />
          <stop offset="1" stopColor="#253241" />
        </linearGradient>
        <linearGradient id="sp-rim" x1="1" y1="0" x2="0" y2="0">
          <stop offset="0" stopColor="#f3c27a" stopOpacity="0.9" />
          <stop offset="0.35" stopColor="#f3c27a" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="sp-skin" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e4bd9c" />
          <stop offset="1" stopColor="#b98b6d" />
        </linearGradient>
      </defs>
      <ellipse cx="100" cy="414" rx="60" ry="6" fill="#000" opacity="0.35" />
      {/* legs + boots */}
      <path d="M72 300 L66 400 L90 402 L98 300Z" fill="#2a2622" />
      <path d="M104 300 L110 402 L134 400 L128 300Z" fill="#2a2622" />
      <rect x="60" y="392" width="34" height="14" rx="5" fill="#1b1714" />
      <rect x="106" y="392" width="34" height="14" rx="5" fill="#1b1714" />
      {/* coat */}
      <path d="M56 150 Q100 128 144 150 L152 318 Q100 332 48 318Z" fill="url(#sp-coat)" />
      <path d="M56 150 Q100 128 144 150 L152 318 Q100 332 48 318Z" fill="url(#sp-rim)" />
      <path d="M100 150 L100 320" stroke="#1d2631" strokeWidth="3" />
      <rect x="54" y="232" width="92" height="12" fill="#6b4f2e" />
      <rect x="92" y="230" width="16" height="16" rx="2" fill="#c89c5a" />
      {/* scarf */}
      <path d="M70 142 Q100 160 130 142 L126 160 Q100 172 74 160Z" fill="#b5553f" />
      {/* raised left arm (viewer's left) holding up */}
      <path d="M58 158 Q34 140 30 104 L44 98 Q52 128 72 150Z" fill="url(#sp-coat)" />
      <circle cx="36" cy="96" r="10" fill="url(#sp-skin)" />
      {/* right arm */}
      <path d="M142 158 Q160 210 150 262 L138 258 Q144 214 130 170Z" fill="url(#sp-coat)" />
      <circle cx="144" cy="264" r="9" fill="url(#sp-skin)" />
      {/* head */}
      <rect x="90" y="120" width="20" height="18" fill="#c99d7c" />
      <ellipse cx="100" cy="100" rx="28" ry="32" fill="url(#sp-skin)" />
      <path d="M70 98 Q70 62 100 62 Q132 62 132 100 Q126 80 100 78 Q80 80 70 98Z" fill="#231a18" />
      <path d="M128 96 Q140 120 128 140 Q124 118 122 100Z" fill="#231a18" />
      {/* goggles */}
      <rect x="72" y="72" width="56" height="10" rx="5" fill="#3b2e22" />
      <circle cx="86" cy="76" r="9" fill="#8fc3c8" stroke="#c89c5a" strokeWidth="3" />
      <circle cx="114" cy="76" r="9" fill="#8fc3c8" stroke="#c89c5a" strokeWidth="3" />
    </svg>
  );
}

export function PortraitPlaceholder() {
  return (
    <svg viewBox="0 0 100 100" className="block h-full w-full">
      <defs>
        <radialGradient id="pt-bg" cx="0.5" cy="0.35" r="0.75">
          <stop offset="0" stopColor="#4a5a70" />
          <stop offset="1" stopColor="#1a2130" />
        </radialGradient>
        <linearGradient id="pt-skin" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e7c2a3" />
          <stop offset="1" stopColor="#b88a6c" />
        </linearGradient>
      </defs>
      <rect width="100" height="100" fill="url(#pt-bg)" />
      <path d="M18 100 Q50 72 82 100Z" fill="#34485c" />
      <path d="M36 82 Q50 90 64 82 L62 90 Q50 96 38 90Z" fill="#b5553f" />
      <ellipse cx="50" cy="52" rx="20" ry="23" fill="url(#pt-skin)" />
      <path d="M29 52 Q28 24 50 24 Q73 24 71 52 Q66 36 50 35 Q35 36 29 52Z" fill="#231a18" />
      <rect x="31" y="31" width="38" height="7" rx="3.5" fill="#3b2e22" />
      <circle cx="41" cy="34" r="6" fill="#8fc3c8" stroke="#c89c5a" strokeWidth="2" />
      <circle cx="59" cy="34" r="6" fill="#8fc3c8" stroke="#c89c5a" strokeWidth="2" />
    </svg>
  );
}

export function KeyIcon() {
  return (
    <svg viewBox="0 0 64 64" className="block h-full w-full">
      <defs>
        <linearGradient id="ki" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fde2a6" />
          <stop offset="0.5" stopColor="#e3a94e" />
          <stop offset="1" stopColor="#8d5d1f" />
        </linearGradient>
      </defs>
      <circle cx="20" cy="22" r="12" fill="none" stroke="url(#ki)" strokeWidth="6" />
      <path d="M28 30 L52 54" stroke="url(#ki)" strokeWidth="6" strokeLinecap="round" />
      <path d="M44 46 L50 40 M48 50 L54 44" stroke="url(#ki)" strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}

export function MapIcon() {
  return (
    <svg viewBox="0 0 64 64" className="block h-full w-full">
      <defs>
        <linearGradient id="mi" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f6e7c4" />
          <stop offset="1" stopColor="#c9a86c" />
        </linearGradient>
      </defs>
      <path d="M8 14 L24 8 L40 14 L56 8 L56 50 L40 56 L24 50 L8 56Z" fill="url(#mi)" stroke="#7a5b2c" strokeWidth="2" strokeLinejoin="round" />
      <path d="M24 8 L24 50 M40 14 L40 56" stroke="#7a5b2c" strokeOpacity="0.45" strokeWidth="2" />
      <path d="M14 42 Q22 30 30 34 T48 20" stroke="#b5553f" strokeWidth="2.5" strokeDasharray="4 3" fill="none" />
      <circle cx="48" cy="20" r="3.5" fill="#b5553f" />
    </svg>
  );
}

function IconPlaceholder({ src }: { src: string }) {
  return /map|chizu/i.test(src) ? <MapIcon /> : <KeyIcon />;
}

const PLACEHOLDERS: Record<Kind, (p: { src: string }) => React.ReactElement> = {
  plate: PlatePlaceholder,
  cover: PlatePlaceholder,
  sprite: SpritePlaceholder,
  portrait: PortraitPlaceholder,
  icon: IconPlaceholder,
};
