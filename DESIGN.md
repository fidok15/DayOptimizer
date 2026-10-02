# DayOptimizer Web Planner: Design

The browser planner (`dayoptimizer web`) is where a user describes what their
typical week looks like: which categories of time they have and when those blocks
usually happen. Everything they set is saved to `~/.dayoptimizer/config.local.yaml`.

## Design read

A personal planning tool for people who use the plugin, built around a calm,
living scene that follows the clock. Stack: Vite, React, Tailwind v4 and Motion,
with a procedural canvas skyline behind everything.

Dials: `DESIGN_VARIANCE 6`, `MOTION_INTENSITY 7`, `VISUAL_DENSITY 5`.
It is an app, not a landing page. Layout stays predictable where people work
(the calendar grid). The personality comes from the background scene and motion.

## The scene (background)

**Painted mode (preferred).** Five hand-painted illustrations in `web/public/scene/`
(`dawn.webp`, `day.webp`, `afternoon.webp`, `sunset.webp`, `night.webp`), all with the
same composition: a low view across a park pond up at a downtown skyline, willow
branches and cherry blossoms framing both sides, towers mirrored in the water, ducks
and a frog in the foreground. Painterly, visible brush texture, cinematic grading
(pastel misty dawn, clear blue day, golden afternoon, orange-violet sunset, cool
moonlit blue night). Sources are 2760×1536 JPEGs, converted with
`cwebp -q 80 -resize 2560 0` (about 220 KB each).

`web/src/scene/Painted.tsx` crossfades between the two images around the current
hour, re-evaluated every 30 s with a 30 s linear fade:

| Time | Wallpaper |
|---|---|
| 21:00 to 05:30 | night |
| 05:30 to 06:30 | night fades to dawn |
| 06:30 to 09:30 | dawn fades to day |
| 09:30 to 13:30 | day |
| 13:30 to 16:30 | day fades to afternoon |
| 16:30 to 19:30 | afternoon fades to sunset |
| 19:30 to 21:00 | sunset fades to night |

The painted background is static: no drift, no parallax, no birds. Only the clock
changes it. If any image is missing, the procedural scene below is used instead,
so a fresh clone works without them.

**Procedural mode (fallback).**

An illustrated riverside downtown at the user's local time: tall skyscrapers, a
river with reflections, an arched footbridge and a park in the foreground. It is
drawn on a `<canvas>` fixed behind the UI.

The scene is hand-drawn on purpose, because it has to follow the clock. A
photographic version was tried and rejected: it looked foreign next to the flat UI.

| Layer | Behaviour |
|---|---|
| Sky | Vertical gradient blended between 10 keyframes (00:00, 05:00, 06:15, 07:30, 10:00, 13:00, 17:00, 19:00, 20:30, 22:00). Re-evaluated every 30 s. |
| Sun / moon | Sun follows an arc from 06:00 to 20:00, moon from 20:00 to 06:00. Soft glow. |
| Stars | Visible when dark. They twinkle, with an occasional shooting star. |
| Clouds | Soft, slowly drifting shapes. Dimmer at night. |
| Skyline | Three layers (far, mid, near) of tall towers standing on the far bank (`GROUND`, 74 % of the height). Generated from a fixed seed, so the city is the same on every visit. Hand-placed landmarks: supertalls, an art-deco spire tower, glass towers. Far layers fade into the haze. |
| Windows | Each window has its own threshold, so more lights come on as it gets darker. Some slowly switch on and off. |
| Far bank | Promenade with trees and lamps that glow at night. |
| River | Mirrors the sky, the skyline and the bank as shimmering horizontal strips. At night, lit windows become warm streaks on the water. |
| Bridge | Arched footbridge over the river, with lamps and its own reflection. |
| Park | Foreground bank: trees, a path, benches and lamps. |
| Life | Birds by day, a plane and shooting stars at night, boats crossing the river. |
| Cherry blossoms | Branches hang into both top corners and frame the city, like a painted moonlit skyline seen through a tree. Grown from a fixed seed in `web/src/scene/blossom.ts`. Reach is capped (`min(30 % W, 45 % H, 380 px)`) so they never reach the planner. Five-petal flowers in three pinks (`#f7c6d4 #ec9db8 #fde4ea`) on dark bark (`#4a3434`). |
| Moonlit grading | At night the bark goes to ink and petals cool toward the sky colour (up to 55 % toward a moonlight blue), so night reads cool blue and day reads warm. |
| Falling petals | 18 petals drift down near the corners they fell from, swaying and spinning. Motion only. |
| Brush grain | A static noise tile over the whole scene (`overlay`, 7 % alpha) so flat fills read as painted, not vector. |
| Parallax | Depth follows the pointer, from far towers (least) to the blossom branches (most). |

