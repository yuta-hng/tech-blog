# Cloud Run concurrency load test

Cloud Runの同時実行数を1、20、80へ変え、100ms待つHTTPアプリへ100接続で1,000リクエストを送った検証です。
各条件を3回ずつ測定しています。

## 検証条件

|項目|条件|
|-|-|
|リージョン|`asia-northeast1`|
|Google Cloud SDK|583.0.0|
|CPU|1 vCPU|
|メモリ|512 MiB|
|最小インスタンス数|0|
|最大インスタンス数|10|
|同時実行数|1、20、80|
|アプリサーバー|Gunicorn 23.0.0、1 worker、100 threads|
|負荷生成ツール|Python 3.12、`urllib.request`、100スレッド|
|リクエスト数|ウォームアップ20件、本測定1,000件|
|繰り返し|各条件3回|

`load_test.py` は接続を共有するプールを実装していないため、TCPとTLSの接続確立を含む結果です。
負荷生成側のCPU使用率とネットワーク使用率は記録していません。

## デプロイ

```bash
export PROJECT_ID="自分のプロジェクトID"
export REGION="asia-northeast1"
export SERVICE="cloud-run-concurrency-test"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --cpu 1 \
  --memory 512Mi \
  --min 0 \
  --max 10 \
  --concurrency 1 \
  --set-env-vars WORK_MS=100
```

`--min` と `--max` はサービス単位の設定です。
検証用サービスは公開アクセスを許可するため、本番データや認証が必要な処理には使わないでください。

## 負荷試験

```bash
export SERVICE_URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --format='value(status.url)')"

python3 load_test.py \
  --url "$SERVICE_URL/?work_ms=100" \
  --requests 1000 \
  --clients 100 \
  --warmup 20 \
  --repeat 3 \
  --label concurrency-1 \
  --output results/concurrency-1.json
```

`gcloud run services update` の `--concurrency` を20、80へ変え、1条件ずつ測定します。
`load_test.py` は結果へ実際のサービスURLを保存せず、 `https://<SERVICE_URL>/` へ置き換えます。

## 結果

|同時実行数|成功率|RPS中央値|P95中央値|最大アクティブインスタンス数|
|-:|-:|-:|-:|-:|
|1|100%|82.9|1,856.6ms|7|
|20|100%|261.5|360.0ms|5|
|80|100%|243.7|392.0ms|2|

負荷試験の結果は `results/concurrency-*.json`、Cloud Monitoringの公開用データは `results/monitoring-instance-count.json` です。
Monitoringデータは `run.googleapis.com/container/instance_count` の `state=active` を60秒ごとに `ALIGN_MAX` で集計しています。

固定した結果ファイルのSHA-256は下記です。

```text
37f638cc1bfa11bcf33d737177835f1d3f991622233d5723306953e836d7ba6f  results/concurrency-1.json
0fef8cf333ef60961128941f5ff26d8bfeceb95f5610bde811b3a35a00f66633  results/concurrency-20.json
a70b4f371d140da8e7410b803b7424b51f04d0e062ed2b6ee0ee6e3ae2f4658f  results/concurrency-80.json
2144ca78bc5b9f20ee47933346f79084188518cfceb62b4bfe685edc9bdde115  results/monitoring-instance-count.json
```

## テスト

```bash
python3 -m unittest discover -s tests -v
```

## 後片付け

```bash
gcloud run services delete "$SERVICE" --region "$REGION"
```

Artifact Registryの共有リポジトリには別のイメージがあるかもしれないため、対象を確認してから削除してください。

## ライセンスとデータ

`app.py` と `load_test.py` はリポジトリルートのMIT Licenseを適用します。
`results/` の測定結果はMIT Licenseの対象外です。
詳しくはリポジトリルートの `NOTICE.md` を確認してください。
