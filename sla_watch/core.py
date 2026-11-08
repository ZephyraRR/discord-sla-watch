"""SLA tracking core for support tickets. No Discord code in here, so it is easy to test and to reuse with other ticket systems.

A ticket has an opening time, messages from the customer and from staff, and an optional closing time.
Two clocks matter: time to first staff response, and time to resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SLAConfig:
    first_response: timedelta = timedelta(minutes=15)
    resolution: timedelta = timedelta(hours=24)
    # Optional business hours in UTC, for example (8, 18) for 08:00 to 18:00 on weekdays. None = the clock never stops.
    business_hours: tuple[int, int] | None = None


@dataclass
class Ticket:
    ticket_id: str
    opened_at: datetime
    opener_id: str = ""
    first_staff_response_at: datetime | None = None
    first_staff_id: str = ""
    closed_at: datetime | None = None
    alerted_first_response: bool = False
    alerted_resolution: bool = False
    messages: int = 0


@dataclass
class Alert:
    ticket_id: str
    kind: str          # "first_response" or "resolution"
    waited: timedelta
    limit: timedelta


def working_time(start: datetime, end: datetime, hours: tuple[int, int] | None) -> timedelta:
    """Elapsed time that counts against the SLA. Without business hours this is simply end - start."""
    if end <= start:
        return timedelta(0)
    if hours is None:
        return end - start
    open_h, close_h = hours
    total = timedelta(0)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        if day.weekday() < 5:
            w_start = max(start, day + timedelta(hours=open_h))
            w_end = min(end, day + timedelta(hours=close_h))
            if w_end > w_start:
                total += w_end - w_start
        day += timedelta(days=1)
    return total


class Tracker:
    def __init__(self, config: SLAConfig | None = None):
        self.config = config or SLAConfig()
        self.tickets: dict[str, Ticket] = {}

    # events -----------------------------------------------------------------
    def open_ticket(self, ticket_id: str, opener_id: str = "", at: datetime | None = None) -> Ticket:
        t = self.tickets.get(ticket_id)
        if t is None:
            t = Ticket(ticket_id=ticket_id, opened_at=at or utcnow(), opener_id=opener_id)
            self.tickets[ticket_id] = t
        return t

    def message(self, ticket_id: str, author_id: str, is_staff: bool, at: datetime | None = None) -> None:
        t = self.tickets.get(ticket_id)
        if t is None or t.closed_at is not None:
            return
        t.messages += 1
        if is_staff and t.first_staff_response_at is None:
            t.first_staff_response_at = at or utcnow()
            t.first_staff_id = author_id

    def close_ticket(self, ticket_id: str, at: datetime | None = None) -> None:
        t = self.tickets.get(ticket_id)
        if t is not None and t.closed_at is None:
            t.closed_at = at or utcnow()

    # checks -----------------------------------------------------------------
    def check(self, now: datetime | None = None) -> list[Alert]:
        """Return each breach once. Call it every minute."""
        now = now or utcnow()
        out: list[Alert] = []
        for t in self.tickets.values():
            if t.closed_at is not None:
                continue
            if t.first_staff_response_at is None and not t.alerted_first_response:
                waited = working_time(t.opened_at, now, self.config.business_hours)
                if waited > self.config.first_response:
                    t.alerted_first_response = True
                    out.append(Alert(t.ticket_id, "first_response", waited, self.config.first_response))
            if not t.alerted_resolution:
                waited = working_time(t.opened_at, now, self.config.business_hours)
                if waited > self.config.resolution:
                    t.alerted_resolution = True
                    out.append(Alert(t.ticket_id, "resolution", waited, self.config.resolution))
        return out

    # reporting --------------------------------------------------------------
    def report(self, since: datetime | None = None) -> dict:
        rows = [t for t in self.tickets.values() if since is None or t.opened_at >= since]
        frt = [working_time(t.opened_at, t.first_staff_response_at, self.config.business_hours) for t in rows if t.first_staff_response_at]
        res = [working_time(t.opened_at, t.closed_at, self.config.business_hours) for t in rows if t.closed_at]
        within = sum(1 for d in frt if d <= self.config.first_response)
        per_staff: dict[str, int] = {}
        for t in rows:
            if t.first_staff_id:
                per_staff[t.first_staff_id] = per_staff.get(t.first_staff_id, 0) + 1
        return {
            "tickets": len(rows),
            "answered": len(frt),
            "unanswered": sum(1 for t in rows if t.first_staff_response_at is None and t.closed_at is None),
            "first_response_median_min": round(median(d.total_seconds() for d in frt) / 60, 1) if frt else None,
            "first_response_p90_min": round(_percentile([d.total_seconds() for d in frt], 90) / 60, 1) if frt else None,
            "first_response_within_sla_pct": round(100 * within / len(frt), 1) if frt else None,
            "resolved": len(res),
            "resolution_median_h": round(median(d.total_seconds() for d in res) / 3600, 2) if res else None,
            "first_responses_per_staff": per_staff,
        }


def _percentile(values: list[float], pct: float) -> float:
    v = sorted(values)
    k = max(0, min(len(v) - 1, int(round(pct / 100 * (len(v) - 1)))))
    return v[k]


def format_report(r: dict, title: str = "Support SLA report") -> str:
    def f(x, unit=""):
        return "n/a" if x is None else f"{x}{unit}"

    lines = [
        f"# {title}",
        "",
        f"- Tickets: {r['tickets']} (answered {r['answered']}, still unanswered {r['unanswered']}, resolved {r['resolved']})",
        f"- First response: median {f(r['first_response_median_min'], ' min')}, p90 {f(r['first_response_p90_min'], ' min')}, within SLA {f(r['first_response_within_sla_pct'], '%')}",
        f"- Resolution: median {f(r['resolution_median_h'], ' h')}",
    ]
    if r["first_responses_per_staff"]:
        lines += ["", "First responses per staff member:"] + [f"- {k}: {v}" for k, v in sorted(r["first_responses_per_staff"].items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)
