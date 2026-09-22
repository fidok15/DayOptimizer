export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Weekday = (typeof WEEKDAYS)[number];
export const WEEKDAY_LABEL: Record<Weekday, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
};

export interface Category {
  movable: boolean; // true = Flexible (planner moves it), false = Fixed
  priority: number; // 0-10
  color?: string; // #rrggbb
  emoji?: string; // optional icon shown next to the name
}
export type Categories = Record<string, Category>;

/** A block of the typical week. `id` is client-only and never sent to the server. */
export interface Block {
  id: string;
  start: string; // "HH:MM"
  end: string; // "HH:MM" or "24:00", always > start
  category: string; // key of Categories
  title: string;
}
export type Week = Record<Weekday, Block[]>;

export type View = "day" | "week";

/** Shape of GET /api/state (blocks arrive without ids). */
export interface ServerState {
  categories: Categories;
  typical_week: Partial<Record<Weekday, Omit<Block, "id">[]>>;
  defaults: string[];
  day_start: string;
  day_end: string;
}

export type SaveStatus = "idle" | "saving" | "saved" | "error";
