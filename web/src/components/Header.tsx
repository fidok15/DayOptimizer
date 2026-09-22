import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowClockwise, CalendarBlank, Check, CircleNotch, Columns, WarningCircle } from "@phosphor-icons/react";
import { greeting, lineOfTheDay } from "../lib/copy";
import { fromMin, sceneHour } from "../lib/time";
import type { Categories, SaveStatus, View, Week, Weekday } from "../lib/types";
import GarminConnect from "./GarminConnect";
import ImportCalendar from "./ImportCalendar";

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
const pill = "glass inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-medium";

export default function Header(props: {
  view: View;
  onViewChange: (v: View) => void;
  saveStatus: SaveStatus;
  saveError: string;
  onRetry: () => void;
  categories: Categories;
  onImport: (week: Week, replace: boolean, days: Weekday[]) => void;
  day: Weekday;
}) {
  const { view, onViewChange, saveStatus, saveError, onRetry, categories, onImport, day } = props;
  const [hour, setHour] = useState(sceneHour);
  useEffect(() => {
    const t = setInterval(() => setHour(sceneHour()), 30_000);
    return () => clearInterval(t);
  }, []);
  const line = lineOfTheDay();

  return (
    <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="relative isolate min-w-0 max-w-2xl">
        {/* radial scrim: darkens behind the text and fades to nothing, so no box edge shows over the scene */}
        <div
          aria-hidden
          className="pointer-events-none absolute -inset-x-16 -inset-y-12 -z-10 bg-[radial-gradient(ellipse_farthest-side_at_40%_55%,rgb(4_6_16/0.72),rgb(4_6_16/0.5)_45%,transparent)]"
        />
        <p className="glass inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium text-ink">
          {greeting(hour)}
          <span aria-hidden className="text-ink-dim">·</span>
          <span className="font-mono text-ink-dim">{fromMin(Math.floor(hour * 60))}</span>
        </p>
        <AnimatePresence mode="wait">
          <motion.h1
            key={line}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
            className="mt-3 line-clamp-3 max-w-[22ch] md:line-clamp-2 text-3xl leading-[1.1] font-semibold tracking-tight [text-shadow:0_1px_1px_rgb(0_0_0/0.45),0_2px_16px_rgb(4_6_16/0.5)] md:text-5xl"
          >
            {line}
          </motion.h1>
        </AnimatePresence>
        <p className="mt-2 max-w-[60ch] text-[15px] text-ink [text-shadow:0_1px_1px_rgb(0_0_0/0.45),0_1px_12px_rgb(4_6_16/0.55)]">
          Draw your usual days here: work, meals, training, rest. Every week DayOptimizer turns them into a fresh plan that fits around what's already in your calendar. Done? Close this tab and use <code className="rounded bg-black/30 px-1 font-mono text-[13px]">dayoptimizer</code> in your terminal.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <GarminConnect />
        <ImportCalendar categories={categories} onImport={onImport} view={view} day={day} />
        <div role="group" aria-label="View" className="glass inline-flex rounded-full p-1">
          {VIEWS.map(({ id, label, Icon }) => {
            const active = view === id;
            return (
              <button
                key={id}
                type="button"
                aria-pressed={active}
                onClick={() => onViewChange(id)}
                className={`relative inline-flex items-center gap-1.5 rounded-full min-h-8 px-3.5 py-1.5 text-sm font-medium transition active:scale-[0.98] ${
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

        <div aria-live="polite" className="flex min-h-9 min-w-0 items-center text-sm">
          <AnimatePresence mode="wait" initial={false}>
            {saveStatus === "saving" && (
              <motion.span key="saving" {...fade} className={`${pill} text-ink`}>
                <CircleNotch size={16} weight="bold" className="animate-spin text-accent motion-reduce:animate-none" aria-hidden />
                Saving...
              </motion.span>
            )}
            {saveStatus === "saved" && (
              <motion.span key="saved" {...fade} className={`${pill} text-ink`}>
                <Check size={16} weight="bold" className="text-accent" aria-hidden />
                All changes saved
              </motion.span>
            )}
            {saveStatus === "error" && (
              <motion.span key="error" {...fade} className={`${pill} min-w-0 border-[#ff8a80]/40 py-1 pr-1 text-ink`}>
                <WarningCircle size={16} weight="bold" className="shrink-0 text-[#ff8a80]" aria-hidden />
                <span className="max-w-[16rem] truncate" title={saveError}>
                  {saveError || "Couldn't save"}
                </span>
                <button
                  type="button"
                  onClick={onRetry}
                  className="ml-1 inline-flex min-h-7 shrink-0 items-center gap-1 rounded-full bg-accent px-3 text-xs font-semibold text-night transition active:scale-[0.98]"
                >
                  <ArrowClockwise size={14} weight="bold" aria-hidden />
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
