#!/usr/bin/env python3
"""Compare Speech-to-Text V2 and local Whisper on a PyCon JP talk."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
AUDIO_PATH = ROOT / "source" / "pyconjp-search-talk.flac"
YOUTUBE_CAPTIONS_PATH = ROOT / "source" / "5EEH8MHfAyA.ja-orig.json3"
RESULTS_DIR = ROOT / "results"
VIDEO_ID = "5EEH8MHfAyA"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
CLIP_START_SECONDS = 471.08
CLIP_END_SECONDS = 2182.00
TECHNICAL_TERMS = {
    "Python": ["Python", "パイソン"],
    "Elasticsearch": ["Elasticsearch", "エラスティックサーチ"],
    "Solr": ["Solr", "ソーラー", "ソルアー"],
    "OSS": ["OSS", "オープンソースソフトウェア"],
    "Grep": ["Grep", "グレップ"],
    "転置インデックス": ["転置インデックス", "逆インデックス"],
    "ポスティングリスト": ["ポスティングリスト"],
    "トークナイズ": ["トークナイズ", "トークン化"],
    "形態素解析": ["形態素解析"],
    "N-gram": ["N-gram", "Nグラム", "エヌグラム"],
    "Character Filter": ["Character Filter", "キャラクターフィルター"],
    "Tokenizer": ["Tokenizer", "トークナイザー"],
    "Token Filter": ["Token Filter", "トークンフィルター"],
    "Analyzer": ["Analyzer", "アナライザー"],
    "TF-IDF": ["TF-IDF", "TFIDF", "ティーエフアイディーエフ"],
    "Janome": ["Janome", "ジャノメ"],
    "NLTK": ["NLTK"],
    "Porter Stemmer": ["Porter Stemmer", "ポーターステマー"],
}


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z一-龠ぁ-んァ-ヶー]", "", text).lower()


def edit_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def youtube_caption_text() -> str:
    source = json.loads(YOUTUBE_CAPTIONS_PATH.read_text(encoding="utf-8"))
    parts = []
    for event in source["events"]:
        start_seconds = event.get("tStartMs", 0) / 1000
        if not CLIP_START_SECONDS <= start_seconds < CLIP_END_SECONDS:
            continue
        text = "".join(segment.get("utf8", "") for segment in event.get("segs", []))
        text = text.replace("\n", "").strip()
        if text:
            parts.append(text)
    return "".join(parts)


def evaluate(transcript: str, final_offset_seconds: float | None) -> dict:
    normalized = normalize(transcript)
    caption = normalize(youtube_caption_text())
    distance = edit_distance(caption, normalized)
    term_matches = {
        canonical: next(
            (alias for alias in aliases if normalize(alias) in normalized),
            None,
        )
        for canonical, aliases in TECHNICAL_TERMS.items()
    }
    return {
        "normalized_characters": len(normalized),
        "youtube_auto_caption_characters": len(caption),
        "youtube_auto_caption_edit_distance": distance,
        "youtube_auto_caption_cer": distance / len(caption),
        "term_matches": term_matches,
        "matched_term_count": sum(value is not None for value in term_matches.values()),
        "term_count": len(term_matches),
        "final_offset_seconds": final_offset_seconds,
    }


def result_path(engine: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return RESULTS_DIR / f"{engine}-{timestamp}.json"


def save_result(engine: str, payload: dict) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    output_path = result_path(engine)
    common = {
        "created_at": datetime.now().astimezone().isoformat(),
        "source": {
            "video_id": VIDEO_ID,
            "video_url": VIDEO_URL,
            "title": "入門 自作検索エンジン",
            "event": "PyCon JP 2019",
            "speaker": "ryo kato",
            "license": "Creative Commons Attribution",
            "clip_start_seconds": CLIP_START_SECONDS,
            "clip_end_seconds": CLIP_END_SECONDS,
            "audio_duration_seconds": CLIP_END_SECONDS - CLIP_START_SECONDS,
            "audio_path": str(AUDIO_PATH.relative_to(ROOT)),
            "audio_sha256": sha256(AUDIO_PATH),
        },
        "reference_note": (
            "The YouTube caption is automatically generated. Agreement with it is "
            "reported for reproducibility, but it is not treated as ground truth."
        ),
        **payload,
    }
    output_path.write_text(
        json.dumps(common, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def run_whisper(models: list[str], cpu_threads: int, beam_size: int) -> Path:
    import ctranslate2
    import faster_whisper
    from faster_whisper import WhisperModel

    records = []
    for model_name in models:
        load_started = time.perf_counter()
        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
        )
        load_seconds = time.perf_counter() - load_started

        transcribe_started = time.perf_counter()
        segments, info = model.transcribe(
            str(AUDIO_PATH),
            language="ja",
            task="transcribe",
            beam_size=beam_size,
            vad_filter=False,
            condition_on_previous_text=True,
        )
        segments = list(segments)
        transcribe_seconds = time.perf_counter() - transcribe_started
        transcript = "".join(segment.text for segment in segments).strip()
        final_offset = segments[-1].end if segments else None
        records.append(
            {
                "engine": "faster-whisper",
                "model": model_name,
                "load_seconds": load_seconds,
                "transcribe_seconds": transcribe_seconds,
                "transcript": transcript,
                "evaluation": evaluate(transcript, final_offset),
                "language_probability": info.language_probability,
                "segments": [
                    {"start": segment.start, "end": segment.end, "text": segment.text}
                    for segment in segments
                ],
            }
        )

    return save_result(
        "whisper",
        {
            "runtime": {
                "implementation": "faster-whisper",
                "faster_whisper_version": faster_whisper.__version__,
                "ctranslate2_version": ctranslate2.__version__,
                "device": "cpu",
                "compute_type": "int8",
                "cpu_threads": cpu_threads,
                "beam_size": beam_size,
                "vad_filter": False,
                "condition_on_previous_text": True,
                "logical_cpu_count": os.cpu_count(),
                "platform": platform.platform(),
                "python_version": platform.python_version(),
            },
            "records": records,
        },
    )


def gcloud_value(*args: str) -> str:
    return subprocess.check_output(["gcloud", *args], text=True).strip()


def request_json(url: str, token: str, project: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        ),
        headers={
            "Authorization": f"Bearer {token}",
            "X-Goog-User-Project": project,
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000]}") from exc


def run_google(gcs_uri: str, poll_seconds: int) -> Path:
    project = gcloud_value("config", "get-value", "project")
    token = gcloud_value("auth", "print-access-token")
    recognizer = f"projects/{project}/locations/global/recognizers/_"
    payload = {
        "config": {
            "autoDecodingConfig": {},
            "languageCodes": ["ja-JP"],
            "model": "long",
            "features": {"enableAutomaticPunctuation": True},
        },
        "files": [{"uri": gcs_uri}],
        "recognitionOutputConfig": {"inlineResponseConfig": {}},
    }

    started = time.perf_counter()
    operation = request_json(
        f"https://speech.googleapis.com/v2/{recognizer}:batchRecognize",
        token,
        project,
        payload,
    )
    operation_url = f"https://speech.googleapis.com/v2/{operation['name']}"
    while not operation.get("done"):
        time.sleep(poll_seconds)
        token = gcloud_value("auth", "print-access-token")
        operation = request_json(operation_url, token, project)
    elapsed = time.perf_counter() - started
    if "error" in operation:
        raise RuntimeError(json.dumps(operation["error"], ensure_ascii=False))

    file_result = operation["response"]["results"][gcs_uri]
    transcript_results = file_result["inlineResult"]["transcript"]["results"]
    transcript = "".join(
        result.get("alternatives", [{}])[0].get("transcript", "")
        for result in transcript_results
    ).strip()
    offsets = [
        float(result["resultEndOffset"].rstrip("s"))
        for result in transcript_results
        if result.get("resultEndOffset")
    ]
    return save_result(
        "google",
        {
            "runtime": {
                "api": "Speech-to-Text V2 batchRecognize",
                "model": "long",
                "language_code": "ja-JP",
                "input_object": gcs_uri.rsplit("/", 1)[-1],
            },
            "records": [
                {
                    "engine": "google-cloud-speech-to-text-v2",
                    "model": "long",
                    "transcribe_seconds": elapsed,
                    "transcript": transcript,
                    "evaluation": evaluate(transcript, max(offsets) if offsets else None),
                    "total_billed_duration": operation["response"].get(
                        "totalBilledDuration"
                    ),
                }
            ],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    whisper_parser = subparsers.add_parser("whisper")
    whisper_parser.add_argument(
        "--models", nargs="+", default=["small", "large-v3-turbo"]
    )
    whisper_parser.add_argument("--cpu-threads", type=int, default=6)
    whisper_parser.add_argument("--beam-size", type=int, default=5)

    google_parser = subparsers.add_parser("google")
    google_parser.add_argument("--gcs-uri", required=True)
    google_parser.add_argument("--poll-seconds", type=int, default=10)

    args = parser.parse_args()
    if args.command == "whisper":
        output = run_whisper(args.models, args.cpu_threads, args.beam_size)
    else:
        output = run_google(args.gcs_uri, args.poll_seconds)
    print(output)


if __name__ == "__main__":
    main()
