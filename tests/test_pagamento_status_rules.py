from __future__ import annotations

from datetime import date
import unittest

from database.db import calcular_status_pagamento, _normalize_month_reference_iso_loose


class PagamentoStatusRulesTests(unittest.TestCase):
    def test_status_em_dia_quando_pagamento_mes_atual_true(self):
        status = calcular_status_pagamento(
            {
                "vencimento_dia": 10,
                "pagamento_mes_atual": True,
            },
            hoje=date(2026, 3, 26),
        )
        self.assertEqual(status, "em_dia")

    def test_status_pendente_quando_sem_pagamento_e_antes_do_vencimento(self):
        status = calcular_status_pagamento(
            {
                "vencimento_dia": 28,
                "pagamento_mes_atual": False,
            },
            hoje=date(2026, 3, 10),
        )
        self.assertEqual(status, "pendente")

    def test_status_em_atraso_quando_sem_pagamento_e_apos_vencimento(self):
        status = calcular_status_pagamento(
            {
                "vencimento_dia": 10,
                "pagamento_mes_atual": False,
            },
            hoje=date(2026, 3, 26),
        )
        self.assertEqual(status, "em_atraso")

    def test_status_em_dia_reconhece_mes_legado_no_historico(self):
        status = calcular_status_pagamento(
            {
                "vencimento_dia": 10,
                "pagamento_mes_atual": False,
                "pagamentos": [
                    {"mes_referencia": "MAR/2026", "status": "confirmado"},
                ],
            },
            hoje=date(2026, 3, 26),
        )
        self.assertEqual(status, "em_dia")

    def test_normalize_month_reference_iso_loose_variantes(self):
        self.assertEqual(_normalize_month_reference_iso_loose("2026-03"), "2026-03")
        self.assertEqual(_normalize_month_reference_iso_loose("2026/03"), "2026-03")
        self.assertEqual(_normalize_month_reference_iso_loose("03/2026"), "2026-03")
        self.assertEqual(_normalize_month_reference_iso_loose("MAR/2026"), "2026-03")
        self.assertEqual(_normalize_month_reference_iso_loose("MAR-2026"), "2026-03")
        self.assertEqual(_normalize_month_reference_iso_loose("202603"), "2026-03")


if __name__ == "__main__":
    unittest.main()
