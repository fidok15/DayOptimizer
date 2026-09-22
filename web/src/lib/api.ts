import type { Categories, ImportedBlock, ServerState, Week, Weekday } from "./types";

async function parse(res: Response): Promise<ServerState> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
  return body as ServerState;
}

export const fetchState = (): Promise<ServerState> =>
  fetch("/api/state", { cache: "no-store" }).then(parse);

export const saveState = (categories: Categories, week: Week): Promise<ServerState> => {
  const typical_week = Object.fromEntries(
    Object.entries(week).map(([day, blocks]) => [
      day,
      blocks.map(({ start, end, category, title }) => ({ start, end, category, title })),
    ]),
  );
  return fetch("/api/state", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ categories, typical_week }),
  }).then(parse);
};

export type ImportedWeek = Partial<Record<Weekday, ImportedBlock[]>>;

/** API failure with a machine-readable reason, e.g. setup | denied | auth | mfa | rate | offline | expired. */
export class ApiError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
  }
}

/** Read one calendar week (Monday date) as blocks tagged with their calendar. Nothing is saved. */
export const importWeek = async (weekStart: string): Promise<ImportedWeek> => {
  const body = await post<{ typical_week?: unknown }>("/api/import", { week_start: weekStart });
  if (typeof body.typical_week !== "object" || !body.typical_week) throw new ApiError("The calendar answer looked wrong. Try again.", "bad");
  return body.typical_week as ImportedWeek;
};

/** POST JSON and return the body, or throw ApiError with the server's code. */
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
