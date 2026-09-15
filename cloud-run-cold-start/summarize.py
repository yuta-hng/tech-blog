import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


VALID_FIRST_STATES = {
    "min-0": "new_process",
    "min-1": "prestarted_process",
}


def describe(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "median": round(statistics.median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def summarize_service(target: dict, expected_warm_requests: int) -> dict:
    first_rows = [
        row for row in target["requests"] if row["phase"] == "first_after_idle"
    ]
    first = first_rows[0] if len(first_rows) == 1 else None
    expected_state = VALID_FIRST_STATES.get(target["group"])
    first_valid = (
        first is not None
        and first.get("observed_state") == expected_state
        and "response" in first
    )
    first_outcome = (
        "valid"
        if first_valid
        else first.get("error_type", "invalid_or_ambiguous")
        if first
        else "missing"
    )

    warm_rows = [
        row
        for row in target["requests"]
        if row["phase"] == "warm"
        and row.get("observed_state") == "same_process"
        and "response" in row
    ]
    warm_attempts = [row for row in target["requests"] if row["phase"] == "warm"]
    outcome_counts = Counter(
        "valid"
        if row.get("observed_state") == "same_process" and "response" in row
        else row.get("error_type", "invalid_or_ambiguous")
        for row in warm_attempts
    )
    return {
        "group": target["group"],
        "label": target["label"],
        "first": {
            "valid": first_valid,
            "outcome": first_outcome,
            "observed_state": first.get("observed_state") if first else "missing",
            "client_latency_ms": first.get("client_latency_ms") if first else None,
            "http_status": first.get("http_status") if first else None,
            "app_uptime_ms": (
                first["response"]["app_uptime_ms"] if first_valid else None
            ),
            "request_index": (
                first["response"]["request_index"] if first_valid else None
            ),
        },
        "warm": {
            "complete": (
                len(warm_attempts) == expected_warm_requests
                and len(warm_rows) == expected_warm_requests
            ),
            "expected_request_count": expected_warm_requests,
            "valid_request_count": len(warm_rows),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "client_latency_ms": describe(
                [row["client_latency_ms"] for row in warm_rows]
            ),
        },
    }


def summarize(measurements: dict) -> dict:
    if measurements.get("schema_version") != 2:
        raise ValueError("measurements must use schema_version 2")

    expected_warm_requests = measurements["settings"][
        "warm_request_count_per_service"
    ]
    services = [
        summarize_service(target, expected_warm_requests)
        for target in measurements["targets"]
    ]
    by_group = defaultdict(list)
    for service in services:
        by_group[service["group"]].append(service)

    groups = {}
    for group, group_services in sorted(by_group.items()):
        valid_first = [service for service in group_services if service["first"]["valid"]]
        first_outcomes = Counter(
            service["first"]["outcome"] for service in group_services
        )
        complete_warm_services = [
            service for service in group_services if service["warm"]["complete"]
        ]
        warm_outcomes = Counter()
        for service in group_services:
            warm_outcomes.update(service["warm"]["outcome_counts"])
        groups[group] = {
            "service_count": len(group_services),
            "first": {
                "valid_service_count": len(valid_first),
                "excluded_service_count": len(group_services) - len(valid_first),
                "outcome_counts": dict(sorted(first_outcomes.items())),
                "client_latency_ms": describe(
                    [service["first"]["client_latency_ms"] for service in valid_first]
                ),
                "app_uptime_ms": describe(
                    [service["first"]["app_uptime_ms"] for service in valid_first]
                ),
            },
            "warm": {
                "complete_service_count": len(complete_warm_services),
                "incomplete_service_count": (
                    len(group_services) - len(complete_warm_services)
                ),
                "request_count_in_complete_services": sum(
                    service["warm"]["valid_request_count"]
                    for service in complete_warm_services
                ),
                "outcome_counts": dict(sorted(warm_outcomes.items())),
                "per_service_median_client_latency_ms": describe(
                    [
                        service["warm"]["client_latency_ms"]["median"]
                        for service in complete_warm_services
                    ]
                ),
            },
        }
    return {
        "schema_version": 1,
        "run_id": measurements["run_id"],
        "groups": groups,
        "services": services,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize cold-start measurements.")
    parser.add_argument("measurements", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        measurements = json.loads(args.measurements.read_text(encoding="utf-8"))
        result = summarize(measurements)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"invalid measurements: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
