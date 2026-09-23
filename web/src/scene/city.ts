import { GROUND, MAX_TOP } from "./layout";
import { clamp01, css, hex, mix, smooth, type Palette, type RGB } from "./sky";

/** Buildings are laid out on a virtual strip this many units wide, then scaled to the viewport. */
export const CITY_W = 1600;

/** Tallest possible roof (incl. spires/antennas) above the ground, as a fraction of H. */
export const MAX_H = GROUND - MAX_TOP;

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
  top: number; // roof height above the ground as a fraction of viewport height
  shift?: number; // units moved sideways (twisting towers)
}

export interface Building {
  x: number;
  w: number;
  tiers: Tier[];
  antenna: number;
  spire: number;
  tank: boolean;
  glass?: boolean; // floor-band windows, mullions, sky reflection
  roof?: "slant" | "dome"; // shape on top of the last tier (tier.top is its peak)
  slantLeft?: boolean; // high side of a slanted roof
  crown?: boolean; // tier edges outlined with lights at night
  hvac?: boolean; // rooftop machinery boxes
}

type Range = [number, number];
const lerp = ([a, b]: Range, t: number): number => a + (b - a) * t;

const SPEC: { w: Range; h: Range; gap: Range; env: number }[] = [
  { w: [26, 62], h: [0.28, 0.52], gap: [-6, 0], env: 1 }, // far
  { w: [34, 76], h: [0.2, 0.46], gap: [-4, 2], env: 0.85 }, // mid
  { w: [44, 104], h: [0.1, 0.3], gap: [-2, 7], env: 0.35 }, // near
];

// Height envelope: main downtown core center-left, a smaller cluster right.
const bump = (x: number, c: number, s: number): number => Math.exp(-(((x - c) / s) ** 2));
const skyline = (x: number): number => Math.max(bump(x, 540, 280), 0.75 * bump(x, 1240, 160));

const taper = (n: number, w: number, from: number, to: number, twist: number): Tier[] =>
  Array.from({ length: n }, (_, k) => ({
    inset: (w * 0.32 * k) / (n - 1),
    top: from + ((to - from) * k) / (n - 1),
    shift: Math.sin(k * 1.1) * twist,
  }));

