"""Score the task scenarios in evals/tasks against a real model.

    uv run python scripts/eval_tasks.py --backend ollama --few-shot off
    uv run python scripts/eval_tasks.py --backend anthropic --only overdue

A scenario passes when its tasks are placed or reported as expected (the
outcome); it is "clean" when, on top of that, the validator had to drop none
of the model's blocks. Soft misses (order, block length) are printed only.
Run it with --few-shot off and on to see what the worked examples add."""
from __future__ import annotations
import argparse
import time
from datetime import date, datetime
from pathlib import Path
import yaml
from dayoptimizer.core.constraints import parse_rules, skippable
from dayoptimizer.core.models import Event, Task
from dayoptimizer.core.rules import CategoryRule, _parse_typical_week
from dayoptimizer.llm import week_plan
from dayoptimizer.llm.task_rules import minutes
from dayoptimizer.llm.week_plan import plan_days, routine_spans
from dayoptimizer.routine import render_routine

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "evals" / "tasks"
DAYS = ROOT / "evals" / "days.yaml"
CATEGORIES = ["Sleep", "Food", "Work", "Learn", "Home"]


def _dt(text) -> datetime:
    return datetime.strptime(str(text), "%Y-%m-%d %H:%M").astimezone()


def load(path: Path, s: dict | None = None) -> dict:
    s = s if s is not None else yaml.safe_load(path.read_text())
    s.setdefault("name", path.stem)
    s["now"] = _dt(s["now"])
    s["days"] = [date.fromisoformat(str(d)) for d in s["days"]]
    s.setdefault("categories", CATEGORIES)
    if s.get("routine", "default") == "default":
        s["routine"] = (SCENARIOS / "_routine.md").read_text()
    s["notes"] = s.get("notes") or ""
    s["expect"] = s.get("expect") or {}
    s["events"] = [Event(id=e.get("id", f"e{i}"), calendar=e["calendar"], title=e["title"],
                         start=_dt(f"{e['day']} {e['start']}"), end=_dt(f"{e['day']} {e['end']}"),
                         managed=e.get("managed", False), task_id=e.get("task_id"))
                   for i, e in enumerate(s.get("events") or [], 1)]
    s["tasks"] = [Task(id=t["id"], title=t["title"], category=t["category"], duration_min=t["duration_min"],
                       due=_dt(t["due"]) if t.get("due") else None,
                       not_before=_dt(t["not_before"]) if t.get("not_before") else None,
                       min_chunk_min=t.get("min_chunk_min"), priority=t.get("priority", "normal"))
                  for t in s.get("tasks") or []]
    return s


def load_days(path: Path = DAYS) -> list[dict]:
    """The whole-day set: one file, a drawn routine and compiled notes shared
    by every scenario, planned the way the cli plans (routine spans, rules)."""
    data = yaml.safe_load(path.read_text())
    week = _parse_typical_week(data["typical_week"])
    cats = {k: CategoryRule(movable=v["movable"], priority=v["priority"]) for k, v in data["categories"].items()}
    routine = render_routine(data["categories"], data["typical_week"], data["notes"])
    out = []
    for raw in data["scenarios"]:
        s = load(path, dict(raw, routine=routine, categories=list(cats)))
        s["notes"], s["rules"] = data["notes"], parse_rules(data["rules"])
        s["routine_days"], s["reserved"] = routine_spans(week, cats, s["days"])
        out.append(s)
    return out


def measure(s: dict, changes) -> dict:
    """What the rules forbid (code enforces it, so this should stay 0), who
    placed the task blocks, and routine blocks the day ended up without."""
    creates = [c for c in changes if c.kind == "create"]
    now, rules = s["now"], s.get("rules", [])
    blocking = [e for e in s["events"] if not e.all_day and (not e.managed or e.start < now)
                and not skippable(rules, e)]
    bad = sum(1 for c in creates for e in blocking if e.start < c.new_end and e.end > c.new_start)
    bad += sum(1 for c in creates if c.task_id for x in (s.get("reserved") or {}).get(c.new_start.date(), [])
               if x[0] < c.new_end and x[1] > c.new_start and x[3] != c.category)
    have = {(c.new_start.date(), c.category, c.title) for c in creates} | {
        (e.start.date(), e.calendar, e.title) for e in s["events"] if e.managed}
    lost = sum(1 for d, spans in (s.get("routine_days") or {}).items() for x in spans
               if x[0] >= now and (d, x[2], x[3]) not in have)
    tasks = [c for c in creates if c.task_id]
    code = sum(1 for c in tasks if c.reason == "placed by code")
    return {"violations": bad, "routine_lost": lost, "by_model": len(tasks) - code, "by_code": code}


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


