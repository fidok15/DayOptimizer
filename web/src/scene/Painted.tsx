import { useEffect, useRef, useState } from "react";
import { drawFlocks, makeFlock, type Flock } from "./birds";
import { sceneHour } from "../lib/time";
import Skyline from "./Skyline";

// Painted backgrounds in web/public/scene/, one per time of day, all with the
// same composition so they crossfade cleanly. Sorted by hour; the list wraps
// around midnight. If any image is missing, the procedural Skyline is used.
const KEYS = [
  { h: 0, src: "night" },
  { h: 5.5, src: "night" },
  { h: 7, src: "dawn" },
  { h: 10, src: "day" },
  { h: 16.5, src: "day" },
  { h: 19, src: "sunset" },
  { h: 21, src: "night" },
];
const NAMES = [...new Set(KEYS.map((k) => k.src))];
const url = (name: string) => `/scene/${name}.webp`;

/** The two images around `hour` and how far (0..1) we are from the first to the second. */
export function blend(hour: number): { a: string; b: string; t: number } {
  let i = KEYS.length - 1;
  while (i > 0 && KEYS[i].h > hour) i--;
  const a = KEYS[i];
  const b = KEYS[(i + 1) % KEYS.length];
  const span = (b.h - a.h + 24) % 24 || 24;
  return { a: a.src, b: b.src, t: ((hour - a.h + 24) % 24) / span };
}

export default function Painted() {
  const [ready, setReady] = useState<boolean | null>(null);
  const [mix, setMix] = useState(() => blend(sceneHour()));

  useEffect(() => {
    let alive = true;
    const load = (n: string) =>
      new Promise<void>((ok, fail) => {
        const img = new Image();
        img.onload = () => ok();
        img.onerror = fail;
        img.src = url(n);
      });
    Promise.all(NAMES.map(load)).then(
      () => alive && setReady(true),
      () => alive && setReady(false),
    );
    const id = window.setInterval(() => setMix(blend(sceneHour())), 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (ready === false) return <Skyline />;
  if (ready === null) return <div aria-hidden className="fixed inset-0 -z-10 bg-[#0b0e1a]" />;
  const layer = "pointer-events-none fixed inset-0 -z-10 h-full w-full object-cover";
  return (
    <>
      <img src={url(mix.a)} alt="" aria-hidden className={layer} />
      {mix.b !== mix.a && (
        // keyed by image, so a new top layer starts at its own opacity instead of fading from the old one
        <img
          key={mix.b}
          src={url(mix.b)}
          alt=""
          aria-hidden
          className={`${layer} transition-opacity duration-[30s] ease-linear motion-reduce:transition-none`}
          style={{ opacity: mix.t }}
        />
      )}
      <Birds />
    </>
  );
}

/** Flocks crossing the painted sky by day. Nothing is drawn with reduced motion. */
function Birds() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let W = 0;
    let H = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const flocks: Flock[] = [];
    let next = 0;
    let raf = 0;
    const loop = (now: number) => {
      const t = now / 1000;
      const h = sceneHour();
      if (t >= next) {
        next = t + 10 + Math.random() * 15;
        if (h >= 6 && h < 20 && flocks.length < 3) flocks.push(makeFlock(t, W, H));
      }
      ctx.clearRect(0, 0, W, H);
      drawFlocks(ctx, flocks, t, W, "rgb(28 24 32 / 0.75)");
      raf = requestAnimationFrame(loop);
    };
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);
  return <canvas ref={ref} aria-hidden className="pointer-events-none fixed inset-0 -z-10 h-full w-full" />;
}
