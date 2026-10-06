import { mulberry32 } from "./city";
import { css, hex, mix, type Palette, type RGB } from "./sky";

interface Seg { x0: number; y0: number; cx: number; cy: number; x1: number; y1: number; w: number }
interface Flower { x: number; y: number; r: number; tone: number }
interface Branch { segs: Seg[]; flowers: Flower[] }
export interface Petal { x: number; y: number; r: number; fall: number; sway: number; phase: number; spin: number }

export const BLOSSOM_MARGIN = 40;

function grow(seed: number, x: number, y: number, angle: number): Branch {
  const rand = mulberry32(seed);
  const out: Branch = { segs: [], flowers: [] };
  const cluster = (cx: number, cy: number, n: number, spread: number) => {
    for (let i = 0; i < n; i++) {
      const a = rand() * 6.2832;
      const d = rand() * spread;
      out.flowers.push({ x: cx + Math.cos(a) * d, y: cy + Math.sin(a) * d, r: 0.005 + rand() * 0.006, tone: rand() });
    }
  };
  const branch = (x: number, y: number, a: number, len: number, w: number, depth: number) => {
    const x1 = x + Math.cos(a) * len;
    const y1 = y + Math.sin(a) * len;
    const bend = (rand() - 0.5) * len * 0.35;
    const cx = (x + x1) / 2 - Math.sin(a) * bend;
    const cy = (y + y1) / 2 + Math.cos(a) * bend;
    out.segs.push({ x0: x, y0: y, cx, cy, x1, y1, w });
    if (depth === 0) return cluster(x1, y1, 6 + Math.floor(rand() * 5), 0.03);
    if (depth <= 2) cluster(cx, cy, 2 + Math.floor(rand() * 3), 0.02);
    const kids = depth > 3 ? 2 : 2 + Math.floor(rand() * 2);
    for (let k = 0; k < kids; k++) {
      const da = (k - (kids - 1) / 2) * (0.45 + rand() * 0.35) + 0.08;
      branch(x1, y1, a + da, len * (0.62 + rand() * 0.16), w * 0.62, depth - 1);
    }
  };
  branch(x, y, angle, 0.26, 0.03, 5);
  return out;
}

const LEFT = grow(0xb105, -0.06, 0.02, 0.2);
const RIGHT = grow(0x5a4a, -0.06, -0.02, 0.3);

export function renderBlossoms(c: HTMLCanvasElement, W: number, H: number, dpr: number, pal: Palette): void {
  const w = W + BLOSSOM_MARGIN * 2;
  c.width = Math.ceil(w * dpr);
  c.height = Math.ceil(H * dpr);
  const g = c.getContext("2d")!;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const d = pal.darkness;
  const bark = css(mix(hex("#4a3434"), hex("#0b0d18"), d));
  const moon = mix(pal.top, hex("#cdd6f4"), 0.4);
  const pinks: RGB[] = ["#f7c6d4", "#ec9db8", "#fde4ea"].map((p) => mix(hex(p), moon, d * 0.55));
  const S = Math.min(W * 0.3, H * 0.45, 380);

  const side = (b: Branch, flip: boolean) => {
    const X = (u: number) => (flip ? w - BLOSSOM_MARGIN - u * S : BLOSSOM_MARGIN + u * S);
    const Y = (v: number) => v * S;
    g.strokeStyle = bark;
    g.lineCap = "round";
    for (const s of b.segs) {
      g.lineWidth = Math.max(1, s.w * S);
      g.beginPath();
      g.moveTo(X(s.x0), Y(s.y0));
      g.quadraticCurveTo(X(s.cx), Y(s.cy), X(s.x1), Y(s.y1));
      g.stroke();
    }
    for (const f of b.flowers) {
      const r = f.r * S;
      const p = pinks[Math.floor(f.tone * pinks.length)];
      const x = X(f.x);
      const y = Y(f.y);
      g.fillStyle = css(p, 0.85);
      g.beginPath();
      for (let k = 0; k < 5; k++) {
        const a = f.tone * 6.28 + k * 1.2566;
        g.moveTo(x + Math.cos(a) * r * 0.55 + r * 0.5, y + Math.sin(a) * r * 0.55);
        g.arc(x + Math.cos(a) * r * 0.55, y + Math.sin(a) * r * 0.55, r * 0.5, 0, 6.2832);
      }
      g.fill();
      g.fillStyle = css(mix(p, hex("#b0476e"), 0.6), 0.9);
      g.beginPath();
      g.arc(x, y, r * 0.18, 0, 6.2832);
      g.fill();
    }
  };
  side(LEFT, false);
  side(RIGHT, true);
}

export function makePetals(n: number): Petal[] {
  return Array.from({ length: n }, () => ({
    x: Math.random(),
    y: Math.random(),
    r: 2 + Math.random() * 2.5,
    fall: 14 + Math.random() * 18,
    sway: 10 + Math.random() * 25,
    phase: Math.random() * 6.28,
    spin: 0.6 + Math.random() * 1.4,
  }));
}

export function drawPetals(ctx: CanvasRenderingContext2D, petals: Petal[], t: number, W: number, H: number, pal: Palette): void {
  ctx.fillStyle = css(mix(hex("#f4bccd"), pal.top, pal.darkness * 0.5), 0.85);
  for (const p of petals) {
    const y = ((p.y * H + t * p.fall) % (H + 20)) - 10;
    const base = p.x < 0.5 ? p.x * 0.6 : 1 - (1 - p.x) * 0.6;
    const x = base * W + Math.sin(t * 0.8 + p.phase) * p.sway;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(t * p.spin + p.phase);
    ctx.beginPath();
    ctx.ellipse(0, 0, p.r, p.r * 0.55, 0, 0, 6.2832);
    ctx.fill();
    ctx.restore();
  }
}

export function grainPattern(ctx: CanvasRenderingContext2D): CanvasPattern | null {
  const size = 160;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const img = g.createImageData(size, size);
  const rand = mulberry32(0x6a1a);
  for (let i = 0; i < img.data.length; i += 4) {
    img.data[i] = img.data[i + 1] = img.data[i + 2] = 110 + rand() * 145;
    img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return ctx.createPattern(c, "repeat");
}
