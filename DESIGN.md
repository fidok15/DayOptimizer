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

A city skyline at the user's local time, drawn on a `<canvas>` and fixed behind
the UI.

This is a hand-built illustration on purpose. A photo cannot show every hour of
the day, and the whole point of the scene is that it changes with the clock.

| Layer | Behaviour |
|---|---|
| Sky | Vertical gradient blended between 10 keyframes (00:00, 05:00, 06:15, 07:30, 10:00, 13:00, 17:00, 19:00, 20:30, 22:00). Re-evaluated every 30 s. |
| Sun / moon | Sun follows an arc from 06:00 to 20:00, moon from 20:00 to 06:00. Soft radial glow. |
| Stars | Visible when the scene is dark. They twinkle, and a shooting star crosses the sky every 20-40 s. |
| Clouds | Soft, slowly drifting shapes. Dimmer at night. |
| Skyline | Three layers of buildings (far, mid, near), generated from a fixed seed so the city looks the same on every visit. Far layers fade into the horizon haze. |
| Windows | Each window has its own threshold, so more lights come on as it gets darker. Lights switch on and off slowly, like people moving between rooms. |
| Life | Flocks of birds fly across the sky during the day. At night a plane with blinking lights crosses instead. |
| Parallax | The layers shift a few pixels with the pointer, so the city has depth. |

`?hour=21.5` in the URL overrides the clock. It is used for QA screenshots and
to preview other times of day.

Reduced motion (`prefers-reduced-motion: reduce`): the scene is drawn once and
redrawn every 30 s. No birds, planes, parallax, twinkle or cloud drift.

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

- Grid: `grid-cols-[18rem_1fr]` from `lg` up. Below `lg` the sidebar sits above the calendar in a single column.
- Page width is capped at `max-w-[1400px] mx-auto`. Viewport height uses `min-h-[100dvh]`.
- On screens narrower than `md`, the planner opens in Day view by default. Week view scrolls sideways inside its own panel, never the whole page.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--glass` | `rgb(12 16 30 / .58)` | Panels (smoke glass) |
| `--glass-strong` | `rgb(12 16 30 / .82)` | Popovers, reduced-transparency fallback |
| `--line` | `rgb(255 255 255 / .10)` | 1 px borders, hour lines |
| `--ink` | `#f3f1ec` | Primary text |
| `--ink-dim` | `#b9bccb` | Secondary text (AA on `--glass` over the brightest sky) |
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
- **Empty week:** a hint inside the grid: "Drag on a day to add your first block".

## Accessibility

- Every control is a real `<button>`, `<input>` or `<select>` with a label. Focus ring is `--accent`.
- Blocks are buttons that open the editor, so the calendar works from the keyboard.
- Text contrast is at least AA on `--glass` over the brightest sky frame. This was checked at `?hour=13`.

## Copy

- No em-dashes anywhere in the UI.
- Motivational lines are plain and concrete. One is picked per day, from a list in `web/src/lib/copy.ts`.
- The footer reads exactly: `made with ❤️ by fidok ©`
