from datetime import datetime
from unittest.mock import MagicMock
import anthropic
import httpx
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import DayRequest, NewEvent, format_changes
from dayoptimizer.llm.anthropic_backend import AnthropicBackend

def test_day_request_model_validates():
    r = DayRequest(events=[NewEvent(title="Standup", category="Work")])
    assert r.events[0].day == "today" and r.events[0].start_time is None and r.reply is None


def test_resolve_day_words():
    from datetime import date
    from dayoptimizer.llm.backend import resolve_day
    tue = date(2026, 9, 22)
    assert resolve_day("tomorrow", tue) == date(2026, 9, 23)
    assert resolve_day("thursday", tue) == date(2026, 9, 24)
    assert resolve_day("tuesday", tue) == tue and resolve_day("monday", tue) == date(2026, 9, 28)

def test_format_changes_readable():
    ch = PlannedChange(kind="move", category="Gym", title="Workout",
                       reason="low Body Battery",
                       new_start=datetime(2026, 7, 3, 17, 0), new_end=datetime(2026, 7, 3, 18, 0))
    text = format_changes([ch])
    assert "Gym" in text and "17:00" in text and "Body Battery" in text
    from dataclasses import replace
    later = replace(ch, new_start=datetime(2026, 7, 4, 17, 0), new_end=datetime(2026, 7, 4, 18, 0))
    assert "Sat 04.07 17:00-18:00" in format_changes([ch, later])

def test_parse_request_sends_user_categories():
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.model = "claude-sonnet-5"
    backend.client = MagicMock()
    fake = MagicMock()
    fake.parsed_output = DayRequest()
    backend.client.messages.parse.return_value = fake
    req = backend.parse_request("plan my day", today="2026-07-03", now="09:00", categories=["Choir", "Work"])
    assert req.events == []
    kwargs = backend.client.messages.parse.call_args.kwargs
    assert kwargs["output_format"] is DayRequest
    assert "Choir, Work" in kwargs["messages"][0]["content"]
    assert "temperature" not in kwargs

def test_summarize_changes_uses_messages_create():
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.model = "claude-sonnet-5"
    backend.client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "summary"
    fake = MagicMock()
    fake.content = [block]
    backend.client.messages.create.return_value = fake

    ch = PlannedChange(kind="move", category="Gym", title="Workout", reason="low Body Battery")
    result = backend.summarize_changes([ch])

    assert result == "summary"
    kwargs = backend.client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 1000
    assert "temperature" not in kwargs

def test_summarize_changes_falls_back_on_api_error():
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.model = "claude-sonnet-5"
    backend.client = MagicMock()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    backend.client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    ch = PlannedChange(kind="move", category="Gym", title="Workout", reason="low Body Battery")
    result = backend.summarize_changes([ch])

    assert result == format_changes([ch])

def test_format_changes_create_kind():
    ch = PlannedChange(kind="create", category="Learn", title="Python course", reason="free time")
    text = format_changes([ch])
    assert "[create]" in text and "Learn" in text and "Python course" in text

def test_format_changes_note_kind():
    ch = PlannedChange(kind="note", category="Free time", title="Note", reason="no conflict")
    text = format_changes([ch])
    assert "[note]" in text and "Free time" in text

def test_format_changes_requires_approval_flag():
    ch = PlannedChange(kind="move", category="Work", title="Meeting", reason="conflict",
                        requires_approval=True)
    text = format_changes([ch])
    assert "[approval required]" in text

def test_format_changes_empty_list():
    assert format_changes([]) == "No changes — the plan is consistent."


def test_one_named_day_overrides_the_model():
    from dayoptimizer.llm.backend import DayRequest, NewEvent, pin_day
    wrong = DayRequest(events=[NewEvent(title="x", category="Gym", day="saturday", start_time="14:00")])
    for text, day in [("spotkanie w środę o 14", "wednesday"), ("jutro o 10", "tomorrow"),
                      ("pojutrze basen o 14", "day_after_tomorrow"), ("gym on Friday at 14", "friday")]:
        assert pin_day(text, wrong).events[0].day == day
    assert pin_day("dziś o 10 i jutro o 12", wrong).events[0].day == "saturday"
    days = [("w poniedziałku", "monday"), ("w poniedzialku", "monday"), ("we wtorku", "tuesday"),
            ("do środy", "wednesday"), ("do srody", "wednesday"), ("w czwartku", "thursday"),
            ("w piątku", "friday"), ("w piatku", "friday"), ("do soboty", "saturday"), ("w niedzieli", "sunday"),
            ("po środzie", "wednesday"), ("po sobocie", "saturday"), ("w poniedziałek", "monday"),
            ("we wtorek", "tuesday"), ("w niedzielę", "sunday"), ("po niedzieli", "sunday")]
    for text, day in days:
        assert pin_day(f"{text} o 14", wrong).events[0].day == day, text
    for text in ("o piątej", "o czwartej", "w środku dnia", "piątka z matmy", "dostałem piątkę"):  # an hour or 'the middle', not a weekday
        assert pin_day(f"{text} 14:00", wrong).events[0].day == "saturday", text


