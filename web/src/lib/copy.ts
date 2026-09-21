const LINES = [
  "Protect your peak hours. Spend them on what matters.",
  "A planned day is a lighter day.",
  "Deep work first. Everything else fits around it.",
  "Rest is part of the plan, not a break from it.",
  "Small blocks done daily beat big plans done never.",
  "Give every hour a job, including the easy ones.",
  "Energy is the budget. Spend it where it counts.",
  "Decide once in the morning, not fifty times a day.",
  "Sleep well tonight and tomorrow plans itself.",
];

/** One line per calendar day, stable for the whole day. */
export const lineOfTheDay = (d = new Date()): string => {
  const day = Math.floor(d.getTime() / 86_400_000);
  return LINES[day % LINES.length];
};

export const greeting = (hour: number): string =>
  hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
