import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type RefObject } from "react";
import { WEEKDAYS, type Block, type View, type Weekday } from "../../lib/types";
import { DAY_MIN, SNAP, snap, toMin } from "../../lib/time";
import { DRAFT_ID, PX_PER_MIN, clamp } from "./geometry";

/** Live position of the block being dragged (or the draft being drawn), in minutes. */
export interface Preview { id: string; from: Weekday; day: Weekday; start: number; end: number }

type Gesture = { x0: number; y0: number; moved: boolean; day: Weekday } & (
  | { kind: "create"; anchor: number; floor: number }
  | { kind: "move"; id: string; offset: number; dur: number }
  | { kind: "resize"; id: string; start: number }
);

export interface DragOpts {
  colsRef: RefObject<HTMLDivElement | null>;
  view: View;
  /** Called on pointerdown on empty space; return false to block creation. */
  canCreate: () => boolean;
  onDragStart: () => void;
  onCreate: (day: Weekday, start: number, end: number) => void;
  onCommit: (p: Preview) => void;
}

export interface DragHandlers {
  onColumnPointerDown: (e: RPointerEvent<HTMLElement>, day: Weekday) => void;
  onBlockPointerDown: (e: RPointerEvent<HTMLElement>, b: Block, day: Weekday) => void;
  /** True once if the last pointer gesture was a drag, so the following click is ignored. */
  takeSuppressClick: () => boolean;
}

const DRAG_THRESHOLD = 4;

export function useGridDrag(o: DragOpts): { preview: Preview | null; handlers: DragHandlers } {
  const opts = useRef(o);
  opts.current = o;
  const [preview, setPreview] = useState<Preview | null>(null);

  const api = useMemo(() => {
    let g: Gesture | null = null;
    let current: Preview | null = null;
    let suppress = false;

    const set = (p: Preview | null) => {
      const c = current;
      if (c && p && c.id === p.id && c.day === p.day && c.start === p.start && c.end === p.end) return;
      current = p;
      setPreview(p);
    };

    const slot = (x: number, y: number) => {
      const el = opts.current.colsRef.current;
      if (!el) return { dayIdx: 0, min: 0 };
      const r = el.getBoundingClientRect();
      return {
        dayIdx: clamp(Math.floor(((x - r.left) / r.width) * 7), 0, 6),
        min: clamp((y - r.top) / PX_PER_MIN, 0, DAY_MIN),
      };
    };

    const onMove = (e: PointerEvent) => {
      if (!g) return;
      if (!g.moved && Math.hypot(e.clientX - g.x0, e.clientY - g.y0) < DRAG_THRESHOLD) return;
      g.moved = true;
      const { dayIdx, min } = slot(e.clientX, e.clientY);
      if (g.kind === "create") {
        const m = snap(min);
        let s = Math.min(g.anchor, m);
        let end = Math.max(g.anchor, m);
        if (end - s < SNAP) end = s + SNAP;
        if (end > DAY_MIN) [s, end] = [DAY_MIN - SNAP, DAY_MIN];
        set({ id: DRAFT_ID, from: g.day, day: g.day, start: s, end });
      } else if (g.kind === "move") {
        const s = clamp(snap(min - g.offset), 0, DAY_MIN - g.dur);
        const day = opts.current.view === "week" ? WEEKDAYS[dayIdx] : g.day;
        set({ id: g.id, from: g.day, day, start: s, end: s + g.dur });
      } else {
        set({ id: g.id, from: g.day, day: g.day, start: g.start, end: clamp(snap(min), g.start + SNAP, DAY_MIN) });
      }
    };

    const stop = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };

    function onUp(e: PointerEvent) {
      stop();
      const cur = g;
      const p = current;
      g = null;
      set(null);
      if (!cur) return;
      // The click that follows a block drag must not open the editor; clear it after that click.
      suppress = cur.moved && cur.kind !== "create";
      if (suppress) setTimeout(() => (suppress = false), 0);
      if (e.type === "pointercancel") return;
      if (cur.kind === "create") {
        if (cur.moved && p) opts.current.onCreate(cur.day, p.start, p.end);
        else {
          const s = Math.min(cur.floor, DAY_MIN - 60);
          opts.current.onCreate(cur.day, s, s + 60);
        }
      } else if (cur.moved && p) {
        opts.current.onCommit(p);
      }
    }

    const begin = (e: RPointerEvent<HTMLElement>, gesture: Gesture) => {
      stop();
      e.currentTarget.setPointerCapture(e.pointerId);
      g = gesture;
      suppress = false;
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    };

    const handlers: DragHandlers = {
      onColumnPointerDown(e, day) {
        if (e.button !== 0 || (e.target as HTMLElement).closest("[data-block-id]")) return;
        if (!opts.current.canCreate()) return;
        const { min } = slot(e.clientX, e.clientY);
        begin(e, {
          kind: "create", day, x0: e.clientX, y0: e.clientY, moved: false,
          anchor: snap(min), floor: Math.floor(min / SNAP) * SNAP,
        });
      },
      onBlockPointerDown(e, b, day) {
        if (e.button !== 0) return;
        opts.current.onDragStart();
        const base = { day, x0: e.clientX, y0: e.clientY, moved: false, id: b.id };
        const s = toMin(b.start);
        if ((e.target as HTMLElement).closest("[data-handle]")) begin(e, { ...base, kind: "resize", start: s });
        else {
          const { min } = slot(e.clientX, e.clientY);
          begin(e, { ...base, kind: "move", offset: min - s, dur: toMin(b.end) - s });
        }
      },
      takeSuppressClick() {
        const v = suppress;
        suppress = false;
        return v;
      },
    };
    return { handlers, stop };
  }, []);

  useEffect(() => api.stop, [api]);

  return { preview, handlers: api.handlers };
}
