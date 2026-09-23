import { ArrowClockwise, WarningCircle } from "@phosphor-icons/react";

const pulse = "rounded-[10px] bg-white/[0.07] animate-pulse motion-reduce:animate-none";

export function LoadingSkeleton() {
  return (
    <div className="grid flex-1 grid-cols-1 gap-5 lg:grid-cols-[18rem_1fr]" aria-busy="true" aria-label="Loading planner">
      <div className="glass order-2 flex flex-col gap-3 rounded-[20px] p-3 lg:order-none">
        <div className={`${pulse} h-4 w-24`} />
        <div className={`${pulse} h-3 w-full`} />
        <div className={`${pulse} h-9`} />
        {Array.from({ length: 7 }, (_, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className={`${pulse} size-6 rounded-full`} />
            <div className={`${pulse} h-4 flex-1`} />
            <div className={`${pulse} h-8 w-[3.75rem] rounded-full`} />
            <div className={`${pulse} h-8 w-14 rounded-full`} />
          </div>
        ))}
      </div>
      <div className="glass min-h-[28rem] rounded-[20px] p-4 lg:min-h-[32rem]">
        <div className={`${pulse} h-full min-h-[26rem]`} />
      </div>
    </div>
  );
}

export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="glass mx-auto flex max-w-md flex-col items-center gap-2.5 rounded-[20px] p-6 text-center">
      <WarningCircle size={28} weight="bold" className="text-[#ff8a80]" aria-hidden />
      <h2 className="text-lg font-semibold tracking-tight">Can't reach the planner server</h2>
      {message && <p className="rounded-[10px] bg-white/5 px-3 py-1.5 font-mono text-xs break-words text-ink-dim">{message}</p>}
      <p className="text-sm text-ink">
        Is <code className="font-mono text-accent">dayoptimizer web</code> still running? Start it, then retry.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-1 inline-flex min-h-9 items-center gap-2 rounded-full bg-accent px-4 text-sm font-semibold text-night transition active:scale-[0.98]"
      >
        <ArrowClockwise size={16} weight="bold" aria-hidden />
        Retry
      </button>
    </div>
  );
}
