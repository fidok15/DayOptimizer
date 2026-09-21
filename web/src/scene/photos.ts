import day from "../assets/scene/day.webp";
import golden from "../assets/scene/golden.webp";
import sunset from "../assets/scene/sunset.webp";
import night from "../assets/scene/night.webp";

export type PhotoKey = "day" | "golden" | "sunset" | "night";
export type Weights = Record<PhotoKey, number>;

/** Stacking order, bottom first. See assets/scene/CREDITS.md. */
export const PHOTOS: { key: PhotoKey; src: string; position: string }[] = [
  { key: "night", src: night, position: "50% 45%" },
  { key: "sunset", src: sunset, position: "50% 60%" },
  { key: "golden", src: golden, position: "50% 55%" },
  { key: "day", src: day, position: "50% 40%" },
];

const W = (day: number, golden: number, sunset: number, night: number): Weights => ({ day, golden, sunset, night });

// hour -> how much of each photo shows. Each photo holds its part of the day;
// crossfades last 30 min because different shots ghost when blended longer.
const KEYS: [number, Weights][] = [
  [0, W(0, 0, 0, 1)],
  [5, W(0, 0, 0, 1)],
  [5.5, W(0, 0, 1, 0)],
  [6.5, W(0, 0, 1, 0)],
  [7, W(0, 1, 0, 0)],
  [9, W(0, 1, 0, 0)],
  [9.5, W(1, 0, 0, 0)],
  [17, W(1, 0, 0, 0)],
  [17.5, W(0, 1, 0, 0)],
  [18.75, W(0, 1, 0, 0)],
  [19.25, W(0, 0, 1, 0)],
  [20.5, W(0, 0, 1, 0)],
  [21, W(0, 0, 0, 1)],
  [24, W(0, 0, 0, 1)],
];

export function weights(hour: number): Weights {
  const i = KEYS.findIndex(([h]) => h > hour);
  const [h0, a] = KEYS[i - 1];
  const [h1, b] = KEYS[i];
  const t = (hour - h0) / (h1 - h0);
  return W(
    a.day + (b.day - a.day) * t,
    a.golden + (b.golden - a.golden) * t,
    a.sunset + (b.sunset - a.sunset) * t,
    a.night + (b.night - a.night) * t,
  );
}

/** Per-layer CSS opacity so stacked layers composite to exactly the weighted blend. */
export function layerOpacities(w: Weights): Weights {
  const out = { ...w };
  let below = 0;
  for (const { key } of PHOTOS) {
    below += w[key];
    out[key] = below > 0 ? w[key] / below : 0;
  }
  return out;
}

export const darkness = (w: Weights): number => w.night + 0.45 * w.sunset;
