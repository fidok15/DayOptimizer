from __future__ import annotations
import time
from datetime import datetime
from dayoptimizer.core.models import Event

def normalize_calendar(title: str) -> str:
    """'🔨 Work ' -> 'Work': calendar names carry emoji prefixes and stray
    spaces in EventKit, while config.yaml categories use plain names."""
    for i, ch in enumerate(title):
        if ch.isalnum():
            return title[i:].strip()
    return title.strip()

def ek_to_event(identifier, calendar_title, title, start, end, location, all_day=False) -> Event:
    return Event(id=identifier, calendar=normalize_calendar(calendar_title), title=title,
                 start=start, end=end, location=location, all_day=all_day)

class CalendarClient:
    def __init__(self):
        import EventKit  # deferred: import only on macOS at runtime
        self._EventKit = EventKit
        self._store = EventKit.EKEventStore.alloc().init()

    def request_access(self) -> bool:
        # Completion handler fires only when the runloop is pumped — a plain
        # threading.Event deadlocks in CLI context and the TCC prompt never shows.
        from Foundation import NSDate, NSRunLoop

        granted_holder = {}

        def handler(granted, error):
            granted_holder["granted"] = bool(granted)

        self._store.requestFullAccessToEventsWithCompletion_(handler)
        runloop = NSRunLoop.currentRunLoop()
        deadline = time.time() + 120
        while "granted" not in granted_holder and time.time() < deadline:
            runloop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
        return granted_holder.get("granted", False)

    def _nsdate(self, dt: datetime):
        from Foundation import NSDate
        return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        pred = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            self._nsdate(start), self._nsdate(end), None)
        ek_events = self._store.eventsMatchingPredicate_(pred) or []
        out = []
        for ev in ek_events:
            out.append(ek_to_event(
                str(ev.eventIdentifier()),
                str(ev.calendar().title()),
                str(ev.title() or ""),
                datetime.fromtimestamp(ev.startDate().timeIntervalSince1970()).astimezone(),
                datetime.fromtimestamp(ev.endDate().timeIntervalSince1970()).astimezone(),
                str(ev.location()) if ev.location() else None,
                bool(ev.isAllDay()),
            ))
        return sorted(out, key=lambda e: e.start)

    def move_event(self, event_id: str, new_start: datetime, new_end: datetime) -> None:
        ev = self._store.eventWithIdentifier_(event_id)
        if ev is None:
            raise KeyError(f"Event {event_id} not found")
        ev.setStartDate_(self._nsdate(new_start))
        ev.setEndDate_(self._nsdate(new_end))
        ok, err = self._store.saveEvent_span_error_(ev, 0, None)  # 0 = EKSpanThisEvent
        if not ok:
            raise RuntimeError(f"Save failed: {err}")

    def create_event(self, calendar_name: str, title: str, start: datetime, end: datetime) -> str:
        EventKit = self._EventKit
        target = None
        for cal in self._store.calendarsForEntityType_(EventKit.EKEntityTypeEvent):
            if normalize_calendar(str(cal.title())) == calendar_name:
                target = cal
                break
        if target is None:
            raise KeyError(f"Calendar '{calendar_name}' not found")
        ev = EventKit.EKEvent.eventWithEventStore_(self._store)
        ev.setTitle_(title)
        ev.setStartDate_(self._nsdate(start))
        ev.setEndDate_(self._nsdate(end))
        ev.setCalendar_(target)
        ok, err = self._store.saveEvent_span_error_(ev, 0, None)
        if not ok:
            raise RuntimeError(f"Save failed: {err}")
        return str(ev.eventIdentifier())
