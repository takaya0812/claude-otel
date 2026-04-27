#!/usr/bin/env python3
"""
Claude Code OTel JSONL → SQLite 変換スクリプト

使い方:
  python3 ingest.py                    # 一回実行
  python3 ingest.py --watch            # ファイル監視して継続的に取り込み
  python3 ingest.py --jsonl /path/to/otel-logs.jsonl
"""

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_JSONL = Path(__file__).parent.parent / "data" / "otel-logs.jsonl"
DEFAULT_DB    = Path(__file__).parent.parent / "data" / "claude_code.db"


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS api_requests (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        ingested_at      TEXT    NOT NULL,
        event_timestamp  TEXT,
        session_id       TEXT,
        event_sequence   INTEGER,
        user_email       TEXT,
        user_id          TEXT,
        organization_id  TEXT,
        model            TEXT,
        cost_usd         REAL,
        duration_ms      INTEGER,
        input_tokens     INTEGER,
        output_tokens    INTEGER,
        cache_read_tokens     INTEGER,
        cache_creation_tokens INTEGER,
        service_version  TEXT,
        os_type          TEXT,
        host_arch        TEXT,
        raw_json         TEXT
    );

    CREATE TABLE IF NOT EXISTS session_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ingested_at     TEXT    NOT NULL,
        event_timestamp TEXT,
        session_id      TEXT,
        event_name      TEXT,
        user_email      TEXT,
        user_id         TEXT,
        organization_id TEXT,
        service_version TEXT,
        raw_json        TEXT
    );

    CREATE TABLE IF NOT EXISTS raw_records (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ingested_at TEXT NOT NULL,
        record_type TEXT,
        raw_json    TEXT
    );

    CREATE TABLE IF NOT EXISTS metrics (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        ingested_at      TEXT    NOT NULL,
        metric_name      TEXT,
        metric_timestamp TEXT,
        session_id       TEXT,
        user_email       TEXT,
        value            REAL,
        attributes       TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_api_session   ON api_requests(session_id);
    CREATE INDEX IF NOT EXISTS idx_api_ts        ON api_requests(event_timestamp);
    CREATE INDEX IF NOT EXISTS idx_api_email     ON api_requests(user_email);
    CREATE INDEX IF NOT EXISTS idx_api_model     ON api_requests(model);
    CREATE INDEX IF NOT EXISTS idx_sess_session  ON session_events(session_id);
    CREATE INDEX IF NOT EXISTS idx_sess_name     ON session_events(event_name);
    CREATE INDEX IF NOT EXISTS idx_metrics_name  ON metrics(metric_name);
    CREATE INDEX IF NOT EXISTS idx_metrics_ts    ON metrics(metric_timestamp);

    -- 便利なビュー: 日次コスト集計
    CREATE VIEW IF NOT EXISTS daily_cost AS
    SELECT
        DATE(event_timestamp) AS date,
        user_email,
        model,
        COUNT(*) AS api_calls,
        ROUND(SUM(cost_usd), 6)   AS total_cost_usd,
        SUM(input_tokens)         AS total_input_tokens,
        SUM(output_tokens)        AS total_output_tokens,
        SUM(cache_read_tokens)    AS total_cache_read_tokens,
        ROUND(AVG(duration_ms))   AS avg_duration_ms
    FROM api_requests
    WHERE event_timestamp IS NOT NULL
    GROUP BY DATE(event_timestamp), user_email, model;

    -- 便利なビュー: セッション別集計
    CREATE VIEW IF NOT EXISTS session_summary AS
    SELECT
        session_id,
        user_email,
        MIN(event_timestamp) AS session_start,
        MAX(event_timestamp) AS session_end,
        COUNT(*) AS api_calls,
        ROUND(SUM(cost_usd), 6) AS total_cost_usd,
        SUM(input_tokens)       AS total_input_tokens,
        SUM(output_tokens)      AS total_output_tokens,
        GROUP_CONCAT(DISTINCT model) AS models_used
    FROM api_requests
    WHERE session_id IS NOT NULL
    GROUP BY session_id, user_email;
    """)
    conn.commit()


def parse_attributes(attrs) -> dict:
    """OTel の attributes 配列 or dict を flat dict に変換"""
    result = {}
    if isinstance(attrs, list):
        for item in attrs:
            if isinstance(item, dict) and "key" in item:
                val = item.get("value", {})
                # { stringValue: "..." } / { intValue: "..." } / { doubleValue: ... }
                for vk, vv in val.items():
                    result[item["key"]] = vv
                    break
    elif isinstance(attrs, dict):
        result = attrs
    return result


def extract_string(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return str(v)
    return None


def extract_float(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def extract_int(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                pass
    return None


def process_metric_record(resource_metrics: dict, conn: sqlite3.Connection):
    """OTel resourceMetrics を metrics テーブルへ挿入"""
    resource_attrs = parse_attributes(
        resource_metrics.get("resource", {}).get("attributes", [])
    )
    now = datetime.now(timezone.utc).isoformat()

    _skip_keys = frozenset({
        "service.name", "service.version", "session.id", "user.email",
        "user.id", "user.account_uuid", "organization.id",
        "os.type", "os.version", "host.arch", "terminal.type",
    })

    for scope_metrics in resource_metrics.get("scopeMetrics", []):
        for metric in scope_metrics.get("metrics", []):
            metric_name = metric.get("name", "")
            if not metric_name.startswith("claude_code."):
                continue
            data_points = metric.get("sum", {}).get("dataPoints", [])
            for dp in data_points:
                dp_attrs = parse_attributes(dp.get("attributes", []))
                merged = {**resource_attrs, **dp_attrs}

                raw_value = dp.get("asDouble")
                if raw_value is None:
                    raw_value = dp.get("asInt")
                if raw_value is None:
                    continue

                ts_nano = dp.get("timeUnixNano", "0")
                try:
                    ts = datetime.fromtimestamp(
                        int(ts_nano) / 1e9, tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                except (ValueError, OverflowError):
                    ts = None

                extra = {k: v for k, v in merged.items() if k not in _skip_keys}

                conn.execute("""
                INSERT INTO metrics
                    (ingested_at, metric_name, metric_timestamp,
                     session_id, user_email, value, attributes)
                VALUES (?,?,?,?,?,?,?)
                """, (
                    now,
                    metric_name,
                    ts,
                    extract_string(merged, "session.id"),
                    extract_string(merged, "user.email"),
                    float(raw_value),
                    json.dumps(extra, ensure_ascii=False),
                ))


def migrate_metrics_from_raw_records(conn: sqlite3.Connection):
    """raw_records 内の既存メトリクスデータを metrics テーブルへ移行"""
    rows = conn.execute(
        "SELECT raw_json FROM raw_records WHERE record_type = 'metric'"
    ).fetchall()
    for (raw_json,) in rows:
        try:
            process_metric_record(json.loads(raw_json), conn)
        except Exception:
            pass
    conn.commit()


def process_log_record(record: dict, resource_attrs: dict, conn: sqlite3.Connection):
    """1件のログレコードを解析してDBに挿入"""
    body = record.get("body", {})
    # body が { stringValue: "{...}" } の場合は JSON パース
    body_str = body.get("stringValue", "") if isinstance(body, dict) else str(body)
    try:
        body_data = json.loads(body_str) if body_str.startswith("{") else {}
    except json.JSONDecodeError:
        body_data = {}

    log_attrs = parse_attributes(record.get("attributes", []))
    merged = {**resource_attrs, **log_attrs, **body_data}

    event_name = extract_string(merged, "event.name")
    now = datetime.now(timezone.utc).isoformat()

    if event_name == "api_request":
        conn.execute("""
        INSERT INTO api_requests
            (ingested_at, event_timestamp, session_id, event_sequence,
             user_email, user_id, organization_id, model,
             cost_usd, duration_ms, input_tokens, output_tokens,
             cache_read_tokens, cache_creation_tokens,
             service_version, os_type, host_arch, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            now,
            extract_string(merged, "event.timestamp"),
            extract_string(merged, "session.id"),
            extract_int(merged, "event.sequence"),
            extract_string(merged, "user.email"),
            extract_string(merged, "user.id", "user.account_uuid"),
            extract_string(merged, "organization.id"),
            extract_string(merged, "model"),
            extract_float(merged, "cost_usd"),
            extract_int(merged, "duration_ms"),
            extract_int(merged, "input_tokens"),
            extract_int(merged, "output_tokens"),
            extract_int(merged, "cache_read_tokens"),
            extract_int(merged, "cache_creation_tokens"),
            extract_string(merged, "service.version", "app.version"),
            extract_string(merged, "os.type"),
            extract_string(merged, "host.arch"),
            json.dumps(merged, ensure_ascii=False),
        ))
    else:
        conn.execute("""
        INSERT INTO session_events
            (ingested_at, event_timestamp, session_id, event_name,
             user_email, user_id, organization_id, service_version, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            now,
            extract_string(merged, "event.timestamp"),
            extract_string(merged, "session.id"),
            event_name,
            extract_string(merged, "user.email"),
            extract_string(merged, "user.id", "user.account_uuid"),
            extract_string(merged, "organization.id"),
            extract_string(merged, "service.version", "app.version"),
            json.dumps(merged, ensure_ascii=False),
        ))


def ingest_line(line: str, conn: sqlite3.Connection) -> int:
    """1行のJSONLを解析してDBに挿入。挿入件数を返す"""
    line = line.strip()
    if not line:
        return 0
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        print(f"  [skip] JSON parse error: {e}")
        return 0

    count = 0
    now = datetime.now(timezone.utc).isoformat()

    # OTel JSONL の構造: { "resourceLogs": [...] } or { "resourceMetrics": [...] }
    for resource_logs in data.get("resourceLogs", []):
        resource_attrs = parse_attributes(
            resource_logs.get("resource", {}).get("attributes", [])
        )
        for scope_logs in resource_logs.get("scopeLogs", []):
            for record in scope_logs.get("logRecords", []):
                process_log_record(record, resource_attrs, conn)
                count += 1

    # metrics: raw_records に保存しつつ metrics テーブルへも展開
    for resource_metrics in data.get("resourceMetrics", []):
        conn.execute(
            "INSERT INTO raw_records (ingested_at, record_type, raw_json) VALUES (?,?,?)",
            (now, "metric", json.dumps(resource_metrics, ensure_ascii=False))
        )
        process_metric_record(resource_metrics, conn)
        count += 1

    for resource_spans in data.get("resourceSpans", []):
        conn.execute(
            "INSERT INTO raw_records (ingested_at, record_type, raw_json) VALUES (?,?,?)",
            (now, "trace", json.dumps(resource_spans, ensure_ascii=False))
        )
        count += 1

    return count


def ingest_file(jsonl_path: Path, db_path: Path, offset_path: Path):
    """ファイルの未読部分を読み込んでDBに挿入"""
    if not jsonl_path.exists():
        return 0

    offset = int(offset_path.read_text()) if offset_path.exists() else 0
    file_size = jsonl_path.stat().st_size
    if file_size <= offset:
        return 0

    conn = sqlite3.connect(db_path)
    init_db(conn)

    metrics_count = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    if metrics_count == 0:
        migrate_metrics_from_raw_records(conn)

    total = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        f.seek(offset)
        for line in f:
            total += ingest_line(line, conn)
        new_offset = f.tell()

    conn.commit()
    conn.close()
    offset_path.write_text(str(new_offset))
    return total


def main():
    parser = argparse.ArgumentParser(description="Claude Code OTel JSONL → SQLite")
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--db",   type=Path, default=DEFAULT_DB)
    parser.add_argument("--watch", action="store_true", help="継続監視モード (5秒間隔)")
    args = parser.parse_args()

    offset_path = args.db.with_suffix(".offset")

    print(f"JSONL: {args.jsonl}")
    print(f"DB:    {args.db}")

    if args.watch:
        print("監視モード開始 (Ctrl+C で停止)")
        while True:
            n = ingest_file(args.jsonl, args.db, offset_path)
            if n:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {n}件 取り込み完了")
            time.sleep(5)
    else:
        n = ingest_file(args.jsonl, args.db, offset_path)
        print(f"取り込み完了: {n}件")


if __name__ == "__main__":
    main()
