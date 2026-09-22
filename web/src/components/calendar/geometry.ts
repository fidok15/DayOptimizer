import { WEEKDAYS, type Block, type Weekday } from "../../lib/types";
import { DAY_MIN, SNAP, toMin } from "../../lib/time";

export const HOUR_PX = 52;
export const PX_PER_MIN = HOUR_PX / 60;
export const GRID_H = 24 * HOUR_PX;
export const DRAFT_ID = "__draft__";
/** Opaque grid surface: the scene must never show through the hour cells. */
export const SURFACE = "rgb(15 19 34)";

export const DAY_NAME: Record<Weekday, string> = {
  mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday",
  fri: "Friday", sat: "Saturday", sun: "Sunday",
};

export const todayKey = (): Weekday => WEEKDAYS[(new Date().getDay() + 6) % 7];

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Snap a range to the grid and keep it valid: 0 <= start < end <= 24:00, at least SNAP long. */
export const normalizeRange = (start: number, end: number): [number, number] => {
  const s = clamp(Math.round(start / SNAP) * SNAP, 0, DAY_MIN - SNAP);
  const e = clamp(Math.round(end / SNAP) * SNAP, s + SNAP, DAY_MIN);
  return [s, e];
};

export interface Lane { lane: number; lanes: number }

/** Side-by-side lanes for overlapping blocks. Each cluster of overlaps shares one lane count. */
export function layoutLanes(blocks: Block[]): Map<string, Lane> {
  const sorted = [...blocks].sort((a, b) => toMin(a.start) - toMin(b.start) || toMin(b.end) - toMin(a.end));
  const out = new Map<string, Lane>();
  let cluster: { id: string; lane: number }[] = [];
  let laneEnds: number[] = [];
  let clusterEnd = -1;
  const flush = () => {
    for (const c of cluster) out.set(c.id, { lane: c.lane, lanes: laneEnds.length });
    cluster = [];
    laneEnds = [];
  };
  for (const b of sorted) {
    const s = toMin(b.start);
    const e = toMin(b.end);
    if (s >= clusterEnd) flush();
    let lane = laneEnds.findIndex((end) => end <= s);
    if (lane === -1) lane = laneEnds.push(e) - 1;
    else laneEnds[lane] = e;
    cluster.push({ id: b.id, lane });
    clusterEnd = Math.max(clusterEnd, e);
  }
  flush();
  return out;
}

const NIGHT = [12, 16, 30];
/** Relative luminance of `hex` drawn at `alpha` over the night colour. */
const luminance = (hex: string, alpha = 1) => {
  const n = parseInt(hex.slice(1, 7), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v, i) => {
    const c = (alpha * v + (1 - alpha) * NIGHT[i]) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
};

/** Near-white or night text, whichever contrasts more with the block colour (drawn at 85%). */
export const readableText = (hex: string): string => {
  const l = luminance(hex, 0.85);
  const onWhite = 1.05 / (l + 0.05);
  const onNight = (l + 0.05) / (luminance("#0c101e") + 0.05);
  return onWhite >= onNight ? "#fbfaf7" : "#0c101e";
};
