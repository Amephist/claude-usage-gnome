#!/usr/bin/env python3
"""Claude Code usage stats — outputs JSON for the GNOME panel widget."""

import json
import glob
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
STATS_CACHE = CLAUDE_DIR / "stats-cache.json"
CONFIG_FILE = CLAUDE_DIR / "usage-widget.json"

# Inferred limits (June 4 2026):
#   Period (~5h window): ~2.26M tokens
#   Weekly (resets Thu 4am local): ~22.2M tokens
DEFAULT_PERIOD_LIMIT = 2_260_000
DEFAULT_PERIOD_HOURS = 5
DEFAULT_WEEKLY_LIMIT = 22_200_000
WEEK_RESET_DAY = 3   # Thursday (Mon=0)
WEEK_RESET_HOUR = 4  # 4am local


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def last_thursday_4am():
    """Return datetime of the most recent Thursday 4am local."""
    now = datetime.now()
    days_since_thu = (now.weekday() - WEEK_RESET_DAY) % 7
    last_thu = now - timedelta(days=days_since_thu)
    reset = last_thu.replace(hour=WEEK_RESET_HOUR, minute=0, second=0, microsecond=0)
    if reset > now:
        reset -= timedelta(weeks=1)
    return reset


def anchor_period_start(cfg, period_hours):
    """Compute period start from stored anchor using fixed-grid math."""
    anchor_str = cfg.get("period_anchor_utc")
    if not anchor_str:
        return datetime.now() - timedelta(hours=period_hours)
    try:
        anchor_utc = datetime.fromisoformat(anchor_str)
        now_utc = datetime.now(timezone.utc)
        elapsed = (now_utc - anchor_utc).total_seconds()
        periods_elapsed = math.floor(elapsed / (period_hours * 3600))
        start_utc = anchor_utc + timedelta(hours=period_hours * periods_elapsed)
        return start_utc.astimezone().replace(tzinfo=None)
    except Exception:
        return datetime.now() - timedelta(hours=period_hours)


def current_period_start(cfg, period_hours, msgs=None):
    """Return the start of the current period.

    Uses anchor math as baseline, then validates against actual activity gaps.
    If the anchor-computed start falls inside a real gap >= period_hours, the
    anchor is correct. If there is a gap >= period_hours but the anchor doesn't
    land in it, the anchor is stale — fall back to first token after the most
    recent such gap as a proxy for the new period start.
    """
    math_start = anchor_period_start(cfg, period_hours)

    if not msgs:
        return math_start

    period_sec = period_hours * 3600
    sorted_msgs = sorted(msgs, key=lambda m: m["ts"])

    # Search backwards for the most recent gap >= period_hours
    for i in range(len(sorted_msgs) - 1, 0, -1):
        before = sorted_msgs[i - 1]["ts"]
        after  = sorted_msgs[i]["ts"]
        gap_sec = (after - before).total_seconds()
        if gap_sec < period_sec:
            continue
        # Found a gap big enough to contain a period reset.
        if before < math_start <= after:
            # Anchor math lands inside the gap — anchor is consistent.
            return math_start
        # Anchor doesn't land in this gap — it's stale.
        # Best proxy: first token after the gap.
        return after

    # No long gap found — trust the anchor math.
    return math_start


def parse_iso(ts_str):
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def read_messages(since_dt, days_back=8):
    """Return messages with usage data since since_dt (timezone-aware)."""
    cutoff_mtime = (datetime.now() - timedelta(days=days_back)).timestamp()
    messages = []

    for jsonl_file in PROJECTS_DIR.glob("**/*.jsonl"):
        try:
            if jsonl_file.stat().st_mtime < cutoff_mtime:
                continue
            with open(jsonl_file) as f:
                for line in f:
                    d = json.loads(line)
                    if d.get("type") != "assistant":
                        continue
                    msg = d.get("message")
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    ts = parse_iso(d.get("timestamp", ""))
                    if ts is None:
                        continue
                    # Compare: ts is UTC-aware, since_dt is local naive — normalise
                    ts_local = ts.astimezone().replace(tzinfo=None)
                    if ts_local < since_dt:
                        continue
                    messages.append(
                        {
                            "ts": ts_local,
                            "input": usage.get("input_tokens", 0),
                            "output": usage.get("output_tokens", 0),
                            "cache_read": usage.get("cache_read_input_tokens", 0),
                            "cache_create": usage.get("cache_creation_input_tokens", 0),
                            "model": msg.get("model", "unknown"),
                        }
                    )
        except Exception:
            pass

    messages.sort(key=lambda x: x["ts"])
    return messages


def sum_tokens(msgs):
    inp = sum(m["input"] for m in msgs)
    out = sum(m["output"] for m in msgs)
    cr = sum(m["cache_read"] for m in msgs)
    cc = sum(m["cache_create"] for m in msgs)
    effective = inp + out + cc
    return {
        "input": inp,
        "output": out,
        "cache_read": cr,
        "cache_create": cc,
        "total": inp + out + cr + cc,
        "effective": effective,
        "messages": len(msgs),
    }


