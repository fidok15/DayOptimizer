import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowClockwise, ArrowLeft, CalendarPlus, CircleNotch, DownloadSimple, WarningCircle } from "@phosphor-icons/react";
import { ApiError, importWeek, type ImportedWeek } from "../lib/api";
import { toMin, uid } from "../lib/time";
import { usePopover } from "../lib/usePopover";
import { WEEKDAYS, type Categories, type Week } from "../lib/types";

const WEEKS = [
  { offset: -1, label: "Last week" },
  { offset: 0, label: "This week" },
  { offset: 1, label: "Next week" },
];

/** Local YYYY-MM-DD of the Monday `offset` weeks from now. */
const mondayISO = (offset: number) => {
  const d = new Date();
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + offset * 7);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const ghost =
  "inline-flex min-h-8 items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-sm text-ink-dim transition hover:text-ink active:scale-[0.98]";
const primary =
  "inline-flex min-h-8 items-center gap-1.5 rounded-full bg-accent px-3.5 py-1.5 text-sm font-semibold text-night transition active:scale-[0.98] disabled:opacity-40";

type Failure = { message: string; code: string };

export default function ImportCalendar(props: { categories: Categories; onImport: (week: Week, replace: boolean) => void }) {
  const { categories, onImport } = props;
  const { open, setOpen, ref } = usePopover();
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [found, setFound] = useState<ImportedWeek | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({}); // calendar -> category, "" = skip
  const [replace, setReplace] = useState(false);

  // calendar name -> number of events, biggest first
  const calendars = useMemo(() => {
    const n: Record<string, number> = {};
    for (const d of WEEKDAYS) for (const b of found?.[d] ?? []) n[b.calendar] = (n[b.calendar] ?? 0) + 1;
    return Object.entries(n).sort(([, a], [, b]) => b - a);
  }, [found]);

  const mapped = calendars.filter(([cal]) => categories[mapping[cal]]);
  const mappedCount = mapped.reduce((sum, [, n]) => sum + n, 0);

  const reset = () => {
    setFound(null);
    setFailure(null);
  };

  const load = () => {
    setLoading(true);
    setFailure(null);
    importWeek(mondayISO(offset))
      .then((w) => {
        // preselect a category only where the calendar already has the same name
        const byLower = new Map(Object.keys(categories).map((c) => [c.toLowerCase(), c]));
        const guess: Record<string, string> = {};
        for (const d of WEEKDAYS) for (const b of w[d] ?? []) guess[b.calendar] = byLower.get(b.calendar.toLowerCase()) ?? "";
        setMapping(guess);
        setFound(w);
      })
      .catch((e: unknown) =>
        setFailure(e instanceof ApiError ? { message: e.message, code: e.code } : { message: "Something went wrong. Try again.", code: "failed" }),
      )
      .finally(() => setLoading(false));
  };

  const confirm = () => {
    if (!found) return;
    const week = Object.fromEntries(
      WEEKDAYS.map((d) => [
        d,
        (found[d] ?? [])
          .filter((b) => categories[mapping[b.calendar]] && toMin(b.end) > toMin(b.start))
          .map((b) => ({ id: uid(), start: b.start, end: b.end, category: mapping[b.calendar], title: b.title.slice(0, 60) })),
      ]),
    ) as Week;
    onImport(week, replace);
    setOpen(false);
    reset();
  };

  const categoryNames = Object.keys(categories);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="glass inline-flex min-h-10 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium text-ink transition hover:text-accent active:scale-[0.98]"
      >
        <CalendarPlus size={16} weight="bold" aria-hidden />
        Import
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label="Import from your calendar"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 400, damping: 32 }}
            style={{ transformOrigin: "top right" }}
            className="glass-strong absolute right-0 top-full z-40 mt-2 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-3 rounded-[20px] p-4 shadow-2xl"
          >
            <div>
              <h2 className="text-[15px] font-semibold tracking-tight">Start from your calendar</h2>
              <p className="mt-1 text-xs leading-snug text-ink-dim">
                Copies a real week from Apple Calendar (and Google or other accounts added in macOS Settings) as a starting
                point. You choose which of your categories each calendar belongs to.
              </p>
            </div>

            {!found ? (
              <>
                <div role="radiogroup" aria-label="Week" className="flex gap-1 rounded-full border border-line p-1">
                  {WEEKS.map((w) => (
                    <button
                      key={w.offset}
                      type="button"
                      role="radio"
                      aria-checked={offset === w.offset}
                      onClick={() => setOffset(w.offset)}
                      className={`flex-1 rounded-full px-2 py-1.5 text-sm transition ${
                        offset === w.offset ? "bg-accent font-medium text-night" : "text-ink-dim hover:text-ink"
                      }`}
                    >
                      {w.label}
                    </button>
                  ))}
                </div>
                {failure && (
                  <div role="alert" className="flex gap-2 rounded-[12px] border border-[#ff8a80]/30 bg-[#ff8a80]/10 p-2.5 text-xs leading-snug text-ink">
                    <WarningCircle size={16} weight="bold" className="mt-px shrink-0 text-[#ff8a80]" aria-hidden />
                    <p className="min-w-0 break-words">
                      {failure.code === "setup" ? "Calendar access isn't set up yet. Run this once in the DayOptimizer folder, then try again:" : failure.message}
                      {failure.code === "setup" && (
                        <code className="mt-1.5 block rounded-md bg-black/30 px-2 py-1 font-mono text-[11px] text-ink">
                          ./scripts/setup-bundle.sh
                        </code>
                      )}
                    </p>
                  </div>
                )}
                {loading && <p className="text-xs text-ink-dim">Reading your calendar. The first time, macOS may ask for permission.</p>}
                <div className="flex justify-end">
                  <button type="button" onClick={load} disabled={loading} className={primary}>
                    {loading ? (
                      <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />
                    ) : failure ? (
                      <ArrowClockwise size={16} weight="bold" aria-hidden />
                    ) : (
                      <DownloadSimple size={16} weight="bold" aria-hidden />
                    )}
                    {failure ? "Try again" : "Load events"}
                  </button>
                </div>
              </>
            ) : calendars.length === 0 ? (
              <>
                <p className="text-sm text-ink-dim">No timed events that week. Pick another week or draw your days by hand.</p>
                <div className="flex justify-end">
                  <button type="button" onClick={reset} className={ghost}>
                    <ArrowLeft size={16} weight="bold" aria-hidden /> Pick another week
                  </button>
                </div>
              </>
            ) : (
              <>
                <fieldset>
                  <legend className="mb-1.5 text-xs text-ink-dim">Put each calendar into one of your categories</legend>
                  <ul className="scroll-thin flex max-h-56 flex-col gap-1 overflow-y-auto">
                    {calendars.map(([cal, count]) => (
                      <li key={cal} className="flex items-center gap-2 text-sm">
                        <span className="min-w-0 flex-1 truncate" title={cal}>
                          {cal}
                          <span className="ml-1.5 font-mono text-xs text-ink-dim tabular-nums">{count}</span>
                        </span>
                        <select
                          aria-label={`Category for ${cal}`}
                          value={mapping[cal] ?? ""}
                          onChange={(e) => setMapping((m) => ({ ...m, [cal]: e.target.value }))}
                          className="h-8 w-36 shrink-0 rounded-[10px] border border-line bg-night px-2 text-sm text-ink outline-none focus:border-accent"
                        >
                          <option value="">Skip</option>
                          {categoryNames.map((c) => (
                            <option key={c} value={c}>
                              {categories[c].emoji ? `${categories[c].emoji} ${c}` : c}
                            </option>
                          ))}
                        </select>
                      </li>
                    ))}
                  </ul>
                </fieldset>
                <div role="radiogroup" aria-label="How to import" className="flex flex-col gap-1 text-sm">
                  {[
                    { v: false, label: "Add to my typical week" },
                    { v: true, label: "Replace my typical week" },
                  ].map((o) => (
                    <label key={String(o.v)} className="flex cursor-pointer items-center gap-2 px-1">
                      <input
                        type="radio"
                        name="import-mode"
                        checked={replace === o.v}
                        onChange={() => setReplace(o.v)}
                        className="size-4 accent-[#f4b860]"
                      />
                      {o.label}
                    </label>
                  ))}
                </div>
                <div className="flex items-center justify-between gap-2">
                  <button type="button" onClick={reset} className={ghost}>
                    <ArrowLeft size={16} weight="bold" aria-hidden /> Back
                  </button>
                  <button type="button" onClick={confirm} disabled={mappedCount === 0} className={primary}>
                    {mappedCount === 0 ? "Pick a category" : `Import ${mappedCount} ${mappedCount === 1 ? "event" : "events"}`}
                  </button>
                </div>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
