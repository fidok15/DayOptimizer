// Everything at and below the far bank: promenade, footbridge, river and park.
// Bank and park are pre-rendered sprites (redrawn on resize / palette change);
// the river is composed every frame from the pixels already drawn above it.
import { mulberry32 } from "./city";
import { GROUND, WATER_BOTTOM, WATER_TOP } from "./layout";
import { css, hex, mix, smooth, type Palette, type RGB } from "./sky";

/** Horizontal headroom on each side of a sprite, larger than any parallax shift. */
export const SPRITE_MARGIN = 40;
/** Vertical squash of reflections, so the water shows more of the skyline. */
const SQUASH = 0.6;
const STRIPS = 56;

const WARM = hex("#ffcf85");
const WHITE: RGB = [255, 255, 255];
const BLACK: RGB = [0, 0, 0];
const TAU = Math.PI * 2;

export interface Sprite {
  canvas: HTMLCanvasElement;
  y0: number; // screen y of the sprite's top edge
  w: number;
  h: number;
}

export const newSprite = (): Sprite => ({ canvas: document.createElement("canvas"), y0: 0, w: 0, h: 0 });

/** Sizes the sprite to cover screen rows y0..y1 and returns a context that draws in screen coordinates. */
function prep(s: Sprite, W: number, y0: number, y1: number, dpr: number): CanvasRenderingContext2D {
  s.y0 = Math.floor(y0);
  s.w = W + SPRITE_MARGIN * 2;
  s.h = Math.ceil(y1) - s.y0;
  s.canvas.width = Math.ceil(s.w * dpr);
  s.canvas.height = Math.ceil(s.h * dpr);
  const g = s.canvas.getContext("2d")!;
  g.setTransform(dpr, 0, 0, dpr, SPRITE_MARGIN * dpr, -s.y0 * dpr);
  return g;
}

export function drawSprite(ctx: CanvasRenderingContext2D, s: Sprite, dx: number, dy = 0): void {
  if (s.w) ctx.drawImage(s.canvas, dx - SPRITE_MARGIN, s.y0 + dy, s.w, s.h);
}

// Colour helpers --------------------------------------------------------------

/** Day colour blended toward night by darkness, then tinted by the sky haze. */
const tone = (pal: Palette, day: string, night: string, haze = 0): RGB =>
  mix(mix(hex(day), hex(night), pal.darkness), pal.haze, haze * (1 - pal.darkness * 0.5));

const lampOn = (pal: Palette): number => smooth(0.28, 0.7, pal.darkness);

export function waterColour(pal: Palette): RGB {
  const base = mix(mix(pal.mid, pal.top, 0.35), hex("#16212e"), 0.3 + 0.35 * pal.darkness);
  const grey = (base[0] + base[1] + base[2]) / 3;
  return mix(base, [grey, grey, grey], 0.22);
}

interface Leaves {
  leaf: RGB;
  shade: RGB;
  light: RGB;
  lightA: number;
}

function foliage(pal: Palette, far: number, hue = 0): Leaves {
  const day = mix(hex("#5d8c47"), hex("#3f7a55"), hue);
  const leaf = mix(mix(day, hex("#122024"), pal.darkness), mix(pal.low, pal.haze, 0.5), 0.1 + far * 0.3 + 0.4 * Math.min(pal.darkness, 1 - pal.darkness));
  return {
    leaf,
    shade: mix(leaf, hex("#0a1216"), 0.38),
    light: mix(leaf, mix(hex("#e4f2b6"), pal.low, 0.35), 0.45),
    lightA: 0.6 * (1 - pal.darkness),
  };
}

// Drawing primitives ------------------------------------------------------------

function circle(g: CanvasRenderingContext2D, x: number, y: number, r: number): void {
  g.beginPath();
  g.arc(x, y, r, 0, TAU);
  g.fill();
}

function glow(g: CanvasRenderingContext2D, x: number, y: number, r: number, a: number): void {
  if (a <= 0.01) return;
  const gr = g.createRadialGradient(x, y, 0, x, y, r);
  gr.addColorStop(0, css(WARM, a));
  gr.addColorStop(0.35, css(WARM, a * 0.35));
  gr.addColorStop(1, css(WARM, 0));
  g.fillStyle = gr;
  g.fillRect(x - r, y - r, r * 2, r * 2);
}

