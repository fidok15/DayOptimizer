// Animated layer over the photos: birds by day, shooting stars and a blinking
// plane by night, plus pointer parallax on the photo stack. No static stars:
// the night photo's towers reach the top edge, so dots would land on buildings.

interface Bird { dx: number; dy: number; phase: number }
interface Flock { t0: number; x0: number; dir: number; y: number; speed: number; size: number; flap: number; birds: Bird[] }
interface Plane { t0: number; x0: number; dir: number; y: number; speed: number }
interface Shoot { t0: number; x: number; y: number; vx: number; vy: number }

const PARALLAX = 14; // px the photos travel with the pointer
const between = (a: number, b: number): number => a + Math.random() * (b - a);

export function startLife(
  canvas: HTMLCanvasElement,
  photos: HTMLElement,
  getDarkness: () => number,
): () => void {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return () => {};
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};

  const flocks: Flock[] = [];
  const planes: Plane[] = [];
  let shoot: Shoot | null = null;
  const pointer = { tx: 0, ty: 0, x: 0, y: 0 };
  let W = 0;
  let H = 0;
  let dpr = 1;
  const now = performance.now() / 1000;
  const next = { flock: now + between(2, 5), plane: now + between(4, 10), shoot: now + between(6, 14) };

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
  }

  function makeFlock(t: number): Flock {
    const dir = Math.random() < 0.5 ? 1 : -1;
    const z = between(0.6, 1.3); // depth: nearer flocks are bigger and faster
    const n = 5 + Math.floor(Math.random() * 5);
    const birds: Bird[] = Array.from({ length: n }, (_, i) => {
      const k = Math.ceil(i / 2);
      const side = i % 2 ? 1 : -1;
      return { dx: -dir * k * 15 * z + between(-3, 3), dy: side * k * 7 * z + between(-3, 3), phase: Math.random() * 6.28 };
    });
    return { t0: t, dir, x0: dir > 0 ? -80 : W + 80, y: H * between(0.1, 0.34), speed: 30 + 38 * z, size: 6 * z, flap: between(7, 9.5), birds };
  }

  function spawn(t: number, dark: number) {
    if (t >= next.flock) {
      next.flock = t + between(10, 22);
      if (dark < 0.35) flocks.push(makeFlock(t));
    }
    if (t >= next.plane) {
      next.plane = t + between(24, 36);
      if (dark > 0.6) {
        const dir = Math.random() < 0.5 ? 1 : -1;
        planes.push({ t0: t, dir, x0: dir > 0 ? -20 : W + 20, y: H * between(0.06, 0.24), speed: between(16, 24) });
      }
    }
    if (t >= next.shoot) {
      next.shoot = t + between(18, 36);
      if (dark > 0.7) {
        const dir = Math.random() < 0.5 ? 1 : -1;
        shoot = { t0: t, x: W * between(0.15, 0.85), y: H * between(0.02, 0.1), vx: dir * between(380, 520), vy: between(120, 190) };
      }
    }
  }

  function drawShootingStar(t: number) {
    if (!shoot) return;
    const p = (t - shoot.t0) / 1.1;
    if (p >= 1) {
      shoot = null;
      return;
    }
    const hx = shoot.x + shoot.vx * p * 1.1;
    const hy = shoot.y + shoot.vy * p * 1.1;
    const tail = 0.22;
    const g = ctx!.createLinearGradient(hx, hy, hx - shoot.vx * tail, hy - shoot.vy * tail);
    g.addColorStop(0, `rgb(255 255 255 / ${0.85 * Math.sin(Math.PI * p)})`);
    g.addColorStop(1, "rgb(255 255 255 / 0)");
    ctx!.strokeStyle = g;
    ctx!.lineWidth = 1.3;
    ctx!.beginPath();
    ctx!.moveTo(hx, hy);
    ctx!.lineTo(hx - shoot.vx * tail, hy - shoot.vy * tail);
    ctx!.stroke();
  }

  function drawBirds(t: number) {
    ctx!.strokeStyle = "rgb(14 17 28 / 0.78)";
    ctx!.lineCap = "round";
    for (let i = flocks.length - 1; i >= 0; i--) {
      const f = flocks[i];
      const lead = f.x0 + f.dir * f.speed * (t - f.t0);
      if ((t - f.t0) * f.speed > W + 400) {
        flocks.splice(i, 1);
        continue;
      }
      ctx!.lineWidth = Math.max(1, f.size * 0.22);
      ctx!.beginPath();
      for (const b of f.birds) {
        const s = f.size;
        const x = lead + b.dx;
        const y = f.y + b.dy + Math.sin(t * 1.3 + b.phase) * 2.5;
        const wing = Math.sin(t * f.flap + b.phase);
        const tipY = y - wing * s * 0.6;
        const ctrlY = y - s * 0.3 - wing * s * 0.2;
        ctx!.moveTo(x - s, tipY);
        ctx!.quadraticCurveTo(x - s * 0.4, ctrlY, x, y);
        ctx!.quadraticCurveTo(x + s * 0.4, ctrlY, x + s, tipY);
      }
      ctx!.stroke();
    }
  }

  function drawPlanes(t: number) {
    for (let i = planes.length - 1; i >= 0; i--) {
      const p = planes[i];
      const x = p.x0 + p.dir * p.speed * (t - p.t0);
      if (x < -40 || x > W + 40) {
        planes.splice(i, 1);
        continue;
      }
      ctx!.fillStyle = "rgb(200 205 220 / 0.3)";
      ctx!.fillRect(x - 4, p.y, 8, 1);
      const phase = (t - p.t0) % 1.4;
      if (phase < 0.12) {
        ctx!.fillStyle = "rgb(255 70 60 / 0.95)";
        ctx!.beginPath();
        ctx!.arc(x - p.dir * 3, p.y, 1.6, 0, 6.2832);
        ctx!.fill();
      }
      if (phase > 0.7 && phase < 0.78) {
        ctx!.fillStyle = "rgb(255 255 255 / 0.95)";
        ctx!.beginPath();
        ctx!.arc(x + p.dir * 3, p.y, 1.4, 0, 6.2832);
        ctx!.fill();
      }
    }
  }

  let raf = 0;
  const loop = (ms: number) => {
    const t = ms / 1000;
    const dark = getDarkness();
    spawn(t, dark);
    pointer.x += (pointer.tx - pointer.x) * 0.05;
    pointer.y += (pointer.ty - pointer.y) * 0.05;
    photos.style.transform = `translate3d(${-pointer.x * PARALLAX}px, ${-pointer.y * PARALLAX * 0.5}px, 0)`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    drawShootingStar(t);
    drawBirds(t);
    drawPlanes(t);
    raf = requestAnimationFrame(loop);
  };
  const start = () => {
    if (!raf && !document.hidden) raf = requestAnimationFrame(loop);
  };
  const stop = () => {
    cancelAnimationFrame(raf);
    raf = 0;
  };
  const onPointer = (e: PointerEvent) => {
    pointer.tx = (e.clientX / W) * 2 - 1;
    pointer.ty = (e.clientY / H) * 2 - 1;
  };
  const onVisibility = () => (document.hidden ? stop() : start());

  resize();
  window.addEventListener("resize", resize);
  window.addEventListener("pointermove", onPointer, { passive: true });
  document.addEventListener("visibilitychange", onVisibility);
  start();
  return () => {
    stop();
    window.removeEventListener("resize", resize);
    window.removeEventListener("pointermove", onPointer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
