import { useCallback, useEffect, useLayoutEffect, useRef, useState, type JSX } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { CalendarPlus, Tag } from "@phosphor-icons/react";
import { WEEKDAYS, WEEKDAY_LABEL, type Block, type Categories, type View, type Week, type Weekday } from "../lib/types";
import { categoryColor } from "../lib/colors";
import { durationLabel, fromMin, sceneHour, toMin, uid } from "../lib/time";
import DayColumn from "./calendar/DayColumn";
import Editor from "./calendar/Editor";
import Toolbar from "./calendar/Toolbar";
import { DRAFT_ID, GRID_H, HOUR_PX, PX_PER_MIN, SURFACE, todayKey } from "./calendar/geometry";
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
  backgroundColor: SURFACE,
  backgroundImage: `repeating-linear-gradient(to bottom,
    rgb(255 255 255 / 0.11) 0 1px, transparent 1px ${HOUR_PX / 2}px,
    rgb(255 255 255 / 0.045) ${HOUR_PX / 2}px ${HOUR_PX / 2 + 1}px, transparent ${HOUR_PX / 2 + 1}px ${HOUR_PX}px)`,
};

const dayTotal = (blocks: Block[]) => {
  const m = blocks.reduce((t, b) => t + toMin(b.end) - toMin(b.start), 0);
  return m ? durationLabel(m) : "0h";
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

  const addFirstBlock = () => {
    if (!newCat) return;
    const id = uid();
    const el = scrollRef.current;
    if (el) el.scrollTop = Math.max(0, 8 * HOUR_PX);
    onChange((w) => ({ ...w, [today]: [...w[today], { id, start: "09:00", end: "10:00", category: newCat, title: "" }] }));
    if (view === "day") onDayChange(today);
    setFreshId(id);
    setEditing(id);
  };

  return (
    <section aria-label="Typical week" className="glass flex flex-col gap-4 rounded-[20px] p-4 md:p-5">
      <Toolbar view={view} day={day} week={week} onDayChange={onDayChange} onChange={onChange} />

      <div className="relative">
      <motion.div
        ref={scrollRef}
        layoutScroll
        className="scroll-thin relative h-[70dvh] min-h-[420px] select-none overflow-auto rounded-[14px] border border-line lg:h-[calc(100dvh-330px)]"
        style={{ backgroundColor: SURFACE }}
      >
        <div data-cal-grid className={view === "week" ? "min-w-[760px]" : ""}>
          {view === "week" && (
            <div className="sticky top-0 z-40 grid grid-cols-[3.5rem_1fr] border-b border-line" style={{ backgroundColor: SURFACE }}>
              <div className="sticky left-0" style={{ backgroundColor: SURFACE }} />
              <div className="grid grid-cols-7">
                {WEEKDAYS.map((d) => (
                  <div
                    key={d}
                    className={`flex flex-col items-center gap-0.5 border-l border-line py-2 ${
                      d === today ? "bg-accent/10" : ""
                    }`}
                  >
                    <span
                      className={`rounded-full px-2 text-sm font-medium ${
                        d === today ? "bg-accent text-night" : "text-ink"
                      }`}
                    >
                      {WEEKDAY_LABEL[d]}
                      {d === today && <span className="sr-only"> (today)</span>}
                    </span>
                    <span className="font-mono text-[11px] text-ink-dim">
                      <span className="sr-only">Planned: </span>
                      {dayTotal(week[d])}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-[3.5rem_1fr]">
            <div aria-hidden className="sticky left-0 z-30 border-r border-line" style={{ height: GRID_H, backgroundColor: SURFACE }}>
              <div className="relative h-full">
                {HOURS.map((h) => (
                  <span
                    key={h}
                    className={`absolute right-2 font-mono text-xs text-ink-dim ${h === 0 ? "" : "-translate-y-1/2"}`}
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
                  tint={d === today ? "today" : d === "sat" || d === "sun" ? "weekend" : null}
                  canCreate={hasCats && !editing && !preview}
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
            </div>
          </div>
        </div>
      </motion.div>

      {(!hasCats || (weekEmpty && !editing)) && (
        <div className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center p-4">
          <div className="glass-strong pointer-events-auto flex max-w-sm flex-col items-center gap-3 rounded-[20px] px-6 py-6 text-center shadow-2xl">
            <span className="grid size-11 place-items-center rounded-full bg-accent/15 text-accent">
              {hasCats ? <CalendarPlus weight="bold" size={22} /> : <Tag weight="bold" size={22} />}
            </span>
            <h2 className="text-base font-medium text-ink">{hasCats ? "Your week is empty" : "No categories yet"}</h2>
            <p className="text-sm text-ink-dim">
              {hasCats
                ? "Drag on any day to draw a block, or click an empty slot to add one hour."
                : "Add a category in the sidebar first. Every block needs one."}
            </p>
            {hasCats && (
              <button
                type="button"
                onClick={addFirstBlock}
                className="mt-1 flex min-h-9 items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-night transition active:scale-[0.98]"
              >
                <CalendarPlus weight="bold" size={16} /> Add first block
              </button>
            )}
          </div>
        </div>
      )}
      </div>

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
