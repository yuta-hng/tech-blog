import unittest

from load_test import percentile, redact_url


class LoadTestTest(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(percentile([10.0, 20.0, 30.0], 0.50), 20.0)
        self.assertEqual(percentile([10.0, 20.0], 0.95), 19.5)

    def test_percentile_accepts_empty_values(self):
        self.assertEqual(percentile([], 0.95), 0.0)

    def test_redact_url_removes_service_hostname(self):
        actual = redact_url(
            "https://service-123456789.asia-northeast1.run.app/?work_ms=100"
        )
        self.assertEqual(actual, "https://<SERVICE_URL>/?work_ms=100")


if __name__ == "__main__":
    unittest.main()
