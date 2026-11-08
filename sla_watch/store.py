"""SQLite persistence, so a restart of the bot does not forget open tickets and which alerts were already sent."""
import sqlite3
from datetime import datetime

from .core import Ticket, aware

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY, opened_at TEXT NOT NULL, opener_id TEXT NOT NULL DEFAULT '',
    first_staff_response_at TEXT, first_staff_id TEXT NOT NULL DEFAULT '', closed_at TEXT,
    messages INTEGER NOT NULL DEFAULT 0, alerted TEXT NOT NULL DEFAULT ''
);
"""


def _dt(s: str | None) -> datetime | None:
    return aware(datetime.fromisoformat(s)) if s else None


class Store:
    def __init__(self, path: str = ":memory:"):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def upsert(self, t: Ticket) -> None:
        self.con.execute(
            "INSERT INTO tickets(ticket_id, opened_at, opener_id, first_staff_response_at, first_staff_id, closed_at, messages, alerted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(ticket_id) DO UPDATE SET opened_at=excluded.opened_at, opener_id=excluded.opener_id, "
            "first_staff_response_at=excluded.first_staff_response_at, first_staff_id=excluded.first_staff_id, closed_at=excluded.closed_at, "
            "messages=excluded.messages, alerted=excluded.alerted",
            (t.ticket_id, t.opened_at.isoformat(), t.opener_id, t.first_staff_response_at.isoformat() if t.first_staff_response_at else None,
             t.first_staff_id, t.closed_at.isoformat() if t.closed_at else None, t.messages, t.alerted),
        )
        self.con.commit()

    def load_all(self) -> list[Ticket]:
        return [
            Ticket(ticket_id=r["ticket_id"], opened_at=_dt(r["opened_at"]), opener_id=r["opener_id"], first_staff_response_at=_dt(r["first_staff_response_at"]),
                   first_staff_id=r["first_staff_id"], closed_at=_dt(r["closed_at"]), messages=r["messages"], alerted=r["alerted"])
            for r in self.con.execute("SELECT * FROM tickets")
        ]
