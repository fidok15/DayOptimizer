export const SNAP = 15;
export const DAY_MIN = 24 * 60;

export const toMin = (hhmm: string): number => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

export const fromMin = (min: number): string => {
  const m = Math.max(0, Math.min(DAY_MIN, Math.round(min)));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

export const snap = (min: number, step = SNAP): number => Math.round(min / step) * step;

export const durationLabel = (min: number): string => {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h && m ? `${h}h ${m}m` : h ? `${h}h` : `${m}m`;
};

/** Local hour as a float (21.5 = 21:30). `?hour=` in the URL overrides it for QA. */
export const sceneHour = (): number => {
  const q = new URLSearchParams(window.location.search).get("hour");
  const forced = q === null ? NaN : Number(q);
  if (Number.isFinite(forced)) return ((forced % 24) + 24) % 24;
  const d = new Date();
  return d.getHours() + d.getMinutes() / 60;
};

export const uid = (): string => Math.random().toString(36).slice(2, 10);
