import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AppContractTest(unittest.TestCase):
    def test_requests_report_stable_start_time_and_incrementing_index(self):
        script = """
import json
from app import app

client = app.test_client()
first = client.get('/').get_json()
second = client.get('/').get_json()
print(json.dumps([first, second]))
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        first, second = json.loads(completed.stdout)
        self.assertEqual(
            set(first),
            {
                "app_initialized_at",
                "app_uptime_ms",
                "ok",
                "process_id",
                "request_index",
            },
        )
        self.assertTrue(first["ok"])
        self.assertEqual(first["request_index"], 1)
        self.assertEqual(second["request_index"], 2)
        self.assertEqual(first["app_initialized_at"], second["app_initialized_at"])
        self.assertEqual(first["process_id"], second["process_id"])
        self.assertGreaterEqual(first["app_uptime_ms"], 0)
        self.assertGreaterEqual(second["app_uptime_ms"], first["app_uptime_ms"])


if __name__ == "__main__":
    unittest.main()
