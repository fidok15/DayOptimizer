import { NotePencil } from "@phosphor-icons/react";

const MAX = 2000;

/** Free-text habits and wishes that rules can't express. Goes into the routine
 *  brief the assistant reads, not into the deterministic planner. */
export default function Notes({ notes, onChange }: { notes: string; onChange: (text: string) => void }) {
  const left = MAX - notes.length;

  return (
    <section className="glass flex flex-col gap-2 rounded-[20px] p-4">
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
        className="scroll-thin w-full resize-y rounded-[12px] border border-line bg-white/5 p-3 text-sm leading-relaxed text-ink outline-none transition placeholder:text-ink-dim focus:border-accent"
      />
      <p className="self-end font-mono text-xs text-ink-dim tabular-nums" aria-live="polite">
        {left < 200 ? `${left} characters left` : ""}
      </p>
    </section>
  );
}
