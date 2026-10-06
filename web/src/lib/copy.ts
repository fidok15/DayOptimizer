const LINES = [
  "Show us your rhythm, we'll shape your week",
  "Your routine in, a smarter week out",
  "Sketch your usual week once, get a fresh plan every Monday",
  "Your habits set the rules, your calendar sets the scene",
  "The week you want, fitted around the week you have",
  "Teach it your days, let it optimize the rest",
]

export const lineOfTheDay = (d = new Date()): string => {
  const day = Math.floor(d.getTime() / 86_400_000);
  return LINES[day % LINES.length];
};

export const greeting = (hour: number): string =>
  hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