/** Bumpy round crown from three overlapping circles, with shade and a sunlit cap. */
function roundTree(g: CanvasRenderingContext2D, x: number, base: number, r: number, trunk: RGB, c: Leaves): void {
  const cy = base - r * 1.55;
  g.fillStyle = css(trunk);
  g.fillRect(x - r * 0.09, cy, r * 0.18, base - cy);
  const blobs: [number, number, number][] = [
    [0, -0.12, 1],
    [-0.62, 0.22, 0.72],
    [0.6, 0.18, 0.76],
  ];
  g.fillStyle = css(c.shade);
  for (const [dx, dy, k] of blobs) circle(g, x + dx * r + r * 0.1, cy + dy * r + r * 0.12, r * k);
  g.fillStyle = css(c.leaf);
  for (const [dx, dy, k] of blobs) circle(g, x + dx * r, cy + dy * r, r * k * 0.9);
  if (c.lightA > 0.02) {
    g.fillStyle = css(c.light, c.lightA);
    circle(g, x - r * 0.3, cy - r * 0.45, r * 0.42);
    circle(g, x - r * 0.75, cy + r * 0.05, r * 0.22);
  }
}

function poplar(g: CanvasRenderingContext2D, x: number, base: number, w: number, h: number, trunk: RGB, c: Leaves): void {
  g.fillStyle = css(trunk);
  g.fillRect(x - w * 0.07, base - h * 0.2, w * 0.14, h * 0.2);
  g.fillStyle = css(c.shade);
  g.beginPath();
  g.ellipse(x + w * 0.08, base - h * 0.56, w * 0.5, h * 0.46, 0, 0, TAU);
  g.fill();
  g.fillStyle = css(c.leaf);
  g.beginPath();
  g.ellipse(x - w * 0.04, base - h * 0.58, w * 0.42, h * 0.44, 0, 0, TAU);
  g.fill();
  if (c.lightA > 0.02) {
    g.fillStyle = css(c.light, c.lightA * 0.8);
    g.beginPath();
    g.ellipse(x - w * 0.18, base - h * 0.7, w * 0.14, h * 0.2, 0, 0, TAU);
    g.fill();
  }
}

function conifer(g: CanvasRenderingContext2D, x: number, base: number, w: number, h: number, trunk: RGB, c: Leaves): void {
  g.fillStyle = css(trunk);
  g.fillRect(x - w * 0.06, base - h * 0.14, w * 0.12, h * 0.14);
  for (let k = 0; k < 3; k++) {
    const top = base - h * (0.52 + k * 0.24);
    const bot = base - h * (0.1 + k * 0.22);
    const hw = w * (0.5 - k * 0.1);
    g.fillStyle = css(c.leaf);
    g.beginPath();
    g.moveTo(x, top);
    g.lineTo(x + hw, bot);
    g.lineTo(x - hw, bot);
    g.fill();
    g.fillStyle = css(c.shade);
    g.beginPath();
    g.moveTo(x, top);
    g.lineTo(x + hw, bot);
    g.lineTo(x + hw * 0.2, bot);
    g.fill();
  }
}

function lamp(g: CanvasRenderingContext2D, x: number, base: number, h: number, post: RGB, on: number): void {
  g.strokeStyle = css(post);
  g.lineWidth = Math.max(1, h * 0.06);
  g.beginPath();
  g.moveTo(x, base);
  g.lineTo(x, base - h);
  g.stroke();
  const hw = Math.max(1.5, h * 0.09);
  g.fillStyle = css(post);
  g.fillRect(x - hw - 0.5, base - h - hw * 2.4, hw * 2 + 1, 1);
  g.fillStyle = css(mix(mix(post, hex("#9fb0c0"), 0.4), WARM, on));
  g.fillRect(x - hw, base - h - hw * 2.2, hw * 2, hw * 2.2);
  glow(g, x, base - h - hw, h * 1.3, 0.5 * on);
}

