import { memo, useMemo, useState } from "react";
import type { Block, Categories, Weekday } from "../../lib/types";
import { categoryColor } from "../../lib/colors";
import { DAY_MIN, SNAP, durationLabel, fromMin } from "../../lib/time";
import BlockView from "./BlockView";
import { PX_PER_MIN, layoutLanes } from "./geometry";
import type { DragHandlers, Preview } from "./useGridDrag";

interface Props {
  day: Weekday;
  tint: "today" | "weekend" | null;
  /** Show the hover ghost of a 1 h block (clicking would create it). */
  canCreate: boolean;
  blocks: Block[];
  categories: Categories;
  /** Draft being drawn in this column, if any. */
  draft: Preview | null;
  draftColor: string;
  draggingId: string | null;
  freshId: string | null;
  nowMin: number | null;
  drag: DragHandlers;
  onOpen: (id: string, day: Weekday) => void;
}

const TINT = { today: "bg-accent/[0.05]", weekend: "bg-white/[0.025]" };

function DayColumn({ day, tint, canCreate, blocks, categories, draft, draftColor, draggingId, freshId, nowMin, drag, onOpen }: Props) {
  const lanes = useMemo(() => layoutLanes(blocks), [blocks]);
  const [hover, setHover] = useState<number | null>(null);

  return (
    <div
      className={`relative border-l border-line ${tint ? TINT[tint] : ""}`}
      style={{ touchAction: "pan-x pan-y" }}
      onPointerDown={(e) => drag.onColumnPointerDown(e, day)}
      onPointerMove={(e) => {
        if (e.pointerType !== "mouse" || (e.target as HTMLElement).closest("[data-block-id]")) return setHover(null);
        const min = (e.clientY - e.currentTarget.getBoundingClientRect().top) / PX_PER_MIN;
        // Same slot a click creates (see useGridDrag): the 15 min floor, kept inside the day.
        setHover(Math.min(Math.floor(min / SNAP) * SNAP, DAY_MIN - 60));
      }}
      onPointerLeave={() => setHover(null)}
    >
      {canCreate && hover !== null && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-[2px] z-0 hidden rounded-[10px] border border-dashed border-white/25 bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-ink-dim pointer-fine:block"
          style={{ top: hover * PX_PER_MIN + 1, height: 60 * PX_PER_MIN - 2 }}
        >
          + {fromMin(hover)}
        </div>
      )}

      {blocks.map((b) => (
        <BlockView
          key={b.id}
          block={b}
          day={day}
          color={categoryColor(b.category, categories[b.category]?.color)}
          emoji={categories[b.category]?.emoji}
          lane={lanes.get(b.id) ?? { lane: 0, lanes: 1 }}
          fresh={b.id === freshId}
          dragging={b.id === draggingId}
          drag={drag}
          onOpen={onOpen}
        />
      ))}

      {draft && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-[2px] z-20 rounded-[10px] border border-dashed px-2 py-1 font-mono text-[11px] text-ink"
          style={{
            top: draft.start * PX_PER_MIN + 1,
            height: (draft.end - draft.start) * PX_PER_MIN - 2,
            borderColor: draftColor,
            background: `${draftColor}40`,
          }}
        >
          {fromMin(draft.start)} - {fromMin(draft.end)} · {durationLabel(draft.end - draft.start)}
        </div>
      )}

      {nowMin !== null && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 z-0 h-px bg-accent"
          style={{ top: nowMin * PX_PER_MIN }}
        >
          <span className="absolute -left-1 -top-[3px] size-[7px] rounded-full bg-accent" />
        </div>
      )}
    </div>
  );
}

export default memo(DayColumn);
