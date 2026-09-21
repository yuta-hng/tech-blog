# Private Service Connectの疎通検証

2つの専用VPCを作り、PSCの接続承認、DNS、HTTP、送信元NATを確認するコードです。
2026年9月21日に、1プロジェクト内の2つのVPCで7ケースの実測を完了しました。
本測定は各ケースでIP宛て・名前宛て3回ずつ、合計42回です。
状態変更の待機中に送った通信は、本測定とは分けてevents.jsonlへ記録しています。

## 構成

|項目|設定|
|---|---|
|リージョン / ゾーン|asia-northeast1 / asia-northeast1-b|
|producer / consumer|別々のVPC。1プロジェクト内または別プロジェクト|
|VM|e2-micro 2台、Debian 12、起動ディスク各10GB|
|producer通常 / PSC NATサブネット|10.10.0.0/24 / 10.10.10.0/24|
|consumerサブネット|10.20.0.0/24|
|内部LB / PSCエンドポイント|10.10.0.10:80 / 10.20.0.10:80|
|管理経路|IAP経由SSH。検証用SSH鍵は各VMのメタデータだけに配置|
|DNS|consumer VPC限定のpsc.test.、hello.psc.test. A、TTL 30秒|

VMにはパッケージ取得用の一時外部IPが付きます。
HTTPをインターネットへ公開する許可ルールは作りません。
VMへサービスアカウントは付けません。
OS Loginを無効にした検証専用VMを使うため、組織がOS Loginを必須としている環境では、そのまま実行できません。
組織ポリシーを変更する処理はありません。

リソース名にはprefixを付け、Service Directoryは専用名前空間を指定します。
既定のgoog-psc-defaultは変更・削除しません。
同一プロジェクトで実行した場合は、プロジェクト間のIAM分離を確認した結果として扱いません。

## 前提条件

Google Cloud CLI、Python 3、OpenSSH、ssh-keygen、課金済みの検証用プロジェクトが必要です。
実行者にはネットワーク・VM・DNS・Service Directoryの作成と削除、およびIAP経由のSSHに必要な権限が必要です。
スクリプトはIAM権限を付与せず、CLIの既定プロジェクトも変更しません。

認証を確認します。
トークンや認証コードを記事・結果へ保存しないでください。

```bash
gcloud auth login
export PSC_PRODUCER_PROJECT='your-producer-project-id'
export PSC_CONSUMER_PROJECT='your-consumer-project-id'
export PSC_PREFIX='psc-lab-0921-test1'
```

1プロジェクト内の2つのVPCで試す場合は、両方へ同じプロジェクトIDを指定します。
producerにはCompute Engine APIとIAP API、consumerにはさらにService Directory APIとCloud DNS APIが必要です。
APIが無効なら事前に有効化します。
有効化したAPIは、後片付け時に無効化しません。

```bash
gcloud services enable compute.googleapis.com iap.googleapis.com \
  --project="$PSC_PRODUCER_PROJECT"
gcloud services enable compute.googleapis.com iap.googleapis.com \
  servicedirectory.googleapis.com dns.googleapis.com \
  --project="$PSC_CONSUMER_PROJECT"
```

## 計画と作成

planはオフラインで作成コマンドを表示するだけです。
preflightはAPIとprefixの衝突を読み取り専用で確認し、認証や必要APIが不足していれば作成へ進みません。
既存VPCやVMを再利用する処理はありません。

```bash
python3 lab.py plan --producer-project "$PSC_PRODUCER_PROJECT" \
  --consumer-project "$PSC_CONSUMER_PROJECT" --prefix "$PSC_PREFIX"
python3 lab.py preflight --producer-project "$PSC_PRODUCER_PROJECT" \
  --consumer-project "$PSC_CONSUMER_PROJECT" --prefix "$PSC_PREFIX"
python3 lab.py create --producer-project "$PSC_PRODUCER_PROJECT" \
  --consumer-project "$PSC_CONSUMER_PROJECT" --prefix "$PSC_PREFIX"
```

作成を試みたリソースはAPI呼び出し前に `.private/<prefix>/manifest.json` へ記録します。
途中で失敗した場合もcleanupを実行します。
同じmanifestがある状態ではcreateを再実行できません。
後片付けしてから別のprefixでやり直します。
認証エラーの詳細、環境識別情報、SSH鍵は `.private/` に保存するため公開しません。

## 測定

```bash
python3 measure.py --producer-project "$PSC_PRODUCER_PROJECT" \
  --consumer-project "$PSC_CONSUMER_PROJECT" --prefix "$PSC_PREFIX"
```

未承認、承認後のIP通信、DNS設定後、Aレコード削除後、復旧後、PSC用NAT範囲のHTTP許可ルール無効化後、再復旧後の順に確認します。
各ケースでIPと名前によるHTTPリクエストを3回ずつ送り、curlの終了コード、HTTP応答、アプリが観測した送信元IP、DNS応答を保存します。
接続状態とバックエンドのヘルス状態は各ケースの前後に取得します。
API取得とHTTP測定は同時刻のスナップショットではありません。

