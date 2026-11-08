from datetime import datetime, timedelta, timezone

from sla_watch import SLAConfig, Tracker, format_report, working_time

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)   # a Monday


def tracker(**kw):
    return Tracker(SLAConfig(first_response=timedelta(minutes=15), resolution=timedelta(hours=4), **kw))


def test_no_alert_when_staff_answers_in_time():
    t = tracker()
    t.open_ticket("a", "c", T0)
    t.message("a", "s", True, T0 + timedelta(minutes=5))
    assert t.check(T0 + timedelta(minutes=30)) == []


def test_first_response_breach_is_reported_once():
    t = tracker()
    t.open_ticket("a", "c", T0)
    first = t.check(T0 + timedelta(minutes=16))
    again = t.check(T0 + timedelta(minutes=20))
    assert [x.kind for x in first] == ["first_response"] and again == []


def test_customer_messages_do_not_stop_the_clock():
    t = tracker()
    t.open_ticket("a", "c", T0)
    t.message("a", "c", False, T0 + timedelta(minutes=3))
    assert t.check(T0 + timedelta(minutes=16))


def test_resolution_breach_after_the_limit():
    t = tracker()
    t.open_ticket("a", "c", T0)
    t.message("a", "s", True, T0 + timedelta(minutes=2))
    assert [x.kind for x in t.check(T0 + timedelta(hours=5))] == ["resolution"]


def test_closed_tickets_never_alert():
    t = tracker()
    t.open_ticket("a", "c", T0)
    t.close_ticket("a", T0 + timedelta(minutes=5))
    assert t.check(T0 + timedelta(days=3)) == []


def test_business_hours_skip_nights_and_weekends():
    # Friday 17:00 to Monday 09:30 with hours 8-18: only Friday 17:00-18:00 and Monday 08:00-09:30 count
    fri = datetime(2026, 11, 6, 17, 0, tzinfo=timezone.utc)
    mon = datetime(2026, 11, 9, 9, 30, tzinfo=timezone.utc)
    assert working_time(fri, mon, (8, 18)) == timedelta(hours=1) + timedelta(hours=1, minutes=30)


def test_alerts_respect_business_hours():
    t = tracker(business_hours=(8, 18))
    t.open_ticket("a", "c", datetime(2026, 11, 6, 17, 50, tzinfo=timezone.utc))   # Friday evening
    assert t.check(datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)) == []        # Saturday: the clock is stopped


def test_report_numbers():
    t = tracker()
    for i, answer in enumerate([4, 40, None]):
        t.open_ticket(str(i), "c", T0)
        if answer is not None:
            t.message(str(i), "s", True, T0 + timedelta(minutes=answer))
    t.close_ticket("0", T0 + timedelta(minutes=30))
    r = t.report()
    assert r["tickets"] == 3 and r["answered"] == 2 and r["unanswered"] == 1
    assert r["first_response_within_sla_pct"] == 50.0
    assert r["first_response_median_min"] == 22.0
    assert r["resolved"] == 1


def test_report_text_mentions_the_key_figures():
    t = tracker()
    t.open_ticket("a", "c", T0)
    t.message("a", "ana", True, T0 + timedelta(minutes=5))
    text = format_report(t.report())
    assert "median 5.0 min" in text and "ana: 1" in text


def test_messages_on_unknown_or_closed_tickets_are_ignored():
    t = tracker()
    t.message("ghost", "s", True, T0)
    t.open_ticket("a", "c", T0)
    t.close_ticket("a", T0 + timedelta(minutes=1))
    t.message("a", "s", True, T0 + timedelta(minutes=2))
    assert t.tickets["a"].first_staff_response_at is None