def test_one_named_day_pins_tasks():
    from dayoptimizer.llm.backend import DayRequest, TaskRequest, pin_day
    req = DayRequest(tasks=[TaskRequest(title="x", category="Home", when="sobotę")])
    t = pin_day("w sobotę posprzątaj mieszkanie", req).tasks[0]
    assert (t.not_before_day, t.due_day, t.when) == ("saturday", "saturday", None)
    t = pin_day("na piątek przygotuj prezentację", req).tasks[0]
    assert (t.not_before_day, t.due_day) == (None, "friday")
    t = pin_day("przed piatkiem przygotuj prezentację", req).tasks[0]
    assert (t.not_before_day, t.due_day) == (None, "thursday")  # before Friday starts
    t = pin_day("before monday write it", req).tasks[0]
    assert (t.not_before_day, t.due_day) == (None, "sunday")
    t = pin_day("po czwartku umyj okna", req).tasks[0]
    assert (t.not_before_day, t.due_day) == ("friday", None)
    wrong = DayRequest(tasks=[TaskRequest(title="umyj auto", due_day="wednesday")])  # the model read a deadline
    t = pin_day("po środzie umyj auto 1h", wrong).tasks[0]
    assert (t.not_before_day, t.due_day) == ("thursday", None)
    rano = DayRequest(tasks=[TaskRequest(title="x", when="jutro rano")])
    t = pin_day("jutro rano zrób pranie", rano).tasks[0]
    assert (t.not_before_day, t.due_day, t.when) == ("tomorrow", "tomorrow", "jutro rano")
    assert pin_day("dziś zrób pranie", req).tasks[0].not_before_day is None


def test_each_clause_pins_its_own_items():
    from dayoptimizer.llm.backend import DayRequest, NewEvent, TaskRequest, pin_day
    model = DayRequest(events=[NewEvent(title="dentist", category="Important", day="friday", start_time="10:00")],
                       tasks=[TaskRequest(title="raport", category="Work", duration_minutes=120, due_day="friday")])
    req = pin_day("w czwartek o 10 dentysta i do piątku raport 2h", model)
    assert req.events[0].day == "thursday"
    assert (req.tasks[0].due_day, req.tasks[0].not_before_day) == ("friday", None)
    # the model made both tasks; the one with a clock time is an event that day
    model = DayRequest(tasks=[TaskRequest(title="esej", category="Learn", duration_minutes=120),
                              TaskRequest(title="obiad u mamy", category="Family")])
    req = pin_day("na piątek esej 2h a w niedzielę o 12 obiad u mamy", model)
    assert [(t.title, t.due_day) for t in req.tasks] == [("esej", "friday")]
    assert [(e.title, e.day, e.start_time) for e in req.events] == [("obiad u mamy", "sunday", "12:00")]
    model = DayRequest(tasks=[TaskRequest(title="report"), TaskRequest(title="clean the garage")])
    req = pin_day("before Friday write the report 2h and after Saturday clean the garage 2h", model)
    assert [(t.not_before_day, t.due_day) for t in req.tasks] == [(None, "thursday"), ("sunday", None)]
    # a clause with no day of its own: its clock time stays an event, not an inherited 'do' deadline
    model = DayRequest(tasks=[TaskRequest(title="raport"), TaskRequest(title="spotkanie z anią")])
    req = pin_day("do piątku raport i spotkanie z anią o 15", model)
    assert [(e.title, e.day, e.start_time) for e in req.events] == [("spotkanie z anią", "friday", "15:00")]
    # ...and a day the model gave it stands
    model = DayRequest(tasks=[TaskRequest(title="report"), TaskRequest(title="call mom", due_day="sunday")])
    req = pin_day("write a report by friday and call mom", model)
    assert [t.due_day for t in req.tasks] == ["friday", "sunday"]


