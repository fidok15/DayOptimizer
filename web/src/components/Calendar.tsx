import { useCallback, useEffect, useLayoutEffect, useRef, useState, type JSX } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { WEEKDAYS, WEEKDAY_LABEL, type Block, type Categories, type View, type Week, type Weekday } from "../lib/types";
import { categoryColor } from "../lib/colors";
import { fromMin, sceneHour, toMin, uid } from "../lib/time";
import DayColumn from "./calendar/DayColumn";
import Editor from "./calendar/Editor";
import Toolbar from "./calendar/Toolbar";
import { DRAFT_ID, GRID_H, HOUR_PX, PX_PER_MIN, todayKey } from "./calendar/geometry";
import { useGridDrag, type Preview } from "./calendar/useGridDrag";

interface Props {
  view: View;
  week: Week;
  categories: Categories;
  day: Weekday;
  onDayChange: (d: Weekday) => void;
  onChange: (fn: (w: Week) => Week) => void;
  dayStart: string;
}

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const GRID_BG = {
  height: GRID_H,
  backgroundImage: `repeating-linear-gradient(to bottom,
    var(--color-line) 0 1px, transparent 1px ${HOUR_PX / 2}px,
    rgb(255 255 255 / 0.04) ${HOUR_PX / 2}px ${HOUR_PX / 2 + 1}px, transparent ${HOUR_PX / 2 + 1}px ${HOUR_PX}px)`,
};

/** Blocks of `d` with the in-flight move/resize applied, so only affected days get a new array. */
function shownBlocks(week: Week, d: Weekday, p: Preview | null): Block[] {
  if (!p || p.id === DRAFT_ID || (d !== p.from && d !== p.day)) return week[d];
  const orig = week[p.from].find((b) => b.id === p.id);
  if (!orig) return week[d];
  const moved = { ...orig, start: fromMin(p.start), end: fromMin(p.end) };
  if (d === p.from && d === p.day) return week[d].map((b) => (b.id === p.id ? moved : b));
  if (d === p.from) return week[d].filter((b) => b.id !== p.id);
  return [...week[d], moved];
}

