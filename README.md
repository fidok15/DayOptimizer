# DayOptimizer

DayOptimizer plans and replans your day against your real Apple Calendar. A
deterministic Python engine decides *where things go* — it has no API key and
burns no tokens for the automatic cases (background checks, new-event
reactions, sleep-data reactions). Claude is the language brain on top: it runs
the onboarding interview, turns "move gym to tomorrow" into a tool call,
and explains what changed and why. Optional Garmin data (sleep, Body Battery,
HRV, stress) feeds the engine so recovery — not just free calendar slots —
decides when workouts and deep-work blocks land.

Fixed events (meetings, work, anything you mark non-movable) are never
touched without your explicit approval. Flexible categories (sleep, food,
gym, learning, free time, transport) are rescheduled automatically, with a
notification-style summary of what moved and why.

## Requirements

- macOS (DayOptimizer reads/writes Apple Calendar via EventKit; this only
  works on macOS)
- Apple Calendar with calendars **named exactly after DayOptimizer's planner
  categories** (`Food`, `Gym`, `Learn`, etc.) — see
  [Set up your calendars](#set-up-your-calendars) below. Skip this and the
  planner still computes a plan, but every block for a missing calendar is
  silently skipped.
- [uv](https://docs.astral.sh/uv/) for Python dependency management
- Optional: a Garmin Connect account, if you want recovery-aware planning
- Optional: Claude Code, to use DayOptimizer as a plugin (recommended path)

## Set up your calendars

DayOptimizer writes planned blocks into Apple Calendar calendars whose names
match its planner categories **exactly** — case-sensitive, no emoji, no extra
spaces. There is no fuzzy matching: a calendar named `food` or `🍔 Food` does
not count as `Food`.

Default categories (from `config.default.yaml`):

| Category | The planner... |
|---|---|
| `Food`, `Gym`, `Learn`, `Sleep`, `Free time`, `Transport` | creates/moves blocks in these automatically (flexible) |
| `Work`, `Meeting`, `Important` | only classifies your existing events by these names; it moves them only after you approve the change (fixed) |

**Without a matching calendar for a category, plans are computed but every
block for that category is skipped** — as of this version, that failure is
reported to you explicitly (a "N block(s) could not be written" summary
naming the missing calendars) instead of vanishing silently.

To create the calendars you're missing:

1. Open Calendar.app.
2. `File > New Calendar`.
3. Name it exactly one of the category names above (e.g. `Food`).
4. Pick any account for it (iCloud, local, a Google account) — DayOptimizer
   doesn't care where the calendar lives, only its name.
5. Repeat for each category you want the planner to manage.

`/dayoptimizer:init` (see [Onboarding](#onboarding)) now checks which
calendars already exist and tells you exactly which ones to create before
asking anything else.

**Language note:** the category names above (and the block titles the
planner writes, e.g. "Deep work", "Own work") are English-only in this
version — they are not translated or configurable. What *is* configurable
per-user is meal names (`day_rules.meal_windows[].name`) and the free-time
activity label (`day_rules.free_time_activity`), via `config.local.yaml` /
the onboarding interview — but the calendar names themselves must stay
exactly as listed above.

## Quick start

Needs macOS and [uv](https://docs.astral.sh/uv/). Node is not needed: the web
planner ships prebuilt.

```bash
git clone https://github.com/fidok15/DayOptimizer.git
cd DayOptimizer
scripts/install.sh
```

The installer syncs the Python dependencies, builds the small app bundle macOS
needs for calendar access, and puts a `dayoptimizer` command in `~/.local/bin`
(adding it to your PATH if needed).

The first time you run `dayoptimizer` it opens a page in your browser where you
draw your typical week: your categories, routines and habits. That page is only
for this setup (reopen it with `dayoptimizer setup`). After that you use the
terminal:

```bash
dayoptimizer                                  # optimize today around what's in your calendar
dayoptimizer "meeting at 14:00 for about an hour, then gym"
dayoptimizer "tomorrow I'm off, dentist at 10"
dayoptimizer --help                           # every other command
```

Plain-words requests need a language model. DayOptimizer shows what it understood
and asks before touching the calendar. It uses a local model when
[Ollama](https://ollama.com) is running (free, nothing leaves your Mac):

```bash
brew install ollama && brew services start ollama && ollama pull qwen3:8b
```

Otherwise it uses Claude when `ANTHROPIC_API_KEY=...` is in a `.env` file in the
DayOptimizer folder. `llm.backend` in the config forces one (`ollama`, `anthropic`,
default `auto`). Bare `dayoptimizer` needs neither. Commands that touch
the calendar run through DayOptimizer's app bundle automatically (see
[macOS calendar permission](#macos-calendar-permission-tcc)).

Rerun `scripts/install.sh` after `git pull`; it is safe to repeat.

**Why no Docker image?** DayOptimizer reads and writes Apple Calendar through
macOS itself (EventKit, with the calendar permission granted to its app bundle),
runs in the background through launchd and sends macOS notifications. A Docker
container is a Linux machine with none of those, so the planner would lose the
calendar, which is the point of the app. The installer above is the supported
setup.

## Install as a Claude Code plugin

```
/plugin marketplace add fidok15/DayOptimizer
/plugin install dayoptimizer
```

Then, from the plugin's directory (the checkout Claude Code created for it):

```bash
uv sync
scripts/setup-bundle.sh
```

`uv sync` installs DayOptimizer's Python dependencies. `scripts/setup-bundle.sh`
builds the small macOS app bundle DayOptimizer needs for calendar access — see
[macOS calendar permission (TCC)](#macos-calendar-permission-tcc) below for why
that's a separate step.

## Onboarding

Run `/dayoptimizer:init` in Claude Code. It interviews you conversationally
(work hours, meal times, sleep target, gym frequency, commute) and proposes a
config, which it writes to `~/.dayoptimizer/config.local.yaml` after you
approve it. Garmin is optional — if you have a watch, `/dayoptimizer:init`
tells you to run `uv run dayoptimizer garmin login` in a separate terminal (it never
asks for your Garmin password itself).

### Web planner

**How the week you draw is used.** When you have a typical week, the planner
builds each day from it: every block goes into the calendar at its usual time.
If something already sits there, a Flexible block moves to the nearest free
time and a Fixed one is only flagged, so your own events always win. Days you
leave empty stay empty. Each category gets its own calendar in the Calendar app
(in its colour) when you press **Save my routine**, and the planner creates any
that are still missing when it first writes to them. Deleting a category never
deletes its calendar.

**Your notes become rules.** The notes box is compiled into rules the planner
enforces on its own, once, when you press Save my routine — so planning still
needs no LLM and stays deterministic. "No lunch before 14:00" becomes a real
constraint; "Sundays 18:00-22:00 are family time" keeps that window empty; "I
never train two days in a row" and "gym three times a week at most" cap it.
The dialog lists exactly what became a rule and what stayed a note (a mood like
"I want to feel less rushed" can't be enforced, so the assistant just reads it).
Rules live under `note_rules` in `config.local.yaml`, so you can fix or delete
any of them by hand.

**Recovery-aware training.** With Garmin connected, the planner reads the
watch's recovery time and readiness. Because recovery time only says when the
body is ready for the next *hard* session, a training block is kept and flagged
"keep it easy" rather than dropped, and dropped only when it would load what
recent hard work already tired out (legs after a long run; upper body and desk
work are unaffected). Which region a block trains is learned from the watch's
own history — what it actually recorded in those hours, or in the same
category's other blocks — so nothing needs tagging and non-training blocks are
never touched. Thresholds live in `day_rules`
(`recovery_lighter_hours`, `recovery_skip_hours`, `respect_recovery: false` to
ignore all of it). Without a drawn week, generic rules from
`config.default.yaml` fill the day (meal windows, workouts, focus blocks).

`dayoptimizer setup` (run automatically on first use) opens a local planner at
`http://127.0.0.1:8765/`: add, recolour or remove categories, mark them Fixed or
Flexible, and draw your typical week on a day or week calendar. Changes autosave
to `~/.dayoptimizer/config.local.yaml` (categories plus a `typical_week` section).
The server only listens on localhost. `--port N` changes the port, `--no-open`
skips opening a browser tab. The UI's design is documented in [DESIGN.md](DESIGN.md).

Developing the UI: `cd web && npm install && npm run dev` (Vite proxies `/api` to
a running `dayoptimizer web --no-open`); `npm run build` writes the bundle into
`src/dayoptimizer/web_static/`, which is what the Python server serves.

## Commands (Claude Code plugin)

| Command | What it does |
|---|---|
| `/dayoptimizer:init` | Onboarding interview → writes `config.local.yaml` |
| `/dayoptimizer:plan [date\|week]` | Plans/replans a day or the next 7 days; asks approval for fixed-event changes |
| `/dayoptimizer:today` | Morning briefing: today's schedule + health status |
| `/dayoptimizer:stats` | 14-day Garmin trends and planning suggestions |

## CLI reference

DayOptimizer also works as a standalone CLI. After `scripts/install.sh` the
`dayoptimizer` command works from anywhere, so drop the `uv run` prefix below.
Without the installer, run the commands with `uv run` from the checkout directory — the
`pyproject.toml`-managed virtualenv is what makes the bare `dayoptimizer`
binary resolve at all. If Claude Code installed the plugin for you, that
checkout lives at `~/.claude/plugins/cache/dayoptimizer/dayoptimizer`
(pattern: `~/.claude/plugins/cache/<plugin-name>/<plugin-name>`). If you're
not sure where it is, just ask Claude to "cd into the dayoptimizer plugin
directory" before running any of these.

| Command | What it does |
|---|---|
| `dayoptimizer` | Optimize today around the calendar (first run: opens `setup`) |
| `dayoptimizer "<your day in plain words>"` | Shows the events it understood, adds them on your OK, then replans (local Ollama or `ANTHROPIC_API_KEY`) |
| `uv run dayoptimizer plan [--date YYYY-MM-DD] [--week [N]]` | Plan today (default), a specific date, or `N` days starting there (`--week` alone = 7) |
| `uv run dayoptimizer check` | Stateless background cycle: picks up new sleep data, new calendar events, and stress/Body Battery shifts, replans if needed |
| `uv run dayoptimizer agent install [--interval SECONDS]` | Installs the launchd background agent (label `com.dayoptimizer.check`, default interval 900s / 15 min) that runs `check` periodically |
| `uv run dayoptimizer agent uninstall` | Stops and removes the background agent |
| `uv run dayoptimizer agent status` | Shows whether the agent is installed/running |
| `uv run dayoptimizer garmin login` | Logs into Garmin Connect once and stores OAuth tokens (password is never persisted) |
| `uv run dayoptimizer stats` | 14-day Garmin trends and suggested rule adjustments |
| `uv run dayoptimizer apply --ids 3,4` | Applies pending fixed-event changes by id, after you've reviewed them |
| `uv run dayoptimizer setup [--port N] [--no-open]` | Opens the typical-week setup page in the browser (see [Web planner](#web-planner)) |
| `uv run dayoptimizer chat` | Several plain-words requests in a row, one per line |

Because EventKit needs the TCC bundle (see below), the calendar commands
(`plan`, `apply`, `check`, `sync` and plain-words requests) hand themselves to
the bundle when started from a terminal, and print its output when done.

Plain-words requests and `chat` call the Anthropic API directly (not a local model): they
requires `ANTHROPIC_API_KEY` set in your environment (or in a `.env` file in
the plugin directory, which `dayoptimizer` loads automatically). It does not
work offline.

`/dayoptimizer:today` and `/dayoptimizer:stats` only read DayOptimizer's
local cache (`~/.dayoptimizer/data.db`) — they show nothing, or stale data,
until something has populated it. Either install the background agent
(`uv run dayoptimizer agent install`) so it stays fresh automatically, or
run `/dayoptimizer:plan` (or `uv run dayoptimizer plan`) at least once
first.

## macOS calendar permission (TCC)

macOS only shows the calendar-access permission prompt to processes whose
host app declares `NSCalendarsFullAccessUsageDescription` in its
`Info.plist`. Terminal, iTerm, VS Code, and Claude Code itself don't declare
this key, so EventKit silently denies access from inside them — no prompt,
just a permission failure.

To work around this, `scripts/setup-bundle.sh` builds a minimal app bundle at
`~/.dayoptimizer/DayOptimizer.app` (inside `~/.dayoptimizer`, which is kept
at mode 0700), copying your project's `uv` virtualenv Python into it
alongside an `Info.plist` carrying the required usage-description keys.
macOS's TCC system grants calendar access to *that bundle*, not to your
terminal. `scripts/dayoptimizer-app <command>` runs the CLI through the
bundle via `open -W -a ~/.dayoptimizer/DayOptimizer.app --args <runner>`;
the MCP server's write tools use the same open-the-bundle mechanism
internally. Either way, calendar reads/writes happen inside the permitted
bundle; output is written to a log file and printed back since a bundled app
has no attached stdout.

The first time you run `scripts/dayoptimizer-app plan` (or the plugin calls
`plan`), macOS shows the standard "DayOptimizer would like to access your
calendar" prompt. Approve it once; the grant persists for the bundle.

If you ever rebuild your `.venv` (e.g. after upgrading Python), rerun
`scripts/setup-bundle.sh` to refresh the bundle's copy of the interpreter.

### TCC troubleshooting

- **The permission prompt never appeared.** Rerun
  `scripts/dayoptimizer-app plan` directly in a terminal (not through the
  plugin) so you can see it fail; then check System Settings → Privacy &
  Security → Calendars for a "DayOptimizer" entry. If it's not listed at
  all, `scripts/setup-bundle.sh` may not have run successfully — rerun it.
- **You clicked "Don't Allow" by mistake.** macOS won't re-prompt after a
  denial. Go to System Settings → Privacy & Security → Calendars, find
  "DayOptimizer" in the list, and enable it manually.
- **The background agent stopped working after a plugin update or a moved
  checkout.** The launchd job and the app bundle both hardcode paths from
  when they were installed. Rerun, in order: `uv sync`, then
  `scripts/setup-bundle.sh`, then `uv run dayoptimizer agent install`.

## Privacy & data

- All DayOptimizer data — the SQLite cache (calendar snapshot, Garmin
  history, change log), your local config, and Garmin OAuth tokens — stays
  under `~/.dayoptimizer`, which is created with mode `0700` (only your user
  account can read it).
- In plugin mode, event titles and health summaries are sent to Claude as
  part of your conversation (i.e., to the Anthropic API) so Claude can
  explain and discuss your plan. Nothing is sent anywhere else.
- Garmin credentials are used exactly once, at `uv run dayoptimizer garmin login`
  time, by the unofficial `garminconnect` library to obtain OAuth tokens.
  Your password itself is never written to disk — only the resulting OAuth
  tokens are stored, under `~/.dayoptimizer/garmin`.
- Nothing else leaves your machine. There is no telemetry, analytics, or
  external server component.

## Configuration

Defaults live in the repo at `config.default.yaml` (category movability and
priority, meal windows, gym frequency, deep-work block sizing, sleep target,
etc.). Your personal overrides live in `~/.dayoptimizer/config.local.yaml`
(created by `/dayoptimizer:init`, gitignored by design — it's private data,
never part of a repo) and are merged on top of the defaults.

Every category has a `movable` flag:

- `movable: false` (defaults: `Important`, `Meeting`, `Work`) — the planner
  never changes these events on its own. When a plan would require moving
  one, it's parked as a **pending change** (with an id) instead of applied.
  Review pending changes and approve them with `uv run dayoptimizer apply --ids
  <id,id,...>` (or by replying to the Claude Code plugin's prompt, which
  calls the same `apply_changes` tool).
- `movable: true` (defaults: `Sleep`, `Food`, `Transport`, `Gym`, `Learn`,
  `Free time`) — the planner reschedules these automatically and just
  reports what moved and why.

You can add your own categories or change movability/priority for the
existing ones in `config.local.yaml`; the onboarding interview does this for
you. You can also edit the file directly — but note that direct edits are
not validated; only changes made through the plugin's `save_config` tool are
schema-checked before saving.

The planning window itself is configurable via `day_rules.day_start` /
`day_rules.day_end` (default `06:00`-`23:00`) — the earliest and latest times
the planner will place blocks in; set during the onboarding interview.

`day_rules.work_days` (default Mon-Fri) lists the days the planner fills
spare time with "Own work" blocks — an empty list (`[]`) is valid and means
no work filler on any day; `holiday_calendars` (default
`["Public Holidays", "Holidays"]`) names calendars whose all-day events mark
public holidays — a holiday makes that day a non-work day regardless of
`work_days`. Either way the rest of the day's structure (meals, sleep, gym,
deep work) is still planned; only the work filler is skipped.
