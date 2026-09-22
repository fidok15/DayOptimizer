import { useRef, useState } from "react";
import { CalendarCheck, CheckCircle, CircleNotch, FloppyDisk, Terminal, WarningCircle, X } from "@phosphor-icons/react";
import { ApiError, saveRoutine, type RoutineSaved } from "../lib/api";
import { WEEKDAYS, type Categories, type Week } from "../lib/types";

export default function SaveRoutine({ categories, week }: { categories: Categories; week: Week }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RoutineSaved | null>(null);
  const [error, setError] = useState("");
  const empty = WEEKDAYS.every((d) => week[d].length === 0);

  const save = () => {
    setBusy(true);
    setError("");
    setResult(null);
    dialog.current?.showModal();
    saveRoutine(categories, week)
      .then(setResult)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't save. Try again."))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <button
        type="button"
        onClick={save}
        disabled={empty || busy}
        title={empty ? "Draw at least one block first" : "Save and hand your routine to DayOptimizer"}
        className="inline-flex min-h-10 items-center gap-1.5 rounded-full bg-accent px-4 py-1.5 text-sm font-semibold text-night transition active:scale-[0.98] disabled:opacity-40"
      >
        <FloppyDisk size={16} weight="bold" aria-hidden />
        Save my routine
      </button>

      <dialog
        ref={dialog}
        onClick={(e) => e.target === dialog.current && dialog.current?.close()}
        aria-labelledby="routine-title"
        className="glass-strong m-auto w-[min(34rem,calc(100vw-2rem))] rounded-[20px] p-0 text-ink shadow-2xl backdrop:bg-black/60 backdrop:backdrop-blur-sm"
      >
        <div className="flex flex-col gap-4 p-5">
          <div className="flex items-start gap-3">
            <h2 id="routine-title" className="flex-1 text-lg font-semibold tracking-tight">
              {busy ? "Saving your routine" : error ? "Couldn't save" : "Routine saved"}
            </h2>
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              aria-label="Close"
              className="grid size-8 shrink-0 place-items-center rounded-full text-ink-dim transition hover:bg-white/10 hover:text-ink"
            >
              <X size={16} weight="bold" />
            </button>
          </div>

          {busy && (
            <p className="flex items-center gap-2 text-sm text-ink-dim">
              <CircleNotch size={18} weight="bold" className="animate-spin text-accent motion-reduce:animate-none" aria-hidden />
              Writing it down and setting up your calendars...
            </p>
          )}
          {error && (
            <p role="alert" className="flex gap-2 rounded-[12px] border border-[#ff8a80]/30 bg-[#ff8a80]/10 p-2.5 text-sm">
              <WarningCircle size={18} weight="bold" className="shrink-0 text-[#ff8a80]" aria-hidden />
              {error}
            </p>
          )}
          {result && (
            <>
              <p className="flex items-start gap-2 text-sm leading-snug">
                <CheckCircle size={20} weight="fill" className="shrink-0 text-[#4fb286]" aria-hidden />
                <span>
                  DayOptimizer now knows your typical week. This is exactly what its assistant reads, saved on this Mac only
                  at <code className="font-mono text-[13px] text-ink-dim">{result.path}</code>:
                </span>
              </p>
              {result.calendars.error ? (
                <p role="alert" className="flex gap-2 rounded-[12px] border border-[#f4b860]/30 bg-[#f4b860]/10 p-2.5 text-sm leading-snug">
                  <WarningCircle size={18} weight="bold" className="shrink-0 text-accent" aria-hidden />
                  {result.calendars.error}
                </p>
              ) : (
                <p className="flex items-start gap-2 text-sm leading-snug">
                  <CalendarCheck size={20} weight="bold" className="shrink-0 text-[#4fb286]" aria-hidden />
                  {result.calendars.created.length
                    ? `Added to your Calendar app: ${result.calendars.created.join(", ")}.`
                    : "Every category already has its calendar in the Calendar app."}
                </p>
              )}
              <pre className="scroll-thin max-h-72 overflow-auto rounded-[12px] border border-line bg-black/30 p-3 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-ink">
                {result.text}
              </pre>
              <div className="flex items-start gap-2 rounded-[12px] border border-line bg-white/[0.03] p-3 text-sm leading-snug">
                <Terminal size={18} weight="bold" className="mt-px shrink-0 text-accent" aria-hidden />
                <p>
                  You're set. Close this tab and use the terminal:{" "}
                  <code className="font-mono text-[13px]">dayoptimizer</code> optimizes today, and{" "}
                  <code className="font-mono text-[13px]">dayoptimizer "gym at 18, then..."</code> tells it about your day.
                  Come back with <code className="font-mono text-[13px]">dayoptimizer setup</code> whenever your routine
                  changes.
                </p>
              </div>
            </>
          )}
        </div>
      </dialog>
    </>
  );
}
