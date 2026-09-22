import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, CalendarPlus, CircleNotch, DownloadSimple, WarningCircle } from "@phosphor-icons/react";
import { importWeek } from "../lib/api";
import { categoryColor, freshColor } from "../lib/colors";
import { uid } from "../lib/time";
import { usePopover } from "../lib/usePopover";
import { WEEKDAYS, type Categories, type ServerState, type Week } from "../lib/types";

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

export default function ImportCalendar(props: {
  categories: Categories;
  onImport: (week: Week, newCats: Categories, replace: boolean) => void;
}) {
  const { categories, onImport } = props;
  const { open, setOpen, ref } = usePopover();
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");
  const [found, setFound] = useState<ServerState["typical_week"] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [replace, setReplace] = useState(true);

  // calendar name -> number of blocks, biggest first
  const calendars = useMemo(() => {
    const n: Record<string, number> = {};
    for (const d of WEEKDAYS) for (const b of found?.[d] ?? []) n[b.category] = (n[b.category] ?? 0) + 1;
    return Object.entries(n).sort(([, a], [, b]) => b - a);
  }, [found]);

  const reset = () => {
    setFound(null);
    setStatus("idle");
    setError("");
  };

  const load = () => {
    setStatus("loading");
    importWeek(mondayISO(offset))
      .then((w) => {
        setFound(w);
        setPicked(new Set(Object.values(w).flatMap((bs) => (bs ?? []).map((b) => b.category))));
        setStatus("idle");
      })
      .catch((e: Error) => {
        setError(e.message);
        setStatus("error");
      });
  };

  const confirm = () => {
    if (!found) return;
    const week = Object.fromEntries(
      WEEKDAYS.map((d) => [d, (found[d] ?? []).filter((b) => picked.has(b.category)).map((b) => ({ ...b, id: uid() }))]),
    ) as Week;
    const taken = Object.entries(categories).map(([n, c]) => categoryColor(n, c.color));
    const newCats: Categories = {};
    for (const name of picked) {
      if (categories[name]) continue;
      const color = freshColor(name, taken);
      taken.push(color);
      newCats[name] = { movable: true, priority: 5, color };
    }
    onImport(week, newCats, replace);
    setOpen(false);
    reset();
  };

  const toggle = (name: string) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });

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
            className="glass-strong absolute right-0 top-full z-40 mt-2 flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-3 rounded-[20px] p-4 shadow-2xl"
          >
            <div>
              <h2 className="text-[15px] font-semibold tracking-tight">Import from your calendar</h2>
              <p className="mt-1 text-xs leading-snug text-ink-dim">
                Reads Apple Calendar, including Google and other accounts added in macOS Settings, Internet Accounts.
                Each calendar becomes a category.
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
                {status === "error" && (
                  <p role="alert" className="flex gap-1.5 text-xs text-[#ff8a80]">
                    <WarningCircle size={16} weight="bold" className="shrink-0" aria-hidden />
                    <span className="line-clamp-4 break-words">{error}</span>
                  </p>
                )}
                {status === "loading" && (
                  <p className="text-xs text-ink-dim">Reading your calendar. The first time, macOS may ask for permission.</p>
                )}
                <div className="flex justify-end">
                  <button type="button" onClick={load} disabled={status === "loading"} className={primary}>
                    {status === "loading" ? (
                      <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />
                    ) : (
                      <DownloadSimple size={16} weight="bold" aria-hidden />
                    )}
                    Load events
                  </button>
                </div>
              </>
            ) : calendars.length === 0 ? (
              <>
                <p className="text-sm text-ink-dim">No timed events that week.</p>
                <div className="flex justify-end">
                  <button type="button" onClick={reset} className={ghost}>
                    <ArrowLeft size={16} weight="bold" aria-hidden /> Pick another week
                  </button>
                </div>
              </>
            ) : (
              <>
                <fieldset>
                  <legend className="mb-1.5 text-xs text-ink-dim">Calendars to import</legend>
                  <ul className="scroll-thin flex max-h-52 flex-col gap-0.5 overflow-y-auto">
                    {calendars.map(([name, count]) => (
                      <li key={name}>
                        <label className="flex cursor-pointer items-center gap-2 rounded-[10px] px-2 py-1.5 text-sm hover:bg-white/5">
                          <input
                            type="checkbox"
                            checked={picked.has(name)}
                            onChange={() => toggle(name)}
                            className="size-4 accent-[#f4b860]"
                          />
                          <span className="min-w-0 flex-1 truncate" title={name}>
                            {categories[name]?.emoji && <span aria-hidden className="mr-1">{categories[name].emoji}</span>}
                            {name}
                          </span>
                          {!categories[name] && (
                            <span className="rounded-full bg-accent/15 px-1.5 text-[11px] font-medium text-accent">new</span>
                          )}
                          <span className="w-8 text-right font-mono text-xs text-ink-dim tabular-nums">{count}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </fieldset>
                <div role="radiogroup" aria-label="How to import" className="flex flex-col gap-1 text-sm">
                  {[
                    { v: true, label: "Replace my typical week" },
                    { v: false, label: "Add to my typical week" },
                  ].map((o) => (
                    <label key={String(o.v)} className="flex cursor-pointer items-center gap-2 px-2">
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
                <div className="flex justify-between gap-2">
                  <button type="button" onClick={reset} className={ghost}>
                    <ArrowLeft size={16} weight="bold" aria-hidden /> Back
                  </button>
                  <button type="button" onClick={confirm} disabled={picked.size === 0} className={primary}>
                    Import
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
