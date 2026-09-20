// Scene entry. The player reads where they are and steps in when they are ready.
// The opening turn (a real model call, a few seconds) runs while they read, so the
// pause costs no time: by the time Enter is pressed the character is usually waiting.

import { useGame } from "../store";
import { Picture } from "./Picture";

export function IntroCard() {
  const intro = useGame((s) => s.intro);
  const retry = useGame((s) => s.retryIntro);
  const newJourney = useGame((s) => s.newJourney);
  const enterGame = useGame((s) => s.enterGame);
  const entering = useGame((s) => s.entering);
  const scene = intro?.scene;
  return (
    <main data-testid="intro-card" className="fade-in absolute inset-0 overflow-hidden">
      <Picture src={scene?.cover_url || undefined} className="absolute inset-0" />
      <div className="pointer-events-none absolute inset-0 bg-[#080909]/55" />
      <div className="absolute inset-0 mx-auto flex w-full max-w-[1180px] flex-col justify-end px-6 pb-14 sm:justify-center sm:px-12 sm:pb-0">
        {scene && (
          <div className="rise-in max-w-[560px]">
            <h1 className="over-art m-0 text-[15px] font-semibold tracking-[-0.01em] text-ink-2">{scene.name}</h1>
            <p data-testid="intro-text" className="over-art m-0 mt-4 text-[24px] leading-[1.35] tracking-[-0.015em] text-ink sm:text-[30px]">
              {scene.intro || scene.tagline}
            </p>
          </div>
        )}
        <div className="mt-10 flex min-h-9 items-center gap-4">
          {!intro?.error && (
            <button
              type="button"
              data-testid="enter-button"
              onClick={enterGame}
              disabled={entering}
              className="h-10 rounded-[8px] border-0 bg-ink px-6 text-[14px] font-medium text-[#0e0f0f] transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {entering ? "Opening the door…" : "Enter"}
            </button>
          )}
          {intro?.error ? (
            <p data-testid="intro-error" role="alert" className="fade-in m-0 flex items-center gap-4 text-[14px] text-ink-2">
              {intro.error}
              <button type="button" data-testid="intro-retry" onClick={() => void retry()} className="h-9 rounded-[8px] border border-hair-2 bg-transparent px-4 text-[13px] font-medium text-ink hover:border-ink-3">
                Try again
              </button>
              <button type="button" onClick={() => void newJourney()} className="border-0 bg-transparent p-0 text-[13px] text-ink-2 hover:text-ink">
                Back
              </button>
            </p>
          ) : (
            entering && (
              <div className="thinking" aria-label="Setting the scene">
                <span />
                <span />
                <span />
              </div>
            )
          )}
        </div>
      </div>
    </main>
  );
}