const LANDMARKS: Building[][] = [
  [
    // twisted, tapering supertall: the tallest thing in town
    { x: 400, w: 74, tiers: taper(8, 74, 0.3, 0.6, 3), antenna: 0, spire: 0.035, tank: false, glass: true },
    // slender glass tower with a raked roof, right cluster
    { x: 1235, w: 50, tiers: [{ inset: 0, top: 0.53 }], antenna: 0, spire: 0, tank: false, glass: true, roof: "slant", slantLeft: false },
  ],
  [
    // slim glass mast tower
    { x: 250, w: 44, tiers: [{ inset: 0, top: 0.45 }, { inset: 7, top: 0.48 }], antenna: 0.08, spire: 0, tank: false, glass: true },
    // art deco setback tower with a spire and a crown of lights
    {
      x: 575,
      w: 86,
      tiers: [
        { inset: 0, top: 0.34 },
        { inset: 10, top: 0.4 },
        { inset: 19, top: 0.45 },
        { inset: 27, top: 0.49 },
        { inset: 33, top: 0.51 },
      ],
      antenna: 0,
      spire: 0.075,
      tank: false,
      crown: true,
    },
    // rounded-top glass tower
    { x: 700, w: 62, tiers: [{ inset: 0, top: 0.5 }], antenna: 0, spire: 0, tank: false, glass: true, roof: "dome" },
    // stepped crown tower, right cluster
    {
      x: 1160,
      w: 70,
      tiers: [
        { inset: 0, top: 0.4 },
        { inset: 8, top: 0.44 },
        { inset: 16, top: 0.47 },
      ],
      antenna: 0.06,
      spire: 0,
      tank: false,
      crown: true,
    },
  ],
  [
    // wide office block
    { x: 480, w: 150, tiers: [{ inset: 0, top: 0.2 }, { inset: 22, top: 0.23 }], antenna: 0, spire: 0, tank: false, hvac: true },
    // angled-roof tower
    { x: 990, w: 60, tiers: [{ inset: 0, top: 0.3 }], antenna: 0, spire: 0, tank: false, glass: true, roof: "slant", slantLeft: true },
  ],
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
        x += m.w + lerp(s.gap, rand());
        continue;
      }
      let w = lerp(s.w, rand());
      const e = skyline(x + w / 2);
      let t = clamp01((1 - s.env) * rand() ** 1.3 + s.env * (0.05 + 0.85 * e * (0.6 + 0.4 * rand()) + 0.25 * rand()));
      if (rand() < 0.1) t *= 0.45; // occasional low building breaks up the wall
      let top = lerp(s.h, t);
      const b: Building = { x, w, tiers: [], antenna: 0, spire: 0, tank: false };
      const r = rand();

      if (depth === 2 && r < 0.38) {
        // wide mid-rise office block
        w = b.w = 96 + rand() * 70;
        top = 0.1 + rand() * 0.11;
        b.tiers = [{ inset: 0, top }];
        if (rand() < 0.4) b.tiers.push({ inset: w * 0.12, top: top + 0.025 });
        b.hvac = true;
        b.tank = rand() < 0.35;
      } else if (r < (depth === 2 ? 0.55 : 0.42)) {
        b.glass = true;
        w = b.w = w * 0.85;
        b.tiers = [{ inset: 0, top }];
        if (rand() < 0.3) {
          b.tiers[0].top = top * 0.9;
          b.tiers.push({ inset: w * 0.14, top });
        }
        const q = rand();
        if (q < 0.12) {
          b.roof = "slant";
          b.slantLeft = rand() < 0.5;
        } else if (q < 0.2) b.roof = "dome";
        else if (t > 0.5 && q < 0.45) b.antenna = 0.02 + rand() * 0.04;
      } else if (t > 0.5 && w > 44 && r < 0.62) {
        // art deco setbacks
        const n = 2 + Math.floor(rand() * 2);
        const base = top * (0.7 + rand() * 0.1);
        b.tiers = [{ inset: 0, top: base }];
        for (let k = 1; k <= n; k++) b.tiers.push({ inset: w * 0.12 * k, top: base + ((top - base) * k) / n });
        if (rand() < 0.5) b.spire = 0.03 + rand() * 0.03;
        else b.antenna = 0.02 + rand() * 0.03;
        b.crown = rand() < 0.35;
      } else {
        b.tiers = [{ inset: 0, top }];
        const q = rand();
        if (q < 0.08) {
          b.roof = "slant";
          b.slantLeft = rand() < 0.5;
        } else if (q < 0.25) b.antenna = 0.012 + rand() * 0.03;
        else if (depth > 0 && q < 0.5) b.tank = true;
        else b.hvac = true;
      }
      const peak = b.tiers[b.tiers.length - 1].top;
      b.antenna = Math.min(b.antenna, MAX_H - peak);
      b.spire = Math.min(b.spire, MAX_H - peak);
      out.push(b);
      x += w + lerp(s.gap, rand());
    }
    return out;
  });
}

