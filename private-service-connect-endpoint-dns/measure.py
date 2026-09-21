#!/usr/bin/env python3
"""Measure only resources recorded by lab.py; restore injected failures on exit."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

from lab import Lab, ROOT, REGION, ZONE, utc


def ok(result):
    return (result["exit_code"] == 0 and result["http_status"] == "200"
            and isinstance(result["payload"], dict) and result["payload"].get("message") == "psc-lab-ok")


def validate_case(label, snapshot, rows):
    """Wrong results fail the run and remain in the evidence file."""
    if not rows or snapshot["backend_health"] != ["HEALTHY"]:
        return False
    if label == "pending":
        return snapshot["psc_status"] == "PENDING" and all(r["ip"]["exit_code"] in [7, 28] for r in rows)
    if snapshot["psc_status"] != "ACCEPTED":
        return False
    if label == "dns_removed":
        return all(ok(r["ip"]) and r["hostname"]["exit_code"] == 6
                   and "status: NXDOMAIN" in r["dns"]["answer"] for r in rows)
    if label == "firewall_disabled":
        return snapshot["nat_http_rule_disabled"] and all(
            "10.20.0.10" in r["dns"]["answer"] and r["ip"]["exit_code"] == 28
            and r["hostname"]["exit_code"] == 28 for r in rows)
    if label in ["accepted_ip", "dns_ready", "restored"]:
        for row in rows:
            if not ok(row["ip"]):
                return False
            if ipaddress.ip_address(row["ip"]["payload"].get("peer_ip", "0.0.0.0")) not in ipaddress.ip_network("10.10.10.0/24"):
                return False
            if label != "accepted_ip" and (not ok(row["hostname"]) or "10.20.0.10" not in row["dns"]["answer"]):
                return False
        return not snapshot["nat_http_rule_disabled"]
    raise ValueError("unknown case")


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--producer-project", required=True)
    p.add_argument("--consumer-project", required=True)
    p.add_argument("--prefix", default="psc-lab-0921")
    args = p.parse_args()
    import re
    if not re.fullmatch(r"psc-lab-[a-z0-9-]{1,24}", args.prefix):
        p.error("invalid prefix")
    lab = Lab(args)
    lab.load()
    if not lab.state.get("complete"):
        raise RuntimeError("Creation did not complete")
    output = ROOT / "results" / utc().replace(":", "").replace(".", "-").replace("+", "_")
    output.mkdir(parents=True, exist_ok=False)
    events = output / "events.jsonl"
    cases = []

    def record(name, **fields):
        with events.open("a") as f:
            f.write(json.dumps({"utc": utc(), "event": name, **fields}) + "\n")
        print(name, flush=True)

    def save():
        (output / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")

    def wait_until(description, predicate, seconds=180):
        deadline = time.monotonic() + seconds
        while True:
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for " + description)
            print("Waiting for " + description, flush=True)
            time.sleep(5)

    probe_text = (ROOT / "probe.py").read_text()
    encoded = base64.b64encode(probe_text.encode()).decode()
    remote = "import base64;exec(compile(base64.b64decode(" + repr(encoded) + "),'probe.py','exec'))"

    def probes(attempts):
        result = lab.ssh("c", "python3 -c " + shlex.quote(remote) + " --attempts " + str(attempts))
        return json.loads(result.stdout)

    def capture(label, settle=False):
        if settle:
            def ready():
                snapshot = lab.status()
                rows = probes(1)
                success = validate_case(label, snapshot, rows)
                record("settle_probe", case=label, status=snapshot, probes=rows, matched=success)
                return success
            # Includes DNS negative caching; no assumption that TTL is an exact convergence bound.
            wait_until(label, ready, 300)
        before = lab.status()
        rows = probes(3)
        after = lab.status()
        passed = validate_case(label, before, rows) and validate_case(label, after, rows)
        cases.append({"case": label, "before": before, "probes": rows, "after": after, "passed": passed})
        save()
        record("case_complete", case=label, passed=passed)
        if not passed:
            raise RuntimeError("Unexpected observation in " + label + "; saved actual observations")

    dns_restore_needed = False
    firewall_restore_needed = False
    environment = {"region": REGION, "zone": ZONE, "vm_machine_type": "e2-micro", "vm_count": 2,
                   "same_project": args.producer_project == args.consumer_project, "dns_ttl": 30,
                   "attempts_per_case": 3, "http_connect_timeout_s": 2, "http_max_time_s": 3,
                   "network_scope": "two isolated VPCs", "started_utc": utc(), "completed": False,
                   "source_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
                                     for f in ["lab.py", "measure.py", "probe.py", "startup.sh"]}}
    try:
        for side in ["p", "c"]:
            wait_until("VM startup " + side,
                       lambda side=side: lab.ssh(side, "test -f /opt/psc-lab/ready", check=False).returncode == 0, 600)
        environment["gcloud_version"] = json.loads(subprocess.run(
            ["gcloud", "version", "--format=json"], capture_output=True, text=True, check=True).stdout)
        environment["vm_versions"] = {}
        for side in ["p", "c"]:
            environment["vm_versions"][side] = lab.ssh(side,
                "cat /etc/debian_version; python3 --version; curl --version; dig -v").stdout.strip()
        wait_until("healthy backend", lambda: lab.status()["backend_health"] == ["HEALTHY"])
        if lab.status()["psc_status"] != "PENDING":
            raise RuntimeError("Expected a fresh, unapproved endpoint; do not reuse an already measured lab")
        capture("pending")
        record("accept_start")
        lab.call(args.producer_project, "compute", "service-attachments", "update", args.prefix + "-service",
                 "--region=" + REGION, "--consumer-accept-list=" + args.consumer_project + "=1")
        capture("accepted_ip", settle=True)
        lab.dns(True)
        capture("dns_ready", settle=True)
        dns_restore_needed = True  # Mark before mutation: a client timeout may still apply it.
        record("dns_delete_start")
        lab.dns(False)
        capture("dns_removed", settle=True)
        lab.dns(True)
        dns_restore_needed = False
        capture("restored", settle=True)
        firewall_restore_needed = True
        record("firewall_disable_start")
        lab.firewall(True)
        capture("firewall_disabled", settle=True)
        lab.firewall(False)
        firewall_restore_needed = False
        capture("restored", settle=True)
        environment["completed"] = True
    finally:
        restore_failures = []
        # Restore independently; one failure must not prevent the other attempt.
        for needed, name, action in [(firewall_restore_needed, "firewall", lambda: lab.firewall(False)),
                                     (dns_restore_needed, "dns", lambda: lab.dns(True))]:
            if needed:
                try:
                    action()
                    record("restored_on_exit", resource=name)
                except Exception:
                    restore_failures.append(name)
                    record("restore_failed", resource=name)
        environment["finished_utc"] = utc()
        environment["restore_failures"] = restore_failures
        if restore_failures:
            environment["completed"] = False
        (output / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
        save()
        print("Evidence saved to " + str(output), flush=True)
        if restore_failures:
            raise RuntimeError("Restore failed; inspect resources and run cleanup")


if __name__ == "__main__":
    main()
