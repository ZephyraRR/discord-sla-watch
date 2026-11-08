"""Offline demo, no Discord needed: replays a morning of made-up tickets minute by minute and prints the alerts and the report.

    python demo.py
"""
from datetime import datetime, timedelta, timezone

from sla_watch import SLAConfig, Tracker, format_report

t0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
tr = Tracker(SLAConfig(first_response=timedelta(minutes=15), resolution=timedelta(hours=4)))

# (minute, action, ticket, who, is_staff)
EVENTS = [
    (0, "open", "ticket-0001", "cust", False), (4, "msg", "ticket-0001", "ana", True), (30, "close", "ticket-0001", "", False),
    (10, "open", "ticket-0002", "cust", False), (48, "msg", "ticket-0002", "marko", True), (120, "close", "ticket-0002", "", False),   # answered too late
    (20, "open", "ticket-0003", "cust", False),                                                                                         # nobody answers
    (25, "open", "ticket-0004", "cust", False), (27, "msg", "ticket-0004", "ana", True), (60, "close", "ticket-0004", "", False),
    (40, "open", "ticket-0005", "cust", False), (70, "msg", "ticket-0005", "marko", True),                                              # answered late, never closed
]
EVENTS.sort(key=lambda e: e[0])

print("Alerts raised while replaying the morning:")
for minute in range(0, 6 * 60 + 1):
    now = t0 + timedelta(minutes=minute)
    for _, action, tid, who, staff in [e for e in EVENTS if e[0] == minute]:
        if action == "open":
            tr.open_ticket(tid, "cust", now)
        elif action == "msg":
            tr.message(tid, who, staff, now)
        else:
            tr.close_ticket(tid, now)
    for a in tr.check(now):
        print(f"  +{minute:3d} min  {a.ticket_id}: {a.kind} after {int(a.waited.total_seconds() // 60)} min")

print()
print(format_report(tr.report()))
