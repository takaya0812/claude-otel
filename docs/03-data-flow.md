# 03 - データフロー

Claude Code の API 呼び出し 1 件が Grafana に表示されるまでの流れを追います。

## Step 1: Claude Code がテレメトリを送出

Claude Code CLI は以下の環境変数が設定されているとき、API 呼び出しのたびに OTel ログを送出します。

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_RESOURCE_ATTRIBUTES=user.email=you@example.com
```

送出されるデータは OTLP (OpenTelemetry Protocol) 形式で、HTTP POST `/v1/logs` に送られます。

## Step 2: OTel Collector が受信・バッファリング

OTel Collector (`collector/config.yaml`) が `0.0.0.0:4318` で待ち受けます。

受信したデータは **バッチプロセッサ** で一時的にバッファされます：
- `timeout: 5s` — 5 秒ごとにフラッシュ
- `send_batch_size: 256` — 256 件たまったら即フラッシュ

## Step 3: JSONL ファイルへ書き出し

バッチプロセッサを通過したデータはファイルエクスポータが `data/otel-logs.jsonl` に追記します。

各行は 1 件の OTel バッチで、以下の JSON 構造を持ちます：

```json
{
  "resourceLogs": [
    {
      "resource": {
        "attributes": [
          {"key": "user.email", "value": {"stringValue": "you@example.com"}},
          {"key": "service.version", "value": {"stringValue": "1.0.0"}},
          {"key": "os.type", "value": {"stringValue": "darwin"}},
          {"key": "host.arch", "value": {"stringValue": "arm64"}}
        ]
      },
      "scopeLogs": [
        {
          "logRecords": [
            {
              "attributes": [
                {"key": "event.name", "value": {"stringValue": "api_request"}},
                {"key": "session.id", "value": {"stringValue": "abc123"}},
                {"key": "model",      "value": {"stringValue": "claude-opus-4-5"}},
                {"key": "cost_usd",   "value": {"doubleValue": 0.00234}},
                {"key": "input_tokens",  "value": {"intValue": "1200"}},
                {"key": "output_tokens", "value": {"intValue": "340"}}
              ],
              "body": {"stringValue": "{\"event.name\": \"api_request\", ...}"}
            }
          ]
        }
      ]
    }
  ]
}
```

**注意**: OTel の `attributes` は `{key, value}` オブジェクトの配列形式で、値の型は `stringValue` / `intValue` / `doubleValue` などのラッパーに包まれています。

## Step 4: ingest.py が差分を読み取る

`ingest.py --watch` は 5 秒ごとに次の処理を行います：

1. `claude_code.offset` を読み取り、前回の読み取り終端バイト位置を取得
2. `otel-logs.jsonl` のファイルサイズと比較
3. 差分があれば `seek()` で末尾から読み、新規行だけを処理
4. 処理完了後に新しいバイト位置を `claude_code.offset` に書き戻す

## Step 5: JSONL パースと属性の正規化

各行のパースは 3 段階の属性マージで行われます：

```python
resource_attrs = parse_attributes(resource.attributes)   # リソース属性
log_attrs      = parse_attributes(record.attributes)     # ログ属性
body_data      = json.loads(record.body.stringValue)     # ボディ (JSON)

merged = {**resource_attrs, **log_attrs, **body_data}
# 上書き優先度: body_data > log_attrs > resource_attrs
```

`parse_attributes()` は OTel の `{key, value}` 配列形式をフラットな辞書に変換します：

```python
# 変換前
[{"key": "model", "value": {"stringValue": "claude-opus-4-5"}}]

# 変換後
{"model": "claude-opus-4-5"}
```

## Step 6: event.name による振り分け

マージされた属性の `event.name` によって挿入先テーブルが決まります：

```
event.name == "api_request"  →  api_requests テーブル
それ以外                      →  session_events テーブル
metrics / traces              →  raw_records テーブル
```

`api_request` は Claude Code が API 呼び出しのたびに送出するイベントで、コスト・トークン数などを含む最重要データです。

## Step 7: SQLite に格納

`api_requests` テーブルに主要フィールドが INSERT されます。full JSON も `raw_json` カラムに保存されるため、後から新フィールドを取り出すことができます。

## Step 8: Grafana が SQLite を直接クエリ

Grafana は `frser-sqlite-datasource` プラグインを通じて `data/claude_code.db` をクエリします。ダッシュボードパネルごとに SQL が定義されており、Grafana がリフレッシュ間隔（5 秒〜30 秒）で実行します。中間の API サーバーなどは存在せず、Grafana から SQLite ファイルへの直接アクセスです。
