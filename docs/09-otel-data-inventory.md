# Claude Code OTel データインベントリ

Claude Code が OpenTelemetry 経由で出力できる**全データ**と、本プロジェクトでの **収集 / 可視化 状況** をまとめたもの。

凡例:

- **収集**: `data/otel-logs.jsonl` → `data/claude_code.db` に取り込まれているか
  - ✅ 収集あり（DBに実データあり）
  - ⚠️ 収集パイプラインは通るが該当レコードが生成される条件に未到達（例: PR 作成、コミット作成など）
  - ❌ 収集していない（パイプラインで落としている）
- **可視化**: Grafana ダッシュボード（[claude-code.json](../grafana/provisioning/dashboards/claude-code.json) / [realtime-monitor.json](../grafana/provisioning/dashboards/realtime-monitor.json) / [activity-analysis.json](../grafana/provisioning/dashboards/activity-analysis.json)）で表示されているか
  - ✅ パネルあり
  - 🔶 DB には入っているが専用パネルなし（`raw_json` 等からクエリすれば可視化可能）
  - ❌ パネルなし

---

## 1. シグナル種別（OTLP 3シグナル）

| シグナル | OTLP フィールド | 収集 | 格納先 | 可視化 | 備考 |
|---|---|---|---|---|---|
| Logs（Events） | `resourceLogs` | ✅ | `api_requests` / `session_events` | ✅ 一部 | `event.name` ごとに構造化 |
| Metrics | `resourceMetrics` | ✅ | `raw_records` + `metrics` | ✅ 一部 | `ingest.py` が `metrics` テーブルへ展開。active_time / lines_of_code / code_edit_tool を可視化 |
| Traces | `resourceSpans` | ⚠️ | `raw_records` (record_type='trace') | ❌ | Claude Code は現状 traces を出さない（収集器は受け口のみ確保） |

> メトリクスは集計値として独立シグナルで流れているが、現在の Grafana 可視化は **Logs の `api_request` イベントを SQL 集計した値**のみを使用している。メトリクスを使った可視化は未実装。

---

## 2. Resource 属性（全レコード共通）

Claude Code 起動環境のメタデータ。全イベント/メトリクスに付与される。

| 属性 | 収集 | 可視化 | 用途例 |
|---|---|---|---|
| `service.name` (= `claude-code`) | ✅ | ❌ | サービス識別 |
| `service.version` | ✅ | ✅ | バージョン別 API リクエスト数（activity-analysis） |
| `os.type` | ✅ | ✅ | OS / アーキテクチャ別リクエスト数（activity-analysis） |
| `os.version` | ✅ | ❌ | 〃 |
| `host.arch` | ✅ | ✅ | OS / アーキテクチャ別リクエスト数（activity-analysis） |
| `user.id` (ハッシュ) | ✅ | ❌ | 擬似匿名ユーザ ID |
| `user.email` | ✅ | 🔶 | セッションテーブル列あり。フィルタ用パネルは未作成 |
| `user.account_uuid` | ✅ | ❌ | 課金アカウント UUID |
| `user.account_id` | ✅ | ❌ | 課金アカウント ID |
| `organization.id` | ✅ | ❌ | 組織 ID |
| `terminal.type` | ✅ | ✅ | ターミナル種別別セッション数（activity-analysis） |
| `session.id` | ✅ | ✅ | セッション集計・フィルタ |

---

## 3. Logs / Events

`event.name` をキーに構造化。共通属性として `event.timestamp` / `event.sequence` / `session.id` / `prompt.id`（該当時）が付く。

### 3.1 `api_request` — API 呼び出し 1件ごと（コスト・トークンの主ソース）

本プロジェクトではこれを `api_requests` テーブルに正規化している。ダッシュボードの大半がここから算出。

