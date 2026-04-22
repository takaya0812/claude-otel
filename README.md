# Claude Code OTel ローカル監視環境

Claude CodeのOpenTelemetryデータをローカルで収集・可視化する最小構成です。  
全てDockerで動作し、クラウド費用ゼロ。データはローカルに永続保存されます。

## 構成

```
Claude Code
  │  OTLP/HTTP (port 4318)
  ▼
OTel Collector (Docker)
  │  JSONL ファイル書き出し
  ▼
data/otel-logs.jsonl
  │  ingest.py (Python スクリプト)
  ▼
data/claude_code.db (SQLite)
  │  SQLite プラグイン
  ▼
Grafana (Docker, port 3000)
```

## セットアップ手順

### 1. Dockerを起動

```bash
cd claude-otel
docker compose up -d
```

Grafana が起動するまで30秒ほど待ちます。

### 2. Claude Codeに環境変数を設定

`~/.claude/settings.json` に追記します（ファイルがなければ新規作成）：

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
    "OTEL_RESOURCE_ATTRIBUTES": "user.email=your@email.com"
  }
}
```

`your@email.com` は実際のメールアドレスに変えてください。

### 3. 動作確認（テストデータ送信）

先にテストデータを送ってGrafanaで表示を確認できます：

```bash
python3 scripts/send_test_data.py
```

### 4. ingest.py を実行してSQLiteに取り込む

```bash
# 一回だけ実行
python3 scripts/ingest.py

# 継続監視モード（Claude Codeを使いながら自動取り込み）
python3 scripts/ingest.py --watch
```

### 5. Grafanaでダッシュボードを確認

ブラウザで http://localhost:3000 を開きます。  
ログイン不要で自動的にダッシュボードが表示されます。

## 日常的な使い方

Claude Codeを使い始める前に：

```bash
# Docker起動（初回以降は数秒で起動）
docker compose up -d

# バックグラウンドで自動取り込み
python3 scripts/ingest.py --watch &
```

作業後に http://localhost:3000 でコストやトークン使用量を確認できます。

## データファイル

| ファイル | 内容 |
|----------|------|
| `data/otel-logs.jsonl` | OTel Collectorが書き出す生データ |
| `data/claude_code.db` | SQLite DB（メインの永続ストア） |
| `data/claude_code.offset` | ingest.pyの読み込み位置記録 |

## SQLで直接分析する場合

```bash
sqlite3 data/claude_code.db

-- 日次コスト
SELECT * FROM daily_cost ORDER BY date DESC LIMIT 7;

-- モデル別集計
SELECT model, COUNT(*) AS calls, ROUND(SUM(cost_usd), 4) AS total_usd
FROM api_requests GROUP BY model;

-- セッション別サマリー
SELECT * FROM session_summary ORDER BY session_start DESC LIMIT 10;
```

## Docker停止

```bash
docker compose down
```
