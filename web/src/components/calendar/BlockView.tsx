import { memo } from "react";
import { motion } from "motion/react";
import type { Block, Weekday } from "../../lib/types";
import { toMin } from "../../lib/time";
import { DAY_NAME, PX_PER_MIN, readableText, type Lane } from "./geometry";
import type { DragHandlers } from "./useGridDrag";

export const SPRING = { type: "spring", stiffness: 400, damping: 32 } as const;

interface Props {
  block: Block;
  day: Weekday;
  color: string;
  lane: Lane;
  fresh: boolean;
  dragging: boolean;
  drag: DragHandlers;
  onOpen: (id: string, day: Weekday) => void;
}

function BlockView({ block: b, day, color, lane, fresh, dragging, drag, onOpen }: Props) {
  const s = toMin(b.start);
  const dur = toMin(b.end) - s;
  const label = b.title || b.category;
  const compact = dur < 45;
  const time = `${b.start} - ${b.end}`;
  const ink = readableText(color);

  return (
    <motion.button
      type="button"
      data-block-id={b.id}
      layoutId={b.id}
      layout
      transition={SPRING}
      initial={fresh ? { opacity: 0, scale: 0.96 } : false}
      animate={{ opacity: 1, scale: 1 }}
      aria-label={`${b.title ? `${b.title} (${b.category})` : b.category}, ${DAY_NAME[day]} ${b.start} to ${b.end}`}
      onPointerDown={(e) => drag.onBlockPointerDown(e, b, day)}
      onClick={() => {
        if (!drag.takeSuppressClick()) onOpen(b.id, day);
      }}
      className={`absolute z-[1] overflow-hidden rounded-[10px] text-left transition-[filter,box-shadow] hover:z-10 hover:brightness-110 hover:ring-2 hover:ring-white/40 focus-visible:z-10 focus-visible:outline-offset-1 ${
        dragging ? "z-20 cursor-grabbing shadow-lg" : "cursor-grab"
      }`}
      style={{
        top: s * PX_PER_MIN + 1,
        height: Math.max(dur * PX_PER_MIN - 2, 8),
        left: `calc(${(lane.lane / lane.lanes) * 100}% + 2px)`,
        width: `calc(${100 / lane.lanes}% - 4px)`,
        background: `${color}d9`,
        color: ink,
        // Darker left edge + hairline border give each block a crisp outline on the grid.
        boxShadow: "inset 3px 0 0 rgb(0 0 0 / 0.3), inset 0 0 0 1px rgb(255 255 255 / 0.14)",
        touchAction: "none",
      }}
    >
      <motion.span layout="position" transition={SPRING} className={`block pl-2.5 pr-1.5 ${dur <= 15 ? "py-0" : compact ? "py-[3px]" : "py-1"}`}>
        {compact ? (
          <span className={`flex items-baseline gap-1.5 truncate leading-none ${dur <= 15 ? "text-[11px]" : dur < 30 ? "text-[12px]" : "text-[13px]"}`}>
            <span className="truncate font-medium">{label}</span>
            <span className="font-mono text-[11px] opacity-85">{b.start}</span>
          </span>
        ) : (
          <>
            <span className="block truncate text-[13px] font-medium leading-tight">{label}</span>
            <span className="block font-mono text-[11px] opacity-85">{time}</span>
          </>
        )}
      </motion.span>
      <span data-handle aria-hidden className="absolute inset-x-0 bottom-0 h-2 cursor-ns-resize" />
    </motion.button>
  );
}

export default memo(BlockView);