def test_an_event_without_a_time_is_a_task_and_do_is_its_deadline():
    from dayoptimizer.llm.backend import DayRequest, NewEvent, pin_day
    model = DayRequest(events=[NewEvent(title="raport", category="Learn", day="day_after_tomorrow", duration_minutes=180),
                               NewEvent(title="dentysta", category="Work", day="wednesday", start_time="10:00")])
    req = pin_day("do czwartku raport 3h i w środę o 10 dentysta", model)
    assert [(e.title, e.day) for e in req.events] == [("dentysta", "wednesday")]
    assert [(t.title, t.due_day, t.not_before_day, t.duration_minutes) for t in req.tasks] == [
        ("raport", "thursday", None, 180)]
    # 'za 2h' is no clock time: the model's 20:49 is made up, it stays a task starting in 2h
    model = DayRequest(events=[NewEvent(title="zadzwoń do mamy", category="Free time", day="today",
                                        start_time="20:49", duration_minutes=15),
                               NewEvent(title="siłownia", category="Gym", day="today", start_time="18:00")])
    req = pin_day("za 2h zadzwoń do mamy 15 min i o 18 siłownia", model)
    assert [e.title for e in req.events] == ["siłownia"]
    assert [(t.title, t.duration_minutes) for t in req.tasks] == [("zadzwoń do mamy", 15)]
    assert "za 2h" in req.tasks[0].when


def test_times_the_model_made_up_do_not_make_events():
    from dayoptimizer.llm.backend import DayRequest, NewEvent, pin_day
    made_up = DayRequest(events=[NewEvent(title=t, category="Learn", day="today", start_time=s, duration_minutes=m)
                                 for t, s, m in [("transformery", "10:34", 120), ("bazy danych", "12:34", 60),
                                                 ("IO", "13:34", 60)]])
    req = pin_day("dziś transformery 2h, bazy danych 1h i IO 1h", made_up)
    assert req.events == [] and [(t.title, t.duration_minutes) for t in req.tasks] == [
        ("transformery", 120), ("bazy danych", 60), ("IO", 60)]
    said = DayRequest(events=[NewEvent(title="spotkanie", category="Work", day="today", start_time="18:00"),
                              NewEvent(title="kino", category="Free time", day="today", start_time="20:00")])
    req = pin_day("spotkanie 18:00 i kino o 20", said)
    assert [e.title for e in req.events] == ["spotkanie", "kino"] and req.tasks == []

    # the model's made-up times go, the part of the day said in its own clause stays (no Polish letters typed)
    made_up = DayRequest(events=[NewEvent(title=t, category=c, day="tomorrow", start_time=s, duration_minutes=m)
                                 for t, c, s, m in [("uczyć się ml", "Learn", "18:15", 120),
                                                    ("aws", "Learn", "20:15", 120), ("siłownia", "Gym", "22:15", None)]])
    req = pin_day("jutro chce uczyc sie ml przez 2h, oraz aws przez 2h, i pojsc wieczorem na silownie", made_up)
    assert req.events == [] and [(t.title, t.when) for t in req.tasks] == [
        ("uczyć się ml", None), ("aws", None), ("siłownia", "pojsc wieczorem na silownie")]


def test_a_deadline_time_is_not_an_event():
    from dayoptimizer.llm.backend import DayRequest, TaskRequest, pin_day
    raport = DayRequest(tasks=[TaskRequest(title="raport", category="Work", duration_minutes=120)])
    for text in ("do piątku o 17 raport 2h", "przed piątkiem o 17 oddaj raport"):
        req = pin_day(text, raport)
        assert req.events == [] and (req.tasks[0].due_day, req.tasks[0].due_time) == ("friday", "17:00"), text
    model = DayRequest(tasks=[TaskRequest(title="raport", category="Work", duration_minutes=120, due_time="15:00")])
    req = pin_day("raport 2h przed spotkaniem o 15", model)
    assert req.events == [] and req.tasks[0].due_time == "15:00"


def test_an_item_goes_with_the_clause_sharing_most_of_its_title():
    from dayoptimizer.llm.backend import DayRequest, TaskRequest, pin_day
    model = DayRequest(tasks=[TaskRequest(title="zadzwoń do mamy", category="Family")])
    req = pin_day("w niedzielę obiad u mamy, w piątek zadzwoń do mamy", model)
    assert req.tasks[0].due_day == "friday"
