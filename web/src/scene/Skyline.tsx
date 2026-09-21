import { useEffect, useRef, useState } from "react";
import { sceneHour } from "../lib/time";
import { startLife } from "./life";
import { PHOTOS, darkness, layerOpacities, weights } from "./photos";

/** Photographic city backdrop that follows the clock (see DESIGN.md, "The scene"). */
export default function Skyline() {
  const [w, setW] = useState(() => weights(sceneHour()));
  const canvas = useRef<HTMLCanvasElement>(null);
  const photos = useRef<HTMLDivElement>(null);
  const dark = useRef(darkness(w));
  dark.current = darkness(w);

  useEffect(() => {
    const id = window.setInterval(() => setW(weights(sceneHour())), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => startLife(canvas.current!, photos.current!, () => dark.current), []);

  const opacity = layerOpacities(w);
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-night">
      <div ref={photos} className="absolute -inset-4 will-change-transform">
        <div className="kenburns absolute inset-0">
          {PHOTOS.map((p) => (
            <img
              key={p.key}
              src={p.src}
              alt=""
              decoding="async"
              className="absolute inset-0 h-full w-full object-cover transition-opacity duration-[3000ms]"
              style={{ opacity: opacity[p.key], objectPosition: p.position }}
            />
          ))}
        </div>
      </div>
      {/* shade the top for the headline and the bottom edge for the footer */}
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,rgb(8_10_20/0.6),rgb(8_10_20/0.12)_32%,rgb(8_10_20/0.12)_72%,rgb(8_10_20/0.55))]" />
      <canvas ref={canvas} className="absolute inset-0 h-full w-full" />
    </div>
  );
}