// Far bank + footbridge ------------------------------------------------------------

export interface Span {
  cx: number;
  hw: number;
  deckY: (x: number) => number;
}

/** Footbridge over a canal that joins the river, in front of the towers (screen coords). */
export function bridgeSpan(W: number, H: number): Span {
  const cx = W * 0.655;
  const hw = Math.min(190, Math.max(100, W * 0.1));
  const level = GROUND * H - 3;
  const hump = H * 0.04;
  return {
    cx,
    hw,
    deckY: (x) => {
      const u = Math.min(1, Math.abs(x - cx) / hw);
      return level - hump * (1 - u * u) ** 0.8;
    },
  };
}

export function renderBank(s: Sprite, W: number, H: number, dpr: number, pal: Palette): void {
  const G = GROUND * H;
  const T = WATER_TOP * H;
  const g = prep(s, W, G - H * 0.04 - 48, T + 1, dpr);
  const rand = mulberry32(0xba2c);
  const span = bridgeSpan(W, H);
  const on = lampOn(pal);
  const ink = tone(pal, "#3d4650", "#0b0e16", 0.2);

  // promenade surface and embankment wall
  const top = tone(pal, "#c9bfae", "#262a37", 0.3);
  const wall = tone(pal, "#9c907e", "#171a25", 0.3);
  g.fillStyle = css(top);
  g.fillRect(-SPRITE_MARGIN, G - 4, W + SPRITE_MARGIN * 2, 8);
  g.fillStyle = css(wall);
  g.fillRect(-SPRITE_MARGIN, G + 4, W + SPRITE_MARGIN * 2, T - G - 4 + 1);
  g.fillStyle = css(mix(wall, BLACK, 0.25), 0.8);
  g.fillRect(-SPRITE_MARGIN, G + 4, W + SPRITE_MARGIN * 2, 1.5);
  g.fillRect(-SPRITE_MARGIN, T - 3, W + SPRITE_MARGIN * 2, 3);
  g.fillStyle = css(mix(wall, BLACK, 0.2), 0.45);
  const mid = (G + 4 + T - 3) / 2;
  g.fillRect(-SPRITE_MARGIN, mid, W + SPRITE_MARGIN * 2, 1);
  for (let x = -SPRITE_MARGIN; x < W + SPRITE_MARGIN; x += 16) {
    g.fillRect(x, G + 5.5, 1, mid - G - 5.5);
    g.fillRect(x + 8, mid, 1, T - 3 - mid);
  }

  // trees and lamps along the promenade, leaving room for the bridge
  const leaves = [foliage(pal, 0.55, 0), foliage(pal, 0.55, 0.6)];
  const trunk = tone(pal, "#5b4a3d", "#0d0f15", 0.3);
  const clear = (x: number, pad: number) => Math.abs(x - span.cx) > span.hw + pad;
  let n = 0;
  for (let x = -SPRITE_MARGIN + rand() * 20; x < W + SPRITE_MARGIN; x += 34 + rand() * 30, n++) {
    if (!clear(x, 14)) continue;
    if (n % 3 === 2) lamp(g, x, G - 2, 15, ink, on);
    else roundTree(g, x, G - 1, 7 + rand() * 5, trunk, leaves[n % 2]);
  }

  // railing along the water
  g.strokeStyle = css(ink, 0.55);
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(-SPRITE_MARGIN, G - 1.5);
  g.lineTo(W + SPRITE_MARGIN, G - 1.5);
  g.stroke();

  renderBridge(g, span, G, T, pal, on, ink);
}

