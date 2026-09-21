import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CalendarBlank, Check, CircleNotch, Columns, WarningCircle } from "@phosphor-icons/react";
import { greeting, lineOfTheDay } from "../lib/copy";
import { fromMin, sceneHour } from "../lib/time";
import type { SaveStatus, View } from "../lib/types";

const VIEWS = [
  { id: "day" as const, label: "Day", Icon: CalendarBlank },
  { id: "week" as const, label: "Week", Icon: Columns },
];

const fade = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.2 },
};

export default function Header(props: {
  view: View;
  onViewChange: (v: View) => void;
  saveStatus: SaveStatus;
  saveError: string;
  onRetry: () => void;
}) {
  const { view, onViewChange, saveStatus, saveError, onRetry } = props;
  const [hour, setHour] = useState(sceneHour);
  useEffect(() => {
    const t = setInterval(() => setHour(sceneHour()), 30_000);
    return () => clearInterval(t);
  }, []);
  const line = lineOfTheDay();

  return (
    <header className="flex flex-col gap-4 [text-shadow:0_1px_12px_rgb(0_0_0/0.45)] md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        <p className="text-sm text-ink-dim">
          {greeting(hour)} · <span className="font-mono">{fromMin(Math.floor(hour * 60))}</span>
        </p>
        <AnimatePresence mode="wait">
          <motion.h1
            key={line}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
            className="mt-1 line-clamp-2 max-w-[22ch] text-3xl leading-[1.1] font-semibold tracking-tight md:text-5xl"
          >
            {line}
          </motion.h1>
        </AnimatePresence>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="View" className="glass inline-flex rounded-full p-1 [text-shadow:none]">
          {VIEWS.map(({ id, label, Icon }) => {
            const active = view === id;
            return (
              <button
                key={id}
                type="button"
                aria-pressed={active}
                onClick={() => onViewChange(id)}
                className={`relative inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition active:scale-[0.98] ${
                  active ? "text-night" : "text-ink-dim hover:text-ink"
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="view-pill"
                    className="absolute inset-0 rounded-full bg-accent"
                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                  />
                )}
                <Icon size={16} weight="bold" className="relative" aria-hidden />
                <span className="relative">{label}</span>
              </button>
            );
          })}
        </div>

        <div aria-live="polite" className="flex min-h-8 min-w-0 items-center text-sm">
          <AnimatePresence mode="wait" initial={false}>
            {saveStatus === "saving" && (
              <motion.span key="saving" {...fade} className="inline-flex items-center gap-1.5 text-ink-dim">
                <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />
                Saving
              </motion.span>
            )}
            {saveStatus === "saved" && (
              <motion.span key="saved" {...fade} className="inline-flex items-center gap-1.5 text-ink-dim">
                <Check size={16} weight="bold" className="text-accent" aria-hidden />
                Saved
              </motion.span>
            )}
            {saveStatus === "error" && (
              <motion.span key="error" {...fade} className="inline-flex min-w-0 items-center gap-1.5 text-ink">
                <WarningCircle size={16} weight="bold" className="shrink-0 text-[#ff8a80]" aria-hidden />
                <span className="max-w-[18rem] truncate" title={saveError}>
                  {saveError || "Couldn't save"}
                </span>
                <button
                  type="button"
                  onClick={onRetry}
                  className="ml-1 shrink-0 rounded-full border border-line px-2.5 py-0.5 text-xs font-medium transition hover:bg-white/5 active:scale-[0.98]"
                >
                  Retry
                </button>
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
}
