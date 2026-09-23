from __future__ import annotations
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from dayoptimizer.core.models import Activity, Event, GarminSummary, PlannedChange

_SCHEMA = """
CREATE TABLE IF NOT EXISTS garmin_daily (date TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events_cache (id TEXT PRIMARY KEY, data TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS changes_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, description TEXT NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activities (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, data TEXT NOT NULL
);
"""


def _event_from_json(payload: dict) -> Event:
    payload = dict(payload)
    payload["start"] = datetime.fromisoformat(payload["start"])
    payload["end"] = datetime.fromisoformat(payload["end"])
    return Event(**payload)

class Storage:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)

    def save_garmin(self, summary: GarminSummary) -> None:
        self._conn.execute(
            "INSERT INTO garmin_daily(date, data) VALUES(?, ?) "
            "ON CONFLICT(date) DO UPDATE SET data=excluded.data",
            (summary.date, json.dumps(asdict(summary))),
        )
        self._conn.commit()

    def get_garmin(self, date: str) -> GarminSummary | None:
        row = self._conn.execute("SELECT data FROM garmin_daily WHERE date=?", (date,)).fetchone()
        return GarminSummary(**json.loads(row[0])) if row else None

    def garmin_history(self, days: int) -> list[GarminSummary]:
        rows = self._conn.execute(
            "SELECT data FROM garmin_daily ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [GarminSummary(**json.loads(r[0])) for r in rows]

    def sync_events(self, events: list[Event], window_start: datetime | None = None,
                    window_end: datetime | None = None) -> list[Event]:
        """Upserts the calendar snapshot into the cache and returns events new
        or rescheduled since last sync. "Rescheduled" means start or end
        differs from the cached value — title/location-only edits don't
        count, since callers use this to detect events that need replanning
        around, not cosmetic edits."""
        rows = self._conn.execute("SELECT id, data FROM events_cache").fetchall()
        cached = {rid: json.loads(data) for rid, data in rows}
        now = datetime.now().astimezone().isoformat()
        changed_events = []
        for e in events:
            prior = cached.get(e.id)
            if (prior is None or prior["start"] != e.start.isoformat()
                    or prior["end"] != e.end.isoformat()):
                changed_events.append(e)
            payload = {**asdict(e), "start": e.start.isoformat(), "end": e.end.isoformat()}
            self._conn.execute(
                "INSERT INTO events_cache(id, data, last_seen) VALUES(?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, last_seen=excluded.last_seen",
                (e.id, json.dumps(payload), now),
            )
        if window_start is not None and window_end is not None:
            # `events` is the full calendar content of [window_start, window_end):
            # cached events starting in that window but absent from the sync were
            # deleted/cancelled — drop them so reads don't serve ghosts
            synced_ids = {e.id for e in events}
            ghosts = [
                rid for rid, data in cached.items()
                if rid not in synced_ids
                and window_start <= datetime.fromisoformat(data["start"]) < window_end
            ]
            if ghosts:
                self._conn.execute(
                    f"DELETE FROM events_cache WHERE id IN ({','.join('?' * len(ghosts))})", ghosts)
        self._conn.commit()
        return changed_events

    def last_synced(self, date_iso: str) -> str | None:
        """Most recent last_seen among cached events starting on the given date."""
        rows = self._conn.execute("SELECT data, last_seen FROM events_cache").fetchall()
        stamps = [seen for data, seen in rows
                  if datetime.fromisoformat(json.loads(data)["start"]).date().isoformat() == date_iso]
        return max(stamps) if stamps else None

    def log_change(self, description: str, reason: str) -> None:
        self._conn.execute(
            "INSERT INTO changes_log(ts, description, reason) VALUES(?, ?, ?)",
            (datetime.now().astimezone().isoformat(), description, reason),
        )
        self._conn.commit()

    def recent_changes(self, limit: int = 20) -> list[tuple[str, str, str]]:
        return self._conn.execute(
            "SELECT ts, description, reason FROM changes_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO app_state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self._conn.commit()

    def known_calendars(self) -> list[str]:
        """Distinct calendar names seen across all cached events, sorted —
        used to ground the onboarding interview and the list_calendars MCP
        tool in what's actually in the user's Apple Calendar."""
        rows = self._conn.execute("SELECT data FROM events_cache").fetchall()
        return sorted({json.loads(data)["calendar"] for (data,) in rows})

    def events_on(self, date_iso: str) -> list[Event]:
        rows = self._conn.execute("SELECT data FROM events_cache").fetchall()
        events = [_event_from_json(json.loads(r[0])) for r in rows]
        todays = [e for e in events if e.start.date().isoformat() == date_iso]
        return sorted(todays, key=lambda e: e.start)

    def save_activities(self, activities: list) -> None:
        for a in activities:
            payload = {**asdict(a), "start": a.start.isoformat(), "end": a.end.isoformat()}
            self._conn.execute(
                "INSERT INTO activities(id, data) VALUES(?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data", (a.id, json.dumps(payload)))
        self._conn.commit()

    def activities_since(self, start: datetime) -> list[Activity]:
        rows = self._conn.execute("SELECT data FROM activities").fetchall()
        out = []
        for (data,) in rows:
            d = json.loads(data)
            act = Activity(**{**d, "start": datetime.fromisoformat(d["start"]),
                              "end": datetime.fromisoformat(d["end"])})
            if act.start >= start:
                out.append(act)
        return sorted(out, key=lambda a: a.start)

    def events_between(self, start: datetime, end: datetime) -> list[Event]:
        """Cached events overlapping [start, end), sorted by start."""
        rows = self._conn.execute("SELECT data FROM events_cache").fetchall()
        events = [_event_from_json(json.loads(r[0])) for r in rows]
        return sorted((e for e in events if e.start < end and e.end > start), key=lambda e: e.start)

    def save_pending(self, change: PlannedChange) -> int:
        payload = asdict(change)
        for k in ("new_start", "new_end"):
            if payload[k] is not None:
                payload[k] = payload[k].isoformat()
        if change.event_id is not None:
            # replans re-propose the same unresolved conflict — replace the
            # previous proposal for this event instead of accumulating rows
            self._conn.execute(
                "DELETE FROM pending_changes WHERE json_extract(data, '$.event_id') = ? "
                "AND json_extract(data, '$.kind') = ?",
                (change.event_id, change.kind))
        cur = self._conn.execute(
            "INSERT INTO pending_changes(ts, data) VALUES(?, ?)",
            (datetime.now().astimezone().isoformat(), json.dumps(payload)))
        self._conn.commit()
        return cur.lastrowid

    def get_pending(self, ids: list[int] | None = None) -> list[tuple[int, PlannedChange]]:
        if ids is not None and not ids:
            return []  # an empty selection is NOT "all" — that would bypass the approval gate
        if ids is not None:
            q = f"SELECT id, data FROM pending_changes WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id"
            rows = self._conn.execute(q, ids).fetchall()
        else:
            rows = self._conn.execute("SELECT id, data FROM pending_changes ORDER BY id").fetchall()
        out = []
        for pid, data in rows:
            payload = json.loads(data)
            for k in ("new_start", "new_end"):
                if payload[k] is not None:
                    payload[k] = datetime.fromisoformat(payload[k])
            out.append((pid, PlannedChange(**payload)))
        return out

    def delete_pending(self, ids: list[int]) -> None:
        if not ids:
            return
        self._conn.execute(
            f"DELETE FROM pending_changes WHERE id IN ({','.join('?' * len(ids))})", ids)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