const NIGHT = ["#1b2136", "#111626", "#07090f"].map(hex);
const DAY = ["#8d9db5", "#5a6780", "#2d3546"].map(hex);
const HAZE_MIX = [0.45, 0.18, 0.04];
const WIN = [
  { w: 3, h: 3, gx: 3, gy: 4, pad: 4, lobby: 4 },
  { w: 3, h: 4, gx: 4, gy: 5, pad: 5, lobby: 7 },
  { w: 4, h: 6, gx: 5, gy: 6, pad: 6, lobby: 10 },
];
const WARM = ["#ffd99a", "#ffcc80", "#f9e4b8", "#ffc070", "#ffe0a8"].map(hex);
const TV = hex("#bcd4ff");
const RED = hex("#ff4a3d");
const CROWN = hex("#fff1c8");
const BLACK: RGB = [0, 0, 0];
const WHITE: RGB = [255, 255, 255];

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
  const day = 1 - d;
  const { H, groundY, sx, ox } = v;
  const facade = mix(mix(NIGHT[depth], DAY[depth], day), pal.haze, HAZE_MIX[depth]);
  const glassBase = mix(facade, mix(pal.mid, pal.top, 0.3), 0.3 * day);
  // Sun side (left) picks up the horizon colour by day; right side stays in shade.
  const tone = (c: RGB, sun: number) => ({
    face: css(c),
    sun: css(mix(c, pal.low, sun * day + 0.03)),
    edge: css(mix(c, mix(pal.low, WHITE, 0.4), 0.55 * day + 0.06)),
    shadow: css(mix(c, BLACK, 0.12 + 0.12 * d)),
    unlit: css(mix(mix(c, BLACK, 0.3), mix(c, pal.mid, 0.4), day)),
    line: css(mix(c, BLACK, 0.22)),
  });
  const box = tone(facade, 0.32);
  const glass = tone(glassBase, 0.42);
  const warmCss = WARM.map((c) => css(c, depth === 0 ? 0.7 : 0.95));
  const tvCss = css(TV, 0.85);
  const roofCss = css(mix(facade, pal.low, 0.35), 0.6 * day + 0.1);
  const crownCss = css(CROWN, smooth(0.3, 0.8, d));
  const share = litShare(d);
  const cell = WIN[depth];
  const pitchX = cell.w + cell.gx;
  const pitchY = cell.h + cell.gy;
  const k = [0.6, 0.8, 1][depth]; // rooftop detail scale
  const keys: number[] = [];

  ctx.clearRect(0, 0, v.width, groundY);
  ctx.fillStyle = box.face;
  if (depth === 0) ctx.fillRect(0, groundY - H * 0.08, v.width, H * 0.08);

  buildings.forEach((b, bi) => {
    const px = ox + b.x * sx;
    const pw = b.w * sx;
    if (px > v.width || px + pw < 0) return;
    const m = b.glass ? glass : box;
    const last = b.tiers.length - 1;
    let topX = px;
    let topY = groundY;
    let topW = pw;

    b.tiers.forEach((t, ti) => {
      const x0 = Math.round(px + (t.inset + (t.shift ?? 0)) * sx);
      const tw = Math.round(pw - 2 * t.inset * sx);
      if (tw < 3) return;
      const peak = Math.round(groundY - t.top * H);
      const roofH =
        ti === last && b.roof ? Math.round(Math.min(tw * (b.roof === "dome" ? 0.5 : 0.55), H * 0.06)) : 0;
      const y = peak + roofH;
      // Upper tiers only paint above the tier below, so its windows stay visible.
      const bot = ti === 0 ? groundY : Math.round(groundY - b.tiers[ti - 1].top * H);
      const h = bot - y;

      ctx.fillStyle = m.face;
      ctx.fillRect(x0, y, tw, h);
      if (roofH) {
        ctx.beginPath();
        if (b.roof === "dome") ctx.ellipse(x0 + tw / 2, y + 0.5, tw / 2, roofH, 0, Math.PI, 2 * Math.PI);
        else {
          ctx.moveTo(x0, y + 1);
          ctx.lineTo(b.slantLeft ? x0 : x0 + tw, peak);
          ctx.lineTo(x0 + tw, y + 1);
        }
        ctx.closePath();
        ctx.fill();
      }
      ctx.fillStyle = m.sun;
      ctx.fillRect(x0, y, Math.round(tw * 0.28), h);
      ctx.fillStyle = m.shadow;
      const shW = Math.round(tw * 0.18);
      ctx.fillRect(x0 + tw - shW, y, shW, h);

      const bottom = (ti === 0 ? groundY - cell.lobby : bot) - cell.pad * 0.5;
      const cols = Math.floor((tw - 2 * cell.pad + cell.gx) / pitchX);
      const rows = Math.floor((bottom - y - cell.pad + cell.gy) / pitchY);
      if (cols >= 1 && rows >= 1) {
        const wx0 = Math.round(x0 + (tw - (cols * pitchX - cell.gx)) / 2);
        for (let r = 0; r < rows; r++) {
          const wy = y + cell.pad + r * pitchY;
          for (let c = 0; c < cols; c++) {
            const key = depth * 1e8 + bi * 1e6 + ti * 1e5 + r * 300 + c;
            const lit = hash(key, 7) < share !== toggled.has(key);
            if (lit) {
              ctx.fillStyle = hash(key, 3) < 0.06 ? tvCss : warmCss[Math.floor(hash(key, 5) * warmCss.length)];
            } else if (depth > 0) {
              ctx.fillStyle = m.unlit;
            } else continue;
            // Glass towers: continuous floor bands split only by mullions.
            if (b.glass) ctx.fillRect(wx0 + c * pitchX, wy, pitchX - 1, cell.h);
            else ctx.fillRect(wx0 + c * pitchX, wy, cell.w, cell.h);
            if (depth > 0) keys.push(key);
          }
        }
        if (b.glass && depth > 0) {
          ctx.fillStyle = m.line;
          for (let c = 0; c <= cols; c++) ctx.fillRect(wx0 + c * pitchX - 1, y + 2, 1, bottom - y - 2);
        }
      }

      if (b.glass) {
        ctx.fillStyle = m.edge;
        ctx.fillRect(x0, y, Math.max(1, Math.round(tw * 0.05)), h);
      }
      if (d < 0.95 && !roofH) {
        ctx.fillStyle = roofCss;
        ctx.fillRect(x0, y, tw, 1);
      }
      if (b.crown && d > 0.3) {
        ctx.fillStyle = crownCss;
        for (let lx = x0 + 2; lx < x0 + tw - 1; lx += 4) ctx.fillRect(lx, y, 1.5, 1.5);
        if (ti === last) {
          const len = Math.min(h, 30);
          for (let ly = y + 4; ly < y + len; ly += 4) {
            ctx.fillRect(x0 + 1, ly, 1.5, 1.5);
            ctx.fillRect(x0 + tw - 2.5, ly, 1.5, 1.5);
          }
        }
      }
      topX = x0;
      topY = peak;
      topW = tw;
    });

    const cx = b.roof === "slant" ? (b.slantLeft ? topX + 2 : topX + topW - 2) : topX + topW / 2;
    ctx.fillStyle = box.face;
    ctx.strokeStyle = box.face;
    if (b.spire) {
      const half = Math.max(2, topW * 0.1);
      ctx.beginPath();
      ctx.moveTo(cx - half, topY);
      ctx.lineTo(cx, topY - b.spire * H);
      ctx.lineTo(cx + half, topY);
      ctx.fill();
    }
    if (b.antenna) {
      const tip = topY - b.antenna * H;
      ctx.lineWidth = depth === 0 ? 1 : 1.5;
      ctx.beginPath();
      ctx.moveTo(cx, topY);
      ctx.lineTo(cx, tip);
      ctx.stroke();
      if (d > 0.4) {
        ctx.fillStyle = css(RED, d);
        ctx.fillRect(cx - 1, tip - 1, 2, 2);
      }
    }
    if (b.roof) return;
    ctx.fillStyle = m.line;
    if (b.tank) {
      const tw = Math.min(14 * k, topW * 0.22);
      const tx = topX + topW * 0.2;
      ctx.fillRect(tx, topY - 12 * k, tw, 8 * k);
      ctx.fillRect(tx + 1, topY - 4 * k, 1, 4 * k);
      ctx.fillRect(tx + tw - 2, topY - 4 * k, 1, 4 * k);
    }
    if (b.hvac) {
      const seed = hash(depth, bi);
      ctx.fillRect(Math.round(topX + topW * (0.12 + seed * 0.2)), topY - Math.round(5 * k), Math.round(topW * 0.2), Math.round(5 * k));
      ctx.fillRect(Math.round(topX + topW * 0.6), topY - Math.round(3 * k), Math.round(topW * 0.22), Math.round(3 * k));
    }
  });

  // Atmospheric perspective: far layers sink into the haze toward the ground.
  const hazeAmt = [0.45, 0.18, 0][depth];
  if (hazeAmt) {
    const g = ctx.createLinearGradient(0, groundY - H * MAX_H, 0, groundY);
    g.addColorStop(0, css(pal.haze, 0));
    g.addColorStop(1, css(pal.haze, hazeAmt));
    ctx.globalCompositeOperation = "source-atop";
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, v.width, groundY);
    ctx.globalCompositeOperation = "source-over";
  }
  return keys;
}
