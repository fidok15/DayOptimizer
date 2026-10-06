import { useCallback, useEffect, useRef, useState } from "react";
import { calendarColors, fetchState, saveState } from "./api";
import { uid } from "./time";
import { WEEKDAYS, type Block, type Categories, type RoutineMode, type SaveStatus, type ServerState, type Week, type Weekday } from "./types";

const AUTOSAVE_MS = 700;

/** In one-day mode the day is kept on Monday and every other day is a copy of it. */
export const TEMPLATE_DAY: Weekday = "mon";
const everyDay = (w: Week, from: Weekday): Week =>
  Object.fromEntries(WEEKDAYS.map((d) => [d, d === from ? w[from] : w[from].map((b) => ({ ...b, id: uid() }))])) as Week;

const blockKey = (b: Block) => `${b.start}-${b.end}-${b.title.trim().toLowerCase()}`;

const toWeek = (s: ServerState): Week =>
  Object.fromEntries(
    WEEKDAYS.map((d) => [d, (s.typical_week[d] ?? []).map((b) => ({ ...b, id: uid() }))]),
  ) as Week;

export function usePlanner() {
  const [load, setLoad] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [categories, setCategories] = useState<Categories>({});
  const [week, setWeek] = useState<Week>(() => toWeek({ typical_week: {} } as ServerState));
  const [notes, setNotes] = useState("");
  const [routineMode, setRoutineMode] = useState<RoutineMode | null>(null);
  const modeRef = useRef(routineMode);
  modeRef.current = routineMode;
  // every week change goes through here: in one-day mode the other days follow Monday
  const mirror = (w: Week) => (modeRef.current === "day" ? everyDay(w, TEMPLATE_DAY) : w);
  const [defaults, setDefaults] = useState<string[]>([]);
  const [dayStart, setDayStart] = useState("06:00");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [saveError, setSaveError] = useState("");
  const rev = useRef(0); // bumps on every local edit
  const dirty = useRef(false);

  const reload = useCallback(() => {
    setLoad("loading");
    fetchState()
      .then((s) => {
        setCategories(s.categories);
        setWeek(toWeek(s));
        setNotes(s.notes ?? "");
        // someone who drew a week before the choice existed keeps a week, unasked
        const anyBlock = Object.values(s.typical_week).some((b) => b && b.length > 0);
        setRoutineMode(s.routine_mode ?? (anyBlock ? "week" : null));
        setDefaults(s.defaults);
        setDayStart(s.day_start);
        setLoad("ready");
        // a category without a colour of its own shows its calendar's, so the page and
        // the Calendar app agree from the start (not an edit: nothing is autosaved)
        calendarColors().then((colors) =>
          setCategories((c) =>
            Object.fromEntries(
              Object.entries(c).map(([name, cat]) => [name, cat.color || !colors[name] ? cat : { ...cat, color: colors[name] }]),
            ),
          ),
        );
      })
      .catch((e: Error) => {
        setLoadError(e.message);
        setLoad("error");
      });
  }, []);

  useEffect(reload, [reload]);

  const save = useCallback((cats: Categories, w: Week, n: string, mode: RoutineMode | null) => {
    const mine = rev.current;
    setSaveStatus("saving");
    saveState(cats, w, n, mode)
      .then(() => {
        if (mine === rev.current) {
          dirty.current = false;
          setSaveStatus("saved");
        }
      })
      .catch((e: Error) => {
        if (mine === rev.current) {
          setSaveError(e.message);
          setSaveStatus("error");
        }
      });
  }, []);

  // debounced autosave after any edit
  useEffect(() => {
    if (!dirty.current) return;
    const t = window.setTimeout(() => save(categories, week, notes, routineMode), AUTOSAVE_MS);
    return () => window.clearTimeout(t);
  }, [categories, week, notes, routineMode, save]);

  // warn before closing the tab with unsaved edits
  useEffect(() => {
    const onLeave = (e: BeforeUnloadEvent) => {
      if (dirty.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, []);

  const touch = () => {
    rev.current += 1;
    dirty.current = true;
    setSaveStatus("idle");
  };

  const updateWeek = useCallback((fn: (w: Week) => Week) => {
    touch();
    setWeek((w) => mirror(fn(w)));
  }, []);

  /** Pick how the routine is drawn. Going to one day makes `from` the day used everywhere. */
  const chooseRoutineMode = useCallback((mode: RoutineMode, from: Weekday = TEMPLATE_DAY) => {
    touch();
    modeRef.current = mode;
    setRoutineMode(mode);
    if (mode === "day") setWeek((w) => everyDay({ ...w, [TEMPLATE_DAY]: w[from] }, TEMPLATE_DAY));
  }, []);

  const updateCategories = useCallback((fn: (c: Categories) => Categories) => {
    touch();
    setCategories(fn);
  }, []);

  /** Delete a category together with every block that uses it. */
  const removeCategory = useCallback((name: string) => {
    touch();
    setCategories(({ [name]: _, ...rest }) => rest);
    setWeek((w) =>
      Object.fromEntries(WEEKDAYS.map((d) => [d, w[d].filter((b) => b.category !== name)])) as Week,
    );
  }, []);

  /** Put imported blocks into the given days, replacing them or adding to them. A block
   *  with the same time and title as one already there is skipped, whatever its category,
   *  so importing twice doesn't double the week. */
  const importBlocks = useCallback((incoming: Week, replace: boolean, days: Weekday[]) => {
    touch();
    setWeek((w) =>
      mirror(Object.fromEntries(
        WEEKDAYS.map((d) => {
          if (!days.includes(d)) return [d, w[d]];
          const out = replace ? [] : [...w[d]];
          const seen = new Set(out.map(blockKey));
          for (const b of incoming[d]) {
            const key = blockKey(b);
            if (seen.has(key)) continue;
            seen.add(key);
            out.push(b);
          }
          return [d, out];
        }),
      ) as Week),
    );
  }, []);

  const updateNotes = useCallback((text: string) => {
    touch();
    setNotes(text);
  }, []);

  const retrySave = useCallback(() => save(categories, week, notes, routineMode), [save, categories, week, notes, routineMode]);

  return {
    load, loadError, reload,
    categories, week, notes, defaults, dayStart, updateNotes, routineMode, chooseRoutineMode,
    updateWeek, updateCategories, removeCategory, importBlocks,
    saveStatus, saveError, retrySave,
  };
}
