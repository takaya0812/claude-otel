#!/usr/bin/env python3
"""
OTel Collectorへのテストデータ送信スクリプト
実際のClaude CodeのOTel出力を模したダミーデータを送信します
"""

import json
import random
import time
import urllib.request
from datetime import datetime, timezone, timedelta

ENDPOINT = "http://localhost:4318/v1/logs"
MODELS = ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"]

def make_log_body(event_name: str, session_id: str, seq: int, ts: str) -> dict:
    base = {
        "event.name": event_name,
        "event.timestamp": ts,
        "event.sequence": seq,
        "session.id": session_id,
        "user.email": "your@email.com",
        "service.name": "claude-code",
        "service.version": "1.0.0",
        "os.type": "darwin",
        "host.arch": "arm64",
    }
    if event_name == "api_request":
        model = random.choice(MODELS)
        input_t = random.randint(500, 8000)
        output_t = random.randint(100, 2000)
        # 簡易コスト計算（実際と異なります）
        price = {"claude-opus-4-5": (0.000015, 0.000075),
                 "claude-sonnet-4-5": (0.000003, 0.000015),
                 "claude-haiku-4-5": (0.00000025, 0.00000125)}
        ip, op = price[model]
        cost = round(input_t * ip + output_t * op, 8)
        base.update({
            "model": model,
            "input_tokens": input_t,
            "output_tokens": output_t,
            "cache_read_tokens": random.randint(0, 3000),
            "cache_creation_tokens": random.randint(0, 1000),
            "cost_usd": cost,
            "duration_ms": random.randint(500, 8000),
        })
    return base


def send_test_data(days: int = 7, requests_per_day: int = 10):
    now = datetime.now(timezone.utc)
    total_sent = 0

    for day_offset in range(days, -1, -1):
        day = now - timedelta(days=day_offset)
        session_id = f"test-session-{day.strftime('%Y%m%d')}"

        for i in range(requests_per_day):
            ts = (day + timedelta(hours=random.uniform(9, 22))).isoformat()
            body = make_log_body("api_request", session_id, i, ts)

            payload = {
                "resourceLogs": [{
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "claude-code"}},
                            {"key": "user.email",   "value": {"stringValue": "your@email.com"}},
                        ]
                    },
                    "scopeLogs": [{
                        "logRecords": [{
                            "timeUnixNano": str(int(day.timestamp() * 1e9)),
                            "body": {"stringValue": json.dumps(body)},
                            "attributes": []
                        }]
                    }]
                }]
            }

            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                ENDPOINT,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=3) as resp:
                    total_sent += 1
                    print(f"  送信: {ts[:19]} model={body.get('model')} cost=${body.get('cost_usd', 0):.6f}")
            except Exception as e:
                print(f"  エラー: {e}")
                print("  OTel Collectorが起動しているか確認してください (docker compose up -d)")
                return

    print(f"\n合計 {total_sent} 件のテストデータを送信しました")


if __name__ == "__main__":
    print("=== Claude Code OTel テストデータ送信 ===")
    print(f"エンドポイント: {ENDPOINT}")
    print("過去7日分 × 10リクエスト/日 を送信します\n")
    send_test_data(days=7, requests_per_day=10)
