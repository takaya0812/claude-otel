#!/usr/bin/env python3
"""
Export aggregated tool stats from SQLite to JSON for GitHub Actions analysis.

Usage:
    python3 scripts/export_stats.py [--days N] [--db PATH] [--out PATH]
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "claude_code.db"
OUT_PATH = Path(__file__).parent.parent / "data" / "tool_stats_export.json"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
DEFAULT_DAYS = 30


def get_allowed_tools(settings_path: Path) -> list[str]:
    if not settings_path.exists():
        return []
    with open(settings_path) as f:
        s = json.load(f)
    allow_list = s.get("permissions", {}).get("allow", [])
    return list({e.split("(")[0] for e in allow_list})


def query_tool_stats(conn: sqlite3.Connection, since: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            json_extract(raw_json, '$.tool_name')  AS tool,
            COUNT(*)                                AS total,
            SUM(CASE WHEN json_extract(raw_json, '$.decision') = 'accept'
                     THEN 1 ELSE 0 END)            AS accepts,
            SUM(CASE WHEN json_extract(raw_json, '$.decision') = 'reject'
                     THEN 1 ELSE 0 END)            AS rejects,
            MIN(event_timestamp)                    AS first_seen,
            MAX(event_timestamp)                    AS last_seen
        FROM session_events
        WHERE event_name = 'tool_decision'
          AND event_timestamp >= ?
          AND json_extract(raw_json, '$.tool_name') IS NOT NULL
        GROUP BY tool
        ORDER BY total DESC
        """,
        (since,),
    )
    return [dict(r) for r in cur.fetchall()]


def query_daily_stats(conn: sqlite3.Connection, since: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            strftime('%Y-%m-%d', event_timestamp)  AS day,
            json_extract(raw_json, '$.tool_name')  AS tool,
            COUNT(*)                                AS uses,
            SUM(CASE WHEN json_extract(raw_json, '$.decision') = 'accept'
                     THEN 1 ELSE 0 END)            AS accepts,
            SUM(CASE WHEN json_extract(raw_json, '$.decision') = 'reject'
                     THEN 1 ELSE 0 END)            AS rejects
        FROM session_events
        WHERE event_name = 'tool_decision'
          AND event_timestamp >= ?
          AND json_extract(raw_json, '$.tool_name') IS NOT NULL
        GROUP BY day, tool
        ORDER BY day DESC, uses DESC
        """,
        (since,),
    )
    return [dict(r) for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH)
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: DB not found at {args.db}")
        return 1

    since = (datetime.utcnow() - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(args.db)
    tool_stats = query_tool_stats(conn, since)
    daily_stats = query_daily_stats(conn, since)
    conn.close()

    export = {
        "exported_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": args.days,
        "allowed_tools": get_allowed_tools(args.settings),
        "tool_stats": tool_stats,
        "daily_stats": daily_stats,
    }

    args.out.parent.mkdir(exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(tool_stats)} tools, {len(daily_stats)} daily rows → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
