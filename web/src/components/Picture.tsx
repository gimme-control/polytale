// An image that never leaves a hole: while loading or when the file is missing
// (art 404, network down) a neutral block holds its place.

import { useEffect, useState } from "react";

export function Picture({
  src,
  className = "",
  style,
  onSize,
  fit = "cover",
  position,
}: {
  src: string | undefined;
  className?: string;
  style?: React.CSSProperties;
  onSize?: (w: number, h: number) => void;
  fit?: "cover" | "fill";
  position?: string;
}) {
  const [state, setState] = useState<"loading" | "ok" | "missing">(src ? "loading" : "missing");
  useEffect(() => setState(src ? "loading" : "missing"), [src]);
  return (
    <div className={`overflow-hidden bg-[#141515] ${className}`} style={style} data-art={state}>
      {src && state !== "missing" && (
        <img
          src={src}
          alt=""
          draggable={false}
          onLoad={(e) => {
            setState("ok");
            onSize?.(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight);
          }}
          onError={() => setState("missing")}
          className="h-full w-full select-none transition-opacity duration-500"
          style={{ objectFit: fit, objectPosition: position, opacity: state === "ok" ? 1 : 0 }}
        />
      )}
    </div>
  );
}
