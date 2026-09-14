# Notice

MIT Licenseは、このリポジトリのソースコードへ適用します。

下記のファイルは、検証条件と結果を確認するために収録しており、MIT Licenseの対象外です。

- WAV形式の合成音声
- Speech-to-Text APIの結果JSON
- 集計結果
- `speech-to-text-vs-whisper/results/` に含まれる文字起こし結果
- `wer-cer-evaluation/cases.json` に含まれる正解文と文字起こし結果
- `wer-cer-evaluation/results/` に含まれる集計結果
- `cloud-run-concurrency-load-test/results/` に含まれる負荷試験とCloud Monitoringの結果

合成音声はGemini 2.5 Flash Preview TTSで生成しました。
再利用する場合は、Googleの利用規約と適用される条件を確認してください。

`speech-to-text-vs-whisper/results/` の文字起こし結果は、PyCon JP公式YouTubeチャンネルのCC BY動画を基にしています。
出典、ライセンス、加工内容は `speech-to-text-vs-whisper/SOURCE.md` を確認してください。

Google Cloud、Gemini、Cloud Run、Cloud Logging、Pub/SubはGoogle LLCの商標です。
このリポジトリはGoogle LLCが提供、承認するものではありません。
