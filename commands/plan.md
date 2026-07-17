---
description: Plan a day (or several) — DayOptimizer reshuffles flexible blocks around fixed events
argument-hint: [date or "week"]
---

Plan the user's schedule with the `plan` MCP tool.

- Parse $ARGUMENTS: a date (YYYY-MM-DD or a natural phrase like "tomorrow" —
  convert it), or "week" (= 7 days starting today). Default: today, 1 day.
  Dates passed to tools must always be ISO YYYY-MM-DD.
- Call `plan(date, days)`. Present the returned changes grouped by day, each
  with its reason, in plain language.
- If `plan` returns a validation error string ("Invalid date…", "days must
  be…"), fix the arguments and retry once instead of showing the raw error.
- If any changes are marked pending approval (fixed events), list them clearly
  with their ids and ask the user which to approve. Call `apply_changes(ids)`
  ONLY for ids the user explicitly approved.
- If the tool reports missing calendar access or a missing bundle, walk the
  user through `scripts/setup-bundle.sh` and the macOS permission prompt.
