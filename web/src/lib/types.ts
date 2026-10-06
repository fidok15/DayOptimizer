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

export interface ServerState {
  categories: Categories;
  typical_week: Partial<Record<Weekday, Omit<Block, "id">[]>>;
  notes: string;
  routine_mode?: RoutineMode | null;
  defaults: string[];
  day_start: string;
  day_end: string;
}

export type SaveStatus = "idle" | "saving" | "saved" | "error";
