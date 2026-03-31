from __future__ import annotations

import unittest

from services import clientes_service


class _FakeClienteController:
    @staticmethod
    def salvar_cliente(payload):
        return True, "ok", int(payload.get("id", 0) or 0)


class _FakeDb:
    def __init__(self):
        self.calls = []

    def excluir_cliente(self, mat: int):
        self.calls.append(("excluir", int(mat)))
        return True

    def cancelar_plano_cliente(self, mat: int):
        self.calls.append(("cancelar", int(mat)))
        return True, "cancelado"

    def renovar_contrato_cliente(self, mat: int):
        self.calls.append(("renovar", int(mat)))
        return True, "renovado", {"cliente_id": int(mat)}

    def renovar_contratos_clientes(self, mats: list[int]):
        self.calls.append(("renovar_lote", list(mats)))
        return True, "ok", {"clientes_atualizados": len(mats)}

    def aplicar_reajuste_planos(self, **kwargs):
        self.calls.append(("reajuste_planos", dict(kwargs)))
        return True, "ok", {"modo": "filtros"}

    def aplicar_reajuste_clientes_selecionados(self, **kwargs):
        self.calls.append(("reajuste_sel", dict(kwargs)))
        return True, "ok", {"modo": "selecionados"}

    def aplicar_reajuste_cliente_especifico(self, **kwargs):
        self.calls.append(("reajuste_ind", dict(kwargs)))
        return True, "ok", {"modo": "individual"}


class ClientesServiceTests(unittest.TestCase):
    def setUp(self):
        self._orig_ctrl = clientes_service.cliente_controller
        self._orig_db = clientes_service.db
        clientes_service.cliente_controller = _FakeClienteController()
        clientes_service.db = _FakeDb()

    def tearDown(self):
        clientes_service.cliente_controller = self._orig_ctrl
        clientes_service.db = self._orig_db

    def test_salvar_cliente(self):
        out = clientes_service.salvar_cliente({"id": 42, "nome": "A"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["cliente_id"], 42)

    def test_operacoes_basicas_cliente(self):
        self.assertTrue(clientes_service.excluir_cliente(9)["ok"])
        self.assertTrue(clientes_service.cancelar_plano_cliente(10)["ok"])
        self.assertTrue(clientes_service.renovar_contrato_cliente(11)["ok"])
        self.assertTrue(clientes_service.renovar_contratos_clientes([1, 2])["ok"])

    def test_aplicar_reajuste_por_modo(self):
        db_fake = clientes_service.db
        clientes_service.aplicar_reajuste({"modo": "filtros", "percentual": 3})
        clientes_service.aplicar_reajuste({"modo": "selecionados", "cliente_ids": [1, 2], "percentual": 4})
        clientes_service.aplicar_reajuste({"modo": "individual", "cliente_id": 7, "novo_valor": 199.9})
        tags = [c[0] for c in db_fake.calls]
        self.assertIn("reajuste_planos", tags)
        self.assertIn("reajuste_sel", tags)
        self.assertIn("reajuste_ind", tags)


if __name__ == "__main__":
    unittest.main()
