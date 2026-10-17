from __future__ import annotations
import re
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

def _nscolor(color: str):
    from AppKit import NSColor
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)

def _hex(nscolor) -> str:
    from AppKit import NSColorSpace
    rgb = nscolor.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in
                                   (rgb.redComponent(), rgb.greenComponent(), rgb.blueComponent()))

MARKER = "Planned by DayOptimizer"
SUGGESTED = "Suggested by DayOptimizer"  # a second line on blocks suggested for free time

TASK_TAG = "Task: "
_TASK_RE = re.compile(r"^Task: (\S+)$", re.M)


def task_id_from_notes(notes: str) -> str | None:
    """Which task a planner block works on (the line `create_event` writes)."""
    m = _TASK_RE.search(notes or "")
    return m.group(1) if m else None


def ek_to_event(identifier, calendar_title, title, start, end, location, all_day=False,
                managed=False, task_id=None, suggested=False) -> Event:
    return Event(id=identifier, calendar=normalize_calendar(calendar_title), title=title,
                 start=start, end=end, location=location, all_day=all_day, managed=managed,
                 task_id=task_id, suggested=suggested)

class CalendarClient:
    _shared = None  # one EKEventStore per process: a long-lived caller (MCP server) makes many clients

    def __init__(self):
        import EventKit
        self._EventKit = EventKit
        if CalendarClient._shared is None:
            CalendarClient._shared = EventKit.EKEventStore.alloc().init()
        self._store = CalendarClient._shared

    def request_access(self) -> bool:
        """True when DayOptimizer may read and write the calendar. Asks (and
        waits for the answer) only when macOS hasn't been asked yet: asking again
        and again from one process starts being refused."""
        from Foundation import NSDate, NSRunLoop
        status = self._EventKit.EKEventStore.authorizationStatusForEntityType_(self._EventKit.EKEntityTypeEvent)
        if status == getattr(self._EventKit, "EKAuthorizationStatusFullAccess", 3):
            return True

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
            notes = str(ev.notes() or "")
            managed = MARKER in notes
            out.append(ek_to_event(
                str(ev.eventIdentifier()),
                str(ev.calendar().title()),
                str(ev.title() or ""),
                datetime.fromtimestamp(ev.startDate().timeIntervalSince1970()).astimezone(),
                datetime.fromtimestamp(ev.endDate().timeIntervalSince1970()).astimezone(),
                str(ev.location()) if ev.location() else None,
                bool(ev.isAllDay()),
                managed,
                task_id_from_notes(notes) if managed else None,
                managed and SUGGESTED in notes,
            ))
        return sorted(out, key=lambda e: e.start)

    def move_event(self, event_id: str, new_start: datetime, new_end: datetime) -> None:
        ev = self._store.eventWithIdentifier_(event_id)
        if ev is None:
            raise KeyError(f"Event {event_id} not found")
        if ev.isAllDay():
            ev.setAllDay_(False)
        ev.setStartDate_(self._nsdate(new_start))
        ev.setEndDate_(self._nsdate(new_end))
        ok, err = self._store.saveEvent_span_error_(ev, 0, None)
        if not ok:
            raise RuntimeError(f"Save failed: {err}")

    def _find_calendar(self, name: str):
        for cal in self._store.calendarsForEntityType_(self._EventKit.EKEntityTypeEvent):
            if normalize_calendar(str(cal.title())) == name:
                return cal
        return None

    def ensure_calendar(self, name: str, color: str | None = None) -> bool:
        """Create a calendar called `name` unless one exists (emoji-prefixed
        names count). Returns True when it was created. Tries the account new
        events go to first, then other CalDAV accounts (iCloud), then On My
        Mac: some accounts (e.g. Google) don't allow creating calendars."""
        if self._find_calendar(name) is not None:
            return False
        EK = self._EventKit
        cal = EK.EKCalendar.calendarForEntityType_eventStore_(EK.EKEntityTypeEvent, self._store)
        cal.setTitle_(name)
        if color:
            cal.setColor_(_nscolor(color))
        default = self._store.defaultCalendarForNewEvents()
        sources = [default.source()] if default is not None else []
        sources += [s for s in self._store.sources() if s.sourceType() == EK.EKSourceTypeCalDAV]
        sources += [s for s in self._store.sources() if s.sourceType() == EK.EKSourceTypeLocal]
        errors = []
        for source in sources:
            cal.setSource_(source)
            ok, err = self._store.saveCalendar_commit_error_(cal, True, None)
            if ok:
                return True
            errors.append(str(err))
        raise KeyError(f"Calendar '{name}' not found and couldn't be created ({'; '.join(errors) or 'no account'})")

    def all_calendars(self) -> dict[str, tuple[str | None, str]]:
        """Every event calendar the user has (empty ones too): name -> (#rrggbb, account)."""
        return {normalize_calendar(str(c.title())): (_hex(c.color()) if c.color() is not None else None,
                                                     str(c.source().title()) if c.source() else "")
                for c in self._store.calendarsForEntityType_(self._EventKit.EKEntityTypeEvent)}

    def calendar_color(self, name: str) -> str | None:
        """#rrggbb of the category's calendar, None when there is no such calendar."""
        cal = self._find_calendar(name)
        return _hex(cal.color()) if cal is not None and cal.color() is not None else None

    def set_color(self, name: str, color: str) -> bool:
        """Give the category's calendar this colour. True when it changed;
        raises KeyError when the account refuses the change."""
        cal = self._find_calendar(name)
        if cal is None or self.calendar_color(name) == color.lower():
            return False
        cal.setColor_(_nscolor(color))
        ok, err = self._store.saveCalendar_commit_error_(cal, True, None)
        if not ok:
            raise KeyError(f"couldn't recolour '{name}' ({err})")
        return True

    def create_event(self, calendar_name: str, title: str, start: datetime, end: datetime,
                     task_id: str | None = None, managed: bool = True, suggested: bool = False) -> str:
        """A planner block (marked, so replans may move or remove it), or with
        managed=False an event the user asked for: theirs, never touched again."""
        EventKit = self._EventKit
        target = self._find_calendar(calendar_name)
        if target is None:
            self.ensure_calendar(calendar_name)
            target = self._find_calendar(calendar_name)
        if target is None:
            raise KeyError(f"Calendar '{calendar_name}' not found")
        ev = EventKit.EKEvent.eventWithEventStore_(self._store)
        ev.setTitle_(title)
        ev.setStartDate_(self._nsdate(start))
        ev.setEndDate_(self._nsdate(end))
        ev.setCalendar_(target)
        if managed:
            ev.setNotes_(MARKER + (f"\n{TASK_TAG}{task_id}" if task_id else "") + (f"\n{SUGGESTED}" if suggested else ""))
        ok, err = self._store.saveEvent_span_error_(ev, 0, None)
        if not ok:
            raise RuntimeError(f"Save failed: {err}")
        return str(ev.eventIdentifier())

    def delete_event(self, event_id: str) -> None:
        """Remove a block DayOptimizer created. Anything else is the user's
        and is refused, whatever the caller asked."""
        ev = self._store.eventWithIdentifier_(event_id)
        if ev is None:
            raise KeyError(f"Event {event_id} not found")
        if MARKER not in str(ev.notes() or ""):
            raise RuntimeError("not created by DayOptimizer, left alone")
        ok, err = self._store.removeEvent_span_error_(ev, 0, None)
        if not ok:
            raise RuntimeError(f"Delete failed: {err}")
