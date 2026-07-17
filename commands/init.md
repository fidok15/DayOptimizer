---
description: Set up DayOptimizer — interview the user about their typical day and generate their configuration
---

Run the DayOptimizer onboarding interview. Follow these steps exactly:

1. Call the `list_calendars` MCP tool and the `get_config` MCP tool before
   asking anything — ground the whole interview in what actually exists,
   instead of interviewing blind and finding out about mismatches later.
   - If `get_config` shows a user config already exists, ask whether to
     update it or start over.
   - Compare the calendars `list_calendars` reports against the planner's
     default categories it lists. Tell the user plainly what you found, e.g.
     "I can see calendars Work, Meeting, Gym — which of the planner's
     categories do they map to? You're missing calendars for: Food, Learn,
     Sleep, Free time, Transport — create them in Calendar.app now (File >
     New Calendar, name it exactly, e.g. `Food`), I'll wait." Without a
     matching calendar, that category's blocks are silently skipped, so
     don't move on until the user confirms they've created (or intentionally
     skipped) each missing one.
2. Interview the user conversationally, ONE question at a time. State briefly
   *why* you're asking before or as part of each question:
   - Typical weekday (work/school hours, commute) — this sets the planner's
     fixed anchors for the day.
   - Do they have a job or regular work? Which days do they work — this sets
     `work_days` (default Mon-Fri), the days the planner fills spare time with
     "Own work" blocks; other days keep their structure (meals, sleep, gym,
     deep work) but skip that filler. If they name fixed working hours,
     suggest creating recurring events in the Work calendar for those hours
     instead — those become the fixed anchor the planner plans around.
   - Which of their calendars (from `list_calendars`) is their holidays
     calendar, if any — sets `holiday_calendars`; a holiday always makes that
     day a non-work day regardless of `work_days`. Note macOS often
     auto-subscribes a locale-named one (e.g. a Polish user may see a
     Polish-named holidays calendar even with English system language) —
     point that out if `list_calendars` shows one.
   - Which parts of the day are fixed (meetings, work) vs flexible — decides
     which categories get `movable: true` vs `false`.
   - Usual meal times (breakfast, lunch, dinner) and how long they take —
     defines the meal windows the planner protects.
   - Sleep: target hours, fixed wake-up or flexible — the planner computes a
     sleep window itself, but needs a target and any hard constraint.
   - When does their planable day start and end (earliest time blocks may be
     scheduled, latest time the day winds down)? Defaults to 06:00-23:00 —
     this bounds every block the planner ever places.
   - Regular activities (gym, sports, study, hobbies) and how often per week
     — sets `gym_per_week` and any custom categories.
   - Commute: typical destinations and travel minutes (for
     `transport_routes`) — lets the planner insert transport blocks around
     fixed events automatically.
   - Do they have a Garmin watch? If YES: tell them to run
     `uv run dayoptimizer garmin login` in a separate terminal — NEVER ask
     for the password in this conversation, and never put it in chat.
     Garmin is optional; planning works without it, just without
     recovery-aware adjustments.
3. Build a YAML config proposal covering ONLY: `categories` (their personal
   categories with movable/priority; base categories already exist),
   `day_rules` overrides they mentioned (including `day_start`/`day_end` if
   they gave a planning window other than the default, and `work_days` if
   other than Mon-Fri), `transport_routes`, and top-level `holiday_calendars`
   if they named a holidays calendar.
4. Show the YAML to the user and ask for approval before saving anything.
5. On approval, call the `save_config` MCP tool with the YAML — this is the
   only path that writes `config.local.yaml`; never write the file directly.
   If it returns a validation error, fix the YAML and retry (max 3 attempts,
   then show the error).
6. Close with an interactive checklist — walk through it with the user
   turn by turn, not as a one-shot dump of reminders:
   - Missing calendars from step 1: have they been created now? If not,
     ask if they want to do it now before finishing.
   - Has `scripts/setup-bundle.sh` been run (needed for calendar
     read/write access)? If unsure, ask them to run it in a separate
     terminal and confirm before moving on.
   - Do they want the background agent installed
     (`uv run dayoptimizer agent install`) so plans stay fresh
     automatically? If yes, tell them to run it and confirm it succeeded
     (`uv run dayoptimizer agent status`).
   Only consider onboarding complete once all three are resolved (created,
   confirmed skipped, or confirmed already done).
