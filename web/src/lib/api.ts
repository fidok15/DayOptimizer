import type { Categories, ServerState, Week } from "./types";

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