function renderBridge(g: CanvasRenderingContext2D, sp: Span, G: number, T: number, pal: Palette, on: number, ink: RGB): void {
  const { cx, hw, deckY } = sp;
  const water = waterColour(pal);

  // canal seen through the arches
  const cg = g.createLinearGradient(0, G - 4, 0, T);
  cg.addColorStop(0, css(mix(water, BLACK, 0.45)));
  cg.addColorStop(1, css(mix(water, BLACK, 0.25)));
  g.fillStyle = cg;
  g.fillRect(cx - hw, G - 4, hw * 2, T - G + 5);

  const stone = tone(pal, "#d2c2a6", "#2b2d3a", 0.22);
  const rim = mix(stone, WHITE, 0.25 * (1 - pal.darkness));
  const dark = mix(stone, BLACK, 0.3);

  // body with three arch openings (even-odd fill cuts them out)
  const p = new Path2D();
  p.moveTo(cx - hw - 4, T);
  for (let i = 0; i <= 40; i++) {
    const x = cx - hw + (hw * 2 * i) / 40;
    p.lineTo(x, deckY(x) + 1);
  }
  p.lineTo(cx + hw + 4, T);
  p.closePath();
  const units = [0.1, 0.23, 0.07, 0.3, 0.07, 0.23, 0.1];
  const total = units.reduce((a, b) => a + b, 0);
  const arches: { x: number; rx: number; spring: number; ry: number }[] = [];
  let at = cx - hw;
  units.forEach((u, i) => {
    const w = (u / total) * hw * 2;
    if (i % 2) {
      const ax = at + w / 2;
      const rx = w / 2;
      const crown = deckY(ax) + 8;
      const ry = Math.min(rx * 0.95, T - crown - 1);
      const spring = crown + ry;
      arches.push({ x: ax, rx, spring, ry });
      p.moveTo(at, T);
      p.lineTo(at, spring);
      p.ellipse(ax, spring, rx, ry, 0, Math.PI, TAU);
      p.lineTo(at + w, T);
      p.closePath();
    }
    at += w;
  });
  g.fillStyle = css(stone);
  g.fill(p, "evenodd");

  // arch rims and keystones
  g.lineWidth = 2;
  for (const a of arches) {
    g.strokeStyle = css(rim);
    g.beginPath();
    g.ellipse(a.x, a.spring, a.rx + 1, a.ry + 1, 0, Math.PI, TAU);
    g.stroke();
    g.fillStyle = css(dark);
    g.fillRect(a.x - 1.5, a.spring - a.ry - 3, 3, 3);
  }

  // deck fascia, railing and lamps
  g.strokeStyle = css(dark);
  g.lineWidth = 2;
  g.beginPath();
  for (let x = cx - hw - 4; x <= cx + hw + 4; x += 4) {
    const y = deckY(x) + 3;
    if (x === cx - hw - 4) g.moveTo(x, y);
    else g.lineTo(x, y);
  }
  g.stroke();
  g.strokeStyle = css(ink, 0.9);
  g.lineWidth = 1;
  g.beginPath();
  for (let x = cx - hw; x <= cx + hw; x += 7) {
    g.moveTo(x, deckY(x));
    g.lineTo(x, deckY(x) - 7);
  }
  for (let x = cx - hw; x <= cx + hw + 0.1; x += 2) {
    if (x === cx - hw) g.moveTo(x, deckY(x) - 7);
    else g.lineTo(x, deckY(x) - 7);
  }
  g.stroke();
  for (const f of [-0.85, 0, 0.85]) {
    const x = cx + hw * f;
    lamp(g, x, deckY(x), 20, ink, on);
  }
}

// Near-bank park --------------------------------------------------------------------

