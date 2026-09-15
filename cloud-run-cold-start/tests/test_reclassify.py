import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurements.json"


class ReclassifyCliTest(unittest.TestCase):
    def test_cli_reclassifies_prestarted_process_with_prior_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            output = Path(directory) / "output.json"
            measurements = json.loads(FIXTURE.read_text(encoding="utf-8"))
            measurements["settings"].update(
                {
                    "new_process_max_uptime_ms": 5000.0,
                    "prestarted_min_uptime_ms": 5000.0,
                }
            )
            target = measurements["targets"][3]
            original_latency = target["requests"][0]["client_latency_ms"]
            for index, row in enumerate(target["requests"]):
                row["response"]["request_index"] = index + 3
                row["observed_state"] = "invalid_or_ambiguous"
            expected_payload = copy.deepcopy(measurements)
            source.write_text(json.dumps(measurements), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "reclassify.py", str(source), "--output", str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            requests = result["targets"][3]["requests"]
            self.assertEqual(
                [row["observed_state"] for row in requests],
                ["prestarted_process"] + ["same_process"] * 5,
            )
            self.assertEqual(requests[0]["client_latency_ms"], original_latency)
            self.assertEqual(result["reclassified_from_schema_version"], 2)

            result.pop("reclassified_at")
            result.pop("reclassified_from_schema_version")
            for payload in (result, expected_payload):
                for result_target in payload["targets"]:
                    for row in result_target["requests"]:
                        row.pop("observed_state")
            self.assertEqual(result, expected_payload)


if __name__ == "__main__":
    unittest.main()
