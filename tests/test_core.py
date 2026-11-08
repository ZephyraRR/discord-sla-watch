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


# --- regression tests for problems found in review ------------------------------------------------------------------------
from sla_watch import Store


def test_warning_comes_before_the_breach_and_only_once():
    t = tracker()
    t.open_ticket("a", "c", T0)
    warn = t.check(T0 + timedelta(minutes=13))            # 80% of 15 min = 12 min
    again = t.check(T0 + timedelta(minutes=14))
    breach = t.check(T0 + timedelta(minutes=16))
    assert [a.kind for a in warn] == ["first_response_warn"] and again == []
    assert [a.kind for a in breach] == ["first_response"]
    assert warn[0].is_warning and not breach[0].is_warning


def test_a_breach_without_an_earlier_check_does_not_also_send_a_stale_warning():
    t = tracker()
    t.open_ticket("a", "c", T0)
    assert [a.kind for a in t.check(T0 + timedelta(minutes=20))] == ["first_response"]


def test_warnings_can_be_switched_off():
    t = Tracker(SLAConfig(first_response=timedelta(minutes=15), resolution=timedelta(hours=4), warn_at=0))
    t.open_ticket("a", "c", T0)
    assert t.check(T0 + timedelta(minutes=14)) == []


def test_naive_datetimes_do_not_crash():
    t = tracker()
    t.open_ticket("a", "c", datetime(2026, 11, 2, 9, 0))                 # naive
    assert [a.kind for a in t.check(T0 + timedelta(minutes=20))] == ["first_response"]


def test_a_staff_member_who_opened_the_ticket_is_not_a_first_response():
    t = tracker()
    t.open_ticket("a", "ana", T0)
    t.message("a", "ana", True, T0 + timedelta(minutes=1))
    assert t.tickets["a"].first_staff_response_at is None


def test_the_first_customer_message_sets_the_opener():
    t = tracker()
    t.open_ticket("a", "", T0)
    t.message("a", "customer", False, T0 + timedelta(minutes=1))
    t.message("a", "customer", True, T0 + timedelta(minutes=2))        # same id as the opener: not an answer
    assert t.tickets["a"].opener_id == "customer" and t.tickets["a"].first_staff_response_at is None


def test_reopening_restarts_the_first_response_clock():
    t = tracker()
    t.open_ticket("a", "c", T0)
    t.message("a", "s", True, T0 + timedelta(minutes=2))
    t.close_ticket("a", T0 + timedelta(minutes=10))
    t.reopen_ticket("a")
    tk = t.tickets["a"]
    assert tk.closed_at is None and tk.first_staff_response_at is None and tk.alerted == ""


def test_state_survives_a_restart_and_alerts_are_not_repeated(tmp_path):
    path = str(tmp_path / "sla.sqlite3")
    t1 = Tracker(SLAConfig(first_response=timedelta(minutes=15), resolution=timedelta(hours=4)), Store(path))
    t1.open_ticket("a", "c", T0)
    assert [a.kind for a in t1.check(T0 + timedelta(minutes=16))] == ["first_response"]
    t2 = Tracker(SLAConfig(first_response=timedelta(minutes=15), resolution=timedelta(hours=4)), Store(path))   # "restart"
    assert "a" in t2.tickets
    assert t2.check(T0 + timedelta(minutes=17)) == []                                                            # already alerted before the restart
    t2.message("a", "ana", True, T0 + timedelta(minutes=18))
    t3 = Tracker(SLAConfig(), Store(path))
    assert t3.tickets["a"].first_staff_id == "ana"
