// Three presets, one segmented control. During play a change applies from the
// character's next reply; on the start screen it just picks who you will meet.

import { useGame } from "../store";

export function PersonaSwitch({ full = false, start = false }: { full?: boolean; start?: boolean }) {
  const personas = useGame((s) => (s.personas.length ? s.personas : (s.catalog?.personas ?? [])));
  const active = useGame((s) => (start ? (s.chosenPersona ?? s.personaId ?? s.catalog?.personas[0]?.id) : s.personaId));
  const setPersona = useGame((s) => s.setPersona);
  const choosePersona = useGame((s) => s.choosePersona);
  if (!personas.length) return null;
  return (
    <div
      role="radiogroup"
      aria-label="Character"
      data-testid="persona-switch"
      className={`${full ? "flex" : "inline-flex"} h-9 items-center rounded-[8px] border border-hair bg-glass p-[3px] backdrop-blur-md`}
    >
      {personas.map((p) => {
        const on = p.id === active;
        return (
          <button
            key={p.id}
            type="button"
            role="radio"
            aria-checked={on}
            title={p.blurb}
            data-testid={`persona-${p.id}`}
            data-active={on ? "1" : "0"}
            onClick={() => (start ? choosePersona(p.id) : void setPersona(p.id))}
            className={`h-full rounded-[6px] border-0 px-3 text-[13px] font-medium transition-colors duration-150 ${full ? "flex-1" : ""} ${
              on ? "bg-ink text-night" : "bg-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {p.label}
          </button>
        );
      })}
    </div>
  );
}
