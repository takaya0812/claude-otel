# 07 - Grafana ダッシュボード

## プロビジョニングの仕組み

Grafana 起動時に `grafana/provisioning/` 以下のファイルが自動的に読み込まれます。手動でインポートする必要はありません。

```
grafana/provisioning/
├── datasources/sqlite.yaml     # データソース設定
└── dashboards/
    ├── provider.yaml           # ダッシュボード読み込み元ディレクトリ指定
    ├── claude-code.json        # 履歴ダッシュボード
    └── realtime-monitor.json   # リアルタイムダッシュボード
```

## データソース設定

`grafana/provisioning/datasources/sqlite.yaml`:

```yaml
datasources:
  - name: Claude Code Telemetry
    type: frser-sqlite-datasource     # コミュニティプラグイン
    access: proxy
    isDefault: true
    jsonData:
      path: /data/claude_code.db      # コンテナ内パス（./data にマウント）
```

`frser-sqlite-datasource` は Grafana の Docker イメージ起動時に `GF_INSTALL_PLUGINS=frser-sqlite-datasource` で自動インストールされます（`docker-compose.yml` に設定済み）。

## claude-code.json: 履歴ダッシュボード

**UID**: `claude-code-telemetry`  
**デフォルト時間範囲**: 過去 30 日  
**リフレッシュ間隔**: 30 秒

### パネル構成

| パネル | 種類 | データソース |
|---|---|---|
| 総 API 呼び出し数 | Stat | `api_requests` COUNT |
| 総コスト (USD) | Stat | `api_requests` SUM(cost_usd) |
| 平均レスポンス時間 | Stat | `api_requests` AVG(duration_ms) |
| キャッシュ効率 (%) | Stat | cache_read / (input + cache_read) |
| モデル別コスト内訳 | Pie chart | GROUP BY model |
| 日次コスト推移 | Timeseries | `daily_cost` ビュー |
| 日次トークン推移 | Timeseries | `daily_cost` ビュー |
| セッション一覧 | Table | `session_summary` ビュー |

### 代表的な SQL パターン

```sql
-- 総コスト
SELECT ROUND(SUM(cost_usd), 4)
FROM api_requests
WHERE $__timeFilter(event_timestamp)

-- 日次コスト（タイムシリーズ）
SELECT
    strftime('%Y-%m-%dT%H:%M:%SZ', DATE(event_timestamp)) AS time,
    ROUND(SUM(cost_usd), 6) AS cost_usd
FROM api_requests
WHERE $__timeFilter(event_timestamp)
GROUP BY DATE(event_timestamp)
ORDER BY time
```

`$__timeFilter(event_timestamp)` は Grafana のマクロで、ダッシュボードの時間範囲に応じて自動的に WHERE 条件に展開されます。

## realtime-monitor.json: リアルタイムダッシュボード

**UID**: `claude-code-realtime`  
**デフォルト時間範囲**: 過去 30 分  
**リフレッシュ間隔**: 5 秒

直近の活動状況を把握するための監視用ダッシュボードです。

### パネル構成

| パネル | 種類 | 用途 |
|---|---|---|
| 過去 30 分の API 呼び出し数 | Stat | 現在アクティブかの確認 |
| 過去 30 分のコスト | Stat | 直近のコスト |
| アクティブセッション数 | Stat | 同時進行セッション |
| キャッシュ効率 | Gauge | 直近のキャッシュ状況 |
| 5 分バケットの API 呼び出し | Bar chart | 活動パターン |
| イベントストリーム | Table | 直近 50 件のリアルタイムログ |
| ツール使用ランキング | Table | よく使われるツールTOP |
| セッション詳細 | Table | 進行中セッションの概要 |

### イベントストリームの SQL

```sql
SELECT event_timestamp, 'api_request' AS type, model, cost_usd
FROM api_requests
WHERE $__timeFilter(event_timestamp)
UNION ALL
SELECT event_timestamp, event_name AS type, NULL, NULL
FROM session_events
WHERE $__timeFilter(event_timestamp)
ORDER BY event_timestamp DESC
LIMIT 50
```

`UNION ALL` で `api_requests` と `session_events` を統合し、時系列で見せています。

## Grafana へのアクセス

```
http://localhost:3000
```

認証不要（匿名ログイン有効）。左サイドバーの Dashboards から "Claude Code" フォルダを選びます。

## ダッシュボードの変更方法

Grafana UI で変更した内容を永続化するには JSON をエクスポートして `grafana/provisioning/dashboards/` の該当ファイルに上書きする必要があります。UI での変更は Grafana ボリューム (`grafana-storage`) に保存されますが、ボリュームを削除するとリセットされます。

```bash
# Grafana API でダッシュボード JSON を取得
curl http://localhost:3000/api/dashboards/uid/claude-code-telemetry \
  | jq '.dashboard' > grafana/provisioning/dashboards/claude-code.json
```
