import { useMemo, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowsOutLineVertical, Lock, Minus, Plus, Smiley, Trash } from "@phosphor-icons/react";
import { categoryColor, freshColor, SWATCHES } from "../lib/colors";
import { usePopover } from "../lib/usePopover";
import { durationLabel, toMin } from "../lib/time";
import { WEEKDAYS, type Categories, type Category, type Week } from "../lib/types";

const FIXED_TIP = "Fixed: changes need your approval";
const FLEX_TIP = "Flexible: the planner may move it";
const ghost = "border border-line hover:bg-white/5 transition active:scale-[0.98]";

function MovableToggle({ movable, onToggle, name }: { movable: boolean; onToggle: () => void; name?: string }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={movable ? FLEX_TIP : FIXED_TIP}
      aria-label={`${name ? `${name}: ` : ""}${movable ? "Flexible" : "Fixed"}. Click to make it ${movable ? "Fixed" : "Flexible"}`}
      className={`inline-flex h-8 w-[3.75rem] shrink-0 items-center justify-center gap-1 rounded-full text-xs font-semibold ${ghost} ${
        movable ? "text-ink-dim" : "border-accent/40 bg-accent/10 text-accent"
      }`}
    >
      {movable ? <ArrowsOutLineVertical size={12} weight="bold" aria-hidden /> : <Lock size={12} weight="bold" aria-hidden />}
      {movable ? "Flex" : "Fixed"}
    </button>
  );
}

const pop = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.96 },
  transition: { duration: 0.15 },
};

const EMOJI = [
  "💼", "📚", "🏋️", "🍽️", "😴", "🚗", "🧘", "🎮",
  "🎵", "🎨", "💻", "🧠", "📞", "🛒", "🧹", "❤️",
  "☕", "🏃", "🎓", "🌿", "✍️", "📖", "🎬", "⭐",
];
/** First grapheme only, so "👍🏽" or "🏳️‍🌈" survive but pasted text doesn't. */
const firstGrapheme = (s: string) => [...new Intl.Segmenter().segment(s.trim())][0]?.segment ?? "";

