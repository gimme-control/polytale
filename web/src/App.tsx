import { useEffect } from "react";
import { useGame } from "./store";
import { StartScreen } from "./components/StartScreen";
import { PlayView } from "./components/PlayView";
import { Wordmark } from "./components/Hud";

export default function App() {
  const screen = useGame((s) => s.screen);
  const boot = useGame((s) => s.boot);
  useEffect(() => {
    void boot();
  }, [boot]);

  if (screen === "boot") {
    return (
      <div className="flex h-full items-center justify-center bg-ink" data-testid="boot">
        <div className="fade-in opacity-70">
          <Wordmark />
        </div>
      </div>
    );
  }
  return screen === "start" ? <StartScreen /> : <PlayView />;
}
