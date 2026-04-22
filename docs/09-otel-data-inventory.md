# Claude Code OTel データインベントリ

Claude Code が OpenTelemetry 経由で出力できる**全データ**と、本プロジェクトでの **収集 / 可視化 状況** をまとめたもの。

凡例:

- **収集**: `data/otel-logs.jsonl` → `data/claude_code.db` に取り込まれているか
  - ✅ 収集あり（DBに実データあり）
  - ⚠️ 収集パイプラインは通るが該当レコードが生成される条件に未到達（例: PR 作成、コミット作成など）
  - ❌ 収集していない（パイプラインで落としている）
- **可視化**: Grafana ダッシュボード（[claude-code.json](../grafana/provisioning/dashboards/claude-code.json) / [realtime-monitor.json](../grafana/provisioning/dashboards/realtime-monitor.json)）で表示されているか
  - ✅ パネルあり
  - 🔶 DB には入っているが専用パネルなし（`raw_json` 等からクエリすれば可視化可能）
  - ❌ パネルなし

---

## 1. シグナル種別（OTLP 3シグナル）

| シグナル | OTLP フィールド | 収集 | 格納先 | 可視化 | 備考 |
|---|---|---|---|---|---|
| Logs（Events） | `resourceLogs` | ✅ | `api_requests` / `session_events` | ✅ 一部 | `event.name` ごとに構造化 |
| Metrics | `resourceMetrics` | ✅ | `raw_records` (record_type='metric') | ❌ | JSONL → DBには入るが、`ingest.py` は生 JSON を保管するだけ。Grafana は未参照 |
| Traces | `resourceSpans` | ⚠️ | `raw_records` (record_type='trace') | ❌ | Claude Code は現状 traces を出さない（収集器は受け口のみ確保） |

> メトリクスは集計値として独立シグナルで流れているが、現在の Grafana 可視化は **Logs の `api_request` イベントを SQL 集計した値**のみを使用している。メトリクスを使った可視化は未実装。

---

## 2. Resource 属性（全レコード共通）

Claude Code 起動環境のメタデータ。全イベント/メトリクスに付与される。

| 属性 | 収集 | 可視化 | 用途例 |
|---|---|---|---|
| `service.name` (= `claude-code`) | ✅ | ❌ | サービス識別 |
| `service.version` | ✅ | ❌ | バージョン別の挙動追跡 |
| `os.type` | ✅ | ❌ | OS 別集計 |
| `os.version` | ✅ | ❌ | 〃 |
| `host.arch` | ✅ | ❌ | CPU アーキテクチャ |
| `user.id` (ハッシュ) | ✅ | ❌ | 擬似匿名ユーザ ID |
| `user.email` | ✅ | 🔶 | セッションテーブル列あり。フィルタ用パネルは未作成 |
| `user.account_uuid` | ✅ | ❌ | 課金アカウント UUID |
| `user.account_id` | ✅ | ❌ | 課金アカウント ID |
| `organization.id` | ✅ | ❌ | 組織 ID |
| `terminal.type` | ✅ | ❌ | `Apple_Terminal` / `iTerm` / `ssh-session` / `non-interactive` など |
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
| `service.version` | ✅ | ❌ | — |
| `os.type` / `host.arch` | ✅ | ❌ | — |

### 3.2 `user_prompt` — ユーザが入力したプロンプト

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `prompt.id` | ✅ | ❌ | — |
| `prompt_length` | ✅ | ❌ | 文字数。長さ分布可視化の余地あり |
| `prompt` | ⚠️ | ❌ | `<REDACTED>` で来る（Claude Code デフォルトで内容マスク） |
| 件数カウント | ✅ | ✅ | リアルタイム「直近2時間 ユーザープロンプト」 |

### 3.3 `tool_result` — ツール実行結果

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `tool_name` | ✅ | ✅ | ツール使用ランキング（全期間 / 直近2時間）|
| `success` | ✅ | ❌ | 成功/失敗率の可視化は未実装 |
| `duration_ms` | ✅ | ❌ | ツール別レイテンシの可視化は未実装 |
| `tool_result_size_bytes` | ✅ | ❌ | ペイロードサイズ分布の可視化は未実装 |
| `decision_source` / `decision_type` | ✅ | ❌ | ツール許可経路の可視化は未実装 |

### 3.4 `tool_decision` — ツール許可ダイアログの決定

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `tool_name` | ✅ | ❌ | accept / reject の内訳パネル未作成 |
| `decision` (`accept` / `reject`) | ✅ | ❌ | 〃 |
| `source` (`config` / `user_permanent` / ...) | ✅ | ❌ | 〃 |

### 3.5 `api_error` — API リクエスト失敗

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `model` | ✅ | ❌ | エラーパネル未作成 |
| `error` | ✅ | ❌ | 〃 |
| `status_code` | ✅ | ❌ | 〃 |
| `duration_ms` | ✅ | ❌ | 〃 |
| `attempt` | ✅ | ❌ | リトライ回数 |

