# TypeSafe Jevを東京Cloud Runから検証する

2026年9月20日に、障害注入用とJev判定用の専用Cloud Runサービスで検証しました。
このディレクトリには再現コードと識別情報を除いた固定データを収録しています。
原稿・秘密ファイル・識別情報を含むログは含めません。

## 結果

Cloud Loggingから採取した30件を分類し、事前カテゴリとの一致は30/30でした。
ただし6パターンを5回繰り返したもので、本文は10種類です。
504のChoice confidenceは0.50〜0.64で、カテゴリ一致と不確実性は別に見る必要がありました。
ScoreとNoulには独立した正解ラベルを付けていません。

|質問数|回数|中央値|p95|
|---:|---:|---:|---:|
|1|50|218.5ms|278.2ms|
|3|50|215.3ms|273.8ms|
|10|50|214.3ms|262.0ms|

東京、1 vCPU、512Mi、同時実行1、最小0・最大1インスタンス、Startup CPU Boost無効、第2世代。
Python 3.12.14、APIクライアントは標準ライブラリ、モデルは `jev-1.13.0`。
Cloud Run内部からJevへのHTTP往復時間で、Cloud Run自体の起動時間を含みません。
質問の順は各ラウンドでシャッフルし、seed=920を使用。p95はnearest-rank法です。
モデル内部の推論時間・サービス側キャッシュ・時間帯の影響は分離していません。

## APIなしで固定結果を確認する

```bash
python3 summarize_cloud.py
python3 -m unittest -v
sha256sum results/cloud-cases.json
```

固定入力のSHA-256:

```text
0c0b63d59a6f7e72360dde0ca1a9c1c1d8a42277eaddb6990e45df7fa13fd65d
```

主なファイル:

- `cloud/`: Cloud Run用ソースとDockerfile。`experiment.py` は親フォルダーのAPIクライアントと同一。
- `cloud_lab.py`: 専用リソース作成・ビルド・デプロイ・後片付け。作成記録はGit対象外の `.private/` に保存。
- `cloud_measure.py`: 障害注入・ログ収集・Jev呼び出し。収集時に識別情報を除き、期待カテゴリはモデルへ送らない。
- `cloud_observe.py`: 専用判定サービスの起動指標とIAM公開設定を読み取り確認。
- `results/cloud-cases.json`: Cloud Logging由来の固定入力。
- `results/cloud-benchmark-20260920-142504.json`: 3回のウォームアップ、30件分類、150回計測の全応答。network_baselineも収録。
- `results/cloud-smoke.json`: Cloud Run疎通時の4回のAPI応答。計測の主表には混ぜない。
- `results/cloud-summary.json`: 再集計結果。
- `results/cloud-environment.json`、`cloud-startup-metric.json`、`cloud-cleanup.json`: 設定・起動指標・後片付けの記録。

## 実環境で再実行する

gcloud CLIと、プロジェクトでCloud Run、Cloud Build、サービスアカウント、Artifact Registry、Secret Managerの操作・API有効化ができる権限が必要です。
Cloud Buildの実行サービスアカウントにはコンテナのビルド・pushに必要な権限も必要です。
作成したリソースとAPI利用には課金が発生し得ます。
キーは環境変数 `TYPESAFE_API_KEY` に設定するか、再実行ディレクトリに `api.env` を置いてください。
キー1行または `TYPESAFE_API_KEY=...` 形式に対応します。Gitへ追加しません。

```bash
mkdir -p rerun/results
cp cloud_lab.py cloud_measure.py cloud_observe.py experiment.py rerun/
cp -R cloud rerun/
cd rerun

PROJECT_ID="YOUR_PROJECT_ID"
python3 cloud_lab.py create --project "$PROJECT_ID"
python3 cloud_lab.py build-status --project "$PROJECT_ID"
# SUCCESSを確認してから実行
python3 cloud_lab.py deploy --project "$PROJECT_ID"
python3 cloud_measure.py smoke
python3 cloud_measure.py inject
# Cloud Loggingへの反映を待ってから実行
python3 cloud_measure.py collect
python3 cloud_measure.py benchmark
python3 cloud_observe.py
python3 cloud_lab.py cleanup --project "$PROJECT_ID"
```

デフォルトのリソース接頭辞は `jev-lab-0920` です。
スクリプトは重複した作成記録や固定入力を上書きせず停止します。
30件の分類と150回の計測は183回、疎通は4回、計187回のJev API呼び出しです。
再実行するとモデル応答、ログ、応答時間は変わる場合があります。
新しい結果は日時付きJSONに保存され、元の固定結果は上記の別ディレクトリ方式で保持されます。
`summarize_cloud.py` は記事の固定ファイルを再集計するツールです。

障害注入サービスではOOM、タイムアウト、権限拒否などを意図的に発生させます。
既存アプリへ組み込まず、専用サービスだけで実行してください。
ログ送信前に `results/cloud-cases.json` を確認してください。
DBはCloud SQLではなくSQLiteのロック競合です。
IAM拒否は専用テストシークレットへの実アクセスで403を確認します。
OOMはCloud Runのsystemログ、504はrequestログから取得します。
正解カテゴリは観測した症状の分類として、504をnetwork_error、OOMをapplication_errorへ事前に割り当てています。

## 元のローカル検証

`cases.json`、`generate_logs.py`、`probe_ambiguity.py`、`results/measurements-20260920-140101.*`、`results/ambiguity-20260920-140248.json` は初期のローカル検証です。
Cloud Run結果とは混ぜません。

```bash
python3 experiment.py --summarize results/measurements-20260920-140101.jsonl
```

ローカルの固定入力 `cases.json` のSHA-256:

```text
d84ff3d96e2e2dfc331e41b37b0c556b0f3741fc9a41d3b5c4a1739aeb24cdaa
```

## 費用と後片付け

Cloud Run検証のJev入力は117,716トークン。公式発表の$0.042/100万入力トークンから計算した参考額は$0.004944072です。
初期ローカル検証と合計すると233,883入力トークン、参考額$0.009823086です。
実際の請求額は未確認で、Google Cloudの料金は別です。

今回作成した専用サービス2つ、シークレット2つ、サービスアカウント2つ、Artifact Registryリポジトリとビルド入力オブジェクトは削除済みです。
Cloud Buildの実行記録、Cloud Loggingログ、Secret Manager APIの有効化は残しています。
既存サービスは変更していません。

コードはMIT Licenseです。APIの応答は検証時のモデル出力で、正確性や再生成時の一致を保証しません。
コードのライセンスはTypeSafeのモデル・サービス自体の権利や利用条件を変更しません。
