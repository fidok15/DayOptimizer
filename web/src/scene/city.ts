import { css, hex, mix, smooth, type Palette, type RGB } from "./sky";

/** Buildings are laid out on a virtual strip this many units wide, then scaled to the viewport. */
export const CITY_W = 1600;

export function mulberry32(seed: number): () => number {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Stateless 0..1 hash, so windows need no stored thresholds. */
export const hash = (a: number, b: number): number => {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35);
  h = Math.imul(h ^ (h >>> 16), 0x7feb352d);
  h = Math.imul(h ^ (h >>> 15), 0x846ca68b);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
};

interface Tier {
  inset: number; // units trimmed from each side
  top: number; // roof height as a fraction of viewport height
}

export interface Building {
  x: number;
  w: number;
  tiers: Tier[];
  antenna: number;
  spire: number;
  tank: boolean;
}

type Range = [number, number];
const lerp = ([a, b]: Range, t: number): number => a + (b - a) * t;

const SPEC: { w: Range; h: Range; gap: Range }[] = [
  { w: [28, 80], h: [0.16, 0.34], gap: [0, 5] }, // far
  { w: [38, 96], h: [0.1, 0.29], gap: [2, 9] }, // mid
  { w: [48, 124], h: [0.05, 0.18], gap: [3, 14] }, // near
];

const LANDMARKS: Building[][] = [
  [
    { x: 260, w: 46, tiers: [{ inset: 0, top: 0.35 }, { inset: 9, top: 0.4 }], antenna: 0.05, spire: 0, tank: false },
  ],
  [
    // stepped art deco tower with a spire
    {
      x: 560,
      w: 78,
      tiers: [
        { inset: 0, top: 0.29 },
        { inset: 10, top: 0.35 },
        { inset: 20, top: 0.39 },
        { inset: 28, top: 0.41 },
      ],
      antenna: 0,
      spire: 0.045,
      tank: false,
    },
    // slim glass tower
    { x: 1130, w: 56, tiers: [{ inset: 0, top: 0.42 }], antenna: 0.04, spire: 0, tank: false },
  ],
  [],
];

export function generateCity(): Building[][] {
  const rand = mulberry32(0x5eed1e);
  return SPEC.map((s, depth) => {
    const out: Building[] = [];
    const marks = [...LANDMARKS[depth]];
    let x = -40;
    while (x < CITY_W + 40) {
      if (marks.length && x >= marks[0].x - 10) {
        const m = { ...marks.shift()!, x };
        out.push(m);
        x += m.w + 3 + rand() * 5;
        continue;
      }
      const w = lerp(s.w, rand());
      const top = lerp(s.h, rand() ** 1.4);
      const tiers: Tier[] = [{ inset: 0, top }];
      if (top > 0.13 && w > 44 && rand() < 0.35) {
        const n = rand() < 0.4 ? 2 : 1;
        const base = top * (0.66 + rand() * 0.12);
        tiers[0].top = base;
        for (let k = 1; k <= n; k++) tiers.push({ inset: w * 0.13 * k, top: base + ((top - base) * k) / n });
      }
      const antenna = rand() < 0.18 ? 0.012 + rand() * 0.03 : 0;
      const spire = !antenna && rand() < 0.05 ? 0.02 + rand() * 0.02 : 0;
      const tank = depth > 0 && !antenna && !spire && rand() < 0.2;
      out.push({ x, w, tiers, antenna, spire, tank });
      x += w + lerp(s.gap, rand());
    }
    return out;
  });
}

const NIGHT = ["#1b2136", "#111626", "#07090f"].map(hex);
const DAY = ["#8d9db5", "#5a6780", "#2d3546"].map(hex);
const HAZE_MIX = [0.45, 0.18, 0.04];
const WIN = [
  { w: 2, h: 2, gx: 3, gy: 4, pad: 4 },
  { w: 3, h: 4, gx: 4, gy: 5, pad: 5 },
  { w: 4, h: 6, gx: 5, gy: 6, pad: 6 },
];
const WARM = ["#ffd99a", "#ffcc80", "#f9e4b8", "#ffc070", "#ffe0a8"].map(hex);
const TV = hex("#bcd4ff");
const BLACK: RGB = [0, 0, 0];

/** Share of windows lit: near 0 at noon, about 45% deep at night. */
export const litShare = (darkness: number): number => 0.015 + 0.435 * smooth(0.15, 0.95, darkness);

export interface View {
  width: number; // layer canvas width, css px
  H: number; // viewport height; building heights are fractions of it
  groundY: number; // y of the ground in the layer canvas
  sx: number; // units to px
  ox: number; // px offset of unit 0
}