| フィールド | 収集 | 可視化 | 可視化先パネル |
|---|---|---|---|
| `model` | ✅ | ✅ | モデル別コスト割合 / モデル別呼び出し回数 |
| `cost_usd` | ✅ | ✅ | 累計/今月/今日/日次コスト, 平均コスト/セッション |
| `duration_ms` | ✅ | ✅ | 平均応答時間, 直近 API リクエスト表 |
| `input_tokens` | ✅ | ✅ | 累計/今月/今日 入力トークン, 日次トークン |
| `output_tokens` | ✅ | ✅ | 累計/今月/今日 出力トークン, 日次トークン |
| `cache_read_tokens` | ✅ | ✅ | キャッシュ効率, キャッシュヒット数, 今日のキャッシュ読取 |
| `cache_creation_tokens` | ✅ | ✅ | 日次トークン（cache_creation 系列） |
| `service.version` | ✅ | ✅ | バージョン別 API リクエスト数（activity-analysis） |
| `os.type` / `host.arch` | ✅ | ✅ | OS / アーキテクチャ別リクエスト数（activity-analysis） |

### 3.2 `user_prompt` — ユーザが入力したプロンプト

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `prompt.id` | ✅ | ❌ | — |
| `prompt_length` | ✅ | ✅ | 平均プロンプト長・日次プロンプト数推移（activity-analysis） |
| `prompt` | ⚠️ | ❌ | `<REDACTED>` で来る（Claude Code デフォルトで内容マスク） |
| 件数カウント | ✅ | ✅ | リアルタイム「直近2時間 ユーザープロンプト」・総プロンプト数（activity-analysis） |

### 3.3 `tool_result` — ツール実行結果

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `tool_name` | ✅ | ✅ | ツール使用ランキング（全期間 / 直近2時間）|
| `success` | ✅ | ✅ | ツール成功率・失敗数（activity-analysis） |
| `duration_ms` | ✅ | ✅ | 平均/最大ツール実行時間・ツール別平均実行時間（activity-analysis） |
| `tool_result_size_bytes` | ✅ | ✅ | ツール別平均ペイロードサイズ（activity-analysis） |
| `decision_source` / `decision_type` | ✅ | ❌ | ツール許可経路の可視化は未実装 |

### 3.4 `tool_decision` — ツール許可ダイアログの決定

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `tool_name` | ✅ | ✅ | ツール別 accept/reject 件数（activity-analysis） |
| `decision` (`accept` / `reject`) | ✅ | ✅ | ツール accept 率（activity-analysis） |
| `source` (`config` / `user_permanent` / ...) | ✅ | ✅ | 許可経路別 accept 件数（activity-analysis） |

### 3.5 `api_error` — API リクエスト失敗

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `model` | ✅ | ✅ | モデル別 API エラー数（activity-analysis） |
| `error` | ✅ | ✅ | API エラー詳細一覧（activity-analysis） |
| `status_code` | ✅ | ✅ | 〃 |
| `duration_ms` | ✅ | ✅ | API エラー時平均レイテンシ（activity-analysis） |
| `attempt` | ✅ | ✅ | リトライ回数別 API エラー数（activity-analysis） |

### 3.6 `internal_error` — Claude Code 内部エラー

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `error_name` | ✅ | ✅ | 内部エラー数（activity-analysis） |

### 3.7 `auth` — 認証イベント

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `action` (`login` など) | ✅ | ✅ | 認証アクション別集計（activity-analysis） |
| `success` | ✅ | ✅ | 認証エラー数（activity-analysis） |
| `auth_method` | ✅ | ✅ | 認証方式別件数（activity-analysis） |
| `error_category` / `status_code` | ✅ | ❌ | — |

### 3.8 `mcp_server_connection` — MCP サーバ接続

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `status` (`connected` など) | ✅ | ✅ | MCP 接続数（activity-analysis） |
| `transport_type` (`stdio` / `http`) | ✅ | ✅ | MCP トランスポート種別（activity-analysis） |
| `server_scope` (`local` / `user`) | ✅ | ❌ | — |
| `duration_ms` | ✅ | ✅ | MCP 平均接続レイテンシ（activity-analysis） |

