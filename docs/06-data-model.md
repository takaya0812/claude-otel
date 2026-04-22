# 06 - データモデル

## テーブル構成

```
api_requests      ← API 呼び出しの主要データ（コスト・トークン）
session_events    ← API 以外のイベント（user_prompt, tool_result など）
raw_records       ← metrics / traces の未加工データ
```

## api_requests テーブル

最重要テーブル。Claude Code が API を呼び出すたびに 1 行追加されます。

```sql
CREATE TABLE api_requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ingested_at      TEXT NOT NULL,     -- ingest.py が書いた UTC 時刻 (ISO 8601)
    event_timestamp  TEXT,              -- Claude Code が記録したイベント時刻
    session_id       TEXT,              -- Claude Code のセッション識別子
    event_sequence   INTEGER,           -- セッション内の連番
    user_email       TEXT,              -- OTEL_RESOURCE_ATTRIBUTES で設定したメール
    user_id          TEXT,              -- Anthropic アカウント UUID
    organization_id  TEXT,
    model            TEXT,              -- 使用モデル (例: claude-opus-4-5)
    cost_usd         REAL,              -- このリクエストのコスト（ドル）
    duration_ms      INTEGER,           -- API レスポンスタイム（ミリ秒）
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    cache_read_tokens     INTEGER,      -- プロンプトキャッシュヒット
    cache_creation_tokens INTEGER,      -- 新規キャッシュ作成
    service_version  TEXT,              -- Claude Code のバージョン
    os_type          TEXT,              -- darwin / linux
    host_arch        TEXT,              -- arm64 / x86_64
    raw_json         TEXT               -- マージ済み属性の全 JSON
);
```

### インデックス

```sql
CREATE INDEX idx_api_session ON api_requests(session_id);
CREATE INDEX idx_api_ts      ON api_requests(event_timestamp);
CREATE INDEX idx_api_email   ON api_requests(user_email);
CREATE INDEX idx_api_model   ON api_requests(model);
```

Grafana のダッシュボードクエリはほぼすべて `event_timestamp` での時系列フィルタを使うため、`idx_api_ts` が最も重要です。

## session_events テーブル

```sql
CREATE TABLE session_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ingested_at     TEXT NOT NULL,
    event_timestamp TEXT,
    session_id      TEXT,
    event_name      TEXT,   -- "user_prompt", "tool_result" など
    user_email      TEXT,
    user_id         TEXT,
    organization_id TEXT,
    service_version TEXT,
    raw_json        TEXT
);
```

`api_request` 以外のすべてのイベントがここに入ります。`event_name` で種別がわかります。

## raw_records テーブル

```sql
CREATE TABLE raw_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ingested_at TEXT NOT NULL,
    record_type TEXT,   -- "metric" または "trace"
    raw_json    TEXT
);
```

現状 Claude Code は主に logs を使うため、このテーブルはほぼ空です。将来の拡張用です。

## ビュー

### daily_cost ビュー

```sql
CREATE VIEW daily_cost AS
SELECT
    DATE(event_timestamp) AS date,
    user_email,
    model,
    COUNT(*) AS api_calls,
    ROUND(SUM(cost_usd), 6)   AS total_cost_usd,
    SUM(input_tokens)         AS total_input_tokens,
    SUM(output_tokens)        AS total_output_tokens,
    SUM(cache_read_tokens)    AS total_cache_read_tokens,
    ROUND(AVG(duration_ms))   AS avg_duration_ms
FROM api_requests
WHERE event_timestamp IS NOT NULL
GROUP BY DATE(event_timestamp), user_email, model;
```

日付・ユーザー・モデルごとのコスト集計です。Grafana の履歴ダッシュボードで使用されます。

### session_summary ビュー

```sql
CREATE VIEW session_summary AS
SELECT
    session_id,
    user_email,
    MIN(event_timestamp) AS session_start,
    MAX(event_timestamp) AS session_end,
    COUNT(*) AS api_calls,
    ROUND(SUM(cost_usd), 6) AS total_cost_usd,
    SUM(input_tokens)       AS total_input_tokens,
    SUM(output_tokens)      AS total_output_tokens,
    GROUP_CONCAT(DISTINCT model) AS models_used
FROM api_requests
WHERE session_id IS NOT NULL
GROUP BY session_id, user_email;
```

セッションごとの集計です。1 セッションで複数モデルを使った場合、`models_used` にカンマ区切りで入ります。

## よく使うクエリ例

```sql
-- 直近 7 日のコスト合計
SELECT ROUND(SUM(cost_usd), 4) AS total
FROM api_requests
WHERE event_timestamp >= datetime('now', '-7 days');

-- キャッシュ効率（%）
SELECT ROUND(
    100.0 * SUM(cache_read_tokens) /
    NULLIF(SUM(input_tokens) + SUM(cache_read_tokens), 0),
    1
) AS cache_pct
FROM api_requests;

-- モデル別コスト内訳
SELECT model, COUNT(*) AS calls, ROUND(SUM(cost_usd), 4) AS cost
FROM api_requests
GROUP BY model
ORDER BY cost DESC;

-- セッション内のイベント時系列
SELECT event_timestamp, event_name, raw_json
FROM (
    SELECT event_timestamp, 'api_request' AS event_name, raw_json
    FROM api_requests
    WHERE session_id = 'YOUR_SESSION_ID'
    UNION ALL
    SELECT event_timestamp, event_name, raw_json
    FROM session_events
    WHERE session_id = 'YOUR_SESSION_ID'
)
ORDER BY event_timestamp;
```

## raw_json カラムの活用

`raw_json` には属性のフル JSON が保存されています。スキーマにないフィールドも JSON 関数で取り出せます：

```sql
-- Claude Code のバージョン別集計
SELECT
    json_extract(raw_json, '$.service.version') AS version,
    COUNT(*) AS calls
FROM api_requests
GROUP BY version;
```
