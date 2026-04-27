#!/usr/bin/env python3
"""
Analyze tool usage from Claude Code OTel data and generate settings recommendations.

Usage:
    # From local SQLite DB
    python3 scripts/recommend_settings.py [--days N] [--db PATH] [--settings PATH]

    # From exported JSON (e.g. in GitHub Actions)
    python3 scripts/recommend_settings.py --from-json data/tool_stats_export.json
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "data" / "claude_code.db"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
DEFAULT_DAYS = 7
MIN_USES_THRESHOLD = 3      # ignore tools used fewer than this
RECOMMEND_ACCEPT_RATE = 95  # recommend auto-allow above this %


def load_settings(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def get_allowed_tools(settings: dict) -> set[str]:
    allow_list = settings.get("permissions", {}).get("allow", [])
    allowed = set()
    for entry in allow_list:
        # e.g. "Read", "Bash(git log *)", "mcp__foo__bar"
        tool = entry.split("(")[0]
        allowed.add(tool)
    return allowed


def query_tool_stats(db_path: Path, days: int) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path)
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
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_daily_stats(db_path: Path, days: int) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            strftime('%Y-%m-%d', event_timestamp)  AS day,
            json_extract(raw_json, '$.tool_name')  AS tool,
            COUNT(*)                                AS uses,
            SUM(CASE WHEN json_extract(raw_json, '$.decision') = 'accept'
                     THEN 1 ELSE 0 END)            AS accepts
        FROM session_events
        WHERE event_name = 'tool_decision'
          AND event_timestamp >= ?
          AND json_extract(raw_json, '$.tool_name') IS NOT NULL
        GROUP BY day, tool
        ORDER BY day DESC, uses DESC
        """,
        (since,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def build_report(stats: list[dict], daily: list[dict], allowed: set[str], days: int) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Claude Code 設定おすすめレポート",
        f"",
        f"生成日時: {now}　分析期間: 直近 {days} 日",
        f"",
    ]

    # --- Summary ---
    total_uses = sum(r["total"] for r in stats)
    total_accepts = sum(r["accepts"] for r in stats)
    total_rejects = sum(r["rejects"] for r in stats)
    overall_rate = 100 * total_accepts / total_uses if total_uses else 0

    lines += [
        "## サマリー",
        "",
        f"| 項目 | 値 |",
        f"|---|---|",
        f"| 総ツール使用回数 | {total_uses} |",
        f"| 総 accept 数 | {total_accepts} |",
        f"| 総 reject 数 | {total_rejects} |",
        f"| 全体 accept 率 | {overall_rate:.1f}% |",
        f"| 分析対象ツール数 | {len(stats)} |",
        "",
    ]

    # --- Per-tool stats ---
    lines += [
        "## ツール別使用状況",
        "",
        "| ツール | 使用回数 | accept | reject | accept 率 | 自動許可済み |",
        "|---|---|---|---|---|---|",
    ]
    for r in stats:
        rate = 100 * r["accepts"] / r["total"] if r["total"] else 0
        is_allowed = "✅" if r["tool"] in allowed else "—"
        lines.append(
            f"| {r['tool']} | {r['total']} | {r['accepts']} | {r['rejects']} "
            f"| {rate:.1f}% | {is_allowed} |"
        )
    lines.append("")

    # --- Daily breakdown ---
    lines += ["## 日別ツール使用数（上位ツール）", ""]
    days_seen: dict[str, dict[str, int]] = {}
    top_tools = [r["tool"] for r in stats[:6]]
    for row in daily:
        days_seen.setdefault(row["day"], {})
        if row["tool"] in top_tools:
            days_seen[row["day"]][row["tool"]] = row["uses"]

    header = "| 日付 | " + " | ".join(top_tools) + " |"
    sep = "|---|" + "---|" * len(top_tools)
    lines += [header, sep]
    for day in sorted(days_seen.keys(), reverse=True):
        cells = [str(days_seen[day].get(t, 0)) for t in top_tools]
        lines.append(f"| {day} | " + " | ".join(cells) + " |")
    lines.append("")

    # --- Recommendations ---
    recommend = [
        r for r in stats
        if r["total"] >= MIN_USES_THRESHOLD
        and (100 * r["accepts"] / r["total"]) >= RECOMMEND_ACCEPT_RATE
        and r["tool"] not in allowed
    ]

    lines += ["## おすすめ設定変更", ""]

    if not recommend:
        lines += [
            "現在の設定は最適です。頻繁に使うツールはすべて自動許可済みです。",
            "",
        ]
    else:
        lines += [
            f"以下のツールは **accept 率 {RECOMMEND_ACCEPT_RATE}% 以上** かつ **{MIN_USES_THRESHOLD} 回以上使用** されていますが、",
            "自動許可されていません。`~/.claude/settings.json` の `permissions.allow` に追加すると",
            "確認ダイアログを減らせます。",
            "",
            "| ツール | 使用回数 | accept 率 | 推奨追加エントリ |",
            "|---|---|---|---|",
        ]
        for r in recommend:
            rate = 100 * r["accepts"] / r["total"]
            lines.append(f"| {r['tool']} | {r['total']} | {rate:.1f}% | `\"{r['tool']}\"` |")
        lines.append("")

        # Show the JSON diff
        new_entries = [r["tool"] for r in recommend]
        lines += [
            "### settings.json への追加例",
            "",
            "```json",
            '"permissions": {',
            '  "allow": [',
            '    // ... 既存のエントリ ...',
        ]
        for entry in new_entries:
            lines.append(f'    "{entry}",')
        lines += [
            '  ]',
            '}',
            "```",
            "",
        ]

    # --- Already good ---
    already_good = [
        r for r in stats
        if r["tool"] in allowed
        and r["total"] >= MIN_USES_THRESHOLD
    ]
    if already_good:
        lines += [
            "## 既に最適化済みのツール",
            "",
            "以下は頻繁に使われており、かつ自動許可設定済みです。",
            "",
            "| ツール | 使用回数 |",
            "|---|---|",
        ]
        for r in already_good:
            lines.append(f"| {r['tool']} | {r['total']} |")
        lines.append("")

    # --- Reject analysis ---
    rejected = [r for r in stats if r["rejects"] > 0]
    if rejected:
        lines += [
            "## reject されたツール（注意）",
            "",
            "以下のツールは一度以上 reject されています。意図的な操作か確認してください。",
            "",
            "| ツール | reject 数 | accept 数 |",
            "|---|---|---|",
        ]
        for r in rejected:
            lines.append(f"| {r['tool']} | {r['rejects']} | {r['accepts']} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate Claude Code settings recommendations")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Analysis window in days")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to SQLite DB")
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH, help="Path to settings.json")
    parser.add_argument("--from-json", type=Path, dest="from_json", help="Load stats from export JSON instead of DB")
    parser.add_argument("--output", type=Path, help="Write report to file instead of stdout")
    args = parser.parse_args()

    if args.from_json:
        # GitHub Actions mode: load from committed JSON export
        if not args.from_json.exists():
            print(f"Error: export JSON not found at {args.from_json}")
            return 1
        with open(args.from_json) as f:
            export = json.load(f)
        allowed = set(export.get("allowed_tools", []))
        stats = export["tool_stats"]
        daily = export["daily_stats"]
        days = export.get("days", DEFAULT_DAYS)
    else:
        if not args.db.exists():
            print(f"Error: DB not found at {args.db}")
            print("Run: python3 scripts/ingest.py")
            return 1
        settings = load_settings(args.settings)
        allowed = get_allowed_tools(settings)
        stats = query_tool_stats(args.db, args.days)
        daily = query_daily_stats(args.db, args.days)
        days = args.days

    if not stats:
        print(f"No tool_decision data found.")
        return 0

    report = build_report(stats, daily, allowed, days)

    if args.output:
        args.output.write_text(report)
        print(f"Report written to: {args.output}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
