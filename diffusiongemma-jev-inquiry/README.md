# DiffusionGemma-Jevによる問い合わせ50件の分類検証

2026年9月23日にCloud Run（シンガポール）で測定した入力、実回答、採点コードです。
記事用に用意した問い合わせ50件を使用しています。ID、正解ラベル、注記はモデルに送りません。
IDはA＝Account（アカウント・権限）、N＝Network（ネットワーク）、D＝Device（PC・周辺機器）、S＝Software（ソフトウェア・業務システム）、O＝Other（その他）。数字は各分類内の通し番号です。

## 保存した結果

| 条件 | 部署一致 | 緊急度一致 | 人手対応一致 | 3項目すべて一致 | クライアントp50 |
| --- | --- | --- | --- | --- | --- |
| sg-single：同一リージョン、samples=1 | 44/50 | 42/50 | 40/50 | 30/50 | 71.2 ms |
| sg-auto：同一リージョン、samples=auto | 45/50 | 41/50 | 42/50 | 31/50 | 129.6 ms |
| local-single：ローカルPC、samples=1 | 45/50 | 40/50 | 41/50 | 29/50 | 166.1 ms |

ローカルPCの物理所在地とVPN利用の有無は未確認です。日本からの測定とは断定していません。
sg-load32は同じ50件を10回ずつ、同時実行数32で送った負荷試験です。500件は独立した500種類の問い合わせではありません。31.37秒で500件、15.94 req/s、HTTPエラー0件でした。

- `data/`：固定入力JSONとCSV。JSONのquestionsに判定基準、itemsに本文と正解ラベルがあります。
- `results/<条件>/responses.jsonl`：各リクエストの実回答、採点結果、測定値。
- `predictions.csv`：正解・予測・確率の一覧。
- `summary.json`：集計結果。`warmup.json`は集計対象外のウォームアップ。
- `manifest.json`：測定条件。公開時にサービスURLとローカルPCのホスト名だけを伏せています。

緊急度は確率最大のクラス、人手対応はP(true) >= 0.5で採点します。正解ラベルは実測後も変更していません。
確率が高くても誤判定します。例えばD10のバッテリー膨張は緊急度を低く判定しています。

## 入力とコードの確認（API呼び出しなし）

Python 3の標準ライブラリで実行できます。

```bash
cd diffusiongemma-jev-inquiry
sha256sum -c SHA256SUMS
python3 scripts/audit_dataset.py --out /tmp/djev-dataset-audit.json
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

## 再測定

デプロイ済みのdjevサービスとCloud Run呼び出し権限が必要です。デプロイの実装は [taeold/djev-run](https://github.com/taeold/djev-run) を参照してください。重みの準備、GPUクォータ、ネットワーク、サービスアカウントの設定が別途必要です。

測定環境はNVIDIA RTX PRO 6000 Blackwell×1、20 vCPU、80 GiB RAM、最小0・最大1インスタンスでした。
モデルは `nvidia/diffusiongemma-26B-A4B-it-NVFP4`、リビジョンは `ec4ff3df205028f4e81c954c2227f9312b3ec2ea`。
使用イメージのdigestは `sha256:ea86bdb962b516739b44f824401dcc9dcc052a43384bb529148b4a36a50c763a` です。

```bash
gcloud auth login
export CLOUD_RUN_URL='https://YOUR_CLOUD_RUN_SERVICE_URL'
python3 scripts/evaluate.py --url "$CLOUD_RUN_URL" \
  --out results/rerun-single --client-location '実際の実行場所' \
  --samples 1 --concurrency 1
```

`--account`を省略するとgcloudの有効なアカウントを使います。GCEのサービスアカウントで呼ぶ場合は`--auth metadata`を指定します。
自動サンプリングは`--samples auto`、負荷試験は`--concurrency 32 --repeats 10`です。出力先は毎回新しいディレクトリにしてください。
再測定はクラウド利用料が発生します。このスクリプトはインフラの作成・削除を行いません。
認証トークン取得後に計測し、ウォームアップを除外します。サーバー時間は応答の`diagnostics.timing.total_ms`で、Cloud MonitoringやGPU単体の処理時間ではありません。

固定入力のSHA-256は`SHA256SUMS`に記録しています。同じseedでも結果は変わり得るため、再測定で回答・確率・所要時間が一致するとは限りません。

## ライセンス

コードはMITライセンスです。入力とモデル出力の扱いは`NOTICE.md`を参照してください。モデルやコンテナ本体は含みません。
