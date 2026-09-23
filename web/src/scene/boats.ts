// Moving life on and by the river: boats with wakes and reflections, people on the bridge.
import { WATER_BOTTOM, WATER_TOP } from "./layout";
import { css, hex, mix, type Palette, type RGB } from "./sky";
import type { Span } from "./waterfront";

const between = (a: number, b: number): number => a + Math.random() * (b - a);
const WARM = hex("#ffd58a");
const WHITE: RGB = [255, 255, 255];

export interface Boat {
  t0: number;
  x0: number;
  dir: number;
  y: number; // waterline, screen px
  s: number; // scale
  speed: number;
  tour: boolean;
}

export function makeBoat(t: number, W: number, H: number, darkness: number): Boat {
  const tour = darkness > 0.55 || Math.random() < 0.4;
  const f = between(0.3, 0.85); // across the river: nearer is lower and larger
  const s = (0.85 + f * 0.75) * Math.min(1.3, Math.max(0.8, H / 900));
  const dir = Math.random() < 0.5 ? 1 : -1;
  return {
    t0: t,
    x0: dir > 0 ? -90 * s : W + 90 * s,
    dir,
    y: H * (WATER_TOP + (WATER_BOTTOM - WATER_TOP) * f),
    s,
    speed: (tour ? 22 : 12) * s * between(0.85, 1.15),
    tour,
  };
}

function hull(g: CanvasRenderingContext2D, L: number, h: number, bow: number): void {
  g.beginPath();
  g.moveTo(-L / 2, -h);
  g.lineTo(L / 2 + bow, -h);
  g.quadraticCurveTo(L / 2 - bow * 0.2, -h * 0.2, L / 2 - bow * 1.5, 0);
  g.lineTo(-L / 2 + h * 0.4, 0);
  g.closePath();
  g.fill();
}

/** Boat in local coords: waterline at y=0, bow toward +x. */
function drawShape(g: CanvasRenderingContext2D, b: Boat, t: number, pal: Palette): void {
  const s = b.s;
  const d = pal.darkness;
  const lit = d > 0.35;
  if (b.tour) {
    const L = 66 * s;
    const h = 6 * s;
    g.fillStyle = css(mix(hex("#2d4868"), hex("#10141f"), d));
    hull(g, L, h, 5 * s);
    g.fillStyle = css(mix(WHITE, hex("#39404f"), d), 0.9);
    g.fillRect(-L / 2 + 1, -h + 1.4 * s, L - 2, 1.1 * s);
    const cx0 = -L / 2 + 8 * s;
    const cw = L - 22 * s;
    g.fillStyle = css(mix(hex("#ece6d8"), hex("#2a303d"), d));
    g.fillRect(cx0, -h - 9 * s, cw, 9 * s);
    g.fillStyle = css(mix(hex("#b8423a"), hex("#1a1c26"), d));
    g.fillRect(cx0 - 2 * s, -h - 10.6 * s, cw + 4 * s, 1.8 * s);
    const n = Math.floor(cw / (6 * s));
    g.fillStyle = lit ? css(WARM, 0.95) : css(hex("#7d95ab"));
    for (let i = 0; i < n; i++) g.fillRect(cx0 + 2 * s + i * 6 * s, -h - 7 * s, 3.6 * s, 4 * s);
    // flag at the stern
    g.fillStyle = css(mix(hex("#3b3f4a"), hex("#0e1016"), d));
    g.fillRect(-L / 2 + 2 * s, -h - 14 * s, 0.8 * s, 14 * s);
    g.fillStyle = css(mix(hex("#e0524a"), hex("#3a1c22"), d));
    g.beginPath();
    g.moveTo(-L / 2 + 2.8 * s, -h - 14 * s);
    g.lineTo(-L / 2 + 2.8 * s + 5 * s + Math.sin(t * 5) * 0.6 * s, -h - 12.5 * s);
    g.lineTo(-L / 2 + 2.8 * s, -h - 11 * s);
    g.fill();
    if (lit) {
      g.fillStyle = "rgb(140 255 170 / 0.95)";
      g.fillRect(L / 2 - 2 * s, -h - 1.5 * s, 1.6 * s, 1.6 * s);
    }
  } else {
    const L = 24 * s;
    const h = 3.5 * s;
    const ink = css(mix(hex("#2b3038"), hex("#0c0e14"), d));
    g.fillStyle = css(mix(hex("#9a6340"), hex("#1d1a1d"), d));
    hull(g, L, h, 2.5 * s);
    g.fillStyle = css(mix(hex("#e8dcc2"), hex("#2e2c33"), d), 0.8);
    g.fillRect(-L / 2 + 1, -h, L, 0.8 * s);
    // rower
    g.fillStyle = css(mix(hex("#e0674e"), hex("#221a20"), d));
    g.fillRect(-1.6 * s, -h - 6 * s, 3.2 * s, 6 * s);
    g.fillStyle = ink;
    g.beginPath();
    g.arc(0, -h - 7.6 * s, 1.7 * s, 0, 6.2832);
    g.fill();
    const ph = t * 2.6;
    g.strokeStyle = ink;
    g.lineWidth = Math.max(1, 0.7 * s);
    g.beginPath();
    g.moveTo(0.5 * s, -h - 3.5 * s);
    g.lineTo(-Math.cos(ph) * 9 * s, Math.sin(ph) * 1.8 * s + 0.5 * s);
    g.stroke();
  }
}