export default function Calendar({ view, week, categories, day, onDayChange, onChange, dayStart }: Props): JSX.Element {
  const scrollRef = useRef<HTMLDivElement>(null);
  const colsRef = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [freshId, setFreshId] = useState<string | null>(null);
  const lastCat = useRef<string | null>(null);
  const [nowMin, setNowMin] = useState(() => Math.round(sceneHour() * 60));
  const today = todayKey();
  const catNames = Object.keys(categories);
  const hasCats = catNames.length > 0;
  const newCat = lastCat.current && categories[lastCat.current] ? lastCat.current : catNames[0];

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = Math.max(0, toMin(dayStart) * PX_PER_MIN - 8);
    // Only on mount: later dayStart changes must not yank the user's scroll position.
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNowMin(Math.round(sceneHour() * 60)), 60_000);
    return () => clearInterval(t);
  }, []);

  const editingRef = useRef(editing);
  editingRef.current = editing;
  const hasCatsRef = useRef(hasCats);
  hasCatsRef.current = hasCats;

  const { preview, handlers } = useGridDrag({
    colsRef,
    view,
    canCreate: () => {
      // First click on empty space while the editor is open only closes it.
      if (editingRef.current) {
        setEditing(null);
        return false;
      }
      return hasCatsRef.current;
    },
    onDragStart: () => setEditing(null),
    onCreate: (d, start, end) => {
      if (!newCat) return;
      const id = uid();
      onChange((w) => ({ ...w, [d]: [...w[d], { id, start: fromMin(start), end: fromMin(end), category: newCat, title: "" }] }));
      setFreshId(id);
      setEditing(id);
    },
    onCommit: (p) =>
      onChange((w) => {
        const orig = w[p.from].find((b) => b.id === p.id);
        if (!orig) return w;
        const moved = { ...orig, start: fromMin(p.start), end: fromMin(p.end) };
        if (p.from === p.day) return { ...w, [p.day]: w[p.day].map((b) => (b.id === p.id ? moved : b)) };
        return { ...w, [p.from]: w[p.from].filter((b) => b.id !== p.id), [p.day]: [...w[p.day], moved] };
      }),
  });

  const openEditor = useCallback((id: string) => setEditing(id), []);

  // Locate the edited block anywhere in the week (it may have been moved).
  let edited: { block: Block; day: Weekday } | null = null;
  if (editing) {
    for (const d of WEEKDAYS) {
      const b = week[d].find((x) => x.id === editing);
      if (b) edited = { block: b, day: d };
    }
  }
  useEffect(() => {
    if (editing && !edited) setEditing(null);
  }, [editing, edited]);

  const closeEditor = useCallback((returnFocus: boolean) => {
    const id = editingRef.current;
    setEditing(null);
    if (returnFocus && id) {
      requestAnimationFrame(() =>
        document.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true }),
      );
    }
  }, []);

  const updateEdited = (patch: Partial<Omit<Block, "id">>) => {
    if (!edited) return;
    const { day: d, block } = edited;
    if (patch.category) lastCat.current = patch.category;
    onChange((w) => ({ ...w, [d]: w[d].map((b) => (b.id === block.id ? { ...b, ...patch } : b)) }));
  };
  const deleteEdited = () => {
    if (!edited) return;
    const { day: d, block } = edited;
    onChange((w) => ({ ...w, [d]: w[d].filter((b) => b.id !== block.id) }));
    setEditing(null);
  };

  const days = view === "week" ? WEEKDAYS : [day];
  const weekEmpty = WEEKDAYS.every((d) => week[d].length === 0) && !preview;
  const draftColor = newCat ? categoryColor(newCat, categories[newCat]?.color) : "#f4b860";
  const hintTop = toMin(dayStart) * PX_PER_MIN + 3 * HOUR_PX;

  return (
    <section aria-label="Typical week" className="glass flex flex-col gap-4 rounded-[20px] p-4 md:p-5">
      <Toolbar view={view} day={day} week={week} onDayChange={onDayChange} onChange={onChange} />

      <motion.div
        ref={scrollRef}
        layoutScroll
        className="scroll-thin relative max-h-[calc(100dvh-260px)] min-h-[420px] select-none overflow-auto rounded-[14px] border border-line"
      >
        <div data-cal-grid className={view === "week" ? "min-w-[760px]" : ""}>
          {view === "week" && (
            <div className="sticky top-0 z-40 grid grid-cols-[3.25rem_1fr] border-b border-line bg-[var(--glass-strong)] backdrop-blur-md">
              <div className="sticky left-0 bg-[var(--glass-strong)]" />
              <div className="grid grid-cols-7">
                {WEEKDAYS.map((d) => (
                  <div
                    key={d}
                    className={`flex items-center justify-center gap-1.5 border-l border-line py-2 text-sm ${
                      d === today ? "font-medium text-accent" : "text-ink-dim"
                    }`}
                  >
                    {WEEKDAY_LABEL[d]}
                    {d === today && <span className="sr-only">(today)</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-[3.25rem_1fr]">
            <div aria-hidden className="sticky left-0 z-30 bg-[var(--glass-strong)]" style={{ height: GRID_H }}>
              <div className="relative h-full">
                {HOURS.map((h) => (
                  <span
                    key={h}
                    className={`absolute right-2 font-mono text-[11px] text-ink-dim ${h === 0 ? "" : "-translate-y-1/2"}`}
                    style={{ top: h === 0 ? 2 : h * HOUR_PX }}
                  >
                    {String(h).padStart(2, "0")}:00
                  </span>
                ))}
              </div>
            </div>

            <div
              ref={colsRef}
              className={`relative grid ${view === "week" ? "grid-cols-7" : "grid-cols-1"} ${hasCats ? "cursor-cell" : ""}`}
              style={GRID_BG}
            >
              {days.map((d) => (
                <DayColumn
                  key={d}
                  day={d}
                  blocks={shownBlocks(week, d, preview)}
                  categories={categories}
                  draft={preview?.id === DRAFT_ID && preview.day === d ? preview : null}
                  draftColor={draftColor}
                  draggingId={preview && preview.id !== DRAFT_ID ? preview.id : null}
                  freshId={freshId}
                  nowMin={d === today ? nowMin : null}
                  drag={handlers}
                  onOpen={openEditor}
                />
              ))}

              {(!hasCats || weekEmpty) && (
                <p
                  className="pointer-events-none absolute inset-x-4 z-10 text-center text-sm text-ink-dim"
                  style={{ top: hintTop }}
                >
                  {hasCats
                    ? "Drag on a day to add your first block"
                    : "Add a category in the sidebar first. Every block needs one."}
                </p>
              )}
            </div>
          </div>
        </div>
      </motion.div>

      {createPortal(
        <AnimatePresence>
          {edited && (
            <Editor
              key={edited.block.id}
              block={edited.block}
              categories={categories}
              onUpdate={updateEdited}
              onDelete={deleteEdited}
              onClose={closeEditor}
            />
          )}
        </AnimatePresence>,
        document.body,
      )}
    </section>
  );
}
