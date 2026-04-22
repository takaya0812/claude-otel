# 05 - ingest.py パイプライン

## 概要

`scripts/ingest.py` は JSONL ファイルを読み取り、SQLite データベースに変換する ETL スクリプトです。`--watch` フラグで常駐プロセスになり、5 秒ごとに差分を取り込みます。

## 実行モード

```bash
# 一回実行（現在の差分だけ取り込んで終了）
python3 scripts/ingest.py

# 常駐モード（launchd から呼ばれる）
python3 scripts/ingest.py --watch

# ファイルパスを指定する場合
python3 scripts/ingest.py --jsonl /path/to/file.jsonl --db /path/to/db.sqlite
```

## 処理フロー

```
main()
  └─ ingest_file()             # ファイル差分を読む
       ├─ オフセット読み取り   # .offset ファイル
       ├─ ファイルサイズ確認   # 変化なければ即終了
       └─ for each line: ingest_line()
            ├─ JSON パース
            ├─ resourceLogs を走査
            │    └─ process_log_record()   # ログを DB に挿入
            ├─ resourceMetrics → raw_records
            └─ resourceSpans  → raw_records
```

## 関数詳解

### `ingest_file()`

```python
def ingest_file(jsonl_path, db_path, offset_path):
    offset = int(offset_path.read_text()) if offset_path.exists() else 0
    file_size = jsonl_path.stat().st_size
    if file_size <= offset:
        return 0  # 新しいデータなし

    conn = sqlite3.connect(db_path)
    init_db(conn)  # テーブルが存在しなければ作成

    with open(jsonl_path, "r") as f:
        f.seek(offset)          # 前回の末尾から再開
        for line in f:
            ingest_line(line, conn)
        new_offset = f.tell()   # 読み終わった位置を記録

    conn.commit()
    offset_path.write_text(str(new_offset))
```

`f.seek(offset)` によって既読部分をスキップします。コミットは全行処理後に 1 回だけ行うため、途中で停止した場合は次回起動時に同じ行から再処理されます（冪等性はありません — 重複 INSERT に注意）。

### `parse_attributes()`

OTel の属性は 2 種類の形式で来ます：

```python
# 形式1: 配列（Claude Code が送る形式）
[
  {"key": "model", "value": {"stringValue": "claude-opus-4-5"}},
  {"key": "cost_usd", "value": {"doubleValue": 0.00234}}
]

# 形式2: 辞書（テスト用など）
{"model": "claude-opus-4-5", "cost_usd": 0.00234}
```

どちらも `{"model": "claude-opus-4-5", "cost_usd": 0.00234}` というフラット辞書に変換します。値の型ラッパー (`stringValue`, `doubleValue`, `intValue`) は最初に見つかったものを使います。

### `process_log_record()`

3 段階のマージで属性を結合します：

```
resource 属性（user.email, os.type, host.arch など）
  ↑ 上書き
log record 属性（event.name, session.id, model など）
  ↑ 上書き
body (JSON 文字列をパース)（event.name, cost_usd など）
```

`event.name` の値によって挿入先が変わります：

| event.name | 挿入テーブル | 主な用途 |
|---|---|---|
| `api_request` | `api_requests` | API 呼び出し（コスト・トークン） |
| `user_prompt` | `session_events` | ユーザー入力イベント |
| `tool_result` | `session_events` | ツール実行結果 |
| その他 | `session_events` | その他のセッションイベント |

### 型安全な抽出ヘルパー

```python
extract_string(d, *keys)  # None でも TypeError でも None を返す
extract_float(d, *keys)   # 文字列数値も float に変換
extract_int(d, *keys)     # float("1200") → int 1200 も対応
```

複数の `keys` を受け取り、最初に見つかった非 None 値を返します。OTel のフィールド名が微妙に異なるバージョン間で変わっても対応できます（例：`user.id` と `user.account_uuid`）。

## オフセットファイルの仕組み

```
otel-logs.jsonl (1024 bytes)
[=== 既読 (0-511) ===][=== 未読 (512-1024) ===]
                      ↑
              claude_code.offset: "512"
```

ingest.py 起動のたびにこの位置から読み始めます。ファイルサイズが offset 以下なら何もしません（Collector がローテーションしてファイルが小さくなった場合は offset をリセットする必要があります）。

## init_db(): DB 初期化

接続のたびに `CREATE TABLE IF NOT EXISTS` と `CREATE VIEW IF NOT EXISTS` が実行されます。べき等なので何度呼んでも安全です。テーブル構造の変更（カラム追加など）はこの関数を修正し、既存 DB には `ALTER TABLE` が必要です。
