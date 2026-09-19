import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "./api";
import { useGame } from "../store";

export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

export function useNow(intervalMs: number, enabled = true) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, enabled]);
  return now;
}

/**
 * Resolve an art/plate URL from the server. Absolute paths (`/api/...`, `/mock-art/...`,
 * `http...`) are used as-is; a bare cartridge-relative path (`art/plate.png`) is routed
 * through the art endpoint.
 */
export function resolveArt(url: string | undefined | null): string | undefined {
  if (!url) return undefined;
  if (/^(https?:|blob:|data:|\/)/.test(url)) return url;
  return api.artUrl(useGame.getState().cartridgeId, url);
}
