# WER/CER evaluation

2026年9月11日のSpeech-to-Text検証で保存した4条件の文字起こしを、CERと複数の日本語WERで再評価します。
APIは呼び出しません。

## 実行方法

```bash
uv sync
uv run python evaluate.py
uv run python -m unittest discover -s tests -v
```

結果は `results/scores.json` へ保存されます。

固定入力 `cases.json` のSHA-256は下記です。

```text
de8a48c016a3ceb46c734e7eb4e64bc921d44192f95d286f11c281fd31b51a47  cases.json
```

## 入力

`cases.json` には、合成音声の生成に使った原稿とGoogle Cloud Speech-to-Text V1 `latest_long` の出力を収録しています。
同じ条件を3回試した結果が同一だったため、各条件の1件だけを収録しました。

## 評価上の制約

正解文は人が音声を聞いて作った字幕ではなく、Gemini 2.5 Flash Preview TTSへ渡した入力原稿です。
結果を一般的な日本語音声の認識精度として扱うことはできません。
