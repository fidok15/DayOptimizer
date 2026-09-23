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
| Parallax | Depth follows the pointer, from far towers (least) to the park (most). |

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

| Token | Value | Use |
|---|---|---|
| `--glass` | `rgb(11 14 26 / .94)` | Panels: nearly opaque smoke glass, so text never competes with the scene |
| `--glass-strong` | `rgb(13 17 30 / .97)` | Popovers, reduced-transparency fallback |
| `--line` | `rgb(255 255 255 / .13)` | 1 px borders, hour lines |
| `--ink` | `#f3f1ec` | Primary text |
| `--ink-dim` | `#c9ccd9` | Secondary text (AA on `--glass` over the brightest sky) |
| `--accent` | `#f4b860` | The single UI accent (sunrise amber): primary buttons, focus ring, active toggle |

Panels always use dark smoke glass with light text. The sky behind them goes from
bright noon blue to night navy, so a fixed dark glass is the only option that stays
readable at every hour.

The "theme" is the clock: the scene is the light/dark switch. On top of the blur,
panels get a 1 px `white/10` inner border and an inset top highlight. With
`prefers-reduced-transparency`, panels fall back to `--glass-strong`.

**Category colours** are data, not decoration. Each category has one colour,
chosen from 10 swatches picked to stay apart on dark glass:
`#e0625a #5b8def #4a9ec2 #6c6fd1 #e07b53 #8a94a6 #4fb286 #c77dcb #6fc3b2 #d4b44a`.

## Type

- Geist Variable (self-hosted via `@fontsource-variable`) for the UI, Geist Mono for times and totals.
- Headline: `text-3xl md:text-5xl tracking-tight leading-[1.1]`, max 2 lines.
- Body: `text-sm`. Time labels: `text-[11px] font-mono`.

## Shape

Panels have a 20 px radius, blocks and inputs 10 px, toggles and chips are full pill.
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