/** Draws boats (wake, reflection, hull) at parallax offset `px` and drops ones that left the screen. */
export function drawBoats(ctx: CanvasRenderingContext2D, boats: Boat[], t: number, W: number, dpr: number, px: number, pal: Palette): void {
  const foam = mix(pal.low, WHITE, 0.55);
  const foamA = 0.55 - pal.darkness * 0.3;
  for (let i = boats.length - 1; i >= 0; i--) {
    const b = boats[i];
    const x = b.x0 + b.dir * b.speed * (t - b.t0) + px;
    if ((b.dir > 0 && x > W + 140 * b.s) || (b.dir < 0 && x < -140 * b.s)) {
      boats.splice(i, 1);
      continue;
    }
    const L = (b.tour ? 66 : 24) * b.s;
    ctx.setTransform(dpr * b.dir, 0, 0, dpr, x * dpr, b.y * dpr);

    // wake: two lines fanning out behind the stern, plus a bow wave
    const len = L * (b.tour ? 1.6 : 1.1);
    const wg = ctx.createLinearGradient(-L / 2, 0, -L / 2 - len, 0);
    wg.addColorStop(0, css(foam, foamA));
    wg.addColorStop(1, css(foam, 0));
    ctx.strokeStyle = wg;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const side of [-1, 1]) {
      ctx.moveTo(-L / 2, 0.5);
      ctx.quadraticCurveTo(-L / 2 - len * 0.5, 0.5 + side * 0.6 * b.s, -L / 2 - len, 0.5 + side * 2.6 * b.s);
    }
    ctx.stroke();
    ctx.strokeStyle = css(foam, foamA * 0.8);
    ctx.beginPath();
    ctx.moveTo(L / 2 - 4 * b.s, 0.5);
    ctx.lineTo(L / 2 + 3 * b.s, 1.2 * b.s);
    ctx.stroke();

    // reflection, squashed like the river's
    ctx.setTransform(dpr * b.dir, 0, 0, -dpr * 0.6, x * dpr, (b.y + 1) * dpr);
    ctx.globalAlpha = 0.28;
    drawShape(ctx, b, t, pal);
    ctx.globalAlpha = 1;

    const bob = Math.sin(t * 1.8 + b.t0) * 0.4;
    ctx.setTransform(dpr * b.dir, 0, 0, dpr, x * dpr, (b.y + bob) * dpr);
    drawShape(ctx, b, t, pal);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

export interface Walker {
  t0: number;
  dir: number;
  speed: number;
  tone: number;
}

export const makeWalker = (t: number): Walker => ({
  t0: t,
  dir: Math.random() < 0.5 ? 1 : -1,
  speed: between(9, 14),
  tone: Math.random(),
});

/** Tiny pedestrians strolling along the promenade and over the bridge. */
export function drawWalkers(ctx: CanvasRenderingContext2D, walkers: Walker[], t: number, span: Span, px: number, pal: Palette): void {
  const reach = span.hw + 110;
  const ink = mix(hex("#2a303a"), hex("#05070b"), pal.darkness);
  const coats = ["#c0504a", "#3f6f9c", "#d4a24a", "#4f7d5a"].map(hex);
  ctx.lineCap = "round";
  for (let i = walkers.length - 1; i >= 0; i--) {
    const w = walkers[i];
    const dist = w.speed * (t - w.t0);
    if (dist > reach * 2) {
      walkers.splice(i, 1);
      continue;
    }
    const sx = span.cx - w.dir * reach + w.dir * dist;
    const y = span.deckY(sx) - 1;
    const x = sx + px;
    const step = Math.sin(dist * 0.9) * 1.6;
    ctx.strokeStyle = css(ink);
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    ctx.moveTo(x - step, y);
    ctx.lineTo(x, y - 3.2);
    ctx.lineTo(x + step, y);
    ctx.stroke();
    ctx.strokeStyle = css(mix(coats[Math.floor(w.tone * coats.length)], ink, 0.25 + pal.darkness * 0.7));
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(x, y - 3.4);
    ctx.lineTo(x, y - 6.6);
    ctx.stroke();
    ctx.fillStyle = css(ink);
    ctx.beginPath();
    ctx.arc(x, y - 8, 1.25, 0, 6.2832);
    ctx.fill();
  }
}
