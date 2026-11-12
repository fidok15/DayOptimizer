"""Score what DayOptimizer understands from a message against evals/ask.yaml.

    uv run python scripts/eval_ask.py --backend ollama
    uv run python scripts/eval_ask.py --backend ollama --only next-week --lang pl --repeat 3

Each case runs in Polish and in English through the same path as
`dayoptimizer "<message>"` (parse_request, pin_day, events_to_create, the
task checks, the routine blocks left out), with the eval's routine instead of
the user's and nothing saved or written to a calendar."""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_tasks import _backend

from dayoptimizer import cli, routine
from dayoptimizer.core.rules import CategoryRule, _parse_typical_week, load_rules
from dayoptimizer.llm.backend import pin_day
from dayoptimizer.llm.task_request import skipped_routine

CASES = ROOT / "evals" / "ask.yaml"
DAYS = ROOT / "evals" / "days.yaml"


class _NoStorage:
    """No calendar cache and no open tasks: every task in the message is new."""

    def events_on(self, day):
        return []

    def open_tasks(self):
        return []

    def next_task_id(self):
        return "t1"

    def mark_task_done(self, task_id):
        pass


def setup() -> tuple[dict, object, datetime]:
    data, days = yaml.safe_load(CASES.read_text()), yaml.safe_load(DAYS.read_text())
    cats = dict(days["categories"]) | {c: {"movable": True, "priority": 5} for c in data.get("extra_categories", [])}
    rules = replace(load_rules(ROOT / "tests" / "fixtures" / "config.yaml", ROOT / "no-such-config.yaml"),
                    categories={k: CategoryRule(movable=v["movable"], priority=v["priority"]) for k, v in cats.items()},
                    typical_week=_parse_typical_week(days["typical_week"]))
    text = routine.render_routine(cats, days["typical_week"], days["notes"])
    routine.load_routine = lambda: text  # the eval's routine, never the user's
    return data, rules, datetime.strptime(data["now"], "%Y-%m-%d %H:%M").astimezone()


def understand(backend, text: str, rules, now: datetime):
    """(events as (category, title, start, end), tasks, skipped {day: [labels]}, what was printed)."""
    req = backend.parse_request(text, today=now.date().isoformat(), now=f"{now:%A %Y-%m-%d %H:%M}",
                                categories=list(rules.categories))
    req = pin_day(text, req, now)
    timed = req.model_copy(update={"events": [e for e in req.events if e.start_time and cli._HHMM.match(e.start_time)]})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        events, problems = cli.events_to_create(timed, rules.categories, now.date())
        tasks = [t for t, _ in cli._new_tasks(text, req, rules, _NoStorage(), now, events)]
    skipped = skipped_routine(text, rules.typical_week, [now.date() + timedelta(days=i) for i in range(14)], now.date())
    return events, tasks, skipped, " | ".join([*problems, *out.getvalue().split("\n")]).strip(" |")


def _named(title: str, stems: list[str]) -> bool:
    return any(s in title.lower() for s in stems)


def _one_of(got: str, want) -> bool:
    return got in (want if isinstance(want, list) else [want])


def _when(value, got: datetime | None) -> str | None:
    """Why `got` is not the expected day or time, or None."""
    if value is None:
        return None if got is None else f"none expected, got {got:%a %d.%m %H:%M}"
    if got is None:
        return f"expected {value}, got none"
    value = str(value)
    ok = got.strftime("%Y-%m-%d %H:%M") == value if " " in value else got.date() == date.fromisoformat(value)
    return None if ok else f"expected {value}, got {got:%Y-%m-%d %H:%M}"


