#!/usr/bin/env python3
"""Compare CER and Japanese WER preprocessing on fixed ASR outputs."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import jiwer
from sudachipy import dictionary, tokenizer


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "cases.json"
DEFAULT_OUTPUT = ROOT / "results" / "scores.json"
CER_PATTERN = re.compile(r"[^0-9a-zA-Z一-龠ぁ-んァ-ヶー]")
SUDACHI_MODES = {
    "A": tokenizer.Tokenizer.SplitMode.A,
    "B": tokenizer.Tokenizer.SplitMode.B,
    "C": tokenizer.Tokenizer.SplitMode.C,
}


def normalize_for_cer(text: str) -> str:
    """Match the normalization used in the September 11 experiment."""
    return CER_PATTERN.sub("", text).lower()


def is_scored_token(surface: str) -> bool:
    """Drop whitespace and tokens made only from punctuation or symbols."""
    return any(unicodedata.category(char)[0] in {"L", "N"} for char in surface)


@lru_cache(maxsize=3)
def get_sudachi_tokenizer(mode_name: str):
    return dictionary.Dictionary().create(mode=SUDACHI_MODES[mode_name])


def sudachi_tokens(text: str, mode_name: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    sudachi = get_sudachi_tokenizer(mode_name)
    return [
        morpheme.surface()
        for morpheme in sudachi.tokenize(normalized)
        if is_scored_token(morpheme.surface())
    ]


def word_score(reference: str, hypothesis: str) -> dict[str, int | float]:
    result = jiwer.process_words(reference, hypothesis)
    return {
        "reference_tokens": result.hits + result.substitutions + result.deletions,
        "hypothesis_tokens": result.hits + result.substitutions + result.insertions,
        "substitutions": result.substitutions,
        "deletions": result.deletions,
        "insertions": result.insertions,
        "hits": result.hits,
        "wer": result.wer,
    }


def character_score(reference: str, hypothesis: str) -> dict[str, int | float]:
    result = jiwer.process_characters(reference, hypothesis)
    return {
        "reference_characters": result.hits + result.substitutions + result.deletions,
        "hypothesis_characters": result.hits + result.substitutions + result.insertions,
        "substitutions": result.substitutions,
        "deletions": result.deletions,
        "insertions": result.insertions,
        "hits": result.hits,
        "cer": result.cer,
    }


def evaluate_case(reference: str, hypothesis: str) -> dict:
    normalized_reference = normalize_for_cer(reference)
    normalized_hypothesis = normalize_for_cer(hypothesis)
    scores: dict[str, dict] = {
        "raw_cer": character_score(reference, hypothesis),
        "normalized_cer": character_score(
            normalized_reference, normalized_hypothesis
        ),
        "whitespace_wer": word_score(reference, hypothesis),
        "linebreak_as_space_wer": word_score(
            reference.replace("\n", " "), hypothesis.replace("\n", " ")
        ),
    }

    for mode_name in SUDACHI_MODES:
        reference_tokens = sudachi_tokens(reference, mode_name)
        hypothesis_tokens = sudachi_tokens(hypothesis, mode_name)
        scores[f"sudachi_{mode_name.lower()}_wer"] = word_score(
            " ".join(reference_tokens), " ".join(hypothesis_tokens)
        )
    return scores


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    reference = source["reference"]
    evaluated = []
    for case in source["cases"]:
        evaluated.append(
            {
                "name": case["name"],
                "audio": case["audio"],
                "hints": case["hints"],
                "scores": evaluate_case(reference, case["hypothesis"]),
            }
        )

    output = {
        "source": source["source"],
        "normalization": {
            "cer": "lowercase and keep only ASCII alphanumerics, kanji, hiragana, katakana, and prolonged sound marks",
            "whitespace_wer": "JiWER default: split on ASCII spaces without replacing line breaks",
            "linebreak_as_space_wer": "replace line breaks with ASCII spaces, then use JiWER default",
            "sudachi_wer": "NFKC, lowercase, remove punctuation/symbol tokens, and tokenize with SudachiDict core surface forms",
        },
        "cases": evaluated,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    headers = [
        "case",
        "raw CER",
        "normalized CER",
        "whitespace WER",
        "linebreak as space WER",
        "Sudachi A WER",
        "Sudachi B WER",
        "Sudachi C WER",
    ]
    print("\t".join(headers))
    for case in evaluated:
        scores = case["scores"]
        values = [
            case["name"],
            f'{scores["raw_cer"]["cer"]:.3%}',
            f'{scores["normalized_cer"]["cer"]:.3%}',
            f'{scores["whitespace_wer"]["wer"]:.3%}',
            f'{scores["linebreak_as_space_wer"]["wer"]:.3%}',
            f'{scores["sudachi_a_wer"]["wer"]:.3%}',
            f'{scores["sudachi_b_wer"]["wer"]:.3%}',
            f'{scores["sudachi_c_wer"]["wer"]:.3%}',
        ]
        print("\t".join(values))


if __name__ == "__main__":
    main()