def fmt(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def main():
    cfg = load_config()
    period_limit = cfg.get("daily_budget_tokens", DEFAULT_PERIOD_LIMIT)
    period_hours = cfg.get("period_hours", DEFAULT_PERIOD_HOURS)
    weekly_limit = cfg.get("weekly_budget_tokens", DEFAULT_WEEKLY_LIMIT)

    now = datetime.now()
    week_start = last_thursday_4am()

    # Load all messages since week start (covers both period and weekly windows)
    all_msgs = read_messages(since_dt=week_start)

    # Period window: anchor math validated against real activity gaps
    period_start = current_period_start(cfg, period_hours, all_msgs)
    period_msgs = [m for m in all_msgs if m["ts"] >= period_start]

    # Weekly window: since last Thursday 4am
    weekly_msgs = all_msgs  # all_msgs already filtered to since week_start

    # Recent windows for rate
    now_naive = now
    last_1h = [m for m in all_msgs if m["ts"] >= now_naive - timedelta(hours=1)]
    last_6h = [m for m in all_msgs if m["ts"] >= now_naive - timedelta(hours=6)]

    period_stats = sum_tokens(period_msgs)
    weekly_stats = sum_tokens(weekly_msgs)
    last_1h_stats = sum_tokens(last_1h)

    # Rate: use 6h window clipped to current period start
    rate_start = max(now_naive - timedelta(hours=6), period_start)
    rate_msgs = [m for m in all_msgs if m["ts"] >= rate_start] or period_msgs
    if rate_msgs:
        oldest = min(m["ts"] for m in rate_msgs)
        window_h = max((now_naive - oldest).total_seconds() / 3600, 1 / 60)
        rate_per_hour = sum_tokens(rate_msgs)["effective"] / window_h
    else:
        rate_per_hour = 0.0

    # Time elapsed in current period and week
    hours_in_period = min((now_naive - period_start).total_seconds() / 3600, period_hours)
    hours_in_week = (now_naive - week_start).total_seconds() / 3600

    # Remaining and ETA
    period_used = period_stats["effective"]
    weekly_used = weekly_stats["effective"]
    period_remaining = max(period_limit - period_used, 0)
    weekly_remaining = max(weekly_limit - weekly_used, 0)
    period_pct = min(period_used / period_limit * 100, 100) if period_limit else 0
    weekly_pct = min(weekly_used / weekly_limit * 100, 100) if weekly_limit else 0

    eta_period_h = (period_remaining / rate_per_hour) if rate_per_hour > 1 else None
    eta_weekly_h = (weekly_remaining / rate_per_hour) if rate_per_hour > 1 else None

    # Days/hours until weekly reset
    next_reset = week_start + timedelta(weeks=1)
    time_to_reset = next_reset - now_naive
    reset_in_h = time_to_reset.total_seconds() / 3600

    # Daily history from stats-cache
    daily_history = []
    try:
        with open(STATS_CACHE) as f:
            cache = json.load(f)
        for day in cache.get("dailyModelTokens", [])[-7:]:
            total = sum(day["tokensByModel"].values())
            daily_history.append({"date": day["date"], "tokens": total})
    except Exception:
        pass

    label_mode = cfg.get("label_mode", "raw")  # "raw" | "pct"
    rate_fmt = fmt(rate_per_hour)
    if label_mode == "pct":
        panel_label = f"◆ {round(period_pct)}%  {rate_fmt}/h  |w {round(weekly_pct)}%"
    else:
        panel_label = (
            f"◆ {fmt(period_used)}/{fmt(period_limit)}  {rate_fmt}/h"
            f"  |w {fmt(weekly_used)}/{fmt(weekly_limit)}"
        )

    result = {
        "period": {**period_stats, "limit": period_limit, "pct": round(period_pct, 1),
                   "remaining": period_remaining, "hours": round(hours_in_period, 1),
                   "eta_hours": round(eta_period_h, 1) if eta_period_h else None},
        "weekly": {**weekly_stats, "limit": weekly_limit, "pct": round(weekly_pct, 1),
                   "remaining": weekly_remaining, "hours": round(hours_in_week, 1),
                   "reset_in_hours": round(reset_in_h, 1),
                   "eta_hours": round(eta_weekly_h, 1) if eta_weekly_h else None},
        "last_1h": last_1h_stats,
        "rate_per_hour": int(rate_per_hour),
        "label_mode": label_mode,
        "panel_label": panel_label,
        "week_start": week_start.isoformat(),
        "daily_history": daily_history,
        "fmt": {
            "period_used": fmt(period_used),
            "period_limit": fmt(period_limit),
            "period_remaining": fmt(period_remaining),
            "weekly_used": fmt(weekly_used),
            "weekly_limit": fmt(weekly_limit),
            "weekly_remaining": fmt(weekly_remaining),
            "rate": rate_fmt,
            "last_1h": fmt(last_1h_stats["effective"]),
            "output_period": fmt(period_stats["output"]),
        },
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
