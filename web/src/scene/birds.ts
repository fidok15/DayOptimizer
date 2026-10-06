interface Bird { dx: number; dy: number; phase: number }
export interface Flock { t0: number; x0: number; dir: number; y: number; speed: number; size: number; flap: number; birds: Bird[] }

const between = (a: number, b: number): number => a + Math.random() * (b - a);

export function makeFlock(t: number, W: number, H: number): Flock {
  const dir = Math.random() < 0.5 ? 1 : -1;
  const z = between(0.55, 1.25);
  const n = 5 + Math.floor(Math.random() * 5);
  const birds: Bird[] = Array.from({ length: n }, (_, i) => {
    const k = Math.ceil(i / 2);
    const side = i % 2 ? 1 : -1;
    return { dx: -dir * k * 15 * z + between(-3, 3), dy: side * k * 7 * z + between(-3, 3), phase: Math.random() * 6.28 };
  });
  return { t0: t, dir, x0: dir > 0 ? -80 : W + 80, y: H * between(0.12, 0.42), speed: 28 + 36 * z, size: 5.5 * z, flap: between(7, 9.5), birds };
}

export function drawFlocks(ctx: CanvasRenderingContext2D, flocks: Flock[], t: number, W: number, ink: string): void {
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
}
