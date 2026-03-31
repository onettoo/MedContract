from __future__ import annotations

import unittest

from database.db import _month_reference_candidates, _normalize_contas_alerta_days


class DbMonthAlertHelpersTests(unittest.TestCase):
    def test_month_reference_candidates_includes_common_formats(self):
        cands = set(_month_reference_candidates("2026-03"))
        self.assertIn("2026-03", cands)
        self.assertIn("2026/03", cands)
        self.assertIn("03/2026", cands)
        self.assertIn("202603", cands)
        self.assertIn("MAR/2026", cands)
        self.assertIn("MAR-2026", cands)

    def test_alert_days_normalization_from_csv(self):
        self.assertEqual(_normalize_contas_alerta_days("0, 3, 7, 7, 31, -1"), [0, 3, 7])

    def test_alert_days_normalization_default_when_invalid(self):
        self.assertEqual(_normalize_contas_alerta_days(""), [0, 3, 7])
        self.assertEqual(_normalize_contas_alerta_days("a,b,c"), [0, 3, 7])


if __name__ == "__main__":
    unittest.main()