/** Paints one layer and returns the keys of its windows (used to pick windows to toggle). */
export function renderLayer(
  ctx: CanvasRenderingContext2D,
  buildings: Building[],
  depth: number,
  v: View,
  pal: Palette,
  toggled: Set<number>,
): number[] {
  const d = pal.darkness;
  const { H, groundY, sx, ox } = v;
  const facade = mix(mix(NIGHT[depth], DAY[depth], 1 - d), pal.haze, HAZE_MIX[depth]);
  const facadeCss = css(facade);
  const unlitCss = css(mix(mix(facade, BLACK, 0.3), mix(facade, pal.mid, 0.4), 1 - d));
  const warmCss = WARM.map((c) => css(c, depth === 0 ? 0.7 : 0.95));
  const tvCss = css(TV, 0.85);
  const rimCss = css(pal.low, 0.12 * (1 - d));
  const roofCss = css(mix(facade, pal.low, 0.35), 0.6 * (1 - d) + 0.1);
  const share = litShare(d);
  const cell = WIN[depth];
  const keys: number[] = [];

  ctx.clearRect(0, 0, v.width, groundY);
  ctx.fillStyle = facadeCss;
  if (depth === 0) ctx.fillRect(0, groundY - H * 0.05, v.width, H * 0.05);

  buildings.forEach((b, bi) => {
    const px = ox + b.x * sx;
    const pw = b.w * sx;
    if (px > v.width || px + pw < 0) return;
    let cx = 0;
    let topY = groundY;
    let topW = pw;

    b.tiers.forEach((t, ti) => {
      const x0 = Math.round(px + t.inset * sx);
      const tw = Math.round(pw - 2 * t.inset * sx);
      const y = Math.round(groundY - t.top * H);
      // Upper tiers only paint above the tier below, so its windows stay visible.
      const tierBottom = ti === 0 ? groundY : Math.round(groundY - b.tiers[ti - 1].top * H);
      ctx.fillStyle = facadeCss;
      ctx.fillRect(x0, y, tw, tierBottom - y);
      if (d < 0.95) {
        ctx.fillStyle = rimCss;
        ctx.fillRect(x0, y, Math.max(1, tw * 0.1), tierBottom - y);
        ctx.fillStyle = roofCss;
        ctx.fillRect(x0, y, tw, 1);
      }
      cx = x0 + tw / 2;
      topY = y;
      topW = tw;

      const bottom = (ti === 0 ? groundY - 8 : tierBottom) - cell.pad * 0.5;
      const cols = Math.floor((tw - 2 * cell.pad + cell.gx) / (cell.w + cell.gx));
      const rows = Math.floor((bottom - y - cell.pad + cell.gy) / (cell.h + cell.gy));
      if (cols < 1 || rows < 1) return;
      const sx0 = Math.round(x0 + (tw - (cols * (cell.w + cell.gx) - cell.gx)) / 2);
      for (let r = 0; r < rows; r++) {
        const wy = y + cell.pad + r * (cell.h + cell.gy);
        for (let c = 0; c < cols; c++) {
          const key = depth * 1e8 + bi * 1e6 + ti * 1e5 + r * 300 + c;
          const lit = hash(key, 7) < share !== toggled.has(key);
          if (lit) {
            ctx.fillStyle = hash(key, 3) < 0.06 ? tvCss : warmCss[Math.floor(hash(key, 5) * warmCss.length)];
          } else if (depth > 0) {
            ctx.fillStyle = unlitCss;
          } else continue;
          ctx.fillRect(sx0 + c * (cell.w + cell.gx), wy, cell.w, cell.h);
          if (depth > 0) keys.push(key);
        }
      }
    });

    ctx.fillStyle = facadeCss;
    ctx.strokeStyle = facadeCss;
    if (b.spire) {
      ctx.beginPath();
      ctx.moveTo(cx - topW * 0.2, topY);
      ctx.lineTo(cx, topY - b.spire * H);
      ctx.lineTo(cx + topW * 0.2, topY);
      ctx.fill();
    }
    if (b.antenna) {
      const tip = topY - b.antenna * H;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx, topY);
      ctx.lineTo(cx, tip);
      ctx.stroke();
      if (d > 0.45) {
        ctx.fillStyle = css(hex("#ff4a3d"), d);
        ctx.fillRect(cx - 1, tip - 1, 2, 2);
      }
    }
    if (b.tank) {
      const tw = Math.min(14, topW * 0.22);
      const tx = cx - topW * 0.25;
      ctx.fillRect(tx, topY - 12, tw, 8);
      ctx.fillRect(tx + 1, topY - 4, 1, 4);
      ctx.fillRect(tx + tw - 2, topY - 4, 1, 4);
    }
  });

  // Atmospheric perspective: far layers sink into the haze toward the ground.
  const hazeAmt = [0.4, 0.16, 0][depth];
  if (hazeAmt) {
    const g = ctx.createLinearGradient(0, groundY - H * 0.42, 0, groundY);
    g.addColorStop(0, css(pal.haze, 0));
    g.addColorStop(1, css(pal.haze, hazeAmt));
    ctx.globalCompositeOperation = "source-atop";
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, v.width, groundY);
    ctx.globalCompositeOperation = "source-over";
  }
  return keys;
}
