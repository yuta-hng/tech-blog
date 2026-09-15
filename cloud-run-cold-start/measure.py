import argparse
import http.client
import json
import platform
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
PROCESS_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
RESPONSE_FIELDS = (
    "app_initialized_at",
    "app_uptime_ms",
    "ok",
    "process_id",
    "request_index",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_target(value: str) -> tuple[str, str, str]:
    parts = value.split(",", 2)
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError("target must be GROUP,LABEL,URL")
    group, label, url = parts
    if not IDENTIFIER_PATTERN.fullmatch(group) or not IDENTIFIER_PATTERN.fullmatch(label):
        raise argparse.ArgumentTypeError(
            "group and label must contain only lowercase letters, digits, and hyphens"
        )
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise argparse.ArgumentTypeError("target URL must use http or https")
    if parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("target URL must not contain credentials")
    return group, label, url


def filter_response(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("response must be an object")
    filtered = {field: payload.get(field) for field in RESPONSE_FIELDS}
    if filtered["ok"] is not True:
        raise ValueError("ok must be true")
    if not isinstance(filtered["app_initialized_at"], str):
        raise ValueError("app_initialized_at must be a string")
    uptime = filtered["app_uptime_ms"]
    if isinstance(uptime, bool) or not isinstance(uptime, (int, float)) or uptime < 0:
        raise ValueError("app_uptime_ms must be a non-negative number")
    process_id = filtered["process_id"]
    if not isinstance(process_id, str) or not PROCESS_ID_PATTERN.fullmatch(process_id):
        raise ValueError("process_id must be a 32-character hexadecimal string")
    request_index = filtered["request_index"]
    if isinstance(request_index, bool) or not isinstance(request_index, int) or request_index < 1:
        raise ValueError("request_index must be a positive integer")
    return filtered


def elapsed_ms(started_ns: int) -> float:
    return round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)


def request_error(
    requested_at: str,
    started_ns: int,
    status: int,
    error_type: str,
) -> dict:
    return {
        "request_started_at": requested_at,
        "client_latency_ms": elapsed_ms(started_ns),
        "http_status": status,
        "error_type": error_type,
    }


def send_request(url: str, timeout: float) -> dict:
    requested_at = utc_now()
    started_ns = time.perf_counter_ns()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = response.status
            try:
                payload = filter_response(json.load(response))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return request_error(
                    requested_at,
                    started_ns,
                    status,
                    "invalid_json",
                )
            except ValueError:
                return request_error(
                    requested_at,
                    started_ns,
                    status,
                    "invalid_payload",
                )
    except urllib.error.HTTPError as exc:
        exc.close()
        return request_error(requested_at, started_ns, exc.code, "http_error")
    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        http.client.HTTPException,
        OSError,
    ):
        return request_error(requested_at, started_ns, 0, "connection_error")

    return {
        "request_started_at": requested_at,
        "client_latency_ms": elapsed_ms(started_ns),
        "http_status": status,
        "response": payload,
    }


def classify_first(
    group: str,
    response: dict | None,
    new_process_max_uptime_ms: float,
    prestarted_min_uptime_ms: float,
) -> str:
    if response is None:
        return "invalid_or_ambiguous"
    if (
        group == "min-0"
        and response["request_index"] == 1
        and response["app_uptime_ms"] <= new_process_max_uptime_ms
    ):
        return "new_process"
    if group == "min-1" and response["app_uptime_ms"] >= prestarted_min_uptime_ms:
        return "prestarted_process"
    return "invalid_or_ambiguous"


def measure_target(
    group: str,
    label: str,
    url: str,
    warm_requests: int,
    delay_seconds: float,
    timeout: float,
    new_process_max_uptime_ms: float,
    prestarted_min_uptime_ms: float,
) -> dict:
    rows = []
    first_response = None
    for index in range(warm_requests + 1):
        row = send_request(url, timeout)
        row["sequence"] = index + 1
        row["phase"] = "first_after_idle" if index == 0 else "warm"
        response = row.get("response")
        if index == 0:
            first_response = response
            row["observed_state"] = classify_first(
                group,
                response,
                new_process_max_uptime_ms,
                prestarted_min_uptime_ms,
            )
        elif (
            first_response is not None
            and response is not None
            and response["process_id"] == first_response["process_id"]
            and response["request_index"]
            == first_response["request_index"] + index
        ):
            row["observed_state"] = "same_process"
        else:
            row["observed_state"] = "invalid_or_ambiguous"
        rows.append(row)
        if index < warm_requests and delay_seconds:
            time.sleep(delay_seconds)
    return {"group": group, "label": label, "requests": rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure first-after-idle and warm request latency without storing URLs."
    )
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        type=parse_target,
        metavar="GROUP,LABEL,URL",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--client-label", required=True)
    parser.add_argument("--warm-requests", type=int, default=5)
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--new-process-max-uptime-ms", type=float, default=5000.0)
    parser.add_argument("--prestarted-min-uptime-ms", type=float, default=5000.0)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if (
        args.warm_requests < 0
        or args.delay_seconds < 0
        or args.timeout <= 0
        or args.new_process_max_uptime_ms < 0
        or args.prestarted_min_uptime_ms < 0
    ):
        raise SystemExit("request counts, delays, timeouts, and thresholds are invalid")

    started_at = utc_now()
    targets = [
        measure_target(
            group,
            label,
            url,
            args.warm_requests,
            args.delay_seconds,
            args.timeout,
            args.new_process_max_uptime_ms,
            args.prestarted_min_uptime_ms,
        )
        for group, label, url in args.target
    ]
    result = {
        "schema_version": 2,
        "run_id": args.run_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "client_label": args.client_label,
        "client_platform": platform.platform(),
        "python_version": platform.python_version(),
        "settings": {
            "warm_request_count_per_service": args.warm_requests,
            "delay_seconds": args.delay_seconds,
            "timeout_seconds": args.timeout,
            "new_process_max_uptime_ms": args.new_process_max_uptime_ms,
            "prestarted_min_uptime_ms": args.prestarted_min_uptime_ms,
            "connection_reuse": False,
            "automatic_retries": 0,
        },
        "targets": targets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    has_invalid_observation = any(
        row["observed_state"] == "invalid_or_ambiguous"
        for target in targets
        for row in target["requests"]
    )
    if has_invalid_observation:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
