import { useEffect, useRef, useSyncExternalStore } from "react";

/** The same two queries the stylesheet uses. Components never read the window's size. */
export const DESKTOP = "(min-width: 1024px)";
export const SHORT = "(max-height: 520px) and (orientation: landscape) and (max-width: 1023.98px)";
export const COARSE = "(pointer: coarse)";

export function matches(query: string): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(query).matches;
}

export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", notify);
      return () => mq.removeEventListener("change", notify);
    },
    () => matches(query),
    () => false,
  );
}

/** Close a popover on outside press or Escape. */
export function useDismiss<T extends HTMLElement = HTMLDivElement>(open: boolean, close: () => void) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("pointerdown", down);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("keydown", key);
    };
  }, [open, close]);
  return ref;
}

/** Focus without scrolling anything, and never on a touch screen (it raises the keyboard). */
export function focusQuietly(el: HTMLElement | null | undefined) {
  if (!el || matches(COARSE)) return;
  el.focus({ preventScroll: true });
}
