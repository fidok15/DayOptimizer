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

/** Import failure with a machine-readable reason (setup | denied | timeout | failed | offline | bad). */
export class ImportError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
  }
}

/** Read one calendar week (Monday date) as blocks tagged with their calendar. Nothing is saved. */
export const importWeek = async (weekStart: string): Promise<ImportedWeek> => {
  let res: Response;
  try {
    res = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ week_start: weekStart }),
    });
  } catch {
    throw new ImportError("Can't reach DayOptimizer. Is `dayoptimizer web` still running?", "offline");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok || !body) throw new ImportError(body?.error ?? `Import failed (${res.status}).`, body?.code ?? "failed");
  if (typeof body.typical_week !== "object") throw new ImportError("The calendar answer looked wrong. Try again.", "bad");
  return body.typical_week;
};
