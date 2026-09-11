# Google Cloud Speech-to-Text technical-talk experiment

Google Cloud Speech-to-Textへ模擬技術講演を送り、用語ヒントなし・ありのCERを比較した検証です。

## 収録ファイル

- `experiment.py` は音声生成、ノイズ追加、Speech-to-Textの呼び出し、CER集計を行います。
- `source_transcript.txt` はGemini TTSへ渡した読み上げ原稿です。
- `synthetic-tech-talk-clean.wav` は検証に使ったクリーン音声です。
- `synthetic-tech-talk-noisy.wav` は12dBのホワイトノイズを加えた音声です。
- `results/speech-20260911-100351.json` は12回分のAPIレスポンスと評価結果です。
- `results/summary.md` は集計結果と評価上の制約です。

## 同じ音声で実行する

Python 3.9以上とgcloud CLIを使います。
追加のPythonパッケージはありません。

```bash
gcloud auth login
gcloud config set project "YOUR_PROJECT_ID"
gcloud services enable speech.googleapis.com

python3 experiment.py run --trials 3
```

クリーン音声が置かれている場合、Gemini APIキーは不要です。
スクリプトは同じクリーン音声を使い、ノイズありの音声を作り直してから4条件を各3回認識します。

Speech-to-Text APIの利用料金とクォータを確認してから実行してください。
認証情報は結果JSONへ保存しません。

## 音声を作り直す

Gemini TTSの出力は実行ごとに変わる可能性があり、音声を作り直すと記事の数値とは一致しない場合があります。
新しい音声を作る場合はGemini APIキーを設定します。

```bash
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
rm synthetic-tech-talk-clean.wav
python3 experiment.py generate
```

## 検証音声のSHA-256

```text
629883303048e7d02d65ba96c5ad3b579b36ef19da500d611d144f0f0ca86105  synthetic-tech-talk-clean.wav
d0b2e40749529f49c6714a7b80de876a5f4e76f6735f8293a0e635f61e52f3fe  synthetic-tech-talk-noisy.wav
```
