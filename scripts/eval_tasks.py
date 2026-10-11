"""Score the task scenarios in evals/tasks against a real model.

    uv run python scripts/eval_tasks.py --backend ollama --few-shot off
    uv run python scripts/eval_tasks.py --backend anthropic --only overdue

Hard failures (a broken rule, a task not placed or not reported) fail the
scenario; soft ones (order, block length) are printed but don't. Run it with
--few-shot off and on to see what the worked examples add."""
from __future__ import annotations
import argparse
from datetime import date, datetime
from pathlib import Path
import yaml
from dayoptimizer.core.models import Event, Task
from dayoptimizer.llm.task_rules import minutes
from dayoptimizer.llm.week_plan import plan_days

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "evals" / "tasks"
CATEGORIES = ["Sleep", "Food", "Work", "Learn", "Home"]


def _dt(text) -> datetime:
    return datetime.strptime(str(text), "%Y-%m-%d %H:%M").astimezone()


def load(path: Path) -> dict:
    s = yaml.safe_load(path.read_text())
    s["name"] = path.stem
    s["now"] = _dt(s["now"])
    s["days"] = [date.fromisoformat(str(d)) for d in s["days"]]
    s.setdefault("categories", CATEGORIES)
    if s.get("routine", "default") == "default":
        s["routine"] = (SCENARIOS / "_routine.md").read_text()
    s["notes"] = s.get("notes") or ""
    s["expect"] = s.get("expect") or {}
    s["events"] = [Event(id=e["id"], calendar=e["calendar"], title=e["title"],
                         start=_dt(f"{e['day']} {e['start']}"), end=_dt(f"{e['day']} {e['end']}"))
                   for e in s.get("events") or []]
    s["tasks"] = [Task(id=t["id"], title=t["title"], category=t["category"], duration_min=t["duration_min"],
                       due=_dt(t["due"]) if t.get("due") else None,
                       not_before=_dt(t["not_before"]) if t.get("not_before") else None,
                       min_chunk_min=t.get("min_chunk_min"), priority=t.get("priority", "normal"))
                  for t in s.get("tasks") or []]
    return s


def score(s: dict, changes, problems: list[str], unscheduled: list[str]) -> list[str]:
    """What went wrong against the scenario's expectations; empty = pass."""
    fails = [f"rule: {p}" for p in problems]
    placed: dict[str, int] = {}
    first: dict[str, datetime] = {}
    for c in changes:
        if c.kind == "create" and c.task_id:
            placed[c.task_id] = placed.get(c.task_id, 0) + minutes(c.new_start, c.new_end)
            first[c.task_id] = min(first.get(c.task_id, c.new_start), c.new_start)
    tasks = {t.id: t for t in s["tasks"]}
    listed = {u.split(":", 1)[0].strip() for u in unscheduled}
    exp = s["expect"]
    for tid in exp.get("placed", []):
        if placed.get(tid, 0) < tasks[tid].duration_min:
            fails.append(f"{tid}: placed {placed.get(tid, 0)} of {tasks[tid].duration_min} min")
    for tid in exp.get("unscheduled", []):
        if tid not in listed:
            fails.append(f"{tid}: should be listed as unscheduled")
    for a, b in exp.get("before", []):
        if a in first and b in first and first[a] > first[b]:
            fails.append(f"soft: {a} should start before {b}")
    limit = exp.get("max_block_min")
    for c in changes:
        if limit and c.kind == "create" and c.task_id and minutes(c.new_start, c.new_end) > limit:
            fails.append(f"soft: {c.task_id} block {c.new_start:%a %H:%M}-{c.new_end:%H:%M} is over {limit} min")
    return fails


class Counting:
    """Counts the rounds plan_days needed (1 = right the first time)."""

    def __init__(self, inner):
        self.inner, self.rounds = inner, 0
        self.one_day_at_a_time = getattr(inner, "one_day_at_a_time", False)

    def plan_week(self, system, prompt):
        self.rounds += 1
        return self.inner.plan_week(system, prompt)


def _backend(name: str, model: str | None):
    if name == "ollama":
        from dayoptimizer.llm.ollama_backend import OllamaBackend
        return OllamaBackend(model=model or "qwen3:8b")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from dayoptimizer.llm.anthropic_backend import AnthropicBackend
    return AnthropicBackend(model=model or "claude-sonnet-5-5")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Score the task scenarios against a model.")
    p.add_argument("--backend", choices=["ollama", "anthropic"], required=True)
    p.add_argument("--few-shot", choices=["on", "off"], default="on")
    p.add_argument("--only", default=None, help="run one scenario by file name, without .yaml")
    p.add_argument("--model", default=None)
    a = p.parse_args(argv)
    inner = _backend(a.backend, a.model)
    paths = [x for x in sorted(SCENARIOS.glob("*.yaml")) if a.only in (None, x.stem)]
    passed = 0
    for path in paths:
        s = load(path)
        backend = Counting(inner)
        try:
            changes, _, problems, unscheduled = plan_days(
                backend, s["days"], s["routine"], s["categories"], s["events"], s["notes"], [], s["now"],
                tasks=s["tasks"], left={t.id: t.duration_min for t in s["tasks"]}, few_shot=a.few_shot == "on")
        except Exception as exc:
            print(f"ERROR {s['name']}: {' '.join(str(exc).split())[:200]}")
            continue
        fails = score(s, changes, problems, unscheduled)
        hard = [f for f in fails if not f.startswith("soft:")]
        passed += not hard
        print(f"{'PASS' if not hard else 'FAIL'} {s['name']} ({backend.rounds} rounds)")
        for f in fails:
            print(f"    {f}")
    print(f"\n{passed}/{len(paths)} passed  backend={a.backend} few-shot={a.few_shot}")
    return 0 if passed == len(paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())