設定変更後は最大300秒の範囲で期待する状態を待ち、その途中の応答もevents.jsonlへ記録します。
この待機時間から厳密な切替時間や復旧時間を算出しません。
HTTPは毎回新しいcurlプロセスから送り、接続タイムアウト2秒、全体3秒、再試行なしです。
ホスト名をcurlへ渡す試験はOS標準の名前解決を使い、別途digでもDNS応答を記録します。

判定が期待と違えば、実際の観測を保存して停止します。
DNSやファイアウォールの試験中に例外が起きた場合は、変更した設定の復旧を試みます。
端末やプロセスを強制終了した場合は復旧処理が実行されないため、状態を確認してcleanupを実行します。

`results/<実行日時>/` に次のファイルを保存します。

- `cases.json` に3回ずつの観測とケースの判定を保存します。
- `events.jsonl` に設定変更と待機中の観測を保存します。
- `environment.json` に条件、ソースのSHA-256、完了・復旧失敗の有無を保存します。

結果が1件も取れていない場合や途中失敗時は、成功した実測として扱いません。
Debianイメージとaptパッケージは固定していないので、実行時期によって変わります。

## 固定ログの再集計

今回のログは `results/2026-09-21T144356-752520_0000/` に保存しています。
クラウドへ接続せずに、本文の件数とケースの成否を再計算できます。

```bash
python3 summarize.py results/2026-09-21T144356-752520_0000
```

保存されたpassedだけでなく、通信の終了コード、HTTP応答、送信元IP、接続状態とヘルス状態を再確認します。
ケースや測定件数が欠けている場合、復旧に失敗した場合は集計をエラーで止めます。
テスト内のデータは合成入力であり、クラウド実測ログとは別です。

|ケース|IP成功|名前成功|PSC|
|---|---:|---:|---|
|承認前|0/3|0/3|PENDING|
|承認後・DNS登録前|3/3|0/3|ACCEPTED|
|DNS登録後|3/3|3/3|ACCEPTED|
|Aレコード削除後|3/3|0/3|ACCEPTED|
|DNS復旧後|3/3|3/3|ACCEPTED|
|NAT範囲のHTTP許可無効化|0/3|0/3|ACCEPTED|
|HTTP許可復旧後|3/3|3/3|ACCEPTED|

バックエンドは各ケースの前後でHEALTHYでした。
成功した通信の送信元IPは、すべてPSC用NAT範囲内の10.10.10.2でした。
固定ログのSHA-256はsummary.jsonに、実行したコードのSHA-256とバージョンはenvironment.jsonに記録しています。
再測定では時刻・応答時間・割り当てIPなどが変わるため、同じ結果ファイルにはなりません。

## 後片付け

```bash
python3 lab.py cleanup --producer-project "$PSC_PRODUCER_PROJECT" \
  --consumer-project "$PSC_CONSUMER_PROJECT" --prefix "$PSC_PREFIX"
```

manifestに記録した対象を逆順で削除します。
エンドポイント作成時に専用名前空間へ関連付いた自動DNSゾーンも確認します。
Service Directory名前空間にサービスが残る場合は削除せず、失敗として報告します。
削除失敗した項目はmanifestに残るので、原因を確認してcleanupを再実行します。
manifestがない場合やプロジェクトが一致しない場合は削除しません。
VM作成途中で残る可能性のある起動ディスクも、同名の専用ディスクとして記録します。

VM、ディスク、一時外部IP、内部LB、PSCエンドポイント、データ処理、Cloud DNSなどに料金がかかります。
作成・測定に失敗してもリソースが残れば課金が続くため、その都度cleanupの結果を確認します。
請求実績と総費用は未測定です。

今回の専用リソースは削除済みです。
`results/2026-09-21T144356-752520_0000/cleanup.json` に、manifestの残件0と削除後の一覧確認を記録しました。

## ローカル確認

```bash
python3 -m unittest test_lab test_summarize -v
bash -n startup.sh
```

ローカルテストは判定ロジックと削除対象の制限を確認するものです。
クラウド上でコマンドが成功することやPSCの動作を保証するものではありません。

## 参考資料

- [内部パススルーNLBの作成](https://docs.cloud.google.com/load-balancing/docs/internal/setting-up-internal)
- [PSC公開サービスの接続](https://docs.cloud.google.com/vpc/docs/configure-private-service-connect-services)
- [PSCサービスの公開](https://docs.cloud.google.com/vpc/docs/configure-private-service-connect-producer)
- [ネットワーク料金](https://cloud.google.com/vpc/network-pricing#private-service-connect)

再現コードのライセンスはMITです。
測定結果は個別環境の観測であり、Google Cloudの性能や可用性を保証しません。
公開対象はコード、README、ライセンスとresults内の記録です。
.private内のCLIエラー、manifest、SSH鍵は含めません。
公開前にプロジェクトID・番号、アカウント、外部IP、認証情報、個人・会社・顧客情報を確認します。
