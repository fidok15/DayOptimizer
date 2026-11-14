import { useEffect, useRef } from "react";
import { motion } from "motion/react";
import { CalendarBlank, Columns, Rows } from "@phosphor-icons/react";
import type { RoutineMode, View } from "../lib/types";

const OPTIONS: { id: RoutineMode; label: string; Icon: typeof Rows; text: string }[] = [
  {
    id: "day",
    label: "One typical day",
    Icon: CalendarBlank,
    text: "Draw a single day. It's used every day, and your notes (like \"gym twice a week\") decide how often each thing really happens.",
  },
  {
    id: "week",
    label: "A typical week",
    Icon: Rows,
    text: "Draw each day on its own, for weeks where Monday and Saturday look nothing alike.",
  },
];

export function RoutineChooser({ onChoose }: { onChoose: (m: RoutineMode) => void }) {
  // a native modal dialog: focus moves in, stays in, and the page behind is inert until a choice is made
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      aria-labelledby="routine-mode-title"
      onCancel={(e) => e.preventDefault()}
      className="m-auto w-[min(36rem,calc(100vw-2rem))] bg-transparent p-0 text-ink backdrop:bg-night/60 backdrop:backdrop-blur-sm"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        className="glass-strong flex w-full max-w-xl flex-col gap-4 rounded-2xl p-5 shadow-2xl"
      >
        <div>
          <h2 id="routine-mode-title" className="text-lg font-semibold tracking-tight">How do you want to describe your routine?</h2>
          <p className="mt-1 text-sm text-ink-dim">You can switch later above the calendar.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {OPTIONS.map(({ id, label, Icon, text }) => (
            <button
              key={id}
              type="button"
              onClick={() => onChoose(id)}
              className="flex flex-col items-start gap-2 rounded-[14px] border border-line p-4 text-left transition hover:border-accent hover:bg-ink/5 active:scale-[0.99]"
            >
              <Icon size={22} weight="bold" className="text-accent" aria-hidden />
              <span className="font-semibold">{label}</span>
              <span className="text-sm leading-snug text-ink-dim">{text}</span>
            </button>
          ))}
        </div>
      </motion.div>
    </dialog>
  );
}

export function RoutineSwitch({ mode, onChange }: { mode: RoutineMode; onChange: (m: RoutineMode) => void }) {
  return (
    <div role="group" aria-label="Routine" className="glass-btn inline-flex w-fit items-center gap-1 rounded-full p-1 pl-3.5 text-sm">
      <span className="font-medium text-ink">Routine</span>
      <div className="inline-flex">
        {OPTIONS.map(({ id, label }) => {
          const active = id === mode;
          return (
            <button
              key={id}
              type="button"
              aria-pressed={active}
              onClick={() => !active && onChange(id)}
              className={`relative min-h-8 rounded-full px-3.5 py-1.5 text-sm font-medium transition active:scale-[0.98] ${active ? "text-on-dusk" : "text-ink-dim hover:text-ink"}`}
            >
              {active && <motion.span layoutId="routine-mode-pill" className="absolute inset-0 rounded-full bg-dusk" transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
              <span className="relative">{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

const VIEWS = [
  { id: "day" as const, label: "Day", Icon: CalendarBlank },
  { id: "week" as const, label: "Week", Icon: Columns },
];

export function ViewSwitch({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div role="group" aria-label="View" className="glass-btn inline-flex rounded-full p-1">
      {VIEWS.map(({ id, label, Icon }) => {
        const active = view === id;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(id)}
            className={`relative inline-flex items-center gap-1.5 rounded-full min-h-8 px-3.5 py-1.5 text-sm font-medium transition active:scale-[0.98] ${
              active ? "text-on-dusk" : "text-ink-dim hover:text-ink"
            }`}
          >
            {active && (
              <motion.span
                layoutId="view-pill"
                className="absolute inset-0 rounded-full bg-dusk"
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
              />
            )}
            <Icon size={16} weight="bold" className="relative" aria-hidden />
            <span className="relative">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
