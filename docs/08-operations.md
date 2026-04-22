# 08 - 運用・トラブルシューティング

## 初回セットアップ

### 1. 環境変数を設定

`~/.zshrc` または `~/.zprofile` に追加：

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_RESOURCE_ATTRIBUTES=user.email=your@email.com
```

### 2. スタックを起動

```bash
cd /Users/takaya/dev/claude-otel
docker compose up -d
python3 scripts/ingest.py --watch
```

### 3. Grafana を確認

`http://localhost:3000` を開き、ダッシュボードが表示されれば完了です。

---

## macOS 自動起動（launchd）

### 設定ファイル

`~/Library/LaunchAgents/com.claude.otel-monitor.plist` で管理されます（このリポジトリには含まれていませんが、以下のような内容です）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" ...>
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude.otel-monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>/Users/takaya/dev/claude-otel/scripts/start-monitoring.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

`KeepAlive: true` により、スクリプトが終了した場合でも launchd が自動再起動します。

### `start-monitoring.sh` の動作

1. Docker daemon が起動するまで最大 60 秒待機（2 秒×30 回）
2. `docker compose up -d` でコンテナ起動
3. `pkill -f "ingest.py --watch"` で既存プロセスを強制終了（重複防止）
4. `exec` で `ingest.py --watch` に置き換わる（シェルプロセスが ingest に変換される）

---

## 日常の操作

### 状態確認

```bash
# コンテナの状態
docker ps

# ingest.py が動いているか
pgrep -a python3 | grep ingest

# Collector のログ
docker logs claude-otel-collector --tail 50

# DB の件数確認
sqlite3 data/claude_code.db "SELECT COUNT(*) FROM api_requests;"
```

### 停止

```bash
docker compose down
pkill -f "ingest.py --watch"
```

### 完全リセット

```bash
docker compose down -v          # ボリューム含めて削除
rm data/claude_code.db data/claude_code.offset data/otel-logs.jsonl
```

---

## トラブルシューティング

### データが Grafana に表示されない

**原因 1: ingest.py が動いていない**
```bash
pgrep -a python3 | grep ingest
# 出力がなければ起動
python3 scripts/ingest.py --watch &
```

**原因 2: OTel Collector がファイルを書けていない**
```bash
docker logs claude-otel-collector --tail 20
# エラーがあればコンテナを再起動
docker restart claude-otel-collector
```

**原因 3: オフセットがファイルサイズを超えている（ローテーション後）**
```bash
# オフセットをリセット
echo "0" > data/claude_code.offset
```

### Collector は動いているが JSONL が増えない（長期稼働後）

Collector がファイルハンドルを失う既知の問題です：

```bash
docker restart claude-otel-collector
```

### ingest.py が重複起動している

```bash
pgrep -a python3 | grep ingest
# 複数表示される場合
pkill -f "ingest.py --watch"
python3 scripts/ingest.py --watch &
```

### Grafana プラグインエラー

```
frser-sqlite-datasource: plugin not found
```

Grafana コンテナを再ビルドします：

```bash
docker compose down
docker compose up -d --force-recreate
```

---

## テストデータの送信

実際の Claude Code を使わずにシステムを動作確認する場合：

```bash
python3 scripts/send_test_data.py
```

7 日分×10 件/日 = 70 件のテストデータが OTel Collector 経由で投入されます。

---

## データの調査

SQLite に直接クエリを投げる場合：

```bash
sqlite3 data/claude_code.db

# 基本統計
SELECT
    COUNT(*) AS total_calls,
    ROUND(SUM(cost_usd), 4) AS total_cost,
    MIN(event_timestamp) AS first_event,
    MAX(event_timestamp) AS last_event
FROM api_requests;

# 最新 10 件
SELECT event_timestamp, model, cost_usd, input_tokens, output_tokens
FROM api_requests
ORDER BY event_timestamp DESC
LIMIT 10;
```

---

## 新しいメトリクスを追加する手順

1. `scripts/ingest.py` の `init_db()` にカラムを追加
2. `process_log_record()` に `extract_*(merged, "field.name")` で抽出を追加
3. 既存 DB には `ALTER TABLE api_requests ADD COLUMN new_col TYPE;` を実行
4. Grafana に新しいパネルを追加して JSON をエクスポート

既存の `raw_json` カラムに全データが保存されているため、スキーマ変更なしに `json_extract()` でアドホックなクエリも可能です。
