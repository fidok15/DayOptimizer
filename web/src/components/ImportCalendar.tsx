import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowClockwise, CalendarPlus, CaretLeft, CaretRight, CircleNotch, DownloadSimple, FileArrowUp, WarningCircle } from "@phosphor-icons/react";
import { ApiError, importFiles, importWeek, type ImportedCalendars } from "../lib/api";
import { categoryColor, freshColor } from "../lib/colors";
import { toMin, uid } from "../lib/time";
import { usePopover } from "../lib/usePopover";
import { WEEKDAYS, type Categories, type View, type Week, type Weekday } from "../lib/types";
import { DAY_NAME } from "./calendar/geometry";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fromIso = (s: string) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const addDays = (s: string, n: number) => {
  const d = fromIso(s);
  d.setDate(d.getDate() + n);
  return iso(d);
};

/** Local YYYY-MM-DD of last week's Monday: the most recent complete week. */
const lastMondayISO = () => {
  const d = new Date();
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7) - 7);
  return iso(d);
};

const weekdayOf = (s: string): Weekday => WEEKDAYS[(fromIso(s).getDay() + 6) % 7];
const mondayOf = (s: string) => addDays(s, -WEEKDAYS.indexOf(weekdayOf(s)));

const long = (s: string) => fromIso(s).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
const short = (s: string) => fromIso(s).toLocaleDateString(undefined, { day: "numeric", month: "short" });
const dateLabel = (date: string, mode: View) =>
  mode === "week"
    ? `${short(mondayOf(date))} – ${short(addDays(mondayOf(date), 6))}`
    : fromIso(date).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

// which category each calendar went into last time, so the next import is pre-filled
// (a per-browser convenience: losing it only means picking again)
const MAP_KEY = "dayoptimizer.calendarMap";
const readMap = (): Record<string, string> => {
  try {
    return JSON.parse(localStorage.getItem(MAP_KEY) ?? "{}") ?? {};
  } catch {
    return {};
  }
};
const writeMap = (m: Record<string, string>) => {
  try {
    localStorage.setItem(MAP_KEY, JSON.stringify(m));
  } catch {
    /* private window: nothing to remember */
  }
};

const NEW = "\u0000new"; // "make a new category named after this calendar"

const primary =
  "inline-flex min-h-8 items-center gap-1.5 rounded-lg bg-dusk px-3.5 py-1.5 text-sm font-semibold text-on-dusk transition active:scale-[0.98] disabled:opacity-40";
const arrow = "grid size-8 place-items-center rounded-full border border-line text-ink-dim transition hover:text-ink active:scale-[0.96]";

const arrowText = "inline-flex min-h-8 items-center rounded-full border border-line px-3 py-1 text-sm font-medium text-ink transition hover:bg-ink/5 active:scale-[0.98]";

type Failure = { message: string; code: string };
type Source = "file" | "apple";
type Spread = "all" | "weekdays" | "one";
const SPREAD_DAYS: Record<Spread, (day: Weekday) => Weekday[]> = {
  all: () => [...WEEKDAYS],
  weekdays: () => WEEKDAYS.slice(0, 5),
  one: (day) => [day],
};
const SOURCES: { id: Source; label: string }[] = [
  { id: "file", label: "From file" },
  { id: "apple", label: "Apple Calendar" },
];
const MODES: { id: View; label: string }[] = [
  { id: "day", label: "Day" },
  { id: "week", label: "Week" },
];

