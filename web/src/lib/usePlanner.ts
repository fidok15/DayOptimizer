import { useCallback, useEffect, useRef, useState } from "react";
import { fetchState, saveState } from "./api";
import { uid } from "./time";
import { WEEKDAYS, type Categories, type SaveStatus, type ServerState, type Week } from "./types";

const AUTOSAVE_MS = 700;

const toWeek = (s: ServerState): Week =>
  Object.fromEntries(
    WEEKDAYS.map((d) => [d, (s.typical_week[d] ?? []).map((b) => ({ ...b, id: uid() }))]),
  ) as Week;

export function usePlanner() {
  const [load, setLoad] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [categories, setCategories] = useState<Categories>({});
  const [week, setWeek] = useState<Week>(() => toWeek({ typical_week: {} } as ServerState));
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
        setDefaults(s.defaults);
        setDayStart(s.day_start);
        setLoad("ready");
      })
      .catch((e: Error) => {
        setLoadError(e.message);
        setLoad("error");
      });
  }, []);

  useEffect(reload, [reload]);

  const save = useCallback((cats: Categories, w: Week) => {
    const mine = rev.current;
    setSaveStatus("saving");
    saveState(cats, w)
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
    const t = window.setTimeout(() => save(categories, week), AUTOSAVE_MS);
    return () => window.clearTimeout(t);
  }, [categories, week, save]);

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
    setWeek(fn);
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

  /** Put imported blocks into the week, replacing it or adding to it. */
  const importBlocks = useCallback((incoming: Week, replace: boolean) => {
    touch();
    setWeek((w) => Object.fromEntries(WEEKDAYS.map((d) => [d, replace ? incoming[d] : [...w[d], ...incoming[d]]])) as Week);
  }, []);

  const retrySave = useCallback(() => save(categories, week), [save, categories, week]);

  return {
    load, loadError, reload,
    categories, week, defaults, dayStart,
    updateWeek, updateCategories, removeCategory, importBlocks,
    saveStatus, saveError, retrySave,
  };
}
