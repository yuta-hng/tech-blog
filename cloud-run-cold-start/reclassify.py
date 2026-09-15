import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from measure import classify_first


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reclassify_target(target: dict, settings: dict) -> None:
    requests = target.get("requests", [])
    if not requests:
        return

    first = requests[0]
    first_response = first.get("response")
    first["observed_state"] = classify_first(
        target.get("group", ""),
        first_response,
        settings["new_process_max_uptime_ms"],
        settings["prestarted_min_uptime_ms"],
    )

    for offset, row in enumerate(requests[1:], start=1):
        response = row.get("response")
        if (
            first_response is not None
            and response is not None
            and response.get("process_id") == first_response.get("process_id")
            and response.get("request_index")
            == first_response.get("request_index") + offset
        ):
            row["observed_state"] = "same_process"
        else:
            row["observed_state"] = "invalid_or_ambiguous"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reclassify process-state observations without changing measurements."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.input.resolve() == args.output.resolve():
        raise SystemExit("input and output must be different files")

    result = json.loads(args.input.read_text(encoding="utf-8"))
    schema_version = result.get("schema_version")
    if schema_version != 2:
        raise SystemExit(f"unsupported schema_version: {schema_version!r}")

    settings = result.setdefault("settings", {})
    settings.setdefault("new_process_max_uptime_ms", 5000.0)
    settings.setdefault("prestarted_min_uptime_ms", 5000.0)

    for target in result.get("targets", []):
        reclassify_target(target, settings)

    result["reclassified_from_schema_version"] = schema_version
    result["reclassified_at"] = utc_now()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)

    if any(
        row.get("observed_state") == "invalid_or_ambiguous"
        for target in result.get("targets", [])
        for row in target.get("requests", [])
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