function EmojiPicker({ value, onPick }: { value: string; onPick: (e: string) => void }) {
  const { open, setOpen, ref } = usePopover();
  const choose = (e: string) => {
    onPick(e);
    setOpen(false);
  };
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-label={value ? `Icon ${value}. Change icon` : "Add an icon"}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`grid size-9 place-items-center rounded-[10px] text-lg ${ghost} ${value ? "" : "text-ink-dim"}`}
      >
        {value || <Smiley size={18} weight="bold" aria-hidden />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div {...pop} className="glass-strong absolute top-11 left-0 z-20 w-64 origin-top-left rounded-[10px] p-2">
            <div className="grid grid-cols-8 gap-0.5">
              {EMOJI.map((e) => (
                <button
                  key={e}
                  type="button"
                  aria-label={`Icon ${e}`}
                  aria-pressed={e === value}
                  onClick={() => choose(e)}
                  className={`grid size-7 place-items-center rounded-md text-base transition hover:bg-white/10 active:scale-[0.95] ${e === value ? "bg-white/15 ring-1 ring-accent" : ""}`}
                >
                  {e}
                </button>
              ))}
            </div>
            <div className="mt-2 flex items-center gap-1.5">
              <input
                aria-label="Any emoji"
                placeholder="Or type any emoji"
                maxLength={16}
                onChange={(e) => {
                  const g = firstGrapheme(e.target.value);
                  if (g) choose(g);
                }}
                className="h-8 min-w-0 flex-1 rounded-md border border-line bg-white/5 px-2 text-sm outline-none placeholder:text-ink-dim focus:border-accent"
              />
              {value && (
                <button type="button" onClick={() => choose("")} className={`h-8 shrink-0 rounded-md px-2 text-xs text-ink-dim ${ghost}`}>
                  None
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Swatch({ name, color, onPick }: { name: string; color: string; onPick: (c: string) => void }) {
  const { open, setOpen, ref } = usePopover();

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-label={`Change colour of ${name}`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="grid h-8 w-6 place-items-center rounded-full transition hover:bg-white/10 active:scale-[0.98]"
      >
        <span className="size-3.5 rounded-full ring-1 ring-white/20" style={{ background: color }} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            {...pop}
            className="glass-strong absolute top-9 left-0 z-20 grid origin-top-left grid-cols-5 gap-1.5 rounded-[10px] p-2"
          >
            {SWATCHES.map((s) => (
              <button
                key={s}
                type="button"
                aria-label={`Colour ${s}`}
                aria-pressed={s === color}
                onClick={() => {
                  onPick(s);
                  setOpen(false);
                }}
                className={`size-6 rounded-full transition active:scale-[0.98] ${s === color ? "ring-2 ring-ink" : ""}`}
                style={{ background: s }}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Row(props: {
  name: string;
  cat: Category;
  blocks: number;
  onPatch: (p: Partial<Category>) => void;
  onRemove: () => void;
}) {
  const { name, cat, blocks, onPatch, onRemove } = props;
  const [confirming, setConfirming] = useState(false);
  const step = (d: number) => onPatch({ priority: Math.max(0, Math.min(10, cat.priority + d)) });
  const stepBtn =
    "grid h-8 w-5 place-items-center text-ink-dim transition hover:text-ink active:scale-[0.98] disabled:opacity-35 disabled:hover:text-ink-dim";

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      className="group rounded-[10px] px-1 py-0.5 hover:bg-white/[0.04]"
    >
      <div className="flex items-center gap-1">
        <Swatch name={name} color={categoryColor(name, cat.color)} onPick={(color) => onPatch({ color })} />
        <span className="min-w-0 flex-1 truncate text-[15px] font-medium" title={name}>
          {cat.emoji && <span aria-hidden className="mr-1.5">{cat.emoji}</span>}
          {name}
        </span>
        <MovableToggle name={name} movable={cat.movable} onToggle={() => onPatch({ movable: !cat.movable })} />
        <div
          role="group"
          aria-label={`Priority of ${name}: ${cat.priority} of 10`}
          title={`Priority ${cat.priority} of 10. Higher gets the better hours.`}
          className="flex shrink-0 items-center rounded-full border border-line"
        >
          <button type="button" aria-label={`Lower priority of ${name}`} disabled={cat.priority <= 0} onClick={() => step(-1)} className={stepBtn}>
            <Minus size={12} weight="bold" aria-hidden />
          </button>
          <span className="w-4 text-center font-mono text-xs text-ink tabular-nums" aria-live="polite">
            {cat.priority}
          </span>
          <button type="button" aria-label={`Raise priority of ${name}`} disabled={cat.priority >= 10} onClick={() => step(1)} className={stepBtn}>
            <Plus size={12} weight="bold" aria-hidden />
          </button>
        </div>
        <button
          type="button"
          aria-label={`Delete ${name}`}
          title={`Delete ${name}`}
          onClick={() => (blocks ? setConfirming(true) : onRemove())}
          className="grid h-8 w-7 shrink-0 place-items-center overflow-hidden rounded-full text-ink-dim transition-all hover:bg-white/10 hover:text-[#ff8a80] active:scale-[0.98] [@media(hover:hover)]:w-0 [@media(hover:hover)]:group-focus-within:w-7 [@media(hover:hover)]:group-hover:w-7"
        >
          <Trash size={16} weight="bold" aria-hidden />
        </button>
      </div>
      <AnimatePresence>
        {confirming && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            role="alert"
            className="mb-1 mt-1 rounded-[10px] border border-line bg-white/5 p-2.5 text-sm"
          >
            <p>
              Delete {name} and its {blocks} {blocks === 1 ? "block" : "blocks"}?
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={onRemove}
                className="min-h-8 rounded-full bg-accent px-3.5 text-xs font-semibold text-night transition active:scale-[0.98]"
              >
                Delete
              </button>
              <button type="button" onClick={() => setConfirming(false)} className={`min-h-8 rounded-full px-3.5 text-xs font-medium ${ghost}`}>
                Cancel
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}

function AddCategory({ categories, onAdd }: { categories: Categories; onAdd: (name: string, movable: boolean, emoji: string) => void }) {
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("");
  const [movable, setMovable] = useState(true);
  const [error, setError] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (!n) return setError("Enter a name.");
    if (n.length > 40) return setError("Keep it under 40 characters.");
    if (Object.keys(categories).some((k) => k.toLowerCase() === n.toLowerCase())) return setError(`${n} already exists.`);
    onAdd(n, movable, emoji);
    setName("");
    setEmoji("");
    setError("");
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-1.5" noValidate>
      <label htmlFor="new-category" className="sr-only">
        New category name
      </label>
      <div className="flex items-center gap-1.5">
        <input
          id="new-category"
          value={name}
          maxLength={40}
          onChange={(e) => {
            setName(e.target.value);
            setError("");
          }}
          placeholder="New category"
          aria-invalid={!!error}
          aria-describedby={error ? "new-category-error" : undefined}
          className="h-9 min-w-0 flex-1 rounded-[10px] border border-line bg-white/5 px-3 text-sm outline-none transition placeholder:text-ink-dim focus:border-accent"
        />
        <EmojiPicker value={emoji} onPick={setEmoji} />
        <MovableToggle movable={movable} onToggle={() => setMovable((m) => !m)} />
        <button
          type="submit"
          className="inline-flex h-9 shrink-0 items-center gap-1 rounded-full bg-accent px-3 text-sm font-semibold text-night transition active:scale-[0.98]"
        >
          <Plus size={16} weight="bold" aria-hidden />
          Add
        </button>
      </div>
      {error && (
        <p id="new-category-error" className="text-xs text-[#ff8a80]">
          {error}
        </p>
      )}
    </form>
  );
}

export default function Sidebar(props: {
  categories: Categories;
  week: Week;
  defaults: string[];
  onChange: (fn: (c: Categories) => Categories) => void;
  onRemove: (name: string) => void;
}) {
  const { categories, week, onChange, onRemove } = props;

  const { counts, totals } = useMemo(() => {
    const counts: Record<string, number> = {};
    const totals: Record<string, number> = {};
    for (const d of WEEKDAYS)
      for (const b of week[d]) {
        counts[b.category] = (counts[b.category] ?? 0) + 1;
        totals[b.category] = (totals[b.category] ?? 0) + toMin(b.end) - toMin(b.start);
      }
    return { counts, totals };
  }, [week]);

  const rows = Object.entries(categories).sort(([an, a], [bn, b]) => b.priority - a.priority || an.localeCompare(bn));
  const usage = Object.entries(totals)
    .filter(([, m]) => m > 0)
    .sort(([, a], [, b]) => b - a);
  const max = usage[0]?.[1] ?? 1;

  const patch = (name: string, p: Partial<Category>) => onChange((c) => (c[name] ? { ...c, [name]: { ...c[name], ...p } } : c));

  return (
    <aside className="glass flex flex-col gap-4 rounded-[20px] p-3 lg:sticky lg:top-5 lg:max-h-[calc(100dvh-2.5rem)]">
      <section className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="px-1">
          <h2 className="text-[15px] font-semibold tracking-tight">Categories</h2>
          <p className="mt-0.5 text-xs leading-snug text-ink-dim">
            <span className="font-semibold text-accent">Fixed:</span> moves only with your OK.{" "}
            <span className="font-semibold text-ink">Flex:</span> the planner may shift it.
          </p>
        </div>

        <AddCategory
          categories={categories}
          onAdd={(name, movable, emoji) =>
            onChange((c) => {
              const taken = Object.entries(c).map(([n, cat]) => categoryColor(n, cat.color));
              return { ...c, [name]: { movable, priority: 5, color: freshColor(name, taken), ...(emoji && { emoji }) } };
            })
          }
        />

        <div className="flex min-h-0 flex-1 flex-col">
          <div aria-hidden className="flex items-center gap-1 px-1 pb-1 text-xs text-ink-dim">
            <span className="flex-1 pl-7">Name</span>
            <span className="w-[3.75rem] text-center">Mode</span>
            <span className="w-[3.625rem] text-center">Priority</span>
          </div>
          <ul className="scroll-thin flex min-h-0 flex-col gap-0.5 lg:overflow-y-auto">
            <AnimatePresence initial={false}>
              {rows.map(([name, cat]) => (
                <Row
                  key={name}
                  name={name}
                  cat={cat}
                  blocks={counts[name] ?? 0}
                  onPatch={(p) => patch(name, p)}
                  onRemove={() => onRemove(name)}
                />
              ))}
            </AnimatePresence>
          </ul>
        </div>
      </section>

      <section className="flex shrink-0 flex-col gap-2 border-t border-line px-1 pt-3">
        <h2 className="text-[15px] font-semibold tracking-tight">This week</h2>
        {usage.length === 0 ? (
          <p className="text-sm text-ink-dim">No blocks yet.</p>
        ) : (
          <ul className="scroll-thin flex max-h-56 flex-col gap-1.5 overflow-y-auto">
            {usage.map(([name, min]) => {
              const color = categoryColor(name, categories[name]?.color);
              return (
                <li key={name} className="flex items-center gap-2 text-sm">
                  <span className="size-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
                  <span className="w-24 min-w-0 shrink-0 truncate" title={name}>
                    {name}
                  </span>
                  <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden>
                    <span className="block h-full rounded-full" style={{ width: `${(min / max) * 100}%`, background: color }} />
                  </span>
                  <span className="w-14 shrink-0 text-right font-mono text-xs text-ink tabular-nums">{durationLabel(min)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </aside>
  );
}
