"""Discord front end. It watches ticket channels created by ANY ticket bot (Ticket Tool, Discord Tickets, Sentinel...) and does one thing
those bots do not: it measures first-response time and resolution time and alerts your staff when a ticket is about to breach the SLA.

Configuration comes from environment variables (see README). discord.py is imported here only, the core has no dependency on it.
"""
from __future__ import annotations

import os
from datetime import timedelta

from .core import SLAConfig, Tracker, format_report
from .store import Store

try:
    import discord
    from discord.ext import tasks
except ImportError:  # the core and the tests work without discord.py
    discord = None  # type: ignore


def load_config() -> tuple[SLAConfig, dict]:
    cfg = SLAConfig(
        first_response=timedelta(minutes=float(os.environ.get("SLA_FIRST_RESPONSE_MIN", "15"))),
        warn_at=float(os.environ.get("SLA_WARN_AT", "0.8")),
        resolution=timedelta(hours=float(os.environ.get("SLA_RESOLUTION_HOURS", "24"))),
    )
    bh = os.environ.get("SLA_BUSINESS_HOURS")          # "8-18"
    if bh:
        a, b = bh.split("-")
        cfg.business_hours = (int(a), int(b))
    env = {
        "token": os.environ["DISCORD_TOKEN"],
        "prefix": os.environ.get("TICKET_CHANNEL_PREFIX", "ticket-"),
        "closed_prefix": os.environ.get("CLOSED_CHANNEL_PREFIX", "closed-"),
        "alert_channel": int(os.environ["ALERT_CHANNEL_ID"]),
        "staff_role": int(os.environ["STAFF_ROLE_ID"]),
    }
    return cfg, env


def run() -> None:
    if discord is None:
        raise SystemExit("pip install discord.py to run the bot")
    cfg, env = load_config()
    tracker = Tracker(cfg, Store(os.environ.get("SLA_DB", "sla_watch.sqlite3")))   # survives restarts
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.members = True
    client = discord.Client(intents=intents)

    def is_ticket(channel) -> bool:
        return getattr(channel, "name", "").startswith(env["prefix"])

    @client.event
    async def on_guild_channel_create(channel):
        if is_ticket(channel):
            tracker.open_ticket(str(channel.id), at=channel.created_at)

    @client.event
    async def on_guild_channel_update(before, after):
        if is_ticket(before) and after.name.startswith(env["closed_prefix"]):
            tracker.close_ticket(str(after.id))

    @client.event
    async def on_guild_channel_delete(channel):
        if is_ticket(channel):
            tracker.close_ticket(str(channel.id))

    @client.event
    async def on_message(message):
        if message.author.bot or not is_ticket(message.channel):
            return
        is_staff = any(r.id == env["staff_role"] for r in getattr(message.author, "roles", []))
        tracker.open_ticket(str(message.channel.id), "", message.channel.created_at)   # also covers tickets that existed before the bot started
        if not is_staff:
            tracker.reopen_ticket(str(message.channel.id))                              # a customer writes again in a closed ticket: new wait
        tracker.message(str(message.channel.id), str(message.author.id), is_staff, message.created_at)
        if message.content.strip() == "!sla":
            await message.channel.send("```\n" + format_report(tracker.report()) + "\n```")

    @tasks.loop(minutes=1)
    async def watchdog():
        channel = client.get_channel(env["alert_channel"])
        for a in tracker.check():
            label = "first response" if a.kind.startswith("first_response") else "resolution"
            minutes = int(a.waited.total_seconds() // 60)
            head = "SLA warning" if a.is_warning else "SLA breach"
            if channel:
                await channel.send(f"{head} ({label}): <#{a.ticket_id}> has waited {minutes} min, limit {int(a.limit.total_seconds() // 60)} min.")

    @client.event
    async def on_ready():
        if not watchdog.is_running():
            watchdog.start()

    client.run(env["token"])


if __name__ == "__main__":
    run()
