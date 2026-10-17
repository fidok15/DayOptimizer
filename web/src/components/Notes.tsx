import { NotePencil } from "@phosphor-icons/react";
import type { FreeTime, Variety } from "../lib/types";

const MAX = 2000;
const fieldCls =
  "rounded-[10px] border border-line bg-ink/5 px-2 py-1.5 text-sm text-ink outline-none transition focus:border-accent [&>option]:bg-[var(--surface)]";

export default function Notes({ notes, onChange, freeTime, onFreeTime }: {
  notes: string;
  onChange: (text: string) => void;
  freeTime: FreeTime;
  onFreeTime: (change: Partial<FreeTime>) => void;
}) {
  const left = MAX - notes.length;

  return (
    <section className="glass flex flex-col gap-2 rounded-2xl p-4">
      <div className="flex items-start gap-2">
        <NotePencil size={18} weight="bold" className="mt-0.5 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-tight">
            <label htmlFor="notes">Anything else DayOptimizer should know</label>
          </h2>
          <p className="mt-0.5 text-xs leading-snug text-ink-dim">
            Habits and wishes the calendar can't show. Your assistant reads this every time it plans.
          </p>
        </div>
      </div>
      <textarea
        id="notes"
        value={notes}
        maxLength={MAX}
        rows={4}
        onChange={(e) => onChange(e.target.value)}
        placeholder={"e.g. I don't eat before 11.\nNo hard training two days in a row.\nKeep Sunday evenings free for family.\nDeep work goes in the morning, meetings after 14:00."}
        className="scroll-thin w-full resize-y rounded-[12px] border border-line bg-ink/5 p-3 text-sm leading-relaxed text-ink outline-none transition placeholder:text-ink-dim focus:border-accent"
      />
      <p className="self-end font-mono text-xs text-ink-dim tabular-nums" aria-live="polite">
        {left < 200 ? `${left} characters left` : ""}
      </p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-dim">
        <label className="flex items-center gap-2">
          Completely free each day
          <input
            type="number"
            min={0}
            max={720}
            step={15}
            value={freeTime.min_free_minutes ?? ""}
            placeholder="60"
            onChange={(e) => {
              const n = e.target.valueAsNumber;
              if (e.target.value === "" || (n >= 0 && n <= 720)) onFreeTime({ min_free_minutes: e.target.value === "" ? null : Math.round(n) });
            }}
            className={`${fieldCls} w-20 tabular-nums`}
          />
          min
        </label>
        <label className="flex items-center gap-2">
          Variety in suggested activities
          <select
            value={freeTime.variety ?? "medium"}
            onChange={(e) => onFreeTime({ variety: e.target.value as Variety })}
            className={fieldCls}
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
      </div>
    </section>
  );
}
