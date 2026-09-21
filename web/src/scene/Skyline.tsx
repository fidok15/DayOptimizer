import { useEffect, useRef } from "react";
import { sceneHour } from "../lib/time";
import { CITY_W, generateCity, litShare, mulberry32, renderLayer } from "./city";
import { css, hex, mix, palette, smooth, type Palette, type RGB } from "./sky";

export default function Skyline() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    return startScene(canvas, ctx);
  }, []);
  return <canvas ref={ref} aria-hidden className="pointer-events-none fixed inset-0 -z-10 h-full w-full" />;
}

const MARGIN_X = 24; // extra layer width so parallax never shows an edge
const MARGIN_Y = 8;
const PARALLAX_X = [5, 10, 18];
const PARALLAX_Y = [1.5, 3, 6];
const WHITE: RGB = [255, 255, 255];

interface Star { x: number; y: number; r: number; phase: number; speed: number }
interface Cloud { x: number; y: number; s: number; speed: number; puffs: { dx: number; dy: number; r: number }[] }
interface Bird { dx: number; dy: number; phase: number }
interface Flock { t0: number; x0: number; dir: number; y: number; speed: number; size: number; flap: number; birds: Bird[] }
interface Plane { t0: number; x0: number; dir: number; y: number; speed: number }
interface Shoot { t0: number; x: number; y: number; vx: number; vy: number }

const between = (a: number, b: number): number => a + Math.random() * (b - a);

