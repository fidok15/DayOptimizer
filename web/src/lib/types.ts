export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Weekday = (typeof WEEKDAYS)[number];
export const WEEKDAY_LABEL: Record<Weekday, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
};

export interface Category {
  movable: boolean;
  priority: number;
  color?: string;
  emoji?: string;
}
export type Categories = Record<string, Category>;

export interface Block {
  id: string;
  start: string;
  end: string;
  category: string;
  title: string;
  /** Tasks never take this block's time; it may still move when its category is flexible. */
  protected?: boolean;
  /** An open block: the planner fills it with something that fits this intent. Set (even "") = open. */
  intent?: string;
}
export type Week = Record<Weekday, Block[]>;

export interface ImportedBlock {
  start: string;
  end: string;
  calendar: string;
  title: string;
}

export type View = "day" | "week";

export type RoutineMode = "day" | "week";

export type Variety = "low" | "medium" | "high";
export type Backend = "auto" | "ollama" | "anthropic";
export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

/** GET /api/settings: what the planner reads, merged with the defaults. The API key itself never comes back. */
export interface Settings {
  llm: { backend: Backend; model: string; ollama_model: string };
  key_set: boolean;
  ollama: boolean;
  share_health: boolean;
  garmin: boolean;
  day: {
    day_start: string;
    day_end: string;
    buffer_minutes: number;
    morning_buffer_minutes: number;
    work_days: DayKey[];
    min_free_minutes: number;
    variety: Variety | null;
  };
  agent: { running: boolean; interval_minutes: number | null; bundle: boolean };
}

export interface ServerState {
  categories: Categories;
  typical_week: Partial<Record<Weekday, Omit<Block, "id">[]>>;
  notes: string;
  routine_mode?: RoutineMode | null;
  defaults: string[];
  day_start: string;
  day_end: string;
  min_free_minutes: number | null;
  variety: Variety | null;
}

export type SaveStatus = "idle" | "saving" | "saved" | "error";
