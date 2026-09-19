// The two resources that make choices matter: time and money. Quiet until they move;
// each turn ticks the clock and shows what the move cost, and the last quarter hour
// changes colour.

import { useEffect, useRef, useState } from "react";
import { useGame } from "../store";

const PRESSURE_MIN = 15;

function endTime(time: string, minutesLeft: number): string {
  const [h, m] = time.split(":").map((n) => parseInt(n, 10));
  if (Number.isNaN(h) || Number.isNaN(m)) return "";
  const t = h * 60 + m + minutesLeft;
  return `${String(Math.floor(t / 60) % 24).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

/** The previous value of a number, and the change when it last moved. */
function useDelta(value: number | undefined) {
  const prev = useRef(value);
  const [delta, setDelta] = useState<{ by: number; key: number } | null>(null);
  useEffect(() => {
    if (value == null) return;
    if (prev.current != null && prev.current !== value) {
      const by = value - prev.current; // read now: the updater below runs after prev has moved on
      setDelta((d) => ({ by, key: (d?.key ?? 0) + 1 }));
    }
    prev.current = value;
  }, [value]);
  return delta;
}

export function Hud() {
  const game = useGame((s) => s.game);
  if (!game) return null;
  return (
    <div data-testid="hud" className="over-art flex items-start gap-5 sm:gap-7">
      <Clock />
      <Cash />
    </div>
  );
}

function Clock() {
  const clock = useGame((s) => s.game!.clock);
  const delta = useDelta(clock.minutes_left);
  const urgent = clock.minutes_left <= PRESSURE_MIN;
  const frac = clock.minutes_total > 0 ? Math.max(0, Math.min(1, clock.minutes_left / clock.minutes_total)) : 0;
  return (
    <div data-testid="clock" data-urgent={urgent ? "1" : "0"} data-minutes-left={clock.minutes_left} className="relative" role="timer" aria-label={`${clock.time}. ${clock.label} ${endTime(clock.time, clock.minutes_left)}`}>
      <div className="flex items-baseline gap-2 whitespace-nowrap leading-6">
        <span key={clock.time} className={`tick text-[15px] font-semibold tabular-nums tracking-[-0.01em] transition-colors duration-500 ${urgent ? "text-ember" : "text-ink"}`}>
          {clock.time}
        </span>
        <span className="text-[12px] tabular-nums text-ink-3">
          {clock.label.toLowerCase()} {endTime(clock.time, clock.minutes_left)}
        </span>
        {delta && delta.by < 0 && (
          <span key={delta.key} data-testid="clock-spent" className={`spent absolute left-0 top-full mt-1.5 text-[12px] tabular-nums ${urgent ? "text-ember" : "text-ink-2"}`}>
            +{-delta.by} min
          </span>
        )}
      </div>
      <div className="mt-1 h-px w-full bg-hair">
        <div className={`h-px origin-left transition-[transform,background-color] duration-700 ease-out ${urgent ? "bg-ember" : "bg-ink-2"}`} style={{ transform: `scaleX(${frac})` }} />
      </div>
    </div>
  );
}

function Cash() {
  const wallet = useGame((s) => s.game!.wallet);
  const symbol = useGame((s) => s.language?.currency_symbol ?? "");
  const delta = useDelta(wallet);
  const [shown, setShown] = useState(wallet);
  const from = useRef(wallet);

  // Count down (or up) to the new amount instead of snapping.
  useEffect(() => {
    const start = from.current;
    if (start === wallet) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      from.current = wallet;
      setShown(wallet);
      return;
    }
    const t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 700);
      const eased = 1 - Math.pow(1 - k, 3);
      setShown(Math.round(start + (wallet - start) * eased));
      if (k < 1) raf = requestAnimationFrame(step);
      else from.current = wallet;
    };
    raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      from.current = wallet;
    };
  }, [wallet]);

  return (
    <div data-testid="cash" data-wallet={wallet} className="relative whitespace-nowrap leading-6" aria-label={`Cash ${symbol}${wallet}`}>
      <span className="text-[15px] font-semibold tabular-nums tracking-[-0.01em] text-ink">
        {symbol}
        {shown}
      </span>
      {delta && (
        <span key={delta.key} data-testid="cash-spent" className={`spent absolute left-0 top-full mt-[11px] text-[12px] tabular-nums ${delta.by < 0 ? "text-ember" : "text-jade"}`}>
          {delta.by < 0 ? "−" : "+"}
          {symbol}
          {Math.abs(delta.by)}
        </span>
      )}
    </div>
  );
}