The look is borrowed from painted editorial hero art: a moonlit skyline framed by
cherry blossom branches, visible brush texture and cinematic colour grading (cool
blues at night, warm light by day). Only the background follows that reference;
the panels and tokens below are unchanged.

The vertical composition lives in `web/src/scene/layout.ts`.

`?hour=21.5` in the URL overrides the clock. It is used for QA screenshots and
to preview other times of day.

Reduced motion (`prefers-reduced-motion: reduce`): the scene is drawn once and
redrawn every 30 s. There is no animation and no parallax.

## Layout

```
+----------------------------------------------------------------+
| Good evening · 21:40                         [Day|Week] Saved ✓ |
| Protect your peak hours. Spend them on what matters.           |
+--------------+-------------------------------------------------+
| Categories   |  Mon  Tue  Wed  Thu  Fri  Sat  Sun              |
|  ● Work  🔒  |  06 ┌────┐                                      |
|  ● Gym   ↔   |  07 │Food│        ┌────┐                        |
|  ● Food  ↔   |  08 └────┘        │Gym │                        |
|  + Add       |  ...                                            |
|  This week   |                                                 |
|  Work 32h    |                                                 |
+--------------+-------------------------------------------------+
|                 made with ❤️ by fidok ©                         |
+----------------------------------------------------------------+
```

- Grid: `grid-cols-[20rem_1fr]` from `lg` up. Below `lg` the sidebar sits above the calendar in a single column.
- Page width is capped at `max-w-[1400px] mx-auto`. Viewport height uses `min-h-[100dvh]`.
- On screens narrower than `md`, the planner opens in Day view by default. Week view scrolls sideways inside its own panel, never the whole page.

## Tokens

Two themes, switched by the sun/moon button in the header (`web/src/lib/theme.ts`).
The choice is saved in `localStorage` (`dayoptimizer-theme`); without one the system
preference wins. An inline script in `index.html` sets `data-theme` on `<html>` before
first paint, so there is no flash. Components only use tokens; `:root[data-theme="dark"]`
in `index.css` swaps them. Both themes share the same transparency and blur (panels
`.86` / `blur(24px) saturate(140%)`, header pills `.62` / `blur(20px) saturate(180%)`).

- **Light** (default): editorial theme from `city.md`, painted hero art with frosted parchment UI. Values below.
- **Dark**: the original smoke glass. Ink `#f3f1ec` / `#c9ccd9`, amber accent and fills `#f4b860` with night text, hairlines `white/13`, grid surface `rgb(15 19 34)`, Geist semibold headline.

Light theme tokens:

| Token | Value | Use |
|---|---|---|
| `--glass` | `rgb(254 255 252 / .86)` | Panels: frosted parchment over the painting |
| `--glass-strong` | `rgb(254 255 252 / .97)` | Popovers, dialogs, reduced-transparency fallback |
| `--line` | `#dee2de` | Mist: 1 px hairline borders, hour lines |
| `--ink` | `#2c2c2c` | Graphite: primary text |
| `--ink-dim` | `#646464` | Ash: secondary text |
| `--accent` | `#41a1cf` | Signal blue: outlines, links, focus ring, today, now line. Never a fill |
| `--dusk` | `#1f1f29` | The only filled button colour (primary actions, active Day/Week, today chip) |
| `--linen` | `#f9faf7` | Inputs and code wells |
| `--font-display` | Fraunces Variable | Headline serif, weight 400, `-0.02em` tracking |

Panels are frosted parchment with a white hairline edge and the city.md content-card
shadow (`0 1px 1px` + `0 4px 5px` at 8 % black). The calendar grid is solid white paper,
so block text contrast (`readableText`) is computed against white. The hero headline
and intro stay white on the painting, over a soft dark blur. Hover and tint surfaces
use `ink/N` instead of `white/N`. Errors use `#d14a3f`. With
`prefers-reduced-transparency`, panels fall back to `--glass-strong`.