function startScene(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D): () => void {
  const motion = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const city = generateCity();
  const seeded = mulberry32(0xa11ce);
  const stars: Star[] = Array.from({ length: 180 }, () => ({
    x: seeded(),
    y: seeded() ** 1.5 * 0.62,
    r: 0.4 + seeded() * 1.1,
    phase: seeded() * 6.28,
    speed: 0.6 + seeded() * 1.8,
  }));
  const clouds: Cloud[] = Array.from({ length: 7 }, () => ({
    x: seeded(),
    y: 0.06 + seeded() * 0.32,
    s: 0.6 + seeded() * 0.8,
    speed: 3 + seeded() * 6,
    puffs: Array.from({ length: 5 + Math.floor(seeded() * 4) }, (_, i) => ({
      dx: -0.38 + i * 0.13 + seeded() * 0.06,
      dy: (seeded() - 0.5) * 0.25,
      r: 0.14 + seeded() * 0.12,
    })),
  }));

  const layers = city.map(() => document.createElement("canvas"));
  const layerCtx = layers.map((c) => c.getContext("2d")!);
  const cloudSprites = clouds.map(() => document.createElement("canvas"));
  const winKeys: number[][] = [[], [], []];
  const toggled = new Set<number>();

  let W = 0;
  let H = 0;
  let dpr = 1;
  let hour = sceneHour();
  let pal: Palette = palette(hour);
  let renderedHour = -1;
  let renderedDark = -1;

  const pointer = { tx: 0, ty: 0, x: 0, y: 0 };
  const flocks: Flock[] = [];
  const planes: Plane[] = [];
  let shoot: Shoot | null = null;
  const t0 = performance.now() / 1000;
  const next = { palette: t0 + 30, toggle: t0 + between(2, 4), flock: t0 + between(2, 6), plane: t0 + between(4, 12), shoot: t0 + between(6, 16) };

  function renderLayers(which: number[] = [0, 1, 2]) {
    const lw = W + MARGIN_X * 2;
    const lh = H + MARGIN_Y * 2;
    const sx = Math.max(lw, 900) / CITY_W;
    const ox = (lw - CITY_W * sx) / 2;
    for (const i of which) {
      const c = layerCtx[i];
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      winKeys[i] = renderLayer(c, city[i], i, { width: lw, H, groundY: lh, sx, ox }, pal, toggled);
    }
  }

  function renderClouds() {
    const light = mix(mix(WHITE, pal.low, 0.3), mix(pal.mid, WHITE, 0.25), pal.darkness * 0.8);
    clouds.forEach((cl, i) => {
      const w = 280 * cl.s;
      const h = 120 * cl.s;
      const pad = w * 0.3; // room for puff falloff so the sprite edge never clips
      const c = cloudSprites[i];
      c.width = Math.ceil((w + pad * 2) * dpr);
      c.height = Math.ceil((h + pad * 2) * dpr);
      const g = c.getContext("2d")!;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (const p of cl.puffs) {
        const px = pad + w / 2 + p.dx * w;
        const py = pad + h * 0.55 + p.dy * h;
        const r = p.r * w;
        const grad = g.createRadialGradient(px, py, 0, px, py, r);
        grad.addColorStop(0, css(light, 0.5));
        grad.addColorStop(0.6, css(light, 0.22));
        grad.addColorStop(1, css(light, 0));
        g.fillStyle = grad;
        g.fillRect(0, 0, w + pad * 2, h + pad * 2);
      }
    });
  }

  function refreshPalette(force = false) {
    hour = sceneHour();
    pal = palette(hour);
    if (force || Math.abs(hour - renderedHour) > 0.08 || Math.abs(pal.darkness - renderedDark) > 0.02) {
      renderedHour = hour;
      renderedDark = pal.darkness;
      renderLayers();
      renderClouds();
    }
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    for (const c of layers) {
      c.width = Math.round((W + MARGIN_X * 2) * dpr);
      c.height = Math.round((H + MARGIN_Y * 2) * dpr);
    }
    refreshPalette(true);
  }

  function tick(t: number) {
    const d = pal.darkness;
    if (t >= next.palette) {
      next.palette = t + 30;
      refreshPalette();
    }
    if (t >= next.toggle) {
      next.toggle = t + between(2.5, 5);
      if (litShare(pal.darkness) > 0.05) {
        const layer = Math.random() < 0.6 ? 2 : 1;
        const keys = winKeys[layer];
        for (let n = 2 + Math.floor(Math.random() * 3); n > 0 && keys.length; n--) {
          const k = keys[Math.floor(Math.random() * keys.length)];
          if (!toggled.delete(k)) toggled.add(k);
        }
        renderLayers([layer]);
      }
    }
    if (t >= next.flock) {
      next.flock = t + between(12, 25);
      if (d < 0.35) flocks.push(makeFlock(t));
    }
    if (t >= next.plane) {
      next.plane = t + between(26, 36);
      if (d > 0.6) {
        const dir = Math.random() < 0.5 ? 1 : -1;
        planes.push({ t0: t, dir, x0: dir > 0 ? -20 : W + 20, y: H * between(0.08, 0.28), speed: between(16, 24) });
      }
    }
    if (t >= next.shoot) {
      next.shoot = t + between(20, 40);
      if (d > 0.6) {
        const dir = Math.random() < 0.5 ? 1 : -1;
        shoot = { t0: t, x: W * between(0.15, 0.85), y: H * between(0.05, 0.3), vx: dir * between(380, 520), vy: between(140, 220) };
      }
    }
  }

  function makeFlock(t: number): Flock {
    const dir = Math.random() < 0.5 ? 1 : -1;
    const z = between(0.55, 1.25); // depth: nearer flocks are bigger and faster
    const n = 5 + Math.floor(Math.random() * 5);
    const birds: Bird[] = Array.from({ length: n }, (_, i) => {
      const k = Math.ceil(i / 2);
      const side = i % 2 ? 1 : -1;
      return { dx: -dir * k * 15 * z + between(-3, 3), dy: side * k * 7 * z + between(-3, 3), phase: Math.random() * 6.28 };
    });
    return { t0: t, dir, x0: dir > 0 ? -80 : W + 80, y: H * between(0.12, 0.42), speed: 28 + 36 * z, size: 5.5 * z, flap: between(7, 9.5), birds };
  }

  function drawSky(t: number) {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, css(pal.top));
    g.addColorStop(0.5, css(pal.mid));
    g.addColorStop(0.82, css(pal.low));
    g.addColorStop(1, css(pal.low));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    const starAlpha = smooth(0.4, 0.9, pal.darkness);
    if (starAlpha > 0) {
      ctx.fillStyle = "#fff";
      for (const s of stars) {
        const tw = motion ? 0.65 + 0.35 * Math.sin(t * s.speed + s.phase) : 0.85;
        ctx.globalAlpha = starAlpha * tw * (1 - s.y * 0.6);
        ctx.beginPath();
        ctx.arc(s.x * W, s.y * H, s.r, 0, 6.2832);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    if (shoot) {
      const p = (t - shoot.t0) / 1.1;
      if (p >= 1) shoot = null;
      else {
        const hx = shoot.x + shoot.vx * p * 1.1;
        const hy = shoot.y + shoot.vy * p * 1.1;
        const len = 0.22;
        const lg = ctx.createLinearGradient(hx, hy, hx - shoot.vx * len, hy - shoot.vy * len);
        lg.addColorStop(0, `rgb(255 255 255 / ${0.85 * Math.sin(Math.PI * p)})`);
        lg.addColorStop(1, "rgb(255 255 255 / 0)");
        ctx.strokeStyle = lg;
        ctx.lineWidth = 1.3;
        ctx.beginPath();
        ctx.moveTo(hx, hy);
        ctx.lineTo(hx - shoot.vx * len, hy - shoot.vy * len);
        ctx.stroke();
      }
    }
  }

  function drawOrb() {
    const base = Math.min(W, H);
    const isSun = hour >= 6 && hour < 20;
    const p = isSun ? (hour - 6) / 14 : (((hour - 20 + 24) % 24) / 10);
    const arc = Math.sin(Math.PI * p);
    const x = W * (0.08 + 0.84 * p);
    const y = H * 0.76 - arc * H * 0.6;
    const fade = smooth(0, 0.04, p) * smooth(1, 0.96, p);
    if (isSun) {
      const low = 1 - arc; // warmer and larger near the horizon
      const r = base * 0.026 * (1 + 0.4 * low);
      const disc = mix(hex("#fff5dc"), hex("#ffae63"), low ** 1.5);
      const glow = mix(hex("#ffe2a8"), hex("#ff9a55"), low);
      const gr = ctx.createRadialGradient(x, y, r * 0.5, x, y, r * (7 + 5 * low));
      gr.addColorStop(0, css(glow, 0.45 * fade));
      gr.addColorStop(0.3, css(glow, 0.14 * fade));
      gr.addColorStop(1, css(glow, 0));
      ctx.fillStyle = gr;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = css(disc, fade);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 6.2832);
      ctx.fill();
    } else {
      const r = base * 0.02;
      const gr = ctx.createRadialGradient(x, y, r, x, y, r * 7);
      gr.addColorStop(0, css(hex("#cdd6f4"), 0.16 * fade));
      gr.addColorStop(1, css(hex("#cdd6f4"), 0));
      ctx.fillStyle = gr;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = css(hex("#f2efe4"), 0.95 * fade);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 6.2832);
      ctx.fill();
      // soft shading for a gibbous look
      ctx.fillStyle = css(pal.top, 0.35 * fade);
      ctx.beginPath();
      ctx.arc(x + r * 0.45, y - r * 0.1, r * 0.9, 0, 6.2832);
      ctx.fill();
    }
  }

  function drawClouds(t: number) {
    const span = W + 400;
    ctx.globalAlpha = 0.9 - 0.55 * pal.darkness;
    clouds.forEach((cl, i) => {
      const sprite = cloudSprites[i];
      const w = sprite.width / dpr;
      const drift = motion ? t * cl.speed : 0;
      const x = ((((cl.x * span + drift) % span) + span) % span) - 200 - w / 2;
      ctx.drawImage(sprite, x, cl.y * H - 84 * cl.s, w, sprite.height / dpr);
    });
    ctx.globalAlpha = 1;
  }

  function drawLife(t: number) {
    const ink = css(mix(pal.top, hex("#0a0e18"), 0.7), 0.8);
    ctx.strokeStyle = ink;
    ctx.lineCap = "round";
    for (let i = flocks.length - 1; i >= 0; i--) {
      const f = flocks[i];
      const lead = f.x0 + f.dir * f.speed * (t - f.t0);
      if (lead < -200 || lead > W + 200) {
        if ((t - f.t0) * f.speed > W + 400) flocks.splice(i, 1);
        continue;
      }
      ctx.lineWidth = Math.max(1, f.size * 0.22);
      ctx.beginPath();
      for (const b of f.birds) {
        const s = f.size;
        const x = lead + b.dx;
        const y = f.y + b.dy + Math.sin(t * 1.3 + b.phase) * 2.5;
        const wing = Math.sin(t * f.flap + b.phase);
        const tipY = y - wing * s * 0.6;
        const ctrlY = y - s * 0.3 - wing * s * 0.2;
        ctx.moveTo(x - s, tipY);
        ctx.quadraticCurveTo(x - s * 0.4, ctrlY, x, y);
        ctx.quadraticCurveTo(x + s * 0.4, ctrlY, x + s, tipY);
      }
      ctx.stroke();
    }

    for (let i = planes.length - 1; i >= 0; i--) {
      const p = planes[i];
      const x = p.x0 + p.dir * p.speed * (t - p.t0);
      if (x < -40 || x > W + 40) {
        planes.splice(i, 1);
        continue;
      }
      ctx.fillStyle = "rgb(200 205 220 / 0.25)";
      ctx.fillRect(x - 4, p.y, 8, 1);
      const phase = (t - p.t0) % 1.4;
      if (phase < 0.12) {
        ctx.fillStyle = "rgb(255 70 60 / 0.95)";
        ctx.beginPath();
        ctx.arc(x - p.dir * 3, p.y, 1.6, 0, 6.2832);
        ctx.fill();
      }
      if (phase > 0.7 && phase < 0.78) {
        ctx.fillStyle = "rgb(255 255 255 / 0.95)";
        ctx.beginPath();
        ctx.arc(x + p.dir * 3, p.y, 1.4, 0, 6.2832);
        ctx.fill();
      }
    }
  }

  function draw(t: number) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawSky(t);
    drawOrb();

    // warm haze band where the sky meets the city
    const hz = ctx.createLinearGradient(0, H * 0.45, 0, H * 0.85);
    hz.addColorStop(0, css(pal.haze, 0));
    hz.addColorStop(1, css(pal.haze, 0.45));
    ctx.fillStyle = hz;
    ctx.fillRect(0, H * 0.45, W, H * 0.55);

    drawClouds(t);
    if (motion) {
      pointer.x += (pointer.tx - pointer.x) * 0.05;
      pointer.y += (pointer.ty - pointer.y) * 0.05;
      drawLife(t);
    }
    const lw = W + MARGIN_X * 2;
    const lh = H + MARGIN_Y * 2;
    layers.forEach((c, i) => {
      const dx = -MARGIN_X - pointer.x * PARALLAX_X[i];
      const dy = -MARGIN_Y - pointer.y * PARALLAX_Y[i];
      ctx.drawImage(c, dx, dy, lw, lh);
    });
  }

  resize();
  let raf = 0;
  let interval = 0;

  const loop = (now: number) => {
    const t = now / 1000;
    tick(t);
    draw(t);
    raf = requestAnimationFrame(loop);
  };
  const start = () => {
    if (motion && !raf && !document.hidden) raf = requestAnimationFrame(loop);
  };
  const stop = () => {
    cancelAnimationFrame(raf);
    raf = 0;
  };

  const onResize = () => {
    resize();
    if (!motion) draw(0);
  };
  const onPointer = (e: PointerEvent) => {
    pointer.tx = (e.clientX / W) * 2 - 1;
    pointer.ty = (e.clientY / H) * 2 - 1;
  };
  const onVisibility = () => (document.hidden ? stop() : start());

  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", onVisibility);
  if (motion) {
    window.addEventListener("pointermove", onPointer, { passive: true });
    start();
  } else {
    draw(0);
    interval = window.setInterval(() => {
      if (document.hidden) return;
      refreshPalette();
      draw(0);
    }, 30_000);
  }

  return () => {
    stop();
    clearInterval(interval);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("pointermove", onPointer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
