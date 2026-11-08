"""SLA tracking core for support tickets. No Discord code in here, so it is easy to test and to reuse with other ticket systems.

A ticket has an opening time, messages from the customer and from staff, and an optional closing time.
Two clocks matter: time to first staff response, and time to resolution. Each one can raise a warning (default: at 80% of the limit)
before it raises a breach alert, so staff can still save the SLA.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """Naive datetimes are treated as UTC, so mixing them with aware ones cannot raise TypeError."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class SLAConfig:
    first_response: timedelta = timedelta(minutes=15)
    resolution: timedelta = timedelta(hours=24)
    warn_at: float = 0.8            # fraction of the limit at which a warning is raised; 0 or 1 disables warnings
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
    messages: int = 0
    alerted: str = ""               # comma separated: first_response_warn, first_response, resolution_warn, resolution


@dataclass
class Alert:
    ticket_id: str
    kind: str          # first_response, first_response_warn, resolution, resolution_warn
    waited: timedelta
    limit: timedelta

    @property
    def is_warning(self) -> bool:
        return self.kind.endswith("_warn")


def working_time(start: datetime, end: datetime, hours: tuple[int, int] | None) -> timedelta:
    """Elapsed time that counts against the SLA. Without business hours this is simply end - start."""
    start, end = aware(start), aware(end)
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
    def __init__(self, config: SLAConfig | None = None, store=None):
        self.config = config or SLAConfig()
        self.store = store
        self.tickets: dict[str, Ticket] = {}
        if store is not None:
            self.tickets = {t.ticket_id: t for t in store.load_all()}

    def _save(self, t: Ticket) -> None:
        if self.store is not None:
            self.store.upsert(t)

    # events -----------------------------------------------------------------
    def open_ticket(self, ticket_id: str, opener_id: str = "", at: datetime | None = None) -> Ticket:
        t = self.tickets.get(ticket_id)
        if t is None:
            t = Ticket(ticket_id=ticket_id, opened_at=aware(at) or utcnow(), opener_id=opener_id)
            self.tickets[ticket_id] = t
            self._save(t)
        return t

    def message(self, ticket_id: str, author_id: str, is_staff: bool, at: datetime | None = None) -> None:
        t = self.tickets.get(ticket_id)
        if t is None:
            return
        if t.closed_at is not None:
            return
        t.messages += 1
        if not t.opener_id and not is_staff:
            t.opener_id = author_id                       # the first customer message tells us who opened the ticket
        # a staff member who opened the ticket themselves (a test, a follow-up) is not answering a customer
        if is_staff and t.first_staff_response_at is None and author_id != t.opener_id:
            t.first_staff_response_at = aware(at) or utcnow()
            t.first_staff_id = author_id
        self._save(t)

    def close_ticket(self, ticket_id: str, at: datetime | None = None) -> None:
        t = self.tickets.get(ticket_id)
        if t is not None and t.closed_at is None:
            t.closed_at = aware(at) or utcnow()
            self._save(t)

    def reopen_ticket(self, ticket_id: str) -> None:
        """A closed ticket that gets a new customer message is a new wait: the first response clock restarts from now and old alerts are cleared."""
        t = self.tickets.get(ticket_id)
        if t is not None and t.closed_at is not None:
            t.closed_at = None
            t.first_staff_response_at = None
            t.first_staff_id = ""
            t.opened_at = utcnow()
            t.alerted = ""
            self._save(t)

    # checks -----------------------------------------------------------------
    def check(self, now: datetime | None = None) -> list[Alert]:
        """Return each warning and breach once. Call it every minute."""
        now = aware(now) or utcnow()
        cfg = self.config
        out: list[Alert] = []
        for t in self.tickets.values():
            if t.closed_at is not None:
                continue
            done = set(filter(None, t.alerted.split(",")))
            waited = working_time(t.opened_at, now, cfg.business_hours)
            checks = []
            if t.first_staff_response_at is None:
                checks.append(("first_response", cfg.first_response))
            checks.append(("resolution", cfg.resolution))
            for kind, limit in checks:
                if waited > limit and kind not in done:
                    done.add(kind)
                    done.add(kind + "_warn")           # a breach makes the earlier warning pointless
                    out.append(Alert(t.ticket_id, kind, waited, limit))
                elif 0 < cfg.warn_at < 1 and waited > limit * cfg.warn_at and waited <= limit and kind + "_warn" not in done:
                    done.add(kind + "_warn")
                    out.append(Alert(t.ticket_id, kind + "_warn", waited, limit))
            new = ",".join(sorted(done))
            if new != t.alerted:
                t.alerted = new
                self._save(t)
        return out

    # reporting --------------------------------------------------------------
    def report(self, since: datetime | None = None) -> dict:
        since = aware(since)
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