def score(case: dict, events, tasks, skipped) -> list[str]:
    fails = []
    left = list(events)
    for exp in case.get("events") or []:
        hit = next((e for e in left if _named(e[1], exp["title"])), None)
        if hit is None:
            fails.append(f"event {exp['title'][0]}: missing")
            continue
        left.remove(hit)
        cat, title, start, end = hit
        if str(exp["day"]) != start.date().isoformat():
            fails.append(f"event '{title}': day {start.date()} not {exp['day']}")
        if start.strftime("%H:%M") != exp["start"]:
            fails.append(f"event '{title}': start {start:%H:%M} not {exp['start']}")
        if exp.get("end") and end.strftime("%H:%M") != exp["end"]:
            fails.append(f"event '{title}': end {end:%H:%M} not {exp['end']}")
        if exp.get("category") and not _one_of(cat, exp["category"]):
            fails.append(f"event '{title}': category {cat} not {exp['category']}")
    fails += [f"extra event '{t}' {s:%a %d.%m %H:%M}" for _, t, s, _ in left]
    left = list(tasks)
    for exp in case.get("tasks") or []:
        hit = next((t for t in left if _named(t.title, exp["title"])), None)
        if hit is None:
            fails.append(f"task {exp['title'][0]}: missing")
            continue
        left.remove(hit)
        t = f"task '{hit.title}'"
        if "minutes" in exp and hit.duration_min != exp["minutes"]:
            fails.append(f"{t}: {hit.duration_min} min not {exp['minutes']}")
        for key, got in (("due", hit.due), ("not_before", hit.not_before)):
            if key in exp and (why := _when(exp[key], got)):
                fails.append(f"{t}: {key} {why}")
        if exp.get("category") and not _one_of(hit.category, exp["category"]):
            fails.append(f"{t}: category {hit.category} not {exp['category']}")
        if exp.get("priority") and hit.priority != exp["priority"]:
            fails.append(f"{t}: priority {hit.priority} not {exp['priority']}")
        if "chunk" in exp and hit.min_chunk_min != exp["chunk"]:
            fails.append(f"{t}: chunk {hit.min_chunk_min} not {exp['chunk']}")
    fails += [f"extra task '{t.title}'" for t in left]
    want = {date.fromisoformat(str(d)): set(v) for d, v in (case.get("skip") or {}).items()}
    got = {d: set(v) for d, v in skipped.items()}
    if want != got:
        fails.append(f"skip {({str(d): sorted(v) for d, v in got.items()})} not "
                     f"{({str(d): sorted(v) for d, v in want.items()})}")
    return fails


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Score message understanding against a model.")
    p.add_argument("--backend", choices=["ollama", "anthropic"], required=True)
    p.add_argument("--model", default=None)
    p.add_argument("--only", default=None, help="these cases (names, comma-separated)")
    p.add_argument("--lang", choices=["pl", "en", "both"], default="both")
    p.add_argument("--repeat", type=int, default=1)
    a = p.parse_args(argv)
    data, rules, now = setup()
    if a.repeat < 1 or not [c for c in data["cases"] if not a.only or c["name"] in a.only.split(",")]:
        p.error("nothing to run: --repeat must be 1 or more and --only must name a case")
    backend = _backend(a.backend, a.model)
    langs = ["pl", "en"] if a.lang == "both" else [a.lang]
    runs = passed = 0
    for case in data["cases"]:
        if a.only and case["name"] not in a.only.split(","):
            continue
        for lang in langs:
            for _ in range(a.repeat):
                runs += 1
                began = time.monotonic()
                try:
                    events, tasks, skipped, said = understand(backend, case[lang], rules, now)
                except Exception as exc:
                    print(f"ERROR {case['name']} [{lang}]: {type(exc).__name__}: {' '.join(str(exc).split())[:200]}")
                    continue
                fails = score(case, events, tasks, skipped)
                passed += not fails
                print(f"{'PASS' if not fails else 'FAIL'} {case['name']} [{lang}] "
                      f"{round(time.monotonic() - began)}s  {case[lang]!r}", flush=True)
                for f in fails:
                    print(f"    {f}")
                if fails and said:
                    print(f"    said: {said[:300]}")
    print(f"\n{passed}/{runs} understood  backend={a.backend}")
    return 0 if passed == runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
