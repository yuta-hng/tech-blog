# Google Cloud Speech-to-Text V2とWhisperの長尺文字起こし比較

PyCon JP 2019の講演から切り出した28分30.94秒の音声を、Google Cloud Speech-to-Text V2、Whisper `small`、Whisper `large-v3-turbo` で文字起こしした検証です。

記事本文は `article.md`、素材の出典と加工条件は `SOURCE.md`、検証記録は `VALIDATION.md` にあります。

## 検証素材

- 作品名: [02-203_入門 自作検索エンジン(ryo kato)](https://www.youtube.com/watch?v=5EEH8MHfAyA)
- 登壇者: ryo kato
- 公開者: PyCon JP
- ライセンス: [CC BY](https://www.pycon.jp/committee/license.html)
- 加工内容: 7分51.08秒から36分22.00秒までの音声を切り出し、16kHz、モノラルのFLACへ変換

元動画、加工音声、YouTube自動字幕はリポジトリへ含めません。
動画のライセンスとYouTubeの利用規約を確認し、自分が利用できる方法で素材を用意してください。

## 実行環境

- Python 3.11以上
- uv
- gcloud CLI
- faster-whisper 1.2.0
- CTranslate2 4.8.2
- WSL2

## セットアップ

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync
```

元動画のM4AとYouTube自動字幕のJSON3を `source/` へ置いたあと、検証用FLACを作成します。

```bash
.venv/bin/python prepare_audio.py
```

Whisperを実行します。

```bash
HF_HOME=.hf-cache .venv/bin/python experiment.py whisper \
  --models small large-v3-turbo \
  --cpu-threads 6 \
  --beam-size 5
```

`experiment.py` は `vad_filter=False` と `condition_on_previous_text=True` を固定しています。

Google Cloud側はSpeech-to-Text APIを有効にし、検証用FLACをCloud Storageへアップロードしてから実行します。

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable speech.googleapis.com
gcloud storage cp \
  source/pyconjp-search-talk.flac \
  gs://YOUR_BUCKET/pyconjp-search-talk.flac

.venv/bin/python experiment.py google \
  --gcs-uri gs://YOUR_BUCKET/pyconjp-search-talk.flac
```

検証後はアップロードした音声を削除します。

```bash
gcloud storage rm gs://YOUR_BUCKET/pyconjp-search-talk.flac
```

検証専用に作った空のバケットも不要なら削除します。

```bash
gcloud storage buckets delete gs://YOUR_BUCKET
```

## 実測結果

- `results/whisper-20260912-114806.json`
- `results/google-20260912-121015.json`

YouTube自動字幕は人が確認した正解字幕ではないため、各出力とのCERは一致度の参考値としてだけ扱っています。
