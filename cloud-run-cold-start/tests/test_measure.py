import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CountingHandler(BaseHTTPRequestHandler):
    request_count = 0
    app_uptime_ms = 123.456

    def do_GET(self):
        if self.path == "/error":
            payload = b"private service error"
            self.send_response(500)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/not-json":
            payload = b"private non-json response"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/disconnect":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return

        type(self).request_count += 1
        payload = json.dumps(
            {
                "ok": True,
                "app_initialized_at": "2026-09-15T00:00:00+00:00",
                "app_uptime_ms": type(self).app_uptime_ms,
                "process_id": "0123456789abcdef0123456789abcdef",
                "request_index": type(self).request_count,
                "secret": "must-not-be-persisted",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


class MeasureCliTest(unittest.TestCase):
    def setUp(self):
        CountingHandler.request_count = 0
        CountingHandler.app_uptime_ms = 123.456
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CountingHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def run_measure(
        self,
        output: Path,
        path: str = "/private-service",
        group: str = "min-0",
    ):
        url = f"http://127.0.0.1:{self.server.server_port}{path}"
        completed = subprocess.run(
            [
                sys.executable,
                "measure.py",
                "--target",
                f"{group},trial-1,{url}",
                "--run-id",
                "test-run-01",
                "--client-label",
                "test-client",
                "--warm-requests",
                "2",
                "--delay-seconds",
                "0",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed, url

    def test_cli_records_first_and_warm_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            completed, _ = self.run_measure(output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            requests = result["targets"][0]["requests"]
            self.assertEqual(
                [row["phase"] for row in requests],
                ["first_after_idle", "warm", "warm"],
            )
            self.assertEqual([row["response"]["request_index"] for row in requests], [1, 2, 3])
            self.assertEqual(
                [row["observed_state"] for row in requests],
                ["new_process", "same_process", "same_process"],
            )
            self.assertTrue(all(row["http_status"] == 200 for row in requests))
            self.assertTrue(all(row["client_latency_ms"] >= 0 for row in requests))
            self.assertTrue(all("request_started_at" in row for row in requests))
            self.assertEqual(result["run_id"], "test-run-01")
            self.assertEqual(result["client_label"], "test-client")
            self.assertEqual(result["settings"]["timeout_seconds"], 30.0)
            self.assertIn("started_at", result)
            self.assertIn("finished_at", result)

    def test_output_does_not_persist_service_url(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            completed, url = self.run_measure(output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result_text = output.read_text(encoding="utf-8")
            self.assertNotIn(url, result_text)
            self.assertNotIn("must-not-be-persisted", result_text)
            result = json.loads(result_text)
            self.assertEqual(result["targets"][0]["group"], "min-0")
            self.assertEqual(result["targets"][0]["label"], "trial-1")
            self.assertEqual(
                set(result["targets"][0]["requests"][0]["response"]),
                {
                    "app_initialized_at",
                    "app_uptime_ms",
                    "ok",
                    "process_id",
                    "request_index",
                },
            )

    def test_http_error_is_recorded_without_response_body(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            completed, _ = self.run_measure(output, "/error")

            self.assertEqual(completed.returncode, 1)
            result_text = output.read_text(encoding="utf-8")
            self.assertNotIn("private service error", result_text)
            first = json.loads(result_text)["targets"][0]["requests"][0]
            self.assertEqual(first["http_status"], 500)
            self.assertEqual(first["error_type"], "http_error")
            self.assertEqual(first["observed_state"], "invalid_or_ambiguous")

    def test_non_json_response_is_recorded_without_response_body(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            completed, _ = self.run_measure(output, "/not-json")

            self.assertEqual(completed.returncode, 1)
            result_text = output.read_text(encoding="utf-8")
            self.assertNotIn("private non-json response", result_text)
            first = json.loads(result_text)["targets"][0]["requests"][0]
            self.assertEqual(first["http_status"], 200)
            self.assertEqual(first["error_type"], "invalid_json")
            self.assertEqual(first["observed_state"], "invalid_or_ambiguous")

    def test_prestarted_process_is_recognized_for_minimum_one(self):
        CountingHandler.request_count = 2
        CountingHandler.app_uptime_ms = 6000
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            completed, _ = self.run_measure(output, group="min-1")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            first = json.loads(output.read_text(encoding="utf-8"))["targets"][0][
                "requests"
            ][0]
            self.assertEqual(first["response"]["request_index"], 3)
            self.assertEqual(first["observed_state"], "prestarted_process")

    def test_remote_disconnect_is_recorded_as_connection_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            completed, _ = self.run_measure(output, "/disconnect")

            self.assertEqual(completed.returncode, 1)
            self.assertTrue(output.exists(), completed.stderr)
            first = json.loads(output.read_text(encoding="utf-8"))["targets"][0][
                "requests"
            ][0]
            self.assertEqual(first["http_status"], 0)
            self.assertEqual(first["error_type"], "connection_error")
            self.assertEqual(first["observed_state"], "invalid_or_ambiguous")

    def test_prior_request_marks_measurement_as_ambiguous(self):
        CountingHandler.request_count = 1
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            completed, _ = self.run_measure(output)

            self.assertEqual(completed.returncode, 1)
            first = json.loads(output.read_text(encoding="utf-8"))["targets"][0][
                "requests"
            ][0]
            self.assertEqual(first["response"]["request_index"], 2)
            self.assertEqual(first["observed_state"], "invalid_or_ambiguous")


if __name__ == "__main__":
    unittest.main()
