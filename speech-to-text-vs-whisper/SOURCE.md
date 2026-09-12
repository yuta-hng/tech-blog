# 検証素材

## 出典

- タイトル: 02-203_入門 自作検索エンジン(ryo kato)
- 登壇者: ryo kato
- イベント: PyCon JP 2019
- 公開者: PyCon JP公式YouTubeチャンネル
- URL: https://www.youtube.com/watch?v=5EEH8MHfAyA
- ライセンス: Creative Commons Attribution
- ライセンス確認先: https://www.pycon.jp/committee/license.html

YouTubeの動画メタデータでも `Creative Commons Attribution license (reuse allowed)` と表示されることを2026年9月12日に確認した。
PyCon JPの動画に関する記載とYouTubeの動画情報にはバージョン番号が明記されていないため、推測せず `CC BY` と表記する。

## 使用範囲と加工

- 元動画の長さ: 37分06秒
- 切り出し開始: 7分51.08秒
- 切り出し終了: 36分22.00秒
- 検証音声の長さ: 28分30.94秒
- 変換: AAC 44.1kHzステレオからFLAC 16kHzモノラル
- 内容: セッション紹介、講演、質疑

`prepare_audio.py` で切り出しと変換を再現できる。
元動画、切り出した音声、YouTube自動字幕はこのリポジトリでは再配布しない。
利用者は動画のライセンスとYouTubeの利用規約を確認し、自分が利用できる方法で素材を用意する。

## SHA-256

```text
ca8fad0368e0dbb061113181716d9202baf9278dfe13fd89b0841339257f301b  5EEH8MHfAyA.m4a
c4eff1ba9679cc5feb397ab3a12d3d21e80cfe9d14681a95122a491efc39f5fa  pyconjp-search-talk.flac
8c80bd800744f71fd790b868e3f9433adc6a63450b762c07e12ff8bf88709511  5EEH8MHfAyA.ja-orig.json3
```

## 自動字幕の扱い

`5EEH8MHfAyA.ja-orig.json3` はYouTubeの日本語自動字幕であり、人が確認した正解データではない。
検証では出力間の参考比較にだけ使い、正解率の算出には使わない。
