# 04 - OTel Collector

## 役割

Claude Code から送られてくる生テレメトリを受信し、ファイルに書き出すゲートウェイです。Claude Code が直接ファイルに書かないのは、OTel の標準プロトコル (OTLP) に従うことで、将来的に他のバックエンド（Jaeger、Datadog など）へ切り替えられる柔軟性を持つためです。

## 設定ファイル: `collector/config.yaml`

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 256

exporters:
  file:
    path: /data/otel-logs.jsonl
    rotation:
      max_megabytes: 100
      max_days: 0
      max_backups: 10
  debug:
    verbosity: basic

service:
  pipelines:
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [file, debug]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [file, debug]
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [file, debug]
  telemetry:
    logs:
      level: warn
```

## 各セクションの詳細

### receivers

`otlp` レシーバーは OTLP/HTTP を `0.0.0.0:4318` で待ち受けます。Docker コンテナ内で動いており、`docker-compose.yml` で `4318:4318` とポートフォワードされることでホストから到達可能になります。

OTLP/gRPC（4317 番）は使っておらず、HTTP のみです。Claude Code のデフォルトプロトコルが `http/protobuf` であるためです。

### processors

`batch` プロセッサは受信したテレメトリをバッファし、以下のいずれかで下流に流します：
- 5 秒経過
- 256 件蓄積

これによりファイルへの書き込み回数を減らし、I/O 効率を向上させます。

### exporters

**file エクスポータ**  
`/data/otel-logs.jsonl` に追記します（コンテナ内パスで、ホストの `./data` にマウントされています）。

ローテーション設定：
- `max_megabytes: 100` — 1 ファイルが 100MB を超えたら新ファイルへ
- `max_days: 0` — 日数での削除なし
- `max_backups: 10` — 最大 10 世代保持

**debug エクスポータ**  
コンテナの stdout に基本情報を出力します。`docker logs claude-otel-collector` で確認できます。本番では不要ですが、デバッグに便利です。

### pipelines

logs / metrics / traces の 3 パイプラインが定義されており、すべて同じ receiver → processor → exporter を通ります。Claude Code は主に logs を使いますが、将来的に metrics や traces も送出できるよう準備しています。

## ファイルローテーションの仕組み

OTel Collector のファイルエクスポータは `lumberjack` ライブラリを使います。100MB を超えると現在のファイルを `otel-logs.jsonl.YYYY-MM-DD` 形式でリネームし、新しい `otel-logs.jsonl` に書き続けます。`ingest.py` はオフセット管理をしているため、ローテーション後のファイルを指すように調整が必要な点に注意してください（現状は手動リセットが必要）。

## よくあるトラブル

**長期稼働後にデータが来なくなる**  
Collector がファイルハンドルを失うことがあります（11 日以上稼働後に報告例あり）。対処：

```bash
docker restart claude-otel-collector
```

**ポートが使用中**  
4318 番が他プロセスに使われている場合、Collector が起動失敗します。

```bash
lsof -i :4318
```
