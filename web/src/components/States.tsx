import { ArrowClockwise, WarningCircle } from "@phosphor-icons/react";

const pulse = "glass rounded-[20px] animate-pulse motion-reduce:animate-none";

export function LoadingSkeleton() {
  return (
    <div
      className="grid flex-1 grid-cols-1 gap-5 lg:grid-cols-[18rem_1fr]"
      aria-busy="true"
      aria-label="Loading planner"
    >
      <div className={`${pulse} h-72 lg:h-auto lg:min-h-[32rem]`} />
      <div className={`${pulse} min-h-[28rem] lg:min-h-[32rem]`} />
    </div>
  );
}

export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="glass mx-auto flex max-w-md flex-col items-center gap-3 rounded-[20px] p-8 text-center">
      <WarningCircle size={28} weight="bold" className="text-accent" aria-hidden />
      <h2 className="text-lg font-semibold tracking-tight">Can't reach the planner server</h2>
      {message && <p className="text-sm break-words text-ink-dim">{message}</p>}
      <p className="text-sm text-ink-dim">
        Is <code className="font-mono text-ink">dayoptimizer web</code> still running?
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-2 inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-medium text-night transition active:scale-[0.98]"
      >
        <ArrowClockwise size={16} weight="bold" aria-hidden />
        Retry
      </button>
    </div>
  );
}
