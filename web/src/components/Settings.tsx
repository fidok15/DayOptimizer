import { useRef, useState, type ReactNode } from "react";
import { CircleNotch, GearSix, WarningCircle, X } from "@phosphor-icons/react";
import { ApiError, fetchSettings, saveApiKey, saveSettings, setBackgroundCheck, type SettingsChange } from "../lib/api";
import type { Backend, DayKey, Settings as S, Variety } from "../lib/types";

const field =
  "h-9 rounded-[10px] border border-line bg-ink/5 px-2.5 text-sm text-ink outline-none transition placeholder:text-ink-dim focus:border-accent [&>option]:bg-[var(--surface)]";
const primary =
  "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg bg-dusk px-4 text-sm font-semibold text-on-dusk transition active:scale-[0.98] disabled:opacity-50";
const ghost =
  "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-full border border-line px-3.5 text-sm text-ink-dim transition hover:text-ink active:scale-[0.98] disabled:opacity-50";

const DAYS: [DayKey, string][] = [["mon", "Mo"], ["tue", "Tu"], ["wed", "We"], ["thu", "Th"], ["fri", "Fr"], ["sat", "Sa"], ["sun", "Su"]];
const BACKENDS: [Backend, string, string][] = [
  ["auto", "Automatic", "Claude when an API key is set, else the local model."],
  ["ollama", "Only on this Mac", "A local Ollama model. Free and private; slower, simpler plans."],
  ["anthropic", "Only Claude", "The Anthropic API with your key. Best plans; your routine and events are sent."],
];
const INTERVALS = [5, 10, 15, 30, 60];

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <div>
        <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
        {hint && <p className="mt-0.5 text-xs leading-snug text-ink-dim">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Minutes({ label, hint, value, min, max, step = 5, onChange }: {
  label: string; hint: string; value: number; min: number; max: number; step?: number; onChange: (n: number) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm">
      <span className="flex flex-col">
        {label}
        <span className="text-xs text-ink-dim">{hint}</span>
      </span>
      <span className="flex shrink-0 items-center gap-1.5 text-xs text-ink-dim">
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={Number.isFinite(value) ? value : ""}
          onChange={(e) => onChange(e.target.valueAsNumber)}
          className={`${field} w-20 tabular-nums`}
        />
        min
      </span>
    </label>
  );
}

function Status({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-ink/[0.06] px-2.5 py-1 text-xs text-ink">
      <span className={`size-2 rounded-full ${ok ? "bg-[#4fb286]" : "bg-ink/25"}`} aria-hidden />
      {children}
    </span>
  );
}

function kept<T extends object>(draft: T, before: T, after: T): T {
  const edited = (k: keyof T) => JSON.stringify(draft[k]) !== JSON.stringify(before[k]);
  return Object.fromEntries((Object.keys(after) as (keyof T)[]).map((k) => [k, edited(k) ? draft[k] : after[k]])) as T;
}

export default function Settings() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [draft, setDraft] = useState<S | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const savedRef = useRef<S | null>(null);
  // the server's answer, keeping every edit not saved yet (made before or while a request ran)
  const load = (s: S) => {
    const before = savedRef.current;
    savedRef.current = s;
    setSaved(s);
    setDraft((d) =>
      d && before
        ? { ...s, llm: kept(d.llm, before.llm, s.llm), day: kept(d.day, before.day, s.day),
            agent: kept(d.agent, before.agent, s.agent),
            share_health: d.share_health !== before.share_health ? d.share_health : s.share_health }
        : s,
    );
  };

  const open = () => {
    setError("");
    setNote("");
    dialog.current?.showModal();
    savedRef.current = null; // opening shows what is saved
    fetchSettings().then(load).catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't read your settings."));
  };
  const close = () => dialog.current?.close();

  const run = async (fn: () => Promise<S>, done: string) => {
    setBusy(true);
    setError("");
    setNote("");
    try {
      load(await fn());
      setNote(done);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const day = <K extends keyof S["day"]>(k: K, v: S["day"][K]) => setDraft((d) => d && { ...d, day: { ...d.day, [k]: v } });
  const llm = <K extends keyof S["llm"]>(k: K, v: S["llm"][K]) => setDraft((d) => d && { ...d, llm: { ...d.llm, [k]: v } });

  const changes = (): SettingsChange => {
    if (!draft || !saved) return {};
    const out: SettingsChange = {};
    const l = Object.fromEntries(Object.entries(draft.llm).filter(([k, v]) => saved.llm[k as keyof S["llm"]] !== v));
    if (Object.keys(l).length) out.llm = l;
    if (draft.share_health !== saved.share_health) out.share_health = draft.share_health;
    const d = Object.fromEntries(
      Object.entries(draft.day).filter(([k, v]) => JSON.stringify(saved.day[k as keyof S["day"]]) !== JSON.stringify(v)),
    );
    if (Object.keys(d).length) out.day = d;
    return out;
  };
  const dirty = Object.keys(changes()).length > 0;
  const bad =
    draft &&
    (!(draft.day.day_start < draft.day.day_end) ||
      [draft.day.buffer_minutes, draft.day.morning_buffer_minutes, draft.day.min_free_minutes].some((n) => !Number.isInteger(n)));

  const agentMinutes = draft?.agent.interval_minutes ?? 15;

  return (
    <>
      <button
        type="button"
        onClick={open}
        aria-label="Settings"
        title="Settings"
        className="glass-btn grid size-10 place-items-center rounded-full text-ink transition hover:bg-ink/20 active:scale-[0.98]"
      >
        <GearSix size={18} weight="bold" aria-hidden />
      </button>

      <dialog
        ref={dialog}
        onClick={(e) => e.target === dialog.current && close()}
        aria-labelledby="settings-title"
        className="glass-strong m-auto max-h-[calc(100dvh-2rem)] w-[min(34rem,calc(100vw-2rem))] rounded-2xl p-0 text-ink shadow-2xl backdrop:bg-black/25 backdrop:backdrop-blur-sm"
      >
        <div className="flex items-center justify-between gap-3 px-5 pt-5">
          <h2 id="settings-title" className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <GearSix size={20} weight="bold" className="text-accent" aria-hidden />
            Settings
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close"
            className="grid size-8 place-items-center rounded-full text-ink-dim transition hover:bg-ink/10 hover:text-ink"
          >
            <X size={16} weight="bold" />
          </button>
        </div>

        {!draft ? (
          <div className="flex min-h-40 items-center justify-center p-5 text-sm text-ink-dim">
            {error ? error : <CircleNotch size={20} className="animate-spin motion-reduce:animate-none" aria-label="Loading" />}
          </div>
        ) : (
          <div className="flex flex-col gap-4 p-5">
            <Section title="Who plans" hint="The model that lays out your days. Code checks every plan either way.">
              <div className="flex flex-wrap gap-1.5">
                <Status ok={draft.key_set}>{draft.key_set ? "API key set" : "No API key"}</Status>
                <Status ok={draft.ollama}>{draft.ollama ? "Ollama found" : "Ollama not installed"}</Status>
              </div>
              <div role="radiogroup" aria-label="Who plans" className="flex flex-col gap-1.5">
                {BACKENDS.map(([id, label, text]) => (
                  <label key={id} className="flex cursor-pointer items-start gap-2.5 rounded-[12px] border border-line p-2.5 text-sm has-[:checked]:border-accent has-[:checked]:bg-accent/5">
                    <input type="radio" name="backend" checked={draft.llm.backend === id} onChange={() => llm("backend", id)} className="mt-0.5 size-4 accent-[#f4b860]" />
                    <span className="flex flex-col">
                      {label}
                      <span className="text-xs text-ink-dim">{text}</span>
                    </span>
                  </label>
                ))}
              </div>
              {draft.llm.backend !== "ollama" && (
                <div className="flex flex-col gap-1.5 text-sm">
                  <label htmlFor="api-key">Anthropic API key</label>
                  <div className="flex gap-2">
                    <input
                      id="api-key"
                      type="password"
                      autoComplete="off"
                      value={key}
                      maxLength={300}
                      placeholder={draft.key_set ? "Saved. Paste a new one to replace it." : "sk-ant-…"}
                      onChange={(e) => setKey(e.target.value)}
                      className={`${field} min-w-0 flex-1`}
                    />
                    <button type="button" disabled={busy || !key.trim()} onClick={() => run(() => saveApiKey(key).finally(() => setKey("")), "Key saved.")} className={ghost}>
                      Save key
                    </button>
                    {draft.key_set && (
                      <button type="button" disabled={busy} onClick={() => run(() => saveApiKey(""), "Key removed.")} className={ghost}>
                        Remove
                      </button>
                    )}
                  </div>
                  <span className="text-xs text-ink-dim">Stored only on this Mac in ~/.dayoptimizer/.env, readable by your user alone.</span>
                </div>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                {draft.llm.backend !== "ollama" && (
                  <label className="flex flex-col gap-1 text-xs text-ink-dim">
                    Claude model
                    <input value={draft.llm.model} maxLength={100} onChange={(e) => llm("model", e.target.value)} className={field} />
                  </label>
                )}
                {draft.llm.backend !== "anthropic" && (
                  <label className="flex flex-col gap-1 text-xs text-ink-dim">
                    Local model (Ollama)
                    <input value={draft.llm.ollama_model} maxLength={100} onChange={(e) => llm("ollama_model", e.target.value)} className={field} />
                  </label>
                )}
              </div>
            </Section>

            <Section title="Health & privacy" hint={draft.garmin ? "Garmin is connected." : "Garmin isn't connected (use the Garmin button). Planning works without it."}>
              <label className="flex cursor-pointer items-start gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={draft.share_health}
                  onChange={(e) => setDraft({ ...draft, share_health: e.target.checked })}
                  className="mt-0.5 size-4 shrink-0 accent-[#f4b860]"
                />
                <span className="flex flex-col">
                  Let Claude see my health summary when it plans
                  <span className="text-xs leading-snug text-ink-dim">
                    {draft.share_health
                      ? "On: a one-line summary (sleep, Body Battery, HRV, stress, resting heart rate) goes to Anthropic with each plan Claude makes."
                      : "Off: the summary stays on this Mac. A local model still uses it; Claude plans without it."}
                  </span>
                </span>
              </label>
            </Section>

            <Section title="Your day">
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1 text-xs text-ink-dim">
                  Day starts
                  <input type="time" value={draft.day.day_start} onChange={(e) => day("day_start", e.target.value)} className={field} />
                </label>
                <label className="flex flex-col gap-1 text-xs text-ink-dim">
                  Day ends
                  <input type="time" value={draft.day.day_end} onChange={(e) => day("day_end", e.target.value)} className={field} />
                </label>
              </div>
              <Minutes label="Break around your events" hint="Planned blocks keep this gap before and after your meetings and classes." value={draft.day.buffer_minutes} min={0} max={120} onChange={(n) => day("buffer_minutes", n)} />
              <Minutes label="Morning buffer" hint="Without sleep data, the morning replan runs this long after the day starts." value={draft.day.morning_buffer_minutes} min={0} max={240} step={15} onChange={(n) => day("morning_buffer_minutes", n)} />
              <Minutes label="Completely free each day" hint="Time the planner never fills." value={draft.day.min_free_minutes} min={0} max={720} step={15} onChange={(n) => day("min_free_minutes", n)} />
              <label className="flex items-center justify-between gap-3 text-sm">
                <span className="flex flex-col">
                  Variety in suggested activities
                  <span className="text-xs text-ink-dim">How soon a suggested activity may come back.</span>
                </span>
                <select value={draft.day.variety ?? "medium"} onChange={(e) => day("variety", e.target.value as Variety)} className={field}>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </label>
              <fieldset className="flex flex-col gap-1.5 text-sm">
                <legend className="mb-1.5">Work days</legend>
                <div className="flex flex-wrap gap-1.5">
                  {DAYS.map(([id, label]) => {
                    const on = draft.day.work_days.includes(id);
                    return (
                      <button
                        key={id}
                        type="button"
                        aria-pressed={on}
                        onClick={() => day("work_days", on ? draft.day.work_days.filter((d) => d !== id) : DAYS.map(([d]) => d).filter((d) => d === id || draft.day.work_days.includes(d)))}
                        className={`min-h-9 min-w-10 rounded-full border px-2.5 text-xs font-medium transition ${on ? "border-accent bg-accent/15 text-ink" : "border-line text-ink-dim hover:text-ink"}`}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </fieldset>
            </Section>

            <Section title="In the background" hint="Checks your calendar and adjusts the day when something new shows up.">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Status ok={draft.agent.running}>{draft.agent.running ? "Running" : "Off"}</Status>
                <label className="flex items-center gap-1.5 text-xs text-ink-dim">
                  every
                  <select
                    value={agentMinutes}
                    onChange={(e) => setDraft({ ...draft, agent: { ...draft.agent, interval_minutes: Number(e.target.value) } })}
                    className={field}
                  >
                    {INTERVALS.map((m) => <option key={m} value={m}>{m} min</option>)}
                  </select>
                </label>
                <button
                  type="button"
                  disabled={busy || !draft.agent.bundle}
                  onClick={() => run(() => setBackgroundCheck(true, agentMinutes), "Background check on.")}
                  className={ghost}
                >
                  {draft.agent.running ? "Apply" : "Turn on"}
                </button>
                {draft.agent.running && (
                  <button type="button" disabled={busy} onClick={() => run(() => setBackgroundCheck(false, agentMinutes), "Background check off.")} className={ghost}>
                    Turn off
                  </button>
                )}
              </div>
              {!draft.agent.bundle && <p className="text-xs text-ink-dim">Needs the calendar app bundle: run scripts/install.sh first.</p>}
            </Section>

            {error && (
              <p role="alert" className="flex gap-2 rounded-[12px] border border-danger/30 bg-danger/10 p-2.5 text-sm leading-snug">
                <WarningCircle size={18} weight="bold" className="shrink-0 text-danger" aria-hidden />
                {error}
              </p>
            )}

            <div className="flex items-center justify-end gap-2">
              <span className="mr-auto text-xs text-ink-dim" aria-live="polite">{note}</span>
              <button type="button" onClick={close} className={ghost}>
                Close
              </button>
              <button type="button" disabled={busy || !dirty || !!bad} onClick={() => run(() => saveSettings(changes()), "Saved.")} className={primary}>
                {busy && <CircleNotch size={16} weight="bold" className="animate-spin motion-reduce:animate-none" aria-hidden />}
                Save
              </button>
            </div>
          </div>
        )}
      </dialog>
    </>
  );
}
