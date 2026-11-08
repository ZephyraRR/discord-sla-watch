# discord-sla-watch

Response-time tracking and SLA alerts for support teams that run on Discord.

## The problem

A lot of small digital-goods shops, game communities and SaaS products do their support in Discord tickets. The popular open-source ticket bots (Discord Tickets, Sentinel Tickets, Open Ticket) open and close tickets well, but none of them, as far as I could find, tells you **how long customers wait for the first answer** or warns your staff **before** a ticket breaches your promise. The one tool that does this (Ticket Tool) charges for it. Support leads end up exporting transcripts and measuring in a spreadsheet.

## What this does

- Works **next to any ticket bot**. It only needs to know the ticket channels, by their name prefix (`ticket-` by default).
- Measures **time to first staff response** and **time to resolution** per ticket.
- Posts a **warning** at 80% of the limit and a **breach alert** when a ticket passes the first-response or the resolution limit, in a staff channel (once per ticket and kind).
- Optional **business hours** (for example 08:00 to 18:00 UTC, weekdays), so the clock stops at night and on weekends.
- `!sla` in any ticket channel prints a report: tickets, median and 90th percentile first response, share answered within the SLA, median resolution, first responses per staff member.

The review pass for this repository found and fixed: alerts only after the breach (now warnings too), lost state on restart, naive datetimes crashing the clock, a staff member's own message counting as an answer, and reopened tickets keeping their old clock.

I wrote this because I spent almost three years answering technical and billing tickets for a digital-goods platform in Intercom and Discord. Reporting on response times was always manual.

## Try it without Discord

```bash
python demo.py
```

Replays a made-up morning minute by minute and prints the alerts and the final report.

## Run the bot

```bash
pip install -r requirements.txt
export DISCORD_TOKEN=...            # bot token (needs the Message Content and Server Members intents)
export ALERT_CHANNEL_ID=123...      # staff channel that receives the alerts
export STAFF_ROLE_ID=456...         # role whose messages count as a staff response
export SLA_FIRST_RESPONSE_MIN=15    # optional, default 15
export SLA_RESOLUTION_HOURS=24      # optional, default 24
export SLA_BUSINESS_HOURS=8-18      # optional, UTC, weekdays only
export SLA_WARN_AT=0.8              # optional, warning at this share of the limit (0 turns warnings off)
export SLA_DB=sla_watch.sqlite3     # optional, where state is kept so restarts do not lose open tickets
export TICKET_CHANNEL_PREFIX=ticket-    # optional
export CLOSED_CHANNEL_PREFIX=closed-    # optional: a rename to this prefix, or deleting the channel, closes the ticket
python -m sla_watch.bot
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

18 tests cover warnings and breach alerts (each reported once), customer messages not stopping the clock, closed and reopened tickets, a staff member who opened the ticket not counting as a response, naive datetimes, business hours across a weekend, persistence across a restart without repeating alerts, and the report numbers.

## Design

`sla_watch/core.py` has no Discord code: a `Tracker` receives three events (open, message, close) and answers `check()` and `report()`. That keeps the logic testable and lets you plug in another ticket system. `sla_watch/bot.py` is the thin discord.py layer.

## Limits (honest)

- The core is tested. The Discord layer (`bot.py`) is a thin adapter written against the discord.py 2.x API; I have **not** run it against a live server in this repository's tests, so expect to adjust intents or permissions on first use.
- State is kept in SQLite, but tickets that already existed before the first start are only picked up when their next message arrives.
- The resolution clock keeps running while a ticket waits for the customer; there is no "pending customer" state yet.
- A ticket renamed to the closed prefix stops being tracked, so a customer writing in it again is not noticed.
- Staff are recognised by one role id. Multi-guild setups and slash commands are not implemented.