export function renderPark(s: Sprite, W: number, H: number, dpr: number, pal: Palette): void {
  const B = WATER_BOTTOM * H;
  const g = prep(s, W, B - H * 0.13, H + 16, dpr);
  const rand = mulberry32(0x9a2c);
  const d = pal.darkness;
  const on = lampOn(pal);
  const L = -SPRITE_MARGIN;
  const R = W + SPRITE_MARGIN;
  const depth = H - B;
  const edge = (x: number) => B + Math.sin(x * 0.011) * 2 + Math.sin(x * 0.037 + 1) * 1.2;
  const pathY = (x: number) => B + depth * 0.5 + Math.sin(x * 0.0042 + 0.8) * depth * 0.14;
  const pathW = Math.max(9, depth * 0.15);

  // lawn
  const warm = mix(pal.low, pal.haze, 0.5);
  const dusk = 0.1 + 0.5 * Math.min(d, 1 - d); // sunrise / sunset light tints the lawn
  const grassTop = mix(tone(pal, "#7aa35a", "#15232a"), warm, dusk);
  const grassBot = mix(tone(pal, "#4f7c3f", "#0b151a"), warm, dusk * 0.6);
  const lawn = new Path2D();
  lawn.moveTo(L, H + 16);
  for (let x = L; x <= R; x += 6) lawn.lineTo(x, edge(x));
  lawn.lineTo(R, H + 16);
  lawn.closePath();
  const lg = g.createLinearGradient(0, B, 0, H);
  lg.addColorStop(0, css(grassTop));
  lg.addColorStop(1, css(grassBot));
  g.fillStyle = lg;
  g.fill(lawn);
  // stone lip at the water line
  g.strokeStyle = css(tone(pal, "#b7ad98", "#20242f", 0.2));
  g.lineWidth = 2.5;
  g.beginPath();
  for (let x = L; x <= R; x += 6) (x === L ? g.moveTo(x, edge(x) + 1) : g.lineTo(x, edge(x) + 1));
  g.stroke();

  // path
  const sand = tone(pal, "#d8c49e", "#2a2d35", 0.15);
  g.lineCap = "round";
  for (const [w, c] of [
    [pathW + 3, mix(sand, BLACK, 0.2)],
    [pathW, sand],
  ] as [number, RGB][]) {
    g.strokeStyle = css(c);
    g.lineWidth = w;
    g.beginPath();
    for (let x = L; x <= R; x += 8) (x === L ? g.moveTo(x, pathY(x)) : g.lineTo(x, pathY(x)));
    g.stroke();
  }

  // flowers
  const petals = ["#f7a8c0", "#ffe07a", "#ffffff", "#c9a4f5", "#ff9d7a"].map(hex);
  for (let i = 0; i < Math.round(W / 14); i++) {
    const x = L + rand() * (R - L);
    const y = edge(x) + 6 + rand() * (depth - 8);
    if (Math.abs(y - pathY(x)) < pathW) continue;
    g.fillStyle = css(mix(petals[i % petals.length], grassBot, 0.2 + d * 0.7), 0.9);
    circle(g, x, y, 1 + rand() * 0.8);
  }

  // trees, bushes, benches and lamps, sorted back to front
  type Item = { y: number; draw: () => void };
  const items: Item[] = [];
  const k = Math.min(1.25, Math.max(0.8, H / 900));
  const trunk = tone(pal, "#5a4432", "#0c0e13");
  const post = tone(pal, "#2c3438", "#07090d");
  const wood = tone(pal, "#7a5236", "#16151a");
  const shades = [foliage(pal, 0, 0), foliage(pal, 0, 0.5), foliage(pal, 0, 1)];

  for (let x = L + rand() * 30; x < R; x += (50 + rand() * 80) * k) {
    const roll = rand();
    const back = rand() < 0.55;
    const y = back ? pathY(x) - pathW * 0.8 - rand() * depth * 0.18 : pathY(x) + pathW * 0.9 + rand() * depth * 0.3;
    const c = shades[Math.floor(rand() * 3)];
    const size = (back ? 0.85 : 1.15) * k * (0.8 + rand() * 0.45);
    if (roll < 0.5) items.push({ y, draw: () => roundTree(g, x, y, 22 * size, trunk, c) });
    else if (roll < 0.68) items.push({ y, draw: () => poplar(g, x, y, 20 * size, 78 * size, trunk, c) });
    else if (roll < 0.82) items.push({ y, draw: () => conifer(g, x, y, 30 * size, 70 * size, trunk, c) });
    else continue;
    // a bush or two at the foot of some trees
    if (rand() < 0.5) {
      const bx = x + (rand() - 0.5) * 50;
      const by = y + 4 + rand() * 6;
      const br = (7 + rand() * 6) * k;
      const bc = shades[Math.floor(rand() * 3)];
      items.push({
        y: by,
        draw: () => {
          g.fillStyle = css(bc.shade);
          circle(g, bx + br * 0.2, by - br * 0.5, br);
          circle(g, bx + br * 1.1, by - br * 0.35, br * 0.75);
          g.fillStyle = css(bc.leaf);
          circle(g, bx, by - br * 0.6, br * 0.85);
          circle(g, bx - br * 0.85, by - br * 0.35, br * 0.65);
          if (bc.lightA > 0.02) {
            g.fillStyle = css(bc.light, bc.lightA * 0.8);
            circle(g, bx - br * 0.25, by - br * 0.95, br * 0.3);
          }
        },
      });
    }
  }

  for (let x = L + 90 + rand() * 80; x < R; x += 220 + rand() * 120) {
    const y = pathY(x) - pathW * 0.55;
    const h = 36 * k;
    items.push({
      y,
      draw: () => {
        glow(g, x, y + 2, h * 1.1, 0.18 * on); // pool of light on the path
        lamp(g, x, y, h, post, on);
      },
    });
    const bx = x + 34 * k;
    const by = pathY(bx) - pathW * 0.6;
    items.push({
      y: by,
      draw: () => {
        const bw = 20 * k;
        g.fillStyle = css(post);
        g.fillRect(bx - bw / 2 + 2, by - 5 * k, 1.2, 5 * k);
        g.fillRect(bx + bw / 2 - 3, by - 5 * k, 1.2, 5 * k);
        g.fillStyle = css(wood);
        g.fillRect(bx - bw / 2, by - 5.5 * k, bw, 1.8 * k);
        g.fillRect(bx - bw / 2, by - 10 * k, bw, 1.6 * k);
        g.fillRect(bx - bw / 2 + 1, by - 10 * k, 1, 5 * k);
        g.fillRect(bx + bw / 2 - 2, by - 10 * k, 1, 5 * k);
      },
    });
  }

  // reeds along the water
  g.strokeStyle = css(mix(grassTop, BLACK, 0.2));
  g.lineWidth = 1;
  for (let x = L + rand() * 60; x < R; x += 90 + rand() * 160) {
    g.beginPath();
    for (let j = 0; j < 6; j++) {
      const rx = x + j * 2.2;
      const ry = edge(rx) + 3;
      g.moveTo(rx, ry);
      g.quadraticCurveTo(rx + 1, ry - 5, rx + (j - 2.5) * 1.2, ry - 8 - (j % 3) * 2);
    }
    g.stroke();
  }

  items.sort((a, b) => a.y - b.y).forEach((it) => it.draw());
}

