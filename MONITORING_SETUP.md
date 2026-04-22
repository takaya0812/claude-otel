# Claude Code OTel 常時監視セットアップ

## 概要

全てのClaudeセッションのトークン使用量・コストをローカルで自動収集・可視化する仕組み。

```
Claude Code (全セッション)
  │  OTLP/HTTP (port 4318)  ← settings.json の env で常時有効
  ▼
OTel Collector (Docker, 常時起動)
  │  JSONL ファイル書き出し
  ▼
data/otel-logs.jsonl
  │  ingest.py --watch (常時起動)
  ▼
data/claude_code.db (SQLite)
  │  SQLite プラグイン
  ▼
Grafana (Docker, port 3000)
```

## 構成ファイル

| ファイル | 役割 |
|---|---|
| `docker-compose.yml` | OTel Collector + Grafana を定義 |
| `collector/config.yaml` | OTel Collector の受信・エクスポート設定 |
| `scripts/ingest.py` | JSONL → SQLite 変換スクリプト |
| `scripts/start-monitoring.sh` | 起動スクリプト（launchd から呼ばれる） |
| `~/Library/LaunchAgents/com.claude.otel-monitor.plist` | macOS ログイン時自動起動の設定 |
| `~/.claude/settings.json` | Claude Code へのテレメトリ送信設定 |

## 自動起動の仕組み

### launchd サービス

`~/Library/LaunchAgents/com.claude.otel-monitor.plist` により：
- macOS ログイン時に自動起動
- クラッシュ・停止時に自動再起動（`KeepAlive: true`）
- `start-monitoring.sh` を実行

### start-monitoring.sh の処理順序

1. Docker デーモンの起動を待機（最大60秒）
2. `docker compose up -d` でコレクター・Grafana を起動
3. 既存の `ingest.py --watch` プロセスを kill（重複防止）
4. `ingest.py --watch` を起動

### Claude Code のテレメトリ設定

`~/.claude/settings.json` の `env` セクション：

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
    "OTEL_RESOURCE_ATTRIBUTES": "user.email=t.nakanishi466@gmail.com"
  }
}
```

全セッションに自動適用されるため、個別設定不要。

## 確認方法

```bash
# サービス稼働確認
launchctl list | grep com.claude.otel-monitor

# Docker コンテナ確認
docker ps

# ingest プロセス確認
ps aux | grep "ingest.py"

# データ確認
sqlite3 ~/dev/claude-otel/data/claude_code.db \
  "SELECT date, total_usd FROM daily_cost ORDER BY date DESC LIMIT 7;"
```

Grafana: http://localhost:3000

## ログ

| ファイル | 内容 |
|---|---|
| `data/monitor.log` | start-monitoring.sh の標準出力 |
| `data/monitor-error.log` | エラーログ |
| `data/otel-logs.jsonl` | OTel 生データ |
| `data/claude_code.db` | 集計済み SQLite |

---

## 調査で判明した問題と対処

### 問題1: OTel Collector がファイルに書き込まない

**症状**: `otel-logs.jsonl` のタイムスタンプが11日前のまま。HTTP 200は返るがデータが永続化されない。

**原因**: コレクターが11日間起動し続け、ファイルハンドルが不正な状態になっていた可能性。

**対処**: `docker restart claude-otel-collector` で解消。

### 問題2: ingest.py が4プロセス重複起動

**症状**: launchd 起動分 + ターミナルで手動起動した分が混在。同一ファイルを複数プロセスが読み書きする状態。

**原因**: launchd の `KeepAlive: true` により再起動されるが、手動起動のプロセスが残っていた。

**対処**:
- 古いプロセス（PID 74062, 13272, 13242）を手動 kill
- `start-monitoring.sh` に `pkill -f "ingest.py --watch"` を追加し、以後は重複しない

### 問題3: OTEL_RESOURCE_ATTRIBUTES のフォーマット誤り

**症状**: `settings.json` の値が `"t.nakanishi466@gmail.com"` のみで、キーなし。

**原因**: README の `your@email.com` を直接置換し、`key=value` 形式にしなかった。

**対処**: `"user.email=t.nakanishi466@gmail.com"` に修正。
