import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Check, Trash } from "@phosphor-icons/react";
import type { Block, Categories } from "../../lib/types";
import { categoryColor } from "../../lib/colors";
import { DAY_MIN, durationLabel, fromMin, toMin } from "../../lib/time";
import { clamp, normalizeRange } from "./geometry";

interface Props {
  block: Block;
  categories: Categories;
  onUpdate: (patch: Partial<Omit<Block, "id">>) => void;
  onDelete: () => void;
  /** returnFocus: put focus back on the block (keyboard close). */
  onClose: (returnFocus: boolean) => void;
}

const W = 300;
const M = 12;
// A time input cannot show 24:00, so an end of 00:00 means midnight at the end of the day.
const endToInput = (end: string) => (end === "24:00" ? "00:00" : end);
const endFromInput = (v: string) => (v === "00:00" ? DAY_MIN : toMin(v));

export default function Editor({ block, categories, onUpdate, onDelete, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const uidBase = useId();
  const [sheet] = useState(() => window.innerWidth < 640);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const [start, setStart] = useState(block.start);
  const [end, setEnd] = useState(endToInput(block.end));

  const s = toMin(start);
  const e = endFromInput(end);
  const error = !start || !end || Number.isNaN(s) || Number.isNaN(e)
    ? "Enter a start and end time."
    : e <= s ? "End time must be after start time." : "";

  // Anchor next to the block, flipping sides to stay inside the viewport.
  useLayoutEffect(() => {
    if (sheet) return;
    const anchor = document.querySelector(`[data-block-id="${CSS.escape(block.id)}"]`);
    const pop = ref.current;
    if (!anchor || !pop) return;
    const r = anchor.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = r.right + 10;
    if (left + W > vw - M) left = r.left - 10 - W;
    if (left < M) left = clamp(r.right - W - 8, M, vw - W - M);
    setPos({ left: clamp(left, M, Math.max(M, vw - W - M)), top: clamp(r.top, M, Math.max(M, vh - pop.offsetHeight - M)) });
  }, [block.id, sheet]);

  // A resize could push the popover off-screen; closing is simpler and safe (edits are already applied).
  // (Not for the mobile sheet: the on-screen keyboard fires resize while typing.)
  useEffect(() => {
    if (sheet) return;
    const onResize = () => onClose(false);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [onClose, sheet]);

  useEffect(() => {
    titleRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        onClose(true);
        return;
      }
      const el = document.activeElement;
      const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
      if ((ev.key === "Delete" || ev.key === "Backspace") && !typing) {
        ev.preventDefault();
        onDelete();
      }
    };
    const onDown = (ev: PointerEvent) => {
      const t = ev.target as Element;
      // The grid handles its own pointerdowns (closing, or starting a drag).
      if (ref.current?.contains(t) || t.closest("[data-cal-grid]")) return;
      onClose(false);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown, true);
    };
  }, [onClose, onDelete]);

  const applyTimes = (ns: string, ne: string) => {
    const a = toMin(ns);
    const b = endFromInput(ne);
    if (Number.isNaN(a) || Number.isNaN(b) || b <= a) return;
    const [rs, re] = normalizeRange(a, b);
    onUpdate({ start: fromMin(rs), end: fromMin(re) });
  };
  // Show the snapped result once the user leaves a field.
  const resync = () => {
    if (error) return;
    setStart(block.start);
    setEnd(endToInput(block.end));
  };

  const inputCls =
    "w-full rounded-[10px] border border-white/20 bg-white/[0.06] px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim/70 focus:border-accent";
  const labelCls = "text-xs font-medium text-ink-dim";

  return (
    <motion.div
      ref={ref}
      role="dialog"
      aria-label="Edit block"
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ type: "spring", stiffness: 400, damping: 32 }}
      className={`glass-strong scroll-thin fixed z-50 flex max-h-[calc(100dvh-24px)] flex-col gap-4 overflow-y-auto p-4 shadow-2xl ${
        sheet ? "inset-x-0 bottom-0 rounded-t-[20px] pb-6" : "rounded-[20px]"
      }`}
      style={sheet ? undefined : { width: W, left: pos?.left ?? 0, top: pos?.top ?? 0, visibility: pos ? "visible" : "hidden" }}
    >
      <fieldset className="flex flex-col gap-2">
        <legend className={`mb-2 ${labelCls}`}>Category</legend>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(categories).map(([name, cat]) => {
            const active = name === block.category;
            return (
              <button
                key={name}
                type="button"
                aria-pressed={active}
                onClick={() => onUpdate({ category: name })}
                className={`flex min-h-7 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[13px] transition active:scale-[0.98] ${
                  active ? "border-transparent bg-white/15 font-medium text-ink ring-2 ring-accent" : "border-white/20 text-ink hover:bg-white/10"
                }`}
              >
                <span className="size-2.5 rounded-full" style={{ background: categoryColor(name, cat.color) }} />
                {cat.emoji && <span aria-hidden>{cat.emoji}</span>}
                {name}
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${uidBase}-title`} className={labelCls}>Title</label>
        <input
          id={`${uidBase}-title`}
          ref={titleRef}
          type="text"
          maxLength={60}
          value={block.title}
          placeholder={block.category}
          onChange={(ev) => onUpdate({ title: ev.target.value })}
          onKeyDown={(ev) => ev.key === "Enter" && onClose(true)}
          className={inputCls}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="grid grid-cols-2 gap-2">
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uidBase}-start`} className={labelCls}>Start</label>
            <input
              id={`${uidBase}-start`}
              type="time"
              step={900}
              value={start}
              onChange={(ev) => { setStart(ev.target.value); applyTimes(ev.target.value, end); }}
              onBlur={resync}
              aria-invalid={!!error}
              className={`${inputCls} font-mono`}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uidBase}-end`} className={labelCls}>End</label>
            <input
              id={`${uidBase}-end`}
              type="time"
              step={900}
              value={end}
              onChange={(ev) => { setEnd(ev.target.value); applyTimes(start, ev.target.value); }}
              onBlur={resync}
              aria-invalid={!!error}
              aria-describedby={`${uidBase}-err`}
              className={`${inputCls} font-mono`}
            />
          </div>
        </div>
        <p id={`${uidBase}-err`} aria-live="polite" className={`min-h-4 text-xs ${error ? "text-[#f5988f]" : "text-ink-dim"}`}>
          {error || <>Duration: <span className="font-mono text-ink">{durationLabel(e - s)}</span></>}
        </p>
      </div>

      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onDelete}
          className="flex min-h-8 items-center gap-1.5 rounded-full border border-white/20 px-3 py-1.5 text-sm text-ink transition hover:border-[#f5988f]/60 hover:text-[#f5988f] active:scale-[0.98]"
        >
          <Trash weight="bold" size={16} /> Delete
        </button>
        <button
          type="button"
          onClick={() => onClose(true)}
          className="flex min-h-8 items-center gap-1.5 rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-night transition active:scale-[0.98]"
        >
          <Check weight="bold" size={16} /> Done
        </button>
      </div>
      {!sheet && (
        <p className="-mt-1 text-[11px] text-ink-dim">
          <kbd className="font-mono text-ink">Esc</kbd> to close, <kbd className="font-mono text-ink">Del</kbd> to delete
        </p>
      )}
    </motion.div>
  );
}