### 3.9 `skill_activated` — Skill（Agent Skill）発火

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `skill.name` | ✅ | ✅ | スキル別起動件数（activity-analysis） |
| `skill.source` (`bundled` など) | ✅ | ✅ | Skill ソース別内訳（activity-analysis） |

### 3.10 `hook_execution_start` / `hook_execution_complete` — Hooks 実行

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `hook_event` (`Stop` / `PreToolUse` / ...) | ✅ | ✅ | フックイベント別 成功/失敗件数（activity-analysis） |
| `hook_name` | ✅ | ✅ | Hook 名別実行数（activity-analysis） |
| `num_hooks` / `num_success` / `num_blocking` / `num_non_blocking_error` / `num_cancelled` | ✅ | ✅ | フック成功率（activity-analysis） |
| `total_duration_ms`（complete のみ） | ✅ | ✅ | Hook 平均実行時間（activity-analysis） |
| `managed_only` / `hook_source` | ✅ | ❌ | — |

### 3.11 公式ドキュメントに存在するが本環境では未観測のイベント

| イベント | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `tool_permission_decision` | ⚠️ | ❌ | 本 DB には未出現（`tool_decision` と同義の旧名/新名の可能性あり） |
| `topic_changed` | ⚠️ | ❌ | 本 DB には未出現 |
| `compact` | ⚠️ | ❌ | 本 DB には未出現（自動コンパクション発火条件未到達） |

---

## 4. Metrics

`raw_records` テーブルに JSON のまま保存されている。現在の Grafana パネルは**これらを参照していない**（Logs 由来の `api_request` を SQL 集計している）。

| メトリクス名 | 型 | 収集 | 可視化 | 代替可視化 | 備考 |
|---|---|---|---|---|---|
| `claude_code.session.count` | Counter | ✅ | ❌ | 🔶 ログの session_id DISTINCT で代替済み | セッション開始回数 |
| `claude_code.cost.usage` | Counter | ✅ | ❌ | 🔶 `api_requests.cost_usd` 合計で代替済み | モデル別 USD |
| `claude_code.token.usage` | Counter | ✅ | ❌ | 🔶 `api_requests.*_tokens` で代替済み | `type`=input/output/cache属性で内訳 |
| `claude_code.active_time.total` | Counter | ✅ | ✅ | — | 日別アクティブ時間（activity-analysis）。`metrics` テーブルへ移行済み |
| `claude_code.code_edit_tool.decision` | Counter | ✅ | ✅ | — | 言語別コード編集 accept 率（activity-analysis） |
| `claude_code.lines_of_code.count` | Counter | ✅ | ✅ | — | 追加/削除行数 日別（activity-analysis） |
| `claude_code.pull_request.count` | Counter | ⚠️ | ❌ | — | PR 作成行動をしていないため未観測 |
| `claude_code.commit.count` | Counter | ⚠️ | ❌ | — | Commit 作成行動をしていないため未観測 |

メトリクス共通属性: `user.id` / `user.email` / `user.account_uuid` / `user.account_id` / `organization.id` / `session.id` / `terminal.type` + メトリクス固有属性（`model` / `type` / `language` / `decision` / `source` / `tool_name` / `query_source` / `start_type` など）。

---

## 5. Traces

| 項目 | 状態 |
|---|---|
| Claude Code からの出力 | なし（2025-11 時点の公式仕様に準拠） |
| Collector 受信口 | 設定済み ([collector/config.yaml](../collector/config.yaml) の `traces` パイプライン) |
| `raw_records` への保存 | 準備済み（`record_type='trace'`） |
| 可視化 | ❌ |

---

## 6. サマリー

### 6.1 収集しており **可視化できている** もの

**claude-code.json / realtime-monitor.json**
- コスト（累計 / 今月 / 今日 / セッション平均 / 日次推移 / モデル別割合）
- トークン（累計 / 今月 / 今日 入力・出力・キャッシュ読取 / 日次スタック）
- キャッシュ（キャッシュ効率 % / キャッシュヒット数 / 今日のキャッシュ読取）
- API（総呼び出し回数・平均応答時間・直近リクエスト一覧）
- セッション（総数 / セッション別サマリー）
- モデル別呼び出し回数
- ツール使用ランキング（全期間 / 直近2時間）
- リアルタイム監視（直近2時間の API呼び出し / コスト / アクティブセッション / 応答時間 / ツール実行 / ユーザープロンプト / キャッシュ効率 / 時系列）

