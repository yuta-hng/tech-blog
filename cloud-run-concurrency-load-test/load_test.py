import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percent
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def send_request(url: str, timeout: float) -> dict:
    started = time.perf_counter()
    status = 0
    error = None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = response.status
            response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        error = str(exc)
    except (urllib.error.URLError, TimeoutError) as exc:
        error = str(exc)
    return {
        "status": status,
        "latency_ms": (time.perf_counter() - started) * 1000,
        "error": error,
    }


def run_once(url: str, requests: int, clients: int, timeout: float) -> dict:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=clients) as pool:
        futures = [pool.submit(send_request, url, timeout) for _ in range(requests)]
        rows = [future.result() for future in as_completed(futures)]
    duration = time.perf_counter() - started
    latencies = [row["latency_ms"] for row in rows]
    statuses = Counter(str(row["status"]) for row in rows)
    successes = sum(1 for row in rows if 200 <= row["status"] < 300)
    return {
        "request_count": requests,
        "clients": clients,
        "duration_seconds": round(duration, 3),
        "requests_per_second": round(requests / duration, 3),
        "success_rate_percent": round(successes / requests * 100, 3),
        "status_counts": dict(sorted(statuses.items())),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3),
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies), 3),
        },
    }


def redact_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parts.scheme, "<SERVICE_URL>", parts.path, parts.query, "")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded HTTP load test.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if min(args.requests, args.clients, args.repeat) < 1 or args.warmup < 0:
        raise SystemExit("requests, clients, and repeat must be positive; warmup must be non-negative")

    if args.warmup:
        run_once(args.url, args.warmup, min(args.clients, args.warmup), args.timeout)

    result = {
        "label": args.label,
        "url": redact_url(args.url),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "runs": [
            run_once(args.url, args.requests, args.clients, args.timeout)
            for _ in range(args.repeat)
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
