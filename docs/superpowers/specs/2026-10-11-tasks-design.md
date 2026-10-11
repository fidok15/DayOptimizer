# Tasks: auto-placed work with deadlines

Date: 2026-10-11. Status: approved in chat, awaiting spec review.

## Goal

Next to the routine, the user can add tasks: a piece of work with a length and
usually a deadline ("report for Friday, 3h, in chunks of at least 1h"). The
language model places them into free time before the deadline, and they move
when the calendar changes. Tasks are new; they do not replace the routine.

Success: a task added from the terminal lands in the calendar before its
deadline, never overlaps events or routine blocks, and is re-placed on the
next replan.

The idea follows the task model of auto-schedulers such as FlowSavvy
(duration, deadline, start-no-earlier-than, priority, minimum chunk length).
Only the field set is borrowed; no code.

## Decisions

- **The language model places tasks** (architecture decision 2026-10-07, "the
  model plans, code checks"). No separate greedy scheduler.
- **First step is prompting, not fine-tuning:** better instructions plus
  few-shot examples, measured by an eval set. Fine-tuning (SFT, then RL with the
  validator as reward) is a later, separate decision, made only if the evals
  show the prompt is not enough.
- **Garmin does not influence task placement.**
- **Tasks are added from the CLI** (natural language, parsed by the model).

## Out of scope (v1)

Dependencies between tasks, buffers before/after, repeating tasks, web
planner UI, Apple Reminders sync. Each can be added later if evals or use show
the need.

## 1. Model and storage

`core/models.py` gets:

```python
@dataclass
class Task:
    id: str                 # short, e.g. "t7"
    title: str
    category: str           # one of the user's categories
    duration_min: int
    due: datetime | None = None
    not_before: datetime | None = None
    min_chunk_min: int | None = None   # None = do not split
    priority: Literal["low", "normal", "high"] = "normal"
    done: bool = False
```

SQLite gets a `tasks` table (id primary key, JSON data, like the other
tables) with `save_task`, `get_task`, `open_tasks`, `mark_task_done`.

Task blocks in the calendar are ordinary planner blocks (they carry the
`Planned by DayOptimizer` marker) plus a `Task: <id>` line in the event notes,
so the existing delete and diff rules keep working. `PlannedChange` gets an
optional `task_id`, written into the notes when the event is created.

**Remaining minutes** of a task = `duration_min` minus the minutes of its
blocks that already ended. A past block counts as done. `task done <id>`
closes a task early; a done task is no longer planned and its future blocks are
removed on the next replan.

## 2. CLI

- `dayoptimizer task "<description>"`: the model parses the text into a
  `TaskRequest` (JSON schema, same mechanism as `parse_request`): title,
  category (enum of the user's categories), duration, due, not before, minimum
  chunk, priority. The task is saved, shown back, and the days from today to the
  deadline (at most 7) are replanned.
- `dayoptimizer task list`: open tasks with remaining minutes and deadline.
- `dayoptimizer task done <id>`.

`task` joins `CALENDAR_COMMANDS` (it replans, so it needs the TCC bundle).
Without any language model the task is saved and the user is told it will be
placed once a model is available. Replanning with tasks works also when the
user drew no routine.

## 3. Prompt

`build_prompt` gets a `# Tasks` section, one line per open task:

```
- [t7] Raport kwartalny (Work) 120 min left, due Fri 2026-10-16 17:00,
  not before Wed 2026-10-14 09:00, chunks >= 60 min, priority high
```

Output schema:

- `Block.task_id: str | None` - set on blocks that work on a task.
- `WeekPlan.unscheduled: list[{task_id, reason}]` - tasks (or their rest) the
  model could not fit, with a short reason. Silence is not allowed.

`SYSTEM` gets task rules: place task blocks inside the task's window
(not_before..due), in gaps the routine and events leave free, never displacing
routine blocks or events; chunks no shorter than the minimum (only the last
remainder may be shorter); no more minutes than remain; higher priority and
nearer deadlines first; spread long tasks over days rather than one marathon;
task block category = task category; title = task title.

**Few-shot:** three short worked examples appended to `SYSTEM`, each a compact
input excerpt and the exact JSON it should produce:

1. One task split into two gaps before its deadline.
2. A task that cannot fit before its deadline goes to `unscheduled` with a
   reason; nothing is invented.
3. Two tasks, high priority placed earlier than normal.

A module constant switches the examples off (`few_shot=False`) so evals can
compare with and without.

**Day by day (Ollama):** a small model plans one day per request. Remaining
minutes are carried from day to day: what the model placed on Monday is
subtracted before Tuesday's request, like the weekly-limit history today. On
the last planned day before a deadline, a task with minutes left and no
`unscheduled` entry is a problem.

## 4. Validator

`validate` checks every block with `task_id`:

- the task exists and is open; block category equals the task category;
- block lies inside `not_before`..`due`;
- block length >= `min_chunk_min`, unless it is the final remainder;
- the task's blocks sum to no more than its remaining minutes.

And after all blocks: an open task whose window ends inside the planned days,
with minutes left, that is neither placed in full nor listed in `unscheduled`
is a problem ("t7: 60 min left before Fri 17:00 - place it or list it in
unscheduled").

Problems go back to the model like today (max 3 rounds); invalid blocks are
dropped, not written.

## 5. Tests and evals

**Unit tests (pytest, fake backend):** each new validator rule, remaining
minutes from past blocks, carry-over between days, `TaskRequest` parsing into
`Task`, storage round trip, `task` CLI commands, `task_id` written to event
notes.

**Eval set:** `evals/tasks/*.yaml`, about 10 scenarios to start. Each has:
now, days to plan, categories, routine (as text), notes, events, tasks, and
expectations:

- hard: zero validator problems after the last round; every task that has
  room is fully placed before its deadline; a task without room is in
  `unscheduled`;
- soft: high priority placed before normal; no single task block longer than
  3 h when the task allows chunks.

`scripts/eval_tasks.py --backend ollama|anthropic --few-shot on|off
[--only NAME]` runs every scenario through `plan_days`, prints per scenario
pass/fail, rounds used and broken rules, and a total pass rate. It needs a live
model, so it is not part of pytest. The first run records the baseline
(few-shot off) for comparison.

## Error handling

- Parser returns no usable duration: ask for it in the reply, save nothing.
- Category not among the user's: rejected by the schema enum.
- Deadline in the past: saved, reported as overdue. Its window becomes
  now..end of the planned days (the deadline check is skipped), and the prompt
  marks it `OVERDUE` so the model places it first.
- No model available: task saved, user told it will be placed later.
