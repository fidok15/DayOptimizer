import { categoryColor } from "./colors";
import type { Categories, FreeTime, ImportedBlock, RoutineMode, ServerState, Week, Weekday } from "./types";

async function parse(res: Response): Promise<ServerState> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
  return body as ServerState;
}

export const fetchState = (): Promise<ServerState> =>
  fetch("/api/state", { cache: "no-store" }).then(parse);

const toServerWeek = (week: Week) =>
  Object.fromEntries(
    Object.entries(week).map(([day, blocks]) => [
      day,
      blocks.map(({ start, end, category, title, protected: keep, intent }) => ({
        start, end, category, title, ...(keep && !intent?.trim() && { protected: true }), ...(intent?.trim() && { intent: intent.trim() }),
      })),
    ]),
  );

export const saveState = (categories: Categories, week: Week, notes: string, routineMode: RoutineMode | null, free: FreeTime): Promise<ServerState> => {
  const typical_week = toServerWeek(week);
  return fetch("/api/state", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ categories, typical_week, notes, ...(routineMode && { routine_mode: routineMode }), ...free }),
  }).then(parse);
};

export type ImportedWeek = Partial<Record<Weekday, ImportedBlock[]>>;

export class ApiError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
  }
}

export type ImportedCalendars = {
  week: ImportedWeek;
  calendars: Record<string, string>;
  google: string[];
  span?: [string, string] | null;
  allDay: { calendar: string; title: string; days: Weekday[] }[];
};

const toImported = (body: { typical_week?: unknown; calendars?: unknown; google?: unknown; span?: unknown; all_day?: unknown }): ImportedCalendars => {
  if (typeof body.typical_week !== "object" || !body.typical_week) throw new ApiError("The calendar answer looked wrong. Try again.", "bad");
  const calendars = typeof body.calendars === "object" && body.calendars ? (body.calendars as Record<string, string>) : {};
  const span = Array.isArray(body.span) && body.span.length === 2 ? (body.span as [string, string]) : null;
  const allDay = Array.isArray(body.all_day) ? (body.all_day as ImportedCalendars["allDay"]) : [];
  return { week: body.typical_week as ImportedWeek, calendars, google: Array.isArray(body.google) ? body.google : [], span, allDay };
};

export const importWeek = async (weekStart: string): Promise<ImportedCalendars> =>
  toImported(await post("/api/import", { week_start: weekStart }));

export const importFiles = async (weekStart: string, files: string[]): Promise<ImportedCalendars> =>
  toImported(await post("/api/import-file", { week_start: weekStart, files }));

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError("Can't reach DayOptimizer. Is `dayoptimizer web` still running?", "offline");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok || !data) throw new ApiError(data?.error ?? `Request failed (${res.status}).`, data?.code ?? "failed");
  return data as T;
}

export const garminStatus = (): Promise<{ connected: boolean }> =>
  fetch("/api/garmin", { cache: "no-store" }).then((r) => (r.ok ? r.json() : { connected: false }));
export const garminLogin = (email: string, password: string) =>
  post<{ status: "connected" | "mfa" }>("/api/garmin/login", { email, password });
export const garminMfa = (code: string) => post<{ status: "connected" }>("/api/garmin/mfa", { code });
export const garminDisconnect = () => post<{ status: "disconnected" }>("/api/garmin/disconnect", {});

export interface RoutineSaved {
  path: string;
  text: string;
  calendars: { created: string[]; recolored: string[]; error: string | null };
  notes: { rules: string[]; not_compiled: string[]; error: string | null };
}

export const saveRoutine = (categories: Categories, week: Week, notes: string) => {
  const coloured = Object.fromEntries(
    Object.entries(categories).map(([name, c]) => [name, { ...c, color: categoryColor(name, c.color) }]),
  );
  return post<RoutineSaved>("/api/routine", { categories: coloured, typical_week: toServerWeek(week), notes });
};

export const calendarColors = (): Promise<{ colors: Record<string, string>; calendars: Record<string, string> }> =>
  fetch("/api/calendar-colors", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((b: { colors?: Record<string, string>; calendars?: Record<string, string> } | null) => ({
      colors: b?.colors ?? {},
      calendars: b?.calendars ?? {},
    }))
    .catch(() => ({ colors: {}, calendars: {} }));
