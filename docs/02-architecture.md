# 02 - アーキテクチャ

## コンポーネント構成図

```
┌──────────────────────────────────────────────────────────────────┐
│  macOS ホスト                                                      │
│                                                                    │
│  ┌─────────────────────┐                                          │
│  │  Claude Code (CLI)  │  環境変数でテレメトリを有効化             │
│  │  CLAUDE_CODE_ENABLE_TELEMETRY=1                                │
│  │  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318            │
│  └──────────┬──────────┘                                          │
│             │ OTLP/HTTP POST /v1/logs                             │
│             ▼                                                      │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Docker Compose ネットワーク                               │    │
│  │                                                           │    │
│  │  ┌────────────────────┐    ┌──────────────────────────┐  │    │
│  │  │  OTel Collector    │    │  Grafana                 │  │    │
│  │  │  :4318             │    │  :3000                   │  │    │
│  │  │                    │    │  frser-sqlite-datasource │  │    │
│  │  │  receiver: otlp    │    │  2 dashboards            │  │    │
│  │  │  processor: batch  │    └──────────┬───────────────┘  │    │
│  │  │  exporter: file    │               │ SQL クエリ         │    │
│  │  └────────┬───────────┘               │                   │    │
│  │           │                           │                   │    │
│  └───────────┼───────────────────────────┼───────────────────┘    │
│              │ /data/otel-logs.jsonl     │                        │
│              ▼                           │                        │
│       ┌──────────────────┐              │                        │
│       │  data/           │◄─────────────┘                        │
│       │  otel-logs.jsonl │  /data/claude_code.db                  │
│       │  claude_code.db  │                                        │
│       │  claude_code.offset              │                        │
│       └──────┬───────────┘                                        │
│              │ tail + parse                                        │
│              ▼                                                     │
│       ┌──────────────────┐                                        │
│       │  ingest.py       │  Python プロセス（常駐）               │
│       │  --watch         │  5 秒間隔でポーリング                   │
│       └──────────────────┘                                        │
│                                                                    │
│  launchd → start-monitoring.sh → docker compose + ingest.py       │
└──────────────────────────────────────────────────────────────────┘
```

## ボリュームマウント

Docker Compose の `./data` ディレクトリが OTel Collector と Grafana の両コンテナ、そしてホストの `ingest.py` から共有されています。

```
./data (ホスト)
  ├── otel-logs.jsonl  ← Collector が書く、ingest.py が読む
  └── claude_code.db   ← ingest.py が書く、Grafana が読む
```

これにより 3 つのプロセスがファイルシステム経由で疎結合になっています。各コンポーネントは互いを知る必要がなく、ファイルの存在だけを前提とします。

## ポート一覧

| ポート | プロトコル | 用途 |
|---|---|---|
| 4318 | HTTP | OTLP 受信（Claude Code → Collector） |
| 3000 | HTTP | Grafana Web UI |

## コンテナ外で動くプロセス

`ingest.py --watch` は Docker コンテナではなくホストの Python プロセスとして動作します。理由は `./data` ディレクトリへのシンプルなファイルアクセスで足り、コンテナ化のオーバーヘッドが不要なためです。launchd が管理し、クラッシュ時は自動再起動されます。

## エンドツーエンド遅延

```
Claude Code API 呼び出し完了
    ↓ ~10-50ms
OTel Collector 受信
    ↓ バッチ処理（最大 5s）
JSONL ファイル書き出し
    ↓ ingest.py ポーリング（最大 5s）
SQLite INSERT
    ↓ Grafana クエリ（即時）
Grafana 画面表示

合計: 通常 10〜15 秒以内
```
