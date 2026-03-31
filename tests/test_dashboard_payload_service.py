from __future__ import annotations

import unittest

from services import dashboard_payload_service


class _FailingDb:
    def connect(self):
        raise RuntimeError("db unavailable")


class DashboardPayloadServiceTests(unittest.TestCase):
    def test_compute_dashboard_payload_returns_minimum_shape_on_db_failure(self):
        payload = dashboard_payload_service.compute_dashboard_payload(_FailingDb(), "month")
        self.assertIsInstance(payload, dict)
        self.assertIn("status_counts", payload)
        self.assertIn("live_metrics", payload)
        self.assertIn("resumo", payload)
        self.assertIn("finance_forecast", payload)
        self.assertEqual(payload.get("period_key"), "month")

    def test_compute_dashboard_payload_normalizes_invalid_period(self):
        payload = dashboard_payload_service.compute_dashboard_payload(_FailingDb(), "abc")
        self.assertEqual(payload.get("period_key"), "month")

    def test_compute_dashboard_payload_today_period(self):
        payload = dashboard_payload_service.compute_dashboard_payload(_FailingDb(), "today")
        self.assertEqual(payload.get("period_key"), "today")
        self.assertEqual(payload.get("period_desc"), "Hoje")


if __name__ == "__main__":
    unittest.main()
