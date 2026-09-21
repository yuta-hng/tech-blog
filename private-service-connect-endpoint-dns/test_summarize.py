"""Reject incomplete evidence rather than publishing a successful-looking table."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from summarize import EXPECTED, summarize


class EvidenceTests(unittest.TestCase):
    def fixture(self, directory):
        good = {"exit_code": 0, "http_status": "200", "payload": {
            "message": "psc-lab-ok", "peer_ip": "10.10.10.2"}}
        cases = []
        for label in EXPECTED:
            state = {"psc_status": "PENDING" if label == "pending" else "ACCEPTED",
                     "backend_health": ["HEALTHY"], "nat_http_rule_disabled": label == "firewall_disabled"}
            row = {"utc": "2026-01-01T00:00:00+00:00", "ip": copy.deepcopy(good),
                   "hostname": copy.deepcopy(good), "dns": {"answer": "10.20.0.10"}}
            if label == "pending":
                row["ip"].update(exit_code=28, http_status="000", payload=None)
            if label == "dns_removed":
                row["hostname"].update(exit_code=6, http_status="000", payload=None)
                row["dns"]["answer"] = "status: NXDOMAIN"
            if label == "firewall_disabled":
                for target in ["ip", "hostname"]:
                    row[target].update(exit_code=28, http_status="000", payload=None)
            cases.append({"case": label, "passed": True, "before": state, "after": state,
                          "probes": [dict(copy.deepcopy(row), attempt=i) for i in [1, 2, 3]]})
        (directory / "environment.json").write_text(json.dumps({"completed": True, "restore_failures": []}))
        (directory / "events.jsonl").write_text("")
        (directory / "cases.json").write_text(json.dumps(cases))
        return cases

    def test_recomputes_verdict_even_when_saved_passed_is_true(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cases = self.fixture(directory)
            self.assertEqual(summarize(directory)["http_requests_in_cases"], 42)
            cases[2]["probes"][0]["ip"]["http_status"] = "503"
            (directory / "cases.json").write_text(json.dumps(cases))
            with self.assertRaises(ValueError):
                summarize(directory)

    def test_rejects_missing_case_or_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cases = self.fixture(directory)
            (directory / "cases.json").write_text(json.dumps(cases[:-1]))
            with self.assertRaises(ValueError):
                summarize(directory)
            cases[0]["probes"].pop()
            (directory / "cases.json").write_text(json.dumps(cases))
            with self.assertRaises(ValueError):
                summarize(directory)

    def test_rejects_restoration_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            (directory / "environment.json").write_text(json.dumps({"completed": True, "restore_failures": ["dns"]}))
            with self.assertRaises(ValueError):
                summarize(directory)


if __name__ == "__main__":
    unittest.main()
