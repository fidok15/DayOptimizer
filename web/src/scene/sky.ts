export type RGB = [number, number, number];

export const hex = (s: string): RGB => {
  const n = parseInt(s.slice(1), 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
};

export const mix = (a: RGB, b: RGB, t: number): RGB => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
];

export const css = (c: RGB, a = 1): string =>
  `rgb(${Math.round(c[0])} ${Math.round(c[1])} ${Math.round(c[2])} / ${a})`;

export const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

export const smooth = (e0: number, e1: number, x: number): number => {
  const t = clamp01((x - e0) / (e1 - e0));
  return t * t * (3 - 2 * t);
};

export interface Palette {
  top: RGB;
  mid: RGB;
  low: RGB;
  haze: RGB;
  darkness: number;
}

interface Key {
  h: number;
  top: string;
  mid: string;
  low: string;
  haze: string;
  dark: number;
}

// Sorted by hour, first key at 0 so the lookup below always finds one.
const KEYS: Key[] = [
  { h: 0, top: "#060a1a", mid: "#0c1330", low: "#18213f", haze: "#212a48", dark: 1 },
  { h: 5, top: "#0a0f27", mid: "#1b2046", low: "#3a355f", haze: "#3b3a5e", dark: 0.92 },
  { h: 6.25, top: "#2b3767", mid: "#77699a", low: "#e6a78b", haze: "#d19a8c", dark: 0.55 },
  { h: 7.5, top: "#4d7dbd", mid: "#9ab5d7", low: "#f0d0b2", haze: "#e3c7b3", dark: 0.18 },
  { h: 10, top: "#3d7bc6", mid: "#7eafe0", low: "#c8def0", haze: "#c9dcea", dark: 0 },
  { h: 13, top: "#3675c3", mid: "#73a8de", low: "#bdd8ef", haze: "#c3d8ea", dark: 0 },
  { h: 17, top: "#4a7bbd", mid: "#90b2d6", low: "#e2d5c1", haze: "#dccfbf", dark: 0.05 },
  { h: 19, top: "#3a4e88", mid: "#ae7a8f", low: "#f0a86c", haze: "#df9a79", dark: 0.35 },
  { h: 20.5, top: "#1b224e", mid: "#483c6c", low: "#a5667b", haze: "#6c5070", dark: 0.72 },
  { h: 22, top: "#0a0f25", mid: "#141c3d", low: "#282c51", haze: "#2b3051", dark: 0.95 },
];

const parsed = KEYS.map((k) => ({
  h: k.h,
  top: hex(k.top),
  mid: hex(k.mid),
  low: hex(k.low),
  haze: hex(k.haze),
  dark: k.dark,
}));

export function palette(hour: number): Palette {
  const h = ((hour % 24) + 24) % 24;
  let i = parsed.length - 1;
  while (i > 0 && parsed[i].h > h) i--;
  const a = parsed[i];
  const b = parsed[(i + 1) % parsed.length];
  const span = (b.h - a.h + 24) % 24 || 24;
  const t = smooth(0, 1, ((h - a.h + 24) % 24) / span);
  return {
    top: mix(a.top, b.top, t),
    mid: mix(a.mid, b.mid, t),
    low: mix(a.low, b.low, t),
    haze: mix(a.haze, b.haze, t),
    darkness: a.dark + (b.dark - a.dark) * t,
  };
}
