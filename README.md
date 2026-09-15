# Tech blog examples

テックブログで使った検証コード、入力データ、実行結果を公開するためのリポジトリです。

## Examples

- `google-cloud-speech-transcription/` は、Google Cloud Speech-to-Textで模擬技術講演を文字起こしした検証です。
- `speech-to-text-vs-whisper/` は、28分のPyCon JP講演をGoogle Cloud Speech-to-Text V2とWhisperで文字起こしした検証です。
- `wer-cer-evaluation/` は、保存済みの日本語文字起こしをCER、空白区切りWER、SudachiのA/B/C各モードで再評価した検証です。
- `cloud-run-concurrency-load-test/` は、Cloud Runの同時実行数を1、20、80へ変えた負荷試験です。
- `cloud-run-cold-start/` は、Cloud Runの最小インスタンス数0と1でアイドル後の初回応答を比較した検証です。

APIを実行すると料金が発生する場合があります。
各ディレクトリのREADMEと、利用するサービスの料金ページを確認してから実行してください。

## License

ソースコードにはMIT Licenseを適用します。
合成音声とAPIレスポンスなどの検証データはMIT Licenseの対象外です。
詳しくは `NOTICE.md` を確認してください。
