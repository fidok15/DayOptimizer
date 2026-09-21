import { memo, useMemo } from "react";
import type { Block, Categories, Weekday } from "../../lib/types";
import { categoryColor } from "../../lib/colors";
import { durationLabel, fromMin } from "../../lib/time";
import BlockView from "./BlockView";
import { PX_PER_MIN, layoutLanes } from "./geometry";
import type { DragHandlers, Preview } from "./useGridDrag";

interface Props {
  day: Weekday;
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

function DayColumn({ day, blocks, categories, draft, draftColor, draggingId, freshId, nowMin, drag, onOpen }: Props) {
  const lanes = useMemo(() => layoutLanes(blocks), [blocks]);

  return (
    <div
      className="relative border-l border-line"
      style={{ touchAction: "pan-x pan-y" }}
      onPointerDown={(e) => drag.onColumnPointerDown(e, day)}
    >
      {blocks.map((b) => (
        <BlockView
          key={b.id}
          block={b}
          day={day}
          color={categoryColor(b.category, categories[b.category]?.color)}
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
          className="pointer-events-none absolute inset-x-[2px] z-20 rounded-[10px] border border-dashed px-2 py-1 font-mono text-[10.5px] text-ink"
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