// River ---------------------------------------------------------------------------------

export interface River {
  scratch: HTMLCanvasElement;
  streak: HTMLCanvasElement;
  ripples: { x: number; y: number; len: number; phase: number; speed: number }[];
}

export function newRiver(): River {
  const rand = mulberry32(0x71fe);
  return {
    scratch: document.createElement("canvas"),
    streak: document.createElement("canvas"),
    ripples: Array.from({ length: 34 }, () => ({
      x: rand(),
      y: rand() ** 0.8,
      len: 6 + rand() * 26,
      phase: rand() * TAU,
      speed: 0.5 + rand(),
    })),
  };
}

// Rows (as fractions of H above the ground) sampled for night light streaks.
const STREAK_ROWS = [0.012, 0.03, 0.05, 0.075, 0.1, 0.13, 0.17];

/**
 * Paints the river from WATER_TOP to WATER_BOTTOM. `src` is the main canvas, which must
 * already hold everything above the water (sky, towers, bank): its lower band is mirrored
 * into the water in shimmering horizontal strips, so reflections follow their parallax.
 */
export function drawRiver(
  ctx: CanvasRenderingContext2D,
  src: HTMLCanvasElement,
  r: River,
  W: number,
  H: number,
  dpr: number,
  pal: Palette,
  t: number,
  motion: boolean,
): void {
  const top = WATER_TOP * H;
  const wh = (WATER_BOTTOM - WATER_TOP) * H;
  const sh = Math.ceil(wh / SQUASH);
  const sw = Math.ceil(W);
  // The reflection is sampled at 1x: cheaper, and a little softness suits water.
  if (r.scratch.width !== sw || r.scratch.height !== sh) {
    r.scratch.width = r.streak.width = sw;
    r.scratch.height = r.streak.height = sh;
  }
  const g = r.scratch.getContext("2d")!;
  g.globalCompositeOperation = "copy";
  g.drawImage(src, 0, (top - sh) * dpr, W * dpr, sh * dpr, 0, 0, sw, sh);
  g.globalCompositeOperation = "source-over";

  // Night: stretch thin rows of the skyline downward so lit windows become streaks.
  const night = smooth(0.45, 0.85, pal.darkness);
  if (night > 0) {
    const s = r.streak.getContext("2d")!;
    s.clearRect(0, 0, sw, sh);
    s.globalCompositeOperation = "lighter";
    s.globalAlpha = 0.3;
    for (const o of STREAK_ROWS) {
      const y = (GROUND - o) * H - (top - sh);
      if (y >= 0) s.drawImage(r.scratch, 0, y, sw, 3, 0, 0, sw, sh);
    }
    s.globalAlpha = 1;
    s.globalCompositeOperation = "destination-in";
    const fade = s.createLinearGradient(0, 0, 0, sh);
    fade.addColorStop(0, "rgb(0 0 0 / 0.1)");
    fade.addColorStop(1, "rgb(0 0 0 / 1)");
    s.fillStyle = fade;
    s.fillRect(0, 0, sw, sh);
    s.globalCompositeOperation = "source-over";
    g.globalCompositeOperation = "lighter";
    g.globalAlpha = 0.9 * night;
    g.drawImage(r.streak, 0, 0);
    g.globalAlpha = 1;
    g.globalCompositeOperation = "source-over";
  }

  const water = waterColour(pal);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = css(water);
  ctx.fillRect(0, top, W, wh + 8);

  const hs = wh / STRIPS;
  ctx.globalAlpha = 0.72;
  for (let i = 0; i < STRIPS; i++) {
    const y = top + i * hs;
    const f = i / STRIPS;
    const amp = 0.6 + f * f * 7;
    const wave = motion
      ? Math.sin(t * 1.5 + i * 0.83) * 0.65 + Math.sin(t * 0.6 - i * 0.31 + 1.7) * 0.35
      : Math.sin(i * 0.83) * 0.5;
    const sy = sh - (y + hs - top) / SQUASH;
    // Flip each strip around its own centre, so it mirrors the source rows.
    ctx.setTransform(dpr, 0, 0, -dpr, 0, (2 * y + hs) * dpr);
    ctx.drawImage(r.scratch, 0, Math.max(0, sy), sw, hs / SQUASH, wave * amp - 8, y - 0.4, W + 16, hs + 0.8);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.globalAlpha = 1;

  // fade into the water colour with distance from the far bank, plus a shadow under the wall
  const deep = mix(water, BLACK, 0.12);
  const fg = ctx.createLinearGradient(0, top, 0, top + wh);
  fg.addColorStop(0, css(deep, 0.12));
  fg.addColorStop(1, css(deep, 0.62));
  ctx.fillStyle = fg;
  ctx.fillRect(0, top, W, wh + 8);
  const sg = ctx.createLinearGradient(0, top, 0, top + 7);
  sg.addColorStop(0, css(BLACK, 0.28));
  sg.addColorStop(1, css(BLACK, 0));
  ctx.fillStyle = sg;
  ctx.fillRect(0, top, W, 7);

  // ripple glints
  const glint = mix(pal.low, WHITE, 0.45);
  ctx.lineWidth = 1;
  for (const rp of r.ripples) {
    const pulse = motion ? 0.5 + 0.5 * Math.sin(t * rp.speed + rp.phase) : 0.7;
    const a = (0.1 + 0.16 * rp.y) * pulse * (1 - pal.darkness * 0.55);
    if (a < 0.01) continue;
    const drift = motion ? t * 4 * rp.speed : 0;
    const x = ((rp.x * (W + 60) + drift) % (W + 60)) - 30;
    const y = Math.round(top + 4 + rp.y * (wh - 6)) + 0.5;
    const len = rp.len * (0.5 + rp.y);
    ctx.strokeStyle = css(glint, a);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + len, y);
    ctx.stroke();
  }
}
