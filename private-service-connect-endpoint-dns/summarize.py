#!/usr/bin/env python3
"""Recompute case verdicts and counts from saved observations, without cloud calls."""
import argparse
import hashlib
import json
from pathlib import Path

from measure import ok, validate_case

EXPECTED = ["pending", "accepted_ip", "dns_ready", "dns_removed", "restored",
            "firewall_disabled", "restored"]


def summarize(directory):
    environment = json.loads((directory / "environment.json").read_text())
    cases = json.loads((directory / "cases.json").read_text())
    if not environment.get("completed") or environment.get("restore_failures"):
        raise ValueError("The measurement did not complete or restoration failed")
    if [case["case"] for case in cases] != EXPECTED:
        raise ValueError("Missing, reordered, or unexpected cases")
    rows = []
    for index, case in enumerate(cases, 1):
        probes = case["probes"]
        if len(probes) != 3 or [p["attempt"] for p in probes] != [1, 2, 3]:
            raise ValueError("Each case requires exactly three numbered observations")
        if not case["passed"] or not all(validate_case(case["case"], case[s], probes)
                                         for s in ["before", "after"]):
            raise ValueError("Stored verdict or observations failed: " + case["case"])
        rows.append({"index": index, "case": case["case"], "samples_per_target": len(probes),
            "psc_before": case["before"]["psc_status"], "psc_after": case["after"]["psc_status"],
            "health_before": case["before"]["backend_health"], "health_after": case["after"]["backend_health"],
            "ip_successes": sum(ok(p["ip"]) for p in probes),
            "hostname_successes": sum(ok(p["hostname"]) for p in probes),
            "ip_exit_codes": sorted({p["ip"]["exit_code"] for p in probes}),
            "hostname_exit_codes": sorted({p["hostname"]["exit_code"] for p in probes}),
            "peer_ips": sorted({p[t]["payload"]["peer_ip"] for p in probes
                                for t in ["ip", "hostname"] if ok(p[t])}),
            "first_probe_utc": probes[0]["utc"], "last_probe_utc": probes[-1]["utc"]})
    return {"completed": True, "case_count": len(rows),
            "http_requests_in_cases": sum(r["samples_per_target"] * 2 for r in rows),
            "settling_probes_included": False, "cases": rows,
            "evidence_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                for name in ["cases.json", "events.jsonl", "environment.json"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory), indent=2))


if __name__ == "__main__":
    main()