def outcome_ok(fails: list[str]) -> bool:
    """Tasks placed or reported as expected; blocks the validator dropped
    don't reach the calendar, so they don't spoil the outcome."""
    return not [f for f in fails if not f.startswith(("soft:", "rule:"))]


def clean(fails: list[str]) -> bool:
    """The outcome, and the model's answer needed no block dropped."""
    return outcome_ok(fails) and not [f for f in fails if f.startswith("rule:")]


class Rounds:
    """Stands in for week_plan.validate and records the problems of each round."""

    def __init__(self):
        self.errors: list[int] = []
        self.inner = week_plan.validate

    def __call__(self, *a, **k):
        creates, problems = self.inner(*a, **k)
        self.errors.append(len(problems))
        return creates, problems

def _backend(name: str, model: str | None, mode: str = "layout"):
    if mode == "code":
        return week_plan._ByRule()  # no model at all: the floor a model has to beat
    if name == "ollama":
        from dayoptimizer.llm.ollama_backend import OllamaBackend
        return OllamaBackend(model=model or "qwen3:8b", mode=mode)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from dayoptimizer.llm.anthropic_backend import AnthropicBackend
    return AnthropicBackend(model=model or "claude-sonnet-5-5")



def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Score the task scenarios against a model.")
    p.add_argument("--backend", choices=["ollama", "anthropic"], required=True)
    p.add_argument("--set", choices=["tasks", "days"], default="tasks", help="evals/tasks/*.yaml or evals/days.yaml")
    p.add_argument("--mode", choices=["layout", "slots", "code"], default="layout",
                   help="Ollama lays out the day or picks among code's slots; code = no model at all")
    p.add_argument("--few-shot", choices=["on", "off"], default="on")
    p.add_argument("--only", default=None, help="run these scenarios (names, comma-separated)")
    p.add_argument("--model", default=None)
    p.add_argument("--repeat", type=int, default=1, help="run each scenario N times (a local model varies)")
    a = p.parse_args(argv)
    backend = _backend(a.backend, a.model, a.mode)
    scenarios = load_days() if a.set == "days" else [load(x) for x in sorted(SCENARIOS.glob("*.yaml"))]
    scenarios = [s for s in scenarios if a.only is None or s["name"] in a.only.split(",")]
    passed = tidy = runs = 0
    total: dict[str, int] = {}
    for s in scenarios:
        for _ in range(a.repeat):
            rounds = week_plan.validate = Rounds()
            runs += 1
            began = time.monotonic()
            try:
                changes, _, problems, unscheduled = plan_days(
                    backend, s["days"], s["routine"], s["categories"], s["events"], s["notes"],
                    s.get("rules", []), s["now"], history={},
                    expect={d for d, v in (s.get("routine_days") or {}).items() if v},
                    tasks=s["tasks"], left={t.id: t.duration_min for t in s["tasks"]},
                    few_shot=a.few_shot == "on", reserved=s.get("reserved"), routine_days=s.get("routine_days"))
            except Exception as exc:
                print(f"ERROR {s['name']}: {' '.join(str(exc).split())[:200]}")
                continue
            finally:
                week_plan.validate = rounds.inner
            fails = score(s, changes, problems, unscheduled)
            m = measure(s, changes) | {"seconds": round(time.monotonic() - began), "rounds": len(rounds.errors),
                                       "errors": sum(rounds.errors), "dropped": len(problems),
                                       "prompt_tokens": getattr(backend, "prompt_tokens", None) or 0}
            for k, v in m.items():
                total[k] = max(total.get(k, 0), v) if k == "prompt_tokens" else total.get(k, 0) + v
            passed += outcome_ok(fails)
            tidy += clean(fails)
            mark = "PASS" if outcome_ok(fails) else "FAIL"
            print(f"{mark}{' clean' if clean(fails) else ''} {s['name']} errors/round={rounds.errors} "
                  + " ".join(f"{k}={v}" for k, v in m.items()), flush=True)
            for f in fails:
                print(f"    {f}")
    print(f"\n{passed}/{runs} outcome correct, {tidy}/{runs} clean  backend={a.backend} mode={a.mode} "
          f"few-shot={a.few_shot}\ntotals: " + " ".join(f"{k}={v}" for k, v in total.items())
          + " (prompt_tokens: the largest last-request prompt of a run)")
    return 0 if passed == runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
