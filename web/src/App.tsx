import { useEffect } from "react";
import { useGame } from "./store";
import { StartScreen } from "./components/StartScreen";
import { IntroCard } from "./components/IntroCard";
import { PlayView } from "./components/PlayView";
import { Summary } from "./components/Summary";

export default function App() {
  const screen = useGame((s) => s.screen);
  const boot = useGame((s) => s.boot);
  useEffect(() => {
    void boot();
  }, [boot]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-night" data-screen={screen}>
      {screen === "start" && <StartScreen />}
      {screen === "intro" && <IntroCard />}
      {screen === "play" && <PlayView />}
      {screen === "summary" && <Summary />}
    </div>
  );
}
