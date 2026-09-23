import { useEffect, useRef, useState, type FormEvent } from "react";
import { CheckCircle, CircleNotch, Eye, EyeSlash, LockKey, ShieldCheck, Trash, WarningCircle, Watch, X } from "@phosphor-icons/react";
import { ApiError, garminDisconnect, garminLogin, garminMfa, garminStatus } from "../lib/api";

type Step = "form" | "mfa" | "connected";

const field =
  "h-10 w-full rounded-[10px] border border-line bg-white/5 px-3 text-sm text-ink outline-none transition placeholder:text-ink-dim focus:border-accent";
const primary =
  "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full bg-accent px-4 text-sm font-semibold text-night transition active:scale-[0.98] disabled:opacity-50";
const ghost =
  "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full border border-line px-4 text-sm text-ink-dim transition hover:text-ink active:scale-[0.98]";

const FEEDS = ["Sleep", "Body Battery", "HRV", "Stress", "Resting heart rate"];

export default function GarminConnect() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [step, setStep] = useState<Step>("form");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmOff, setConfirmOff] = useState(false);

  useEffect(() => {
    garminStatus()
      .then((s) => setConnected(s.connected))
      .catch(() => setConnected(false));
  }, []);

  const open = () => {
    setStep(connected ? "connected" : "form");
    setError("");
    setConfirmOff(false);
    dialog.current?.showModal();
  };
  const close = () => dialog.current?.close();

  // Never keep the password around longer than one attempt.
  const onClosed = () => {
    setPassword("");
    setCode("");
    setShowPw(false);
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
      if (e instanceof ApiError && e.code === "expired") setStep("form");
    } finally {
      setBusy(false);
    }
  };

  const done = () => {
    setConnected(true);
    setStep("connected");
    setPassword("");
    setCode("");
  };

  const signIn = (e: FormEvent) => {
    e.preventDefault();
    if (!email.includes("@")) return setError("Enter the email you use for Garmin Connect.");
    if (!password) return setError("Enter your Garmin password.");
    run(async () => {
      try {
        const r = await garminLogin(email.trim(), password);
        if (r.status === "mfa") setStep("mfa");
        else done();
      } finally {
        setPassword("");
      }
    });
  };

  const verify = (e: FormEvent) => {
    e.preventDefault();
    if (!/^\d{4,8}$/.test(code.trim())) return setError("Enter the code Garmin sent you.");
    run(async () => {
      await garminMfa(code.trim());
      done();
    });
  };

  const disconnect = () =>
    run(async () => {
      await garminDisconnect();
      setConnected(false);
      setConfirmOff(false);
      setStep("form");
    });

  return (
    <>
      <button
        type="button"
        onClick={open}
        className="glass inline-flex min-h-10 items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-medium text-ink transition hover:text-accent active:scale-[0.98]"
      >
        <Watch size={16} weight="bold" aria-hidden />
        Garmin
        {connected !== null && (
          <span
            className={`size-2 rounded-full ${connected ? "bg-[#4fb286]" : "bg-white/25"}`}
            title={connected ? "Connected" : "Not connected"}
            aria-label={connected ? "connected" : "not connected"}
          />
        )}
      </button>

      <dialog
        ref={dialog}
        onClose={onClosed}
        onClick={(e) => e.target === dialog.current && close()}
        aria-labelledby="garmin-title"
        className="glass-strong m-auto w-[min(28rem,calc(100vw-2rem))] rounded-[20px] p-0 text-ink shadow-2xl backdrop:bg-black/60 backdrop:backdrop-blur-sm"
      >
        <div className="flex flex-col gap-4 p-5">
          <div className="flex items-start gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent/15 text-accent">
              <Watch size={20} weight="bold" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <h2 id="garmin-title" className="flex items-center gap-2 text-lg font-semibold tracking-tight">
                Connect Garmin
                <span className="rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-ink-dim">Optional</span>
              </h2>
              <p className="mt-1 text-sm leading-snug text-ink-dim">
                DayOptimizer works fine without it. Connected, it reads how you slept and recovered, so hard work lands on
                good days and rest on tired ones.
              </p>
            </div>
            <button
              type="button"
              onClick={close}
              aria-label="Close"
              className="grid size-8 shrink-0 place-items-center rounded-full text-ink-dim transition hover:bg-white/10 hover:text-ink"
            >
              <X size={16} weight="bold" />
            </button>
          </div>

          <ul className="flex flex-wrap gap-1.5" aria-label="Data DayOptimizer reads">
            {FEEDS.map((f) => (
              <li key={f} className="rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-ink">
                {f}
              </li>
            ))}
          </ul>

          {error && (
            <p role="alert" className="flex gap-2 rounded-[12px] border border-[#ff8a80]/30 bg-[#ff8a80]/10 p-2.5 text-sm leading-snug">
              <WarningCircle size={18} weight="bold" className="shrink-0 text-[#ff8a80]" aria-hidden />
              {error}
            </p>
          )}

          {step === "form" && (
            <form onSubmit={signIn} noValidate className="flex flex-col gap-3">
              <label className="flex flex-col gap-1.5 text-sm">
                Garmin Connect email
                <input
                  type="email"
                  autoComplete="username"
                  autoFocus
                  value={email}
                  maxLength={254}
                  onChange={(e) => setEmail(e.target.value)}
                  className={field}
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                Password
                <span className="relative">
                  <input
                    type={showPw ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    maxLength={256}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`${field} pr-11`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((s) => !s)}
                    aria-label={showPw ? "Hide password" : "Show password"}
                    className="absolute inset-y-0 right-1 grid w-9 place-items-center text-ink-dim hover:text-ink"
                  >
                    {showPw ? <EyeSlash size={18} /> : <Eye size={18} />}
                  </button>
                </span>
              </label>

              <ul className="flex flex-col gap-2 rounded-[12px] border border-line bg-white/[0.03] p-3 text-xs leading-snug text-ink-dim">
                <li className="flex gap-2">
                  <LockKey size={16} weight="bold" className="shrink-0 text-accent" aria-hidden />
                  Your password goes from this Mac straight to Garmin's sign-in. DayOptimizer never saves it.
                </li>
                <li className="flex gap-2">
                  <ShieldCheck size={16} weight="bold" className="shrink-0 text-accent" aria-hidden />
                  Garmin sends back a session key, stored only on this Mac in ~/.dayoptimizer, readable by your user
                  alone. No DayOptimizer server exists, nothing is shared.
                </li>
                <li className="flex gap-2">
                  <Trash size={16} weight="bold" className="shrink-0 text-accent" aria-hidden />
                  Disconnect here any time to delete it.
                </li>
              </ul>

              <details className="text-xs text-ink-dim">
                <summary className="cursor-pointer select-none hover:text-ink">Why not a "Sign in with Garmin" button?</summary>
                <p className="mt-1.5 leading-snug">
                  Garmin's official partner API is only open to approved companies that run their own servers. DayOptimizer
                  is a private app that runs only on your computer, so it signs in the same way the Garmin Connect app
                  does. This access isn't officially supported by Garmin and could stop working after a Garmin change. If it
                  does, planning carries on without health data. With two-step verification on, you'll be asked for the code
                  next.
                </p>
              </details>

              <div className="flex justify-end gap-2">
                <button type="button" onClick={close} className={ghost}>
                  Not now
                </button>
                <button type="submit" disabled={busy} className={primary}>
                  {busy && <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />}
                  {busy ? "Connecting" : "Connect"}
                </button>
              </div>
            </form>
          )}

          {step === "mfa" && (
            <form onSubmit={verify} noValidate className="flex flex-col gap-3">
              <label className="flex flex-col gap-1.5 text-sm">
                Garmin sent a verification code to your email or authenticator app
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  value={code}
                  maxLength={8}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  className={`${field} font-mono tracking-[0.3em]`}
                />
              </label>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setStep("form")} className={ghost}>
                  Back
                </button>
                <button type="submit" disabled={busy} className={primary}>
                  {busy && <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />}
                  Verify
                </button>
              </div>
            </form>
          )}

          {step === "connected" && (
            <div className="flex flex-col gap-3">
              <p className="flex items-center gap-2 rounded-[12px] border border-[#4fb286]/30 bg-[#4fb286]/10 p-3 text-sm">
                <CheckCircle size={20} weight="fill" className="shrink-0 text-[#4fb286]" aria-hidden />
                Garmin is connected. Your health data is used from the next planning run.
              </p>
              <div className="flex justify-end gap-2">
                {confirmOff ? (
                  <>
                    <span className="mr-auto self-center text-sm text-ink-dim">Delete the Garmin session?</span>
                    <button type="button" onClick={() => setConfirmOff(false)} className={ghost}>
                      Cancel
                    </button>
                    <button type="button" onClick={disconnect} disabled={busy} className={primary}>
                      Disconnect
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => setConfirmOff(true)} className={ghost}>
                      Disconnect
                    </button>
                    <button type="button" onClick={close} className={primary}>
                      Done
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </dialog>
    </>
  );
}
