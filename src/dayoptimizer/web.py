"""Local web planner: serves the built single-page app (web_static/) and a small
JSON API over the user's config.local.yaml. Binds to 127.0.0.1 only.

API
  GET /api/state  -> {categories, typical_week, defaults, day_start, day_end}
  PUT /api/state  <- {categories, typical_week}  (validated, then saved)
  POST /api/import <- {week_start}  -> {typical_week}  (calendar week as blocks, not saved)
"""
from __future__ import annotations
import json
import webbrowser
from datetime import date, datetime, time, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import yaml
from dayoptimizer import paths
from dayoptimizer.core.models import Event
from dayoptimizer.core.rules import load_config_data
from dayoptimizer.core.storage import Storage
from dayoptimizer.onboarding import ConfigError, save_user_config

STATIC_DIR = Path(__file__).parent / "web_static"
DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config.default.yaml"
MAX_BODY = 256 * 1024


def _defaults() -> dict:
    return yaml.safe_load(DEFAULT_CONFIG.read_text())


def _local() -> dict:
    p = paths.user_config_path()
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def read_state() -> dict:
    merged = load_config_data(DEFAULT_CONFIG)
    rules = merged.get("day_rules", {})
    return {
        "categories": merged["categories"],
        "typical_week": _local().get("typical_week") or {},
        "defaults": list(_defaults()["categories"]),
        "day_start": rules.get("day_start", "06:00"),
        "day_end": rules.get("day_end", "23:00"),
    }


def write_state(payload: object) -> dict:
    """Store only the delta against config.default.yaml, keep every other key
    of config.local.yaml untouched. Raises ConfigError on bad input."""
    if not isinstance(payload, dict):
        raise ConfigError("Body must be a JSON object.")
    categories = payload.get("categories")
    week = payload.get("typical_week") or {}
    if not isinstance(categories, dict) or not isinstance(week, dict):
        raise ConfigError("categories and typical_week must be objects.")
    for day, blocks in week.items():
        for block in blocks if isinstance(blocks, list) else []:
            if isinstance(block, dict) and block.get("category") not in categories:
                raise ConfigError(f"{day}: unknown category {block.get('category')!r}.")

    default_cats = _defaults()["categories"]
    delta: dict = {name: None for name in default_cats if name not in categories}
    delta.update({name: cfg for name, cfg in categories.items() if default_cats.get(name) != cfg})

    local = _local()
    local.pop("categories", None)
    local.pop("typical_week", None)
    if delta:
        local["categories"] = delta
    week = {day: blocks for day, blocks in week.items() if blocks}
    if week:
        local["typical_week"] = week
    save_user_config(yaml.safe_dump(local, sort_keys=False, allow_unicode=True))
    return read_state()


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MIN_BLOCK = timedelta(minutes=5)


def events_to_week(events: list[Event], week_start: date) -> dict[str, list[dict]]:
    """Turn a week of calendar events into typical-week blocks: one block per
    event per day it touches (overnight events are split at midnight), the
    calendar name as category. All-day markers carry no time, so they're skipped."""
    week: dict[str, list[dict]] = {d: [] for d in WEEKDAYS}
    for i in range(7):
        day = week_start + timedelta(days=i)
        d0 = datetime.combine(day, time()).astimezone()
        d1 = datetime.combine(day + timedelta(days=1), time()).astimezone()
        for e in events:
            if e.all_day:
                continue
            s, t = max(e.start, d0).astimezone(), min(e.end, d1).astimezone()
            if t - s < MIN_BLOCK:
                continue
            week[WEEKDAYS[day.weekday()]].append({
                "start": f"{s:%H:%M}",
                "end": "24:00" if t >= d1 else f"{t:%H:%M}",
                "category": e.calendar[:40] or "Imported",
                "title": e.title[:60],
            })
    return week


def import_week(payload: object) -> dict:
    """Read one calendar week through the TCC app bundle (this process must not
    touch EventKit) and return it as blocks. Nothing is saved here."""
    try:
        week_start = date.fromisoformat(payload["week_start"])  # type: ignore[index]
    except (TypeError, KeyError, ValueError):
        raise ConfigError("week_start must be a YYYY-MM-DD date.")
    from dayoptimizer.mcp_server import _bundle_run
    out = _bundle_run(["sync", "--from", week_start.isoformat(), "--days", "7"])
    if "SYNCED" not in out:
        raise ImportFailed(out.strip()[-400:] or "Calendar read failed.")
    start = datetime.combine(week_start, time()).astimezone()
    storage = Storage(paths.db_path())
    try:
        events = storage.events_between(start, start + timedelta(days=7))
    finally:
        storage.close()
    return {"typical_week": events_to_week(events, week_start)}


class ImportFailed(RuntimeError):
    pass


class Handler(SimpleHTTPRequestHandler):
    server_version = "DayOptimizer"

    def _host_ok(self) -> bool:
        # DNS-rebinding guard: only our own loopback names are accepted
        port = self.server.server_address[1]
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _json(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        if self.path.split("?")[0] == "/api/state":
            try:
                return self._json(200, read_state())
            except (OSError, yaml.YAMLError) as exc:
                return self._json(500, {"error": f"Could not read config: {exc}"})
        if self.path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        if not (STATIC_DIR / self.path.split("?")[0].lstrip("/")).is_file():
            self.path = "/index.html"  # SPA fallback
        return super().do_GET()

    def _write(self, action) -> None:
        origin = self.headers.get("Origin")
        # CSRF guard: JSON-only (forces a CORS preflight we never answer) and same origin
        if (not self._host_ok()
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                or (origin is not None and origin != f"http://{self.headers.get('Host')}")):
            return self._json(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            return self._json(413, {"error": "body too large or empty"})
        try:
            return self._json(200, action(json.loads(self.rfile.read(length))))
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON"})
        except ConfigError as exc:
            return self._json(422, {"error": str(exc)})
        except ImportFailed as exc:
            return self._json(502, {"error": str(exc)})

    def do_PUT(self):
        if self.path != "/api/state":
            return self._json(404, {"error": "not found"})
        return self._write(write_state)

    def do_POST(self):
        if self.path != "/api/import":
            return self._json(404, {"error": "not found"})
        return self._write(import_week)

    def log_message(self, format, *args):
        pass  # keep the terminal quiet


def make_server(port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(STATIC_DIR)))


def serve(port: int = 8765, open_browser: bool = True) -> None:
    if not (STATIC_DIR / "index.html").exists():
        raise SystemExit("Web planner is not built — run `npm run build` in web/.")
    server = make_server(port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"DayOptimizer planner running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
