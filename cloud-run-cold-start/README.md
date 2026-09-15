# Cloud Runコールドスタート計測

Cloud Runの最小インスタンス数を0と1に設定し、アイドル後の最初のリクエストと続くウォームリクエストを比較します。

各条件で3サービスを作り、同じコンテナイメージを使います。
同時実行数と最大インスタンス数は1です。

`app_uptime_ms` はFlaskアプリのモジュール初期化後からの経過時間です。
Pythonの起動、依存ライブラリの読み込み、イメージ取得などは含まないため、Cloud Runの起動時間そのものではありません。
`client_latency_ms` はクライアントがレスポンスJSONを読み終わるまでの時間です。

## ローカルテスト

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

## デプロイ

最初のサービスをソースからデプロイします。

```sh
export REGION="asia-northeast1"

gcloud run deploy cr-cold-0-1-20260915 \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 1 \
  --min 0 \
  --max 1 \
  --cpu-boost \
  --cpu-throttling \
  --execution-environment gen2
```

解決されたイメージを取得し、残りのサービスも同じイメージからデプロイします。
最小インスタンス数0を3サービス、1を3サービス作ります。

```sh
export IMAGE="$(gcloud run services describe cr-cold-0-1-20260915 \
  --region "$REGION" \
  --format='value(spec.template.spec.containers[0].image)')"

deploy_service() {
  local service="$1"
  local minimum="$2"
  gcloud run deploy "$service" \
    --image "$IMAGE" \
    --region "$REGION" \
    --allow-unauthenticated \
    --cpu 1 \
    --memory 512Mi \
    --concurrency 1 \
    --min "$minimum" \
    --max 1 \
    --cpu-boost \
    --cpu-throttling \
    --execution-environment gen2
}

for index in 2 3; do
  deploy_service "cr-cold-0-${index}-20260915" 0
done

for index in 1 2 3; do
  deploy_service "cr-cold-1-${index}-20260915" 1
done
```

Cloud Runはアイドル状態のインスタンスを最大15分残すことがあるため、最後のデプロイから20分待ってから測ります。

## 計測

`--target` は `GROUP,LABEL,URL` の形式で、複数回指定できます。
グループを交互に並べ、測定時刻とネットワーク状態が片方へ偏りにくくします。
`urllib.request.urlopen` をリクエストごとに呼び出し、接続は再利用しません。
自動リトライも行いません。

レスポンスは決めた5項目だけを保存し、URLとエラー本文は結果JSONへ残しません。
`min-0` の初回はリクエスト番号1かつアプリ初期化後5秒以内なら `new_process`、`min-1` は初期化後5秒以上なら `prestarted_process` と記録します。
条件に合わないデータは `invalid_or_ambiguous` として主比較から外します。

```sh
.venv/bin/python measure.py \
  --run-id "20260915-cold-start-01" \
  --client-label "codex-managed-linux-egress-location-unmeasured" \
  --target "min-0,trial-1,$MIN_0_URL_1" \
  --target "min-1,trial-1,$MIN_1_URL_1" \
  --target "min-0,trial-2,$MIN_0_URL_2" \
  --target "min-1,trial-2,$MIN_1_URL_2" \
  --target "min-0,trial-3,$MIN_0_URL_3" \
  --target "min-1,trial-3,$MIN_1_URL_3" \
  --warm-requests 5 \
  --delay-seconds 0.2 \
  --output results/measurements.json

.venv/bin/python reclassify.py \
  results/measurements.json \
  --output results/measurements-reclassified.json

.venv/bin/python summarize.py \
  results/measurements-reclassified.json \
  --output results/summary.json
```

実測時、最小インスタンス数1の3サービスにはデプロイ直後にブラウザ由来とみられるアクセスが各2件あり、初回計測の `request_index` は3でした。
初期版の判定条件はこれを曖昧と扱ったため、数値を変えずに状態だけを `reclassify.py` で再判定しています。
元データは `measurements.json`、再判定後は `measurements-reclassified.json` です。
Cloud Loggingから作った匿名化済みの確認記録は `pre-measurement-access.json` にあります。

`deployment-config.json` は、デプロイしたアプリ、計測時のクライアント、公開時の解析コードでSHA-256を分けています。
公開版の `measure.py` には計測後の判定修正と通信エラー処理が入っているため、計測時のファイルとは同一ではありません。
計測時のファイル本体は残しておらず、SHA-256だけを記録しています。
また、ベースイメージと推移依存をダイジェスト固定していなかったため、公開ファイルから実測コンテナをビット単位で再構築することはできません。

ウォームリクエストは1グループ15件ありますが、同じプロセス内の5件は独立した試行ではありません。
`summary.json` はサービスごとのウォーム中央値を先に計算し、3サービスの中央値・最小値・最大値を出します。
5件がそろわないサービスはウォームの主集計から外し、欠損数とエラー種別を別に残します。

## 結果

アイドル後の初回レイテンシ中央値は、最小インスタンス数0が1,237.081ms、1が158.592msでした。
差は1,078.489msで、最小インスタンス数1は0より87.2%短くなりました。

ウォームレイテンシはサービスごとの中央値を集計し、最小インスタンス数0が111.467ms、1が109.127msでした。
6サービスの36リクエストはすべてHTTP 200で、状態判定後も全件が有効でした。

`results/measurements.json` は実行直後の元データです。
`results/measurements-reclassified.json` は判定条件だけを修正したデータで、レイテンシとレスポンス値は変えていません。
`results/summary.json` は記事で使った集計結果です。
`results/pre-measurement-access.json` はCloud Loggingで確認した計測前アクセスの匿名化済み記録です。

## 後片付け

6つの検証用サービスを1つずつ削除します。
Artifact Registryには別のイメージがある可能性があるため、リポジトリ単位では削除しません。

```sh
gcloud run services delete cr-cold-0-1-20260915 --region "$REGION"
gcloud run services delete cr-cold-0-2-20260915 --region "$REGION"
gcloud run services delete cr-cold-0-3-20260915 --region "$REGION"
gcloud run services delete cr-cold-1-1-20260915 --region "$REGION"
gcloud run services delete cr-cold-1-2-20260915 --region "$REGION"
gcloud run services delete cr-cold-1-3-20260915 --region "$REGION"
```

## ライセンスとデータ

`app.py`、`measure.py`、`reclassify.py`、`summarize.py`、テストコードには公開リポジトリのMIT Licenseを適用します。
`results/` の測定結果はMIT Licenseの対象外です。