/** Pill switch in the style of the header's Day/Week toggle. */
function Segmented<T extends string>(props: { label: string; options: { id: T; label: string }[]; value: T; onChange: (v: T) => void; pill: string }) {
  return (
    <div role="group" aria-label={props.label} className="inline-flex rounded-full border border-line p-0.5">
      {props.options.map((o) => {
        const active = o.id === props.value;
        return (
          <button
            key={o.id}
            type="button"
            aria-pressed={active}
            onClick={() => props.onChange(o.id)}
            className={`relative min-h-7 rounded-full px-3 py-1 text-[13px] font-medium transition active:scale-[0.98] ${active ? "text-on-dusk" : "text-ink-dim hover:text-ink"}`}
          >
            {active && <motion.span layoutId={props.pill} className="absolute inset-0 rounded-full bg-dusk" transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export default function ImportCalendar(props: {
  categories: Categories;
  onImport: (week: Week, replace: boolean, days: Weekday[]) => void;
  onCategories: (fn: (c: Categories) => Categories) => void;
  view: View;
  day: Weekday;
  /** one-typical-day routine: only a day can be imported, and it becomes that day */
  oneDay: boolean;
}) {
  const { categories, onImport, onCategories, view, day, oneDay } = props;
  const { open, setOpen, ref } = usePopover();
  const [source, setSource] = useState<Source>("apple");
  const [mode, setMode] = useState<View>(view);
  // the date shown: in week mode only its week counts
  const [date, setDate] = useState(() => addDays(lastMondayISO(), WEEKDAYS.indexOf(day)));
  const [files, setFiles] = useState<{ names: string[]; texts: string[] } | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [found, setFound] = useState<ImportedCalendars | null>(null);
  const [include, setInclude] = useState<Record<string, boolean>>({});
  const [mapping, setMapping] = useState<Record<string, string>>({}); // calendar -> category | NEW | ""
  const [replace, setReplace] = useState(false);
  const [spread, setSpread] = useState<Spread>("all");

  // opening the dialog starts from what the page shows: the whole week or the chosen day
  useEffect(() => {
    if (!open) return;
    setMode(oneDay ? "day" : view);
    setDate((d) => addDays(mondayOf(d), WEEKDAYS.indexOf(day)));
  }, [open, view, day]);

  const monday = mondayOf(date);
  const days: Weekday[] = mode === "week" ? [...WEEKDAYS] : [weekdayOf(date)];
  // a Day import is a sample day: its blocks go into every day it's used for
  const into = mode === "week" ? days : SPREAD_DAYS[oneDay ? "all" : spread](days[0]);
  const categoryNames = Object.keys(categories);

  // the calendars of this tab: busiest first, empty ones (for this week/day) last
  const google = useMemo(() => new Set(found?.google), [found]);
  const calendars = useMemo(() => {
    if (!found) return [];
    const n: Record<string, number> = {};
    for (const cal of Object.keys(found.calendars)) n[cal] = 0;
    for (const d of days) for (const b of found.week[d] ?? []) n[b.calendar] = (n[b.calendar] ?? 0) + 1;
    return Object.entries(n).sort(([a, x], [b, y]) => y - x || a.localeCompare(b));
  }, [found, source, mode, date]);

  const busy = calendars.filter(([, n]) => n > 0);
  const chosen = busy.filter(([cal]) => include[cal]);
  const missing = chosen.find(([cal]) => !mapping[cal])?.[0];
  const count = chosen.reduce((sum, [, n]) => sum + n, 0);
  const allOn = busy.length > 0 && chosen.length === busy.length;
  // a Day import of an empty day while the rest of that week has events: say so instead of "nothing"
  const elsewhere =
    mode === "day" && found
      ? WEEKDAYS.filter((d) => !days.includes(d)).reduce((n, d) => n + (found.week[d] ?? []).length, 0)
      : 0;
  // all-day events can't become blocks (no time): say which were left out
  const skipped = found ? found.allDay.filter((e) => e.days.some((d) => days.includes(d))) : [];
  // a file whose events all lie outside the shown week: point to where they are
  const span = source === "file" && found?.span && busy.length === 0 && elsewhere === 0 ? found.span : null;

  const jumpTo = (iso: string) => {
    setDate(iso);
    if (mondayOf(iso) !== monday) load(mondayOf(iso));
  };

  const load = (week: string, from: Source = source, texts = files?.texts) => {
    if (from === "file" && !texts) return;
    setLoading(true);
    setFailure(null);
    (from === "file" ? importFiles(week, texts!) : importWeek(week))
      .then((r) => {
        const remembered = readMap();
        const byLower = new Map(Object.keys(categories).map((c) => [c.toLowerCase(), c]));
        const names = new Set([...Object.keys(r.calendars), ...WEEKDAYS.flatMap((d) => (r.week[d] ?? []).map((b) => b.calendar))]);
        const guess: Record<string, string> = {};
        const on: Record<string, boolean> = {};
        for (const cal of names) {
          const home = categories[remembered[cal]] ? remembered[cal] : byLower.get(cal.toLowerCase());
          // no home yet: offer a new category named after it (visible, changeable; made only on Import)
          guess[cal] = home ?? NEW;
          // files were picked on purpose, so all their calendars start ticked; of the Calendar
          // app's many (holidays, birthdays...) only those that already have a home
          on[cal] = from === "file" || home !== undefined;
        }
        setMapping(guess);
        setInclude(on);
        setFound(r);
      })
      .catch((e: unknown) =>
        setFailure(e instanceof ApiError ? { message: e.message, code: e.code } : { message: "Something went wrong. Try again.", code: "failed" }),
      )
      .finally(() => setLoading(false));
  };

  const shift = (n: number) => {
    const next = addDays(date, mode === "week" ? 7 * n : n);
    setDate(next);
    if (found && mondayOf(next) !== monday) load(mondayOf(next));
  };

  // the Calendar app and files are separate reads
  const pickSource = (next: Source) => {
    if ((next === "file") !== (source === "file")) {
      setFound(null);
      setFailure(null);
    }
    setSource(next);
  };

  const pickFiles = async (list: FileList | null) => {
    if (!list?.length) return;
    const chosen = [...list].slice(0, 20);
    const texts = await Promise.all(chosen.map((f) => f.text()));
    setFiles({ names: chosen.map((f) => f.name), texts });
    load(monday, "file", texts);
  };

  const confirm = () => {
    if (!found || missing || count === 0) return;
    // calendars put into a new category get one named after them, in the calendar's colour
    const target: Record<string, string> = {};
    const fresh: Categories = {};
    const taken = Object.entries(categories).map(([n, c]) => categoryColor(n, c.color));
    for (const [cal] of chosen) {
      if (mapping[cal] !== NEW) {
        target[cal] = mapping[cal];
        continue;
      }
      const name = cal.slice(0, 40);
      const existing = categoryNames.find((c) => c.toLowerCase() === name.toLowerCase());
      target[cal] = existing ?? name;
      if (!existing) {
        const color = /^#[0-9a-f]{6}$/i.test(found.calendars[cal] ?? "") ? found.calendars[cal] : freshColor(name, taken);
        fresh[name] = { movable: false, priority: 5, color };
        taken.push(color);
      }
    }
    if (Object.keys(fresh).length) onCategories((c) => ({ ...c, ...fresh }));
    const week = Object.fromEntries(
      WEEKDAYS.map((d) => [
        d,
        (into.includes(d) ? (found.week[mode === "week" ? d : days[0]] ?? []) : [])
          .filter((b) => target[b.calendar] && toMin(b.end) > toMin(b.start))
          .map((b) => ({ id: uid(), start: b.start, end: b.end, category: target[b.calendar], title: b.title.slice(0, 60) })),
      ]),
    ) as Week;
    onImport(week, replace, into);
    writeMap({ ...readMap(), ...target });
    setOpen(false);
    setFound(null);
  };

  const target = mode === "week" ? "this week" : `on ${DAY_NAME[weekdayOf(date)]}`;
  const dayName = DAY_NAME[weekdayOf(date)];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="glass-btn inline-flex min-h-10 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium text-ink transition hover:bg-ink/20 active:scale-[0.98]"
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
            className="glass-strong absolute right-0 top-full z-40 mt-2 flex w-[min(26rem,calc(100vw-2rem))] flex-col gap-3 rounded-2xl p-4 shadow-2xl"
          >
            <div>
              <h2 className="text-[15px] font-semibold tracking-tight">Fill your routine from your calendar</h2>
              <p className="mt-1 text-xs leading-snug text-ink-dim">
                Copies events as a starting point. Tick the calendars to copy and choose which of your categories each one goes into.
              </p>
            </div>

            <Segmented label="Import from" options={SOURCES} value={source} onChange={pickSource} pill="import-source" />
            {/* opened by real buttons: Safari won't open the picker from a <label> around an sr-only input */}
            <input
              ref={picker}
              type="file"
              accept=".ics,text/calendar"
              multiple
              hidden
              onChange={(e) => {
                void pickFiles(e.target.files);
                e.target.value = "";
              }}
            />

            <div className="flex flex-wrap items-center justify-between gap-2">
              {!oneDay && <Segmented label="Import a day or a week" options={MODES} value={mode} onChange={setMode} pill="import-mode" />}
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => shift(-1)} disabled={loading} aria-label={mode === "week" ? "Previous week" : "Previous day"} className={arrow}>
                  <CaretLeft size={14} weight="bold" aria-hidden />
                </button>
                <span className="min-w-[8.5rem] text-center text-sm tabular-nums" aria-live="polite">
                  {dateLabel(date, mode)}
                </span>
                <button type="button" onClick={() => shift(1)} disabled={loading} aria-label={mode === "week" ? "Next week" : "Next day"} className={arrow}>
                  <CaretRight size={14} weight="bold" aria-hidden />
                </button>
              </div>
            </div>

            {categoryNames.length === 0 && (
              <p role="status" className="rounded-[12px] border border-line bg-ink/[0.04] p-2.5 text-xs leading-snug text-ink">
                You have no categories yet. Each calendar can become a new one below, or add your own in the sidebar first.
              </p>
            )}

            {failure && (
              <div role="alert" className="flex gap-2 rounded-[12px] border border-danger/30 bg-danger/10 p-2.5 text-xs leading-snug text-ink">
                <WarningCircle size={16} weight="bold" className="mt-px shrink-0 text-danger" aria-hidden />
                <p className="min-w-0 break-words">
                  {failure.code === "setup" ? "Calendar access isn't set up yet. Run this once in the DayOptimizer folder, then try again:" : failure.message}
                  {failure.code === "setup" && (
                    <code className="mt-1.5 block rounded-md bg-linen px-2 py-1 font-mono text-[11px] text-ink">scripts/install.sh</code>
                  )}
                </p>
              </div>
            )}

            {!found ? (
              <>
                {source === "file" ? (
                  <p className="text-xs text-ink-dim">Supports iCalendar files (.ics), one or more at a time.</p>
                ) : (
                  loading && <p className="text-xs text-ink-dim">Reading your calendar. The first time, macOS may ask for permission.</p>
                )}
                <div className="flex justify-end">
                  {source === "file" ? (
                      <button type="button" onClick={() => picker.current?.click()} disabled={loading} className={`${primary} select-none`}>
                        {loading ? (
                          <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />
                        ) : (
                          <FileArrowUp size={16} weight="bold" aria-hidden />
                        )}
                        Choose .ics files
                      </button>
                  ) : (
                  <button type="button" onClick={() => load(monday)} disabled={loading} className={primary}>
                    {loading ? (
                      <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />
                    ) : failure ? (
                      <ArrowClockwise size={16} weight="bold" aria-hidden />
                    ) : (
                      <DownloadSimple size={16} weight="bold" aria-hidden />
                    )}
                    {failure ? "Try again" : "Load events"}
                  </button>
                  )}
                </div>
              </>
            ) : (
              <>
                <fieldset disabled={loading} className={loading ? "opacity-60" : undefined}>
                  <legend className="sr-only">Calendars to import</legend>
                  {source === "file" && files && (
                    <div className="mb-1.5 flex items-center gap-2 text-xs text-ink-dim">
                      <p className="min-w-0 flex-1 truncate" title={files.names.join(", ")}>
                        From {files.names.join(", ")}
                      </p>
                      <button type="button" onClick={() => picker.current?.click()} className="shrink-0 font-medium text-ink underline decoration-line underline-offset-2 hover:decoration-accent">
                        Change files
                      </button>
                    </div>
                  )}
                  {busy.length === 0 && elsewhere > 0 ? (
                    <div role="status" className="flex flex-wrap items-center justify-between gap-2 text-sm text-ink-dim">
                      <p>
                        Nothing {target}, but this week has {elsewhere} {elsewhere === 1 ? "event" : "events"} on other days.
                      </p>
                      <button type="button" onClick={() => setMode("week")} className={arrowText}>
                        Import the whole week
                      </button>
                    </div>
                  ) : span ? (
                    <div role="status" className="flex flex-wrap items-center justify-between gap-2 text-sm text-ink-dim">
                      <p>
                        Nothing {target}. {span[0] === span[1] ? `This file's events are on ${long(span[0])}.` : `This file's events run from ${long(span[0])} to ${long(span[1])}.`}
                      </p>
                      <button type="button" onClick={() => jumpTo(span[1])} className={arrowText}>
                        Go to {short(span[1])}
                      </button>
                    </div>
                  ) : busy.length === 0 ? (
                    <p className="text-sm text-ink-dim">No timed events {target}. Try another {mode}, or draw it by hand.</p>
                  ) : (
                    <label className="mb-1 flex cursor-pointer items-center gap-2 px-1 text-sm font-medium">
                      <input
                        type="checkbox"
                        checked={allOn}
                        onChange={() => setInclude((m) => ({ ...m, ...Object.fromEntries(busy.map(([c]) => [c, !allOn])) }))}
                        className="size-4 accent-[#f4b860]"
                      />
                      All calendars
                    </label>
                  )}
                  <ul className="scroll-thin flex max-h-60 flex-col gap-1 overflow-y-auto">
                    {calendars.map(([cal, n]) => {
                      const empty = n === 0;
                      const flagged = cal === missing;
                      return (
                        <li key={cal} className={`flex min-h-8 items-center gap-2 px-1 text-sm ${empty ? "opacity-45" : ""}`}>
                          <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2" title={cal}>
                            <input
                              type="checkbox"
                              disabled={empty}
                              checked={!empty && !!include[cal]}
                              onChange={(e) => setInclude((m) => ({ ...m, [cal]: e.target.checked }))}
                              className="size-4 shrink-0 accent-[#f4b860]"
                            />
                            <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ background: found.calendars[cal] || "currentColor" }} />
                            <span className="truncate">{cal}</span>
                            {google.has(cal) && (
                              <span className="shrink-0 rounded-full border border-line px-1.5 text-[10px] leading-4 text-ink-dim">Google</span>
                            )}
                            <span className="font-mono text-xs text-ink-dim tabular-nums">{n}</span>
                          </label>
                          {!empty && include[cal] && (
                            <select
                              aria-label={`Category for ${cal}`}
                              aria-invalid={flagged || undefined}
                              value={mapping[cal] ?? ""}
                              onChange={(e) => setMapping((m) => ({ ...m, [cal]: e.target.value }))}
                              className={`h-8 w-40 shrink-0 rounded-[10px] border bg-linen px-2 text-sm text-ink outline-none focus:border-accent ${flagged ? "border-accent ring-2 ring-accent/40" : "border-line"}`}
                            >
                              <option value="" disabled>
                                Choose category…
                              </option>
                              {categoryNames.map((c) => (
                                <option key={c} value={c}>
                                  {categories[c].emoji ? `${categories[c].emoji} ${c}` : c}
                                </option>
                              ))}
                              {!categoryNames.some((c) => c.toLowerCase() === cal.toLowerCase()) && (
                                <option value={NEW}>+ New “{cal.slice(0, 40)}”</option>
                              )}
                            </select>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </fieldset>
                {skipped.length > 0 && (
                  <p className="text-xs leading-snug text-ink-dim">
                    Skipped {skipped.length} all-day {skipped.length === 1 ? "event" : "events"} (
                    {skipped.slice(0, 3).map((e) => e.title || e.calendar).join(", ")}
                    {skipped.length > 3 && ` and ${skipped.length - 3} more`}): a block needs a start and end time. Draw them by hand if they belong in your routine.
                  </p>
                )}
                {mode === "day" && !oneDay && (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-ink-dim">Use this day for</span>
                    <Segmented
                      label="Use this day for"
                      options={[
                        { id: "all", label: "Every day" },
                        { id: "weekdays", label: "Mon–Fri" },
                        { id: "one", label: `Only ${dayName}` },
                      ]}
                      value={spread}
                      onChange={setSpread}
                      pill="import-spread"
                    />
                  </div>
                )}
                <div role="radiogroup" aria-label="How to import" className="flex flex-col gap-1 text-sm">
                  {[
                    { v: false, label: mode === "week" ? "Add to my typical week" : spread === "one" ? `Add to my ${dayName}` : "Add to those days" },
                    { v: true, label: mode === "week" ? "Replace my typical week" : spread === "one" ? `Replace my ${dayName}` : "Replace those days" },
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
                <div className="flex items-center justify-end gap-2">
                  <button type="button" onClick={confirm} disabled={loading || !!missing || count === 0} className={primary}>
                    {missing
                      ? `Choose a category for ${missing.slice(0, 24)}`
                      : count === 0
                        ? "Tick a calendar to import"
                        : `Import ${count} ${count === 1 ? "event" : "events"}${mode === "day" && into.length > 1 ? ` into ${into.length} days` : ""}`}
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