**activity-analysis.json**
- ツール品質（accept 率 / 成功率 / 実行数 / 平均・最大実行時間 / 失敗数 / ツール別 accept/reject / 平均実行時間 / 平均ペイロードサイズ / 許可経路別件数）
- プロンプト分析（総プロンプト数 / 平均プロンプト長 / 日次プロンプト数推移）
- エラー監視（API エラー数 / 内部エラー数 / 認証エラー数 / API エラー詳細一覧 / モデル別エラー数 / エラー時平均レイテンシ / 認証方式別件数）
- MCP・Skills・Hooks（MCP 接続数 / 平均接続レイテンシ / トランスポート種別 / スキル起動数 / フック成功率 / フックイベント別件数 / Hook 名別実行数 / Hook 平均実行時間 / スキル別起動件数）
- Resource 属性軸（バージョン別リクエスト数 / OS・アーキテクチャ別 / ターミナル種別別）
- メトリクス（日別アクティブ時間 / 追加・削除行数日別 / 言語別コード編集 accept 率）

### 6.2 収集しているが **可視化していない**（追加可視化の候補）

**ログイベント系**
- `tool_decision.source` → 許可経路別（config / user_permanent など）内訳 ✅ activity-analysis 追加済み
- `api_error.model` → モデル別エラー数 ✅ activity-analysis 追加済み
- `api_error.duration_ms` → エラー時レイテンシ ✅ activity-analysis 追加済み
- `auth.auth_method` → 認証方式別集計 ✅ activity-analysis 追加済み
- `mcp_server_connection.transport_type` / `duration_ms` → トランスポート種別・接続レイテンシ ✅ activity-analysis 追加済み
- `hook_execution_complete.hook_name` / `total_duration_ms` → Hook 名別・レイテンシ ✅ activity-analysis 追加済み
- `tool_result_size_bytes` → ツール別平均ペイロードサイズ ✅ activity-analysis 追加済み
- `api_error.attempt` → リトライ回数別 API エラー数 ✅ activity-analysis 追加済み
- `auth.action` → 認証アクション別集計 ✅ activity-analysis 追加済み
- `skill_activated.skill.source` → Skill ソース別内訳 ✅ activity-analysis 追加済み

**メトリクス系**
- `claude_code.active_time.total` → 日別アクティブ時間 ✅ activity-analysis 追加済み（metrics テーブルへ移行）
- `claude_code.lines_of_code.count` → 追加/削除行数（日別） ✅ activity-analysis 追加済み
- `claude_code.code_edit_tool.decision` → 言語別コード編集 accept 率 ✅ activity-analysis 追加済み

**Resource 属性軸**
- `terminal.type` 別集計 ✅ activity-analysis 追加済み
- `service.version` 別集計 ✅ activity-analysis 追加済み
- `os.type` / `host.arch` 別集計 ✅ activity-analysis 追加済み

### 6.3 Claude Code が出せる可能性はあるが **本環境で未観測**

- `claude_code.pull_request.count` / `claude_code.commit.count`（該当操作の発生次第で流入）
- `tool_permission_decision` / `topic_changed` / `compact` などの追加イベント
- Traces（Claude Code 側で現在未実装）

### 6.4 改善ヒント

本環境で可視化を広げるには 2 系統のアプローチがある:

1. **Logs ベースで拡張**: `session_events.raw_json` の `json_extract` を使えば既存 DB のままパネルを追加可能（SQLite Plugin で十分）。
2. **Metrics ベースに移行**: `ingest.py` を拡張して `raw_records` から `metrics_*` テーブルを作る。特に `active_time.total` / `lines_of_code.count` は Log からは再構成できないため、メトリクス取り込みが必須。
