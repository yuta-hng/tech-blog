import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "measurements.json"


class SummarizeCliTest(unittest.TestCase):
    def run_summarize(self, source: Path, output: Path):
        return subprocess.run(
            [sys.executable, "summarize.py", str(source), "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_summarizes_each_group_and_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "summary.json"
            completed = self.run_summarize(FIXTURE, output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                result["groups"]["min-0"]["first"]["client_latency_ms"],
                {"count": 3, "median": 1000, "min": 800, "max": 1200},
            )
            self.assertEqual(
                result["groups"]["min-0"]["warm"][
                    "per_service_median_client_latency_ms"
                ],
                {"count": 3, "median": 100, "min": 90, "max": 110},
            )
            self.assertEqual(
                result["groups"]["min-0"]["warm"]["request_count_in_complete_services"],
                15,
            )
            self.assertEqual(
                result["groups"]["min-0"]["warm"]["complete_service_count"],
                3,
            )
            self.assertEqual(result["groups"]["min-0"]["service_count"], 3)
            self.assertEqual(
                result["groups"]["min-1"]["first"]["client_latency_ms"],
                {"count": 3, "median": 110, "min": 100, "max": 120},
            )
            self.assertEqual(result["run_id"], "fixture-run")
            self.assertEqual(len(result["services"]), 6)

    def test_ambiguous_first_observation_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "measurements.json"
            output = Path(directory) / "summary.json"
            measurements = json.loads(FIXTURE.read_text(encoding="utf-8"))
            measurements["targets"][0]["requests"][0][
                "observed_state"
            ] = "invalid_or_ambiguous"
            source.write_text(json.dumps(measurements), encoding="utf-8")

            completed = self.run_summarize(source, output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            first = json.loads(output.read_text(encoding="utf-8"))["groups"]["min-0"][
                "first"
            ]
            self.assertEqual(first["valid_service_count"], 2)
            self.assertEqual(first["excluded_service_count"], 1)
            self.assertEqual(first["client_latency_ms"]["count"], 2)

    def test_incomplete_warm_service_is_excluded_and_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "measurements.json"
            output = Path(directory) / "summary.json"
            measurements = json.loads(FIXTURE.read_text(encoding="utf-8"))
            failed = measurements["targets"][0]["requests"][1]
            failed["observed_state"] = "invalid_or_ambiguous"
            failed["error_type"] = "connection_error"
            failed.pop("response")
            source.write_text(json.dumps(measurements), encoding="utf-8")

            completed = self.run_summarize(source, output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            warm = json.loads(output.read_text(encoding="utf-8"))["groups"]["min-0"][
                "warm"
            ]
            self.assertIn("complete_service_count", warm)
            self.assertEqual(warm["complete_service_count"], 2)
            self.assertEqual(warm["incomplete_service_count"], 1)
            self.assertEqual(warm["request_count_in_complete_services"], 10)
            self.assertEqual(warm["outcome_counts"]["connection_error"], 1)
            self.assertEqual(
                warm["per_service_median_client_latency_ms"]["count"],
                2,
            )

    def test_first_request_error_reason_is_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "measurements.json"
            output = Path(directory) / "summary.json"
            measurements = json.loads(FIXTURE.read_text(encoding="utf-8"))
            failed = measurements["targets"][0]["requests"][0]
            failed["observed_state"] = "invalid_or_ambiguous"
            failed["error_type"] = "connection_error"
            failed["http_status"] = 0
            failed.pop("response")
            source.write_text(json.dumps(measurements), encoding="utf-8")

            completed = self.run_summarize(source, output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            first = json.loads(output.read_text(encoding="utf-8"))["groups"]["min-0"][
                "first"
            ]
            self.assertIn("outcome_counts", first)
            self.assertEqual(first["outcome_counts"]["connection_error"], 1)
            self.assertEqual(first["excluded_service_count"], 1)


if __name__ == "__main__":
    unittest.main()
