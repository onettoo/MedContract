from __future__ import annotations

import importlib
import os
from pathlib import Path
import tempfile
import unittest

from services import dashboard_payload_service


class FinancePreferencesIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "medcontract_test.sqlite3"
        self._env_backup = {
            "MEDCONTRACT_FORCE_SQLITE": os.getenv("MEDCONTRACT_FORCE_SQLITE"),
            "MEDCONTRACT_SQLITE_PATH": os.getenv("MEDCONTRACT_SQLITE_PATH"),
            "MEDCONTRACT_DB_BACKEND": os.getenv("MEDCONTRACT_DB_BACKEND"),
            "MEDCONTRACT_DB_ALLOW_SQLITE_FALLBACK": os.getenv("MEDCONTRACT_DB_ALLOW_SQLITE_FALLBACK"),
            "MEDCONTRACT_DATABASE_URL": os.getenv("MEDCONTRACT_DATABASE_URL"),
            "DATABASE_URL": os.getenv("DATABASE_URL"),
        }
        os.environ["MEDCONTRACT_FORCE_SQLITE"] = "1"
        os.environ["MEDCONTRACT_SQLITE_PATH"] = str(self._db_path)
        os.environ["MEDCONTRACT_DB_BACKEND"] = "sqlite"
        os.environ["MEDCONTRACT_DB_ALLOW_SQLITE_FALLBACK"] = "0"
        os.environ.pop("MEDCONTRACT_DATABASE_URL", None)
        os.environ.pop("DATABASE_URL", None)

        import database.db as db_module

        self.db = importlib.reload(db_module)
        self.db.create_tables()

    def tearDown(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            import database.db as db_module
            importlib.reload(db_module)
        finally:
            self._tmp.cleanup()

    def test_finance_preferences_save_and_load(self):
        payload = {
            "financeiro_query": {
                "search_doc": "123",
                "status_key": "atrasado",
                "only_today": True,
            },
            "contas_query": {
                "search": "energia",
                "only_vencidas": True,
                "vencem_hoje": False,
                "vencem_7d": False,
            },
        }
        out_save = self.db.salvar_preferencias_financeiro_usuario("admin", payload)
        self.assertTrue(out_save.get("ok"))

        out_load = self.db.obter_preferencias_financeiro_usuario("admin")
        self.assertTrue(out_load.get("ok"))
        self.assertEqual(out_load.get("financeiro_query", {}).get("search_doc"), "123")
        self.assertTrue(bool(out_load.get("financeiro_query", {}).get("only_today")))
        self.assertTrue(bool(out_load.get("contas_query", {}).get("only_vencidas")))

    def test_alert_config_scoped_by_user_with_global_fallback(self):
        self.db.salvar_contas_alerta_config([0, 3, 7])
        self.db.salvar_contas_alerta_config([0, 5], usuario="admin")

        user_cfg = self.db.obter_contas_alerta_config(usuario="admin")
        other_cfg = self.db.obter_contas_alerta_config(usuario="analista")
        self.assertEqual(user_cfg.get("dias"), [0, 5])
        self.assertEqual(other_cfg.get("dias"), [0, 3, 7])

    def test_dashboard_payload_uses_user_alert_days(self):
        self.db.salvar_contas_alerta_config([0, 2, 9], usuario="admin")
        payload = dashboard_payload_service.compute_dashboard_payload(
            self.db,
            "month",
            alert_user="admin",
        )
        resumo = dict(payload.get("resumo", {}) or {})
        self.assertEqual(resumo.get("contas_alerta_dias"), [0, 2, 9])

    def test_user_preferences_save_and_load(self):
        payload = {
            "dashboard_period_default": "7d",
            "dashboard_apply_period_on_login": False,
            "auto_refresh_interval_s": 120,
            "finance_page_size": 100,
            "contas_page_size": 75,
            "layout_density": "compact",
        }
        out_save = self.db.salvar_preferencias_usuario("admin", payload)
        self.assertTrue(out_save.get("ok"))

        out_load = self.db.obter_preferencias_usuario("admin")
        self.assertTrue(out_load.get("ok"))
        self.assertEqual(out_load.get("dashboard_period_default"), "7d")
        self.assertFalse(bool(out_load.get("dashboard_apply_period_on_login")))
        self.assertEqual(int(out_load.get("auto_refresh_interval_s")), 120)
        self.assertEqual(int(out_load.get("finance_page_size")), 100)
        self.assertEqual(int(out_load.get("contas_page_size")), 75)
        self.assertEqual(str(out_load.get("layout_density")), "compact")


if __name__ == "__main__":
    unittest.main()
