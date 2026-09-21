"""Offline checks for failure classification and the boundary of destructive actions."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from lab import Lab, build_plan
from measure import validate_case


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"psc_status": "ACCEPTED", "backend_health": ["HEALTHY"], "nat_http_rule_disabled": False}
        self.good = {"exit_code": 0, "http_status": "200", "payload": {"message": "psc-lab-ok", "peer_ip": "10.10.10.2"}}
        self.row = {"ip": copy.deepcopy(self.good), "hostname": copy.deepcopy(self.good),
                    "dns": {"answer": "status: NOERROR; hello.psc.test. 30 IN A 10.20.0.10"}}

    def test_acceptance_alone_does_not_pass_http(self):
        self.row["ip"].update(exit_code=28, http_status="000", payload=None)
        self.assertFalse(validate_case("dns_ready", self.snapshot, [self.row]))

    def test_dns_failure_requires_working_ip_and_nxdomain(self):
        self.row["hostname"].update(exit_code=6, http_status="000", payload=None)
        self.row["dns"]["answer"] = "status: NXDOMAIN"
        self.assertTrue(validate_case("dns_removed", self.snapshot, [self.row]))
        self.row["ip"]["exit_code"] = 28
        self.assertFalse(validate_case("dns_removed", self.snapshot, [self.row]))

    def test_http_403_does_not_count_as_network_timeout(self):
        self.snapshot["nat_http_rule_disabled"] = True
        for target in ["ip", "hostname"]:
            self.row[target].update(exit_code=0, http_status="403", payload=None)
        self.assertFalse(validate_case("firewall_disabled", self.snapshot, [self.row]))

    def test_expected_firewall_failure_still_requires_dns_and_health(self):
        self.snapshot["nat_http_rule_disabled"] = True
        for target in ["ip", "hostname"]:
            self.row[target].update(exit_code=28, http_status="000", payload=None)
        self.assertTrue(validate_case("firewall_disabled", self.snapshot, [self.row]))
        self.snapshot["backend_health"] = ["UNHEALTHY"]
        self.assertFalse(validate_case("firewall_disabled", self.snapshot, [self.row]))

    def test_normal_case_requires_nat_source(self):
        self.assertTrue(validate_case("dns_ready", self.snapshot, [self.row]))
        self.row["ip"]["payload"]["peer_ip"] = "10.20.0.2"
        self.assertFalse(validate_case("dns_ready", self.snapshot, [self.row]))


class ResourceTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(producer_project="producer-example", consumer_project="consumer-example", prefix="psc-lab-test")

    def test_plan_never_deletes_project_or_shared_default_namespace(self):
        plan = build_plan("producer-example", "consumer-example", "psc-lab-test", Path("/tmp/test-psc-private"))
        for action in plan:
            if action["delete"]:
                self.assertIn(action["project"], ["producer-example", "consumer-example"])
                self.assertIn(action["name"], action["delete"])
                self.assertTrue(action["name"].startswith("psc-lab-test-"))
                self.assertNotIn("*", action["delete"])
        self.assertNotIn("goog-psc-default", json.dumps(plan))

    def test_failed_preflight_stops_before_mutation_or_key_generation(self):
        with tempfile.TemporaryDirectory() as d, patch("lab.ROOT", Path(d)):
            lab = Lab(self.args())
            with patch.object(lab, "preflight", side_effect=RuntimeError("reauthentication required")), patch.object(lab, "call") as call:
                with self.assertRaises(RuntimeError):
                    lab.create()
                call.assert_not_called()
                self.assertFalse(lab.manifest.exists())

    def test_cleanup_refuses_project_mismatch(self):
        with tempfile.TemporaryDirectory() as d, patch("lab.ROOT", Path(d)):
            lab = Lab(self.args())
            lab.private.mkdir(parents=True)
            lab.manifest.write_text(json.dumps({"producer_project": "different-project",
                "consumer_project": "consumer-example", "prefix": "psc-lab-test"}))
            with patch.object(lab, "call") as call:
                with self.assertRaises(RuntimeError):
                    lab.cleanup()
                call.assert_not_called()

    def test_cleanup_keeps_nonempty_namespace(self):
        with tempfile.TemporaryDirectory() as d, patch("lab.ROOT", Path(d)):
            lab = Lab(self.args())
            lab.private.mkdir(parents=True)
            item = {"project": "consumer-example", "name": "psc-lab-test-namespace",
                    "kind": ["service-directory", "namespaces"],
                    "delete": ["service-directory", "namespaces", "delete", "psc-lab-test-namespace"]}
            lab.manifest.write_text(json.dumps({"producer_project": "producer-example",
                "consumer_project": "consumer-example", "prefix": "psc-lab-test", "resources": [item]}))
            with patch.object(lab, "read", side_effect=[[], [{"name": "psc-lab-test-namespace"}],
                                                       [{"name": "remaining-service"}]]), patch.object(lab, "call") as call:
                with self.assertRaises(RuntimeError):
                    lab.cleanup()
                call.assert_not_called()
                self.assertEqual(json.loads(lab.manifest.read_text())["resources"], [item])


if __name__ == "__main__":
    unittest.main()
