#!/usr/bin/env python3
"""Run on the consumer VM; report DNS and independent, fresh HTTP requests."""
import argparse
from datetime import datetime, timezone
import json
import subprocess
import time


def http(target):
    start = time.monotonic()
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--noproxy", "*", "--connect-timeout", "2",
         "--max-time", "3", "--write-out", "\n%{http_code}", "http://" + target + "/"],
        capture_output=True, text=True, timeout=8,
    )
    body, _, status = result.stdout.rpartition("\n")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    return {"exit_code": result.returncode, "http_status": status,
            "payload": payload, "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
            "error": result.stderr.strip()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--name", default="hello.psc.test")
    args = parser.parse_args()
    if not 1 <= args.attempts <= 10:
        parser.error("attempts must be 1..10")
    rows = []
    for attempt in range(1, args.attempts + 1):
        dns = subprocess.run(["dig", "+time=2", "+tries=1", "+noall", "+comments", "+answer",
                              args.name, "A"], capture_output=True, text=True, timeout=8)
        rows.append({"utc": datetime.now(timezone.utc).isoformat(), "attempt": attempt,
                     "dns": {"exit_code": dns.returncode, "answer": dns.stdout.strip()},
                     "ip": http("10.20.0.10"), "hostname": http(args.name)})
        if attempt < args.attempts:
            time.sleep(1)
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
