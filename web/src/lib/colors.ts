export const SWATCHES = [
  "#e0625a", "#5b8def", "#4a9ec2", "#6c6fd1", "#e07b53",
  "#8a94a6", "#4fb286", "#c77dcb", "#6fc3b2", "#d4b44a",
];

const DEFAULTS: Record<string, string> = {
  Important: "#e0625a", Meeting: "#5b8def", Work: "#4a9ec2", Sleep: "#6c6fd1",
  Food: "#e07b53", Transport: "#8a94a6", Gym: "#4fb286", Learn: "#c77dcb",
  "Free time": "#6fc3b2",
};

/** Stored colour, else a known default, else a stable swatch from the name. */
export const categoryColor = (name: string, stored?: string): string => {
  if (stored) return stored;
  if (DEFAULTS[name]) return DEFAULTS[name];
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return SWATCHES[h % SWATCHES.length];
};

/** Colour for a new category: its usual one unless taken, else the first free swatch. */
export const freshColor = (name: string, taken: string[]): string => {
  const preferred = categoryColor(name);
  if (!taken.includes(preferred)) return preferred;
  return SWATCHES.find((c) => !taken.includes(c)) ?? preferred;
};
