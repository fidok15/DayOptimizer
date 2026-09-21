import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, Copy, Eraser, Info } from "@phosphor-icons/react";
import { WEEKDAYS, WEEKDAY_LABEL, type View, type Week, type Weekday } from "../../lib/types";
import { uid } from "../../lib/time";
import { DAY_NAME, todayKey } from "./geometry";

interface Props {
  view: View;
  day: Weekday;
  week: Week;
  onDayChange: (d: Weekday) => void;
  onChange: (fn: (w: Week) => Week) => void;
}

const ghost =
  "flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-sm text-ink-dim transition hover:text-ink active:scale-[0.98] disabled:pointer-events-none disabled:opacity-40";
const primary =
  "flex items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-night transition active:scale-[0.98] disabled:opacity-40";

const PICKS: [string, Weekday[]][] = [
  ["Weekdays", ["mon", "tue", "wed", "thu", "fri"]],
  ["Weekend", ["sat", "sun"]],
  ["All", [...WEEKDAYS]],
];

export default function Toolbar({ view, day, week, onDayChange, onChange }: Props) {
  if (view === "week") {
    return (
      <p className="flex items-center gap-2 text-sm text-ink-dim">
        <Info weight="bold" size={16} />
        Drag on a day to add a block. Drag a block to move it, or its bottom edge to resize.
      </p>
    );
  }
  const today = todayKey();
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div role="tablist" aria-label="Day" className="flex flex-wrap gap-1.5">
        {WEEKDAYS.map((d) => (
          <button
            key={d}
            type="button"
            role="tab"
            aria-selected={d === day}
            aria-label={DAY_NAME[d]}
            onClick={() => onDayChange(d)}
            className={`rounded-full px-3 py-1.5 text-sm transition active:scale-[0.98] ${
              d === day ? "bg-accent font-medium text-night" : "text-ink-dim hover:bg-white/5 hover:text-ink"
            }`}
          >
            {WEEKDAY_LABEL[d]}
            {d === today && d !== day && <span className="ml-1 inline-block size-1.5 rounded-full bg-accent align-middle" />}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <CopyDay day={day} disabled={week[day].length === 0} onChange={onChange} />
        <ClearDay key={day} day={day} disabled={week[day].length === 0} onChange={onChange} />
      </div>
    </div>
  );
}

function CopyDay({ day, disabled, onChange }: { day: Weekday; disabled: boolean; onChange: Props["onChange"] }) {
  const [open, setOpen] = useState(false);
  const [targets, setTargets] = useState<Set<Weekday>>(new Set());
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = (d: Weekday) =>
    setTargets((t) => {
      const n = new Set(t);
      if (n.has(d)) n.delete(d);
      else n.add(d);
      return n;
    });

  const confirm = () => {
    const picked = [...targets].filter((d) => d !== day);
    onChange((w) => {
      const next = { ...w };
      for (const d of picked) next[d] = w[day].map((b) => ({ ...b, id: uid() }));
      return next;
    });
    setOpen(false);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => {
          setTargets(new Set());
          setOpen((o) => !o);
        }}
        className={ghost}
      >
        <Copy weight="bold" size={16} /> Copy day
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label={`Copy ${DAY_NAME[day]} to other days`}
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 400, damping: 32 }}
            style={{ transformOrigin: "top right" }}
            className="glass-strong absolute right-0 top-full z-40 mt-2 flex w-64 flex-col gap-3 rounded-[20px] p-4 shadow-2xl"
          >
            <p className="text-xs text-ink-dim">
              Copy {DAY_NAME[day]} to these days. Their blocks will be replaced.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {PICKS.map(([label, days]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => setTargets(new Set(days.filter((d) => d !== day)))}
                  className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-dim transition hover:text-ink active:scale-[0.98]"
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-1">
              {WEEKDAYS.map((d) => (
                <label
                  key={d}
                  className={`flex items-center gap-2 rounded-[10px] px-2 py-1.5 text-sm ${
                    d === day ? "opacity-40" : "cursor-pointer hover:bg-white/5"
                  }`}
                >
                  <input
                    type="checkbox"
                    disabled={d === day}
                    checked={targets.has(d)}
                    onChange={() => toggle(d)}
                    className="size-4 accent-[#f4b860]"
                  />
                  {DAY_NAME[d]}
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setOpen(false)} className={ghost}>Cancel</button>
              <button type="button" disabled={targets.size === 0} onClick={confirm} className={primary}>
                <Check weight="bold" size={16} /> Copy
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ClearDay({ day, disabled, onChange }: { day: Weekday; disabled: boolean; onChange: Props["onChange"] }) {
  const [confirming, setConfirming] = useState(false);
  if (!confirming) {
    return (
      <button type="button" disabled={disabled} onClick={() => setConfirming(true)} className={ghost}>
        <Eraser weight="bold" size={16} /> Clear day
      </button>
    );
  }
  return (
    <div className="flex items-center gap-2" role="group" aria-label={`Clear ${DAY_NAME[day]}?`}>
      <span className="text-sm text-ink-dim">Clear {DAY_NAME[day]}?</span>
      <button type="button" autoFocus onClick={() => setConfirming(false)} className={ghost}>Cancel</button>
      <button
        type="button"
        onClick={() => {
          onChange((w) => ({ ...w, [day]: [] }));
          setConfirming(false);
        }}
        className={primary}
      >
        Clear
      </button>
    </div>
  );
}
