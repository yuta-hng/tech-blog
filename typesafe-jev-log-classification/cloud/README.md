# Cloud Run追加検証の準備

2026-09-20に東京リージョンへデプロイし、30件の実ログ分類と各50回のレイテンシ測定を完了しました。
専用リソースは削除済みです。結果・再現手順は親ディレクトリのREADME.mdを参照してください。
既存のローカル実測は変更せず、Cloud Run実測は別の結果ファイルへ保存します。

## 2つのサービスに分ける

同じソースから次の2サービスを作ります。いずれもCloud Run IAM認証を必須とし、未認証公開しません。

|用途|環境変数|検証時の設定|
|---|---|---|
|障害注入|LAB_ROLE=generator、ENABLE_LAB_FAULTS=1|東京、CPU 1、メモリ512Mi、最小0、最大1、同時実行1、タイムアウト3秒|
|Jev呼び出し|LAB_ROLE=evaluator、LAB_REGION=asia-northeast1|東京、CPU 1、メモリ512Mi、最小0、最大1、同時実行1、タイムアウト300秒|

障害注入サービスにTypeSafeのAPIキーを渡しません。
判定サービスだけがSecret ManagerからTypeSafeキーを読み取ります。
ソース送信対象は `.gcloudignore` で `app.py`、`experiment.py`、`Dockerfile` と除外設定自身に限定しています。
`api.env`、記事、既存ログ、ローカル認証設定はビルドへ送りません。
`experiment.py` は親フォルダーの検証コードと同一です。

## 検証手順

1. 指定プロジェクトのAPIとIAMを読み取り確認し、専用のサービス・サービスアカウント・シークレットを作る。作成したリソース名を非公開の作成記録に保存する。
2. 判定用サービスアカウントへ、TypeSafeキーのシークレット単位でSecret Accessorを付与する。注入用アカウントにはシークレットのアクセス権を付けない。
3. IAM拒否の検証には値が無害な専用テストシークレットを用意し、注入サービスの `DENIED_SECRET_RESOURCE` にそのバージョンのリソース名を設定する。
4. 認証付きで `/fault/database`、`/fault/dns`、`/fault/iam`、`/fault/timeout`、`/fault/oom`、`/fault/normal` へ各5回POSTする。`?case=...` で各試行を識別する。
5. Cloud Loggingから対象サービス・期間のログを取得し、例外だけでなくOOMのsystemログ・504のrequestログを確認する。各試行のHTTP応答とログを対応付ける。
6. プロジェクトID・URL・アカウント・トレースIDなどを除いた判定用テキストを固定する。事前カテゴリやケース名はJevのstateに含めない。
7. 判定サービスの `/benchmark` へ固定入力を渡す。3回のウォームアップ、全入力の3質問分類、質問数1/3/10の各50回計測を同一リクエスト内で順次実行する。
8. service/revision/構成、プロセスID相当のboot_id、ウォームアップを保存する。時間はCloud Run内のHTTP送信からJev本文受信完了までで、Cloud Runを呼ぶクライアント側の待ち時間とは分ける。
9. 作成記録にある専用リソースだけを削除し、既存サービスを変更しない。

入力例（再現コードの疎通用。Cloud Loggingの採取データではない）:

```json
{"cases":[{"id":"smoke","state":"HTTP 200: request completed successfully"}],"repetitions":0}
```

`repetitions=0` でもウォームアップ3回と入力の分類を実行するため、TypeSafe APIを4回呼びます。
`repetitions=50`、30件の場合は183回です。
レスポンスにはAPI実応答・内部計測値が含まれますが、APIキーは含めません。

## 元の設計からの差分

DB障害はCloud SQL接続枯渇ではなく、Cloud Runコンテナ内で作るSQLiteのロック競合です。
これをCloud SQLの検証として扱いません。
IAM拒否は固定401ではなく、権限を持たない専用アカウントからGoogle Secret Managerへアクセスし、403を確認する設計です。
OOMとリクエストタイムアウトはプラットフォームログが取得できて初めて実測成功とします。
ハンドラーの意図だけで発生したと断定しません。
Cloud Runの504はコンテナ処理の停止を意味しないため、タイムアウト注入後は処理の完了を待ってから次の試行へ進みます。

2026-09-20の手元の確認では、構文検査、不正入力時にAPIを呼ばないこと、SQLiteロックの実際の例外発生を確認済みです。
Cloud Run上の起動・IAM拒否・OOM・タイムアウト・Jev呼び出しを実測で確認しました。

参考:

- https://docs.cloud.google.com/run/docs/configuring/services/secrets
- https://docs.cloud.google.com/run/docs/configuring/request-timeout
- https://docs.cloud.google.com/run/docs/configuring/services/memory-limits
