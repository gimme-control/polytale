// Title card: cover art, promise, headphone note, and Start — the moment we ask
// for the microphone, with a plain explanation (PRD §25).

import { useGame } from "../store";
import { api } from "../lib/api";
import { ArtImage } from "./Art";
import { Wordmark } from "./Hud";
import { IconHeadphones, IconMic } from "./icons";

export function StartScreen() {
  const begin = useGame((s) => s.begin);
  const starting = useGame((s) => s.starting);
  const error = useGame((s) => s.bootError);
  const cid = useGame((s) => s.cartridgeId);
  const resumable = useGame((s) => !!s.sid && s.transcript.length > 0);

  return (
    <main className="grain relative h-full w-full overflow-hidden bg-ink" data-testid="start-screen">
      <div className="absolute inset-0" style={{ animation: "slow-zoom 30s ease-out forwards" }}>
        <ArtImage
          src={[api.artUrl(cid, "art/cover.webp"), api.artUrl(cid, "art/cover.png"), api.artUrl(cid, "cover.png")]}
          kind="cover"
          alt=""
          className="h-full w-full object-cover"
        />
      </div>
      <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(8,10,16,0.94)_0%,rgba(8,10,16,0.78)_38%,rgba(8,10,16,0.15)_75%)] max-md:bg-[linear-gradient(0deg,rgba(8,10,16,0.97)_0%,rgba(8,10,16,0.82)_48%,rgba(8,10,16,0.2)_85%)]" />
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-ink to-transparent" />

      <div className="absolute left-6 top-6 sm:left-10 sm:top-8">
        <Wordmark />
      </div>

      <div className="relative flex h-full flex-col justify-end px-6 pb-10 sm:px-10 md:justify-center md:pb-0 lg:px-20">
        <div className="max-w-[560px]">
          <div className="rise-in mb-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/30 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-muted backdrop-blur">
            <span className="jp whitespace-nowrap text-[13px] normal-case tracking-normal text-brass-strong">日本語</span>
            <span className="whitespace-nowrap">
              Japanese · <span className="max-sm:hidden">Absolute </span>beginner · 4 min
            </span>
          </div>
          <h1 className="rise-in font-display text-[46px] font-semibold leading-[1.02] tracking-[-0.01em] text-text sm:text-[68px]" style={{ animationDelay: "80ms" }}>
            The Broken
            <br />
            Airship
          </h1>
          <p className="rise-in mt-5 max-w-[460px] text-[18px] leading-relaxed text-text/90 sm:text-[20px]" style={{ animationDelay: "160ms" }}>
            Learn to speak by making yourself understood.
          </p>
          <p className="rise-in mt-2 max-w-[460px] text-[14.5px] leading-relaxed text-muted" style={{ animationDelay: "220ms" }}>
            A storm is coming. The engineer can fix the airship — but she only speaks Japanese, and she needs your help.
          </p>

          <div className="rise-in mt-7 flex items-center gap-3 text-[14px] text-text/90" style={{ animationDelay: "280ms" }}>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/[0.06] text-sky">
              <IconHeadphones className="h-4.5 w-4.5" />
            </span>
            Put on headphones. You'll speak Japanese out loud.
          </div>

          <div className="rise-in mt-8" style={{ animationDelay: "340ms" }}>
            <button
              type="button"
              onClick={() => void begin()}
              disabled={starting}
              className="group inline-flex h-14 items-center gap-3 rounded-full bg-gradient-to-b from-brass-strong to-brass pl-3 pr-7 text-[16px] font-bold text-ink shadow-[0_18px_50px_-12px_rgba(233,180,95,0.8),inset_0_1px_0_rgba(255,255,255,0.5)] transition hover:brightness-105 active:scale-[0.98] disabled:opacity-70"
              data-testid="start-button"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-ink/15">
                {starting ? (
                  <span className="h-4 w-4 rounded-full border-2 border-ink/30 border-t-ink" style={{ animation: "spin 0.8s linear infinite" }} />
                ) : (
                  <IconMic className="h-5 w-5" />
                )}
              </span>
              {starting ? "Getting ready…" : resumable ? "Continue" : "Start"}
            </button>
            <p className="mt-3 max-w-[420px] text-[12.5px] leading-relaxed text-faint">
              Your browser will ask to use the microphone. It only listens while you hold the talk button, and the audio
              is used only to hear what you said. You can type instead at any time.
            </p>
            {error && (
              <p className="mt-3 rounded-xl border border-rose/30 bg-rose/10 px-3 py-2 text-[13px] text-rose" role="alert">
                {error}
              </p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