### 3.6 `internal_error` — Claude Code 内部エラー

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `error_name` | ✅ | ❌ | 件数ストリーム/集計パネル未作成 |

### 3.7 `auth` — 認証イベント

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `action` (`login` など) | ✅ | ❌ | — |
| `success` | ✅ | ❌ | 認証失敗監視パネル未作成 |
| `auth_method` | ✅ | ❌ | `oauth` など |
| `error_category` / `status_code` | ✅ | ❌ | — |

### 3.8 `mcp_server_connection` — MCP サーバ接続

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `status` (`connected` など) | ✅ | ❌ | MCP 利用状況パネル未作成 |
| `transport_type` (`stdio` / `http`) | ✅ | ❌ | — |
| `server_scope` (`local` / `user`) | ✅ | ❌ | — |
| `duration_ms` | ✅ | ❌ | 接続レイテンシ |

### 3.9 `skill_activated` — Skill（Agent Skill）発火

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `skill.name` | ✅ | ❌ | Skill 利用ランキング未作成 |
| `skill.source` (`bundled` など) | ✅ | ❌ | — |

### 3.10 `hook_execution_start` / `hook_execution_complete` — Hooks 実行

| フィールド | 収集 | 可視化 | 備考 |
|---|---|---|---|
| `hook_event` (`Stop` / `PreToolUse` / ...) | ✅ | ❌ | hook イベント別可視化未作成 |
| `hook_name` | ✅ | ❌ | — |
| `num_hooks` / `num_success` / `num_blocking` / `num_non_blocking_error` / `num_cancelled` | ✅ | ❌ | — |
| `total_duration_ms`（complete のみ） | ✅ | ❌ | hook レイテンシ監視未作成 |
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
| `claude_code.active_time.total` | Counter | ✅ | ❌ | — | **本プロジェクトで未可視化の有用指標**。実作業時間 |
| `claude_code.code_edit_tool.decision` | Counter | ✅ | ❌ | — | 編集ツールの accept/reject、`language` 属性あり |
| `claude_code.lines_of_code.count` | Counter | ✅ | ❌ | — | **本プロジェクトで未可視化の有用指標**。追加/削除行数 |
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

- コスト（累計 / 今月 / 今日 / セッション平均 / 日次推移 / モデル別割合）
- トークン（累計 / 今月 / 今日 入力・出力・キャッシュ読取 / 日次スタック）
- キャッシュ（キャッシュ効率 % / キャッシュヒット数 / 今日のキャッシュ読取）
- API（総呼び出し回数・平均応答時間・直近リクエスト一覧）
- セッション（総数 / セッション別サマリー）
- モデル別呼び出し回数
- ツール使用ランキング（全期間 / 直近2時間）
- リアルタイム監視（直近2時間の API呼び出し / コスト / アクティブセッション / 応答時間 / ツール実行 / ユーザープロンプト / キャッシュ効率 / 時系列）

### 6.2 収集しているが **可視化していない**（追加可視化の候補）

**ログイベント系**
- `tool_result.success` / `tool_result.duration_ms` → ツール別 成功率・レイテンシ
- `tool_decision` → 許可ダイアログの accept/reject 率、ツール別
- `api_error` → エラー発生率・モデル別エラー・status_code 内訳
- `internal_error` → 件数アラート
- `auth` → 認証失敗監視
- `mcp_server_connection` → MCP サーバ接続数・接続時間
- `skill_activated` → Skill 利用ランキング
- `hook_execution_*` → Hook 実行時間・成功率・キャンセル率
- `user_prompt.prompt_length` → プロンプト長分布

**メトリクス系（`raw_records` 内に JSON 保存のみ）**
- `claude_code.active_time.total` → 日別アクティブ時間
- `claude_code.lines_of_code.count` → 追加/削除行数（`type` 属性で内訳）
- `claude_code.code_edit_tool.decision` → 言語別・ツール別 accept 率

**Resource 属性軸**
- `terminal.type` 別集計（Apple_Terminal / ssh-session / non-interactive など）
- `service.version` 別集計（バージョン間のコスト・エラー率比較）
- `os.type` / `host.arch` 別集計

### 6.3 Claude Code が出せる可能性はあるが **本環境で未観測**

- `claude_code.pull_request.count` / `claude_code.commit.count`（該当操作の発生次第で流入）
- `tool_permission_decision` / `topic_changed` / `compact` などの追加イベント
- Traces（Claude Code 側で現在未実装）

### 6.4 改善ヒント

本環境で可視化を広げるには 2 系統のアプローチがある:

1. **Logs ベースで拡張**: `session_events.raw_json` の `json_extract` を使えば既存 DB のままパネルを追加可能（SQLite Plugin で十分）。
2. **Metrics ベースに移行**: `ingest.py` を拡張して `raw_records` から `metrics_*` テーブルを作る。特に `active_time.total` / `lines_of_code.count` は Log からは再構成できないため、メトリクス取り込みが必須。
