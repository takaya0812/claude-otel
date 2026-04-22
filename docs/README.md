# claude-otel 技術ガイド

Claude Code の API 利用をローカルで監視するシステムの技術解説です。

## ドキュメント一覧

| ファイル | 内容 |
|---|---|
| [01-overview.md](01-overview.md) | システム全体像・目的・主要コンポーネント |
| [02-architecture.md](02-architecture.md) | アーキテクチャ図・コンポーネント間の接続 |
| [03-data-flow.md](03-data-flow.md) | データの流れ（Claude Code → Grafana まで） |
| [04-otel-collector.md](04-otel-collector.md) | OTel Collector の設定と動作 |
| [05-ingest-pipeline.md](05-ingest-pipeline.md) | ingest.py の解析ロジック詳解 |
| [06-data-model.md](06-data-model.md) | SQLite スキーマ・ビュー・クエリ例 |
| [07-grafana-dashboards.md](07-grafana-dashboards.md) | Grafana ダッシュボードの構成 |
| [08-operations.md](08-operations.md) | 起動・停止・トラブルシューティング |
| [09-otel-data-inventory.md](09-otel-data-inventory.md) | Claude Code OTel で取得可能な全データと本プロジェクトでの収集・可視化状況 |

## 推奨読書順

初めて読む場合は上から順に読むことを推奨します。特定のコンポーネントだけ知りたい場合は直接該当ページへ。
