# 01 - システム概要

## 目的

Claude Code が Anthropic API を呼び出すたびに発生する使用量データ（トークン数・コスト・レイテンシなど）を、クラウドサービスを一切使わずローカルで収集・可視化するシステムです。

## 解決する問題

Claude Code は OpenTelemetry (OTel) プロトコルでテレメトリを送出する機能を持っています。しかし受信エンドポイントがなければデータは捨てられます。このプロジェクトはそのエンドポイントをローカルに立て、SQLite に永続化し、Grafana で閲覧できるようにします。

## 主要コンポーネント

```
Claude Code CLI
    ↓ OTLP/HTTP (port 4318)
OTel Collector  ← Docker コンテナ
    ↓ JSONL ファイル書き出し
ingest.py       ← Python プロセス（常駐）
    ↓ SQLite INSERT
claude_code.db  ← SQLite データベース
    ↓ frser-sqlite-datasource プラグイン
Grafana         ← Docker コンテナ（port 3000）
```

## 技術スタック

| 役割 | 技術 |
|---|---|
| テレメトリ収集 | opentelemetry-collector-contrib |
| データ永続化 | SQLite 3 |
| ETL | Python 3 (ingest.py) |
| 可視化 | Grafana + frser-sqlite-datasource |
| コンテナ管理 | Docker Compose |
| macOS 自動起動 | launchd |

## 設計上の特徴

**オフセット追跡による増分取り込み**  
`ingest.py` は JSONL ファイルの読み取りバイト位置を `.offset` ファイルに記録します。再起動後も続きから読め、重複取り込みを防ぎます。

**ゼロ認証**  
Grafana は匿名ログインを有効にしており、ローカル専用のため認証不要です。

**プロビジョニング**  
Grafana のデータソースとダッシュボードは起動時に自動設定されます。手動操作なしで即座に使えます。

## ディレクトリ構成

```
claude-otel/
├── docker-compose.yml          # サービス定義
├── collector/
│   └── config.yaml             # OTel Collector 設定
├── grafana/
│   └── provisioning/
│       ├── dashboards/
│       │   ├── provider.yaml   # ダッシュボード読み込み設定
│       │   ├── claude-code.json        # 履歴ダッシュボード
│       │   └── realtime-monitor.json   # リアルタイムダッシュボード
│       └── datasources/
│           └── sqlite.yaml     # SQLite データソース設定
├── scripts/
│   ├── ingest.py               # JSONL → SQLite 変換（メイン処理）
│   ├── send_test_data.py       # テストデータ生成
│   └── start-monitoring.sh     # launchd 用起動スクリプト
└── data/                       # 実行時データ（git 管理外）
    ├── otel-logs.jsonl         # OTel Collector の出力
    ├── claude_code.db          # SQLite DB
    └── claude_code.offset      # 読み取り位置
```