**Header controls** (time badge, Garmin, Import, Save my routine, Day/Week) use
`.glass-btn`, the city.md frosted nav pill: `white/62` fill, `blur(20px) saturate(180%)`,
a 1 px `white/75` edge and a `0 2px 6px` shadow, dark text. The active Day/Week segment
is a dusk pill with white text. "Save my routine" is outlined in signal blue.

**Category colours** are data, not decoration. Each category has one colour,
chosen from 10 swatches (originally picked for dark glass, still distinct on white):
`#e0625a #5b8def #4a9ec2 #6c6fd1 #e07b53 #8a94a6 #4fb286 #c77dcb #6fc3b2 #d4b44a`.

## Type

- Geist Variable (self-hosted via `@fontsource-variable`) for the UI, Geist Mono for times and totals.
- Headline: Fraunces 400, `text-4xl md:text-5xl tracking-[-0.02em] leading-[1.1]`, white, max 2 lines.
- Body: `text-sm`. Time labels: `text-[11px] font-mono`.

## Shape

Panels have a 16 px radius, blocks and inputs 10 px, filled buttons 8 px, header controls and chips are full pill.
The same rule applies everywhere.

## Motion

Every animation has one of four jobs: showing continuous time, confirming an action,
showing a state change, or giving depth.

| Element | Motion | Why |
|---|---|---|
| Page load | Panels rise 16 px and fade in, staggered 80 ms (spring 120/20) | Shows the order to read things in |
| Headline | The motivational line crossfades when it changes | State change |
| Day/Week switch | The active-pill indicator slides (`layoutId`) and columns animate with `layout` | State change |
| Block create/move/resize | Blocks follow the pointer, snap to 15 min and land with a spring | Feedback |
| Block editor | Scales from 0.96 and fades in | Links the editor to its block |
| Save status | Icon crossfade: saving, then saved or error | Feedback |
| Buttons | `active:scale-[0.98]` | Tactile feedback |

Only `transform` and `opacity` are animated. Everything collapses to instant
changes under reduced motion.

## Interactions

- **Create:** drag on an empty part of a day column, or click it to create a 1 h block. The editor opens.
- **Edit:** click a block. The editor lets you pick the category (chips), set a title, adjust start and end, or delete. `Esc` closes it, `Delete` removes the block.
- **Move / resize:** drag a block's body to move it (in Week view you can move it across days). Drag its bottom edge to resize. Both snap to 15 min.
- **Overlaps:** overlapping blocks share the column side by side.
- **Copy day:** in Day view, copy this day's blocks to other days you pick (for example Monday to Tue-Fri).
- **Categories:** add one (name and colour), switch Fixed/Flexible, change priority (0-10), recolour, delete. Deleting a category that has blocks asks for confirmation first, then removes those blocks too.
- **Weekly totals:** the sidebar shows hours per category across the week.

## Persistence

- Changes autosave 700 ms after the last edit with `PUT /api/state`. The header shows Saving, Saved or Error (with a Retry button).
- Only the difference from `config.default.yaml` is written. Keys the planner does not own (`day_rules`, `transport_routes` and so on) are kept.
- Validation happens on the server (pydantic). Its 422 message is shown in the header.

## States

- **Loading:** skeleton panels in the same shape as the final layout.
- **Server unreachable:** the calendar is replaced by a message and a Retry button.
- **Empty week:** a card centred on the grid ("Your week is empty") with an "Add first block" button that creates a 1 h block today at 09:00.

## Accessibility

- Every control is a real `<button>`, `<input>` or `<select>` with a label. Focus ring is `--accent`.
- Blocks are buttons that open the editor, so the calendar works from the keyboard.
- Text contrast is at least AA on `--glass` over the brightest sky frame. This was checked at `?hour=13`.

## Copy

- No em-dashes anywhere in the UI.
- Motivational lines are plain and concrete. One is picked per day, from a list in `web/src/lib/copy.ts`.
- The footer reads exactly: `made with ❤️ by fidok ©`
