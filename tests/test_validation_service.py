from __future__ import annotations

from datetime import date, timedelta
import unittest

from services.validation_service import (
    normalize_cliente_payload,
    normalize_empresa_payload,
    normalize_pagamento_payload,
    parse_date_iso,
    parse_money,
    parse_month_reference_iso,
    validate_cnpj,
    validate_cpf,
)


class ValidationServiceTests(unittest.TestCase):
    def test_parse_month_reference_iso_accepts_iso(self):
        self.assertEqual(parse_month_reference_iso("2026-03"), "2026-03")

    def test_parse_month_reference_iso_accepts_ptbr(self):
        self.assertEqual(parse_month_reference_iso("JAN/2026"), "2026-01")

    def test_parse_month_reference_iso_rejects_invalid(self):
        with self.assertRaises(ValueError):
            parse_month_reference_iso("2026-13")

    def test_parse_money_accepts_br_format(self):
        self.assertEqual(parse_money("1.234,56", field_label="Valor", allow_zero=False), 1234.56)

    def test_parse_money_accepts_us_style(self):
        self.assertEqual(parse_money("1234.56", field_label="Valor", allow_zero=False), 1234.56)

    def test_parse_money_rejects_zero_when_not_allowed(self):
        with self.assertRaises(ValueError):
            parse_money("0,00", field_label="Valor", allow_zero=False)

    def test_parse_money_allows_zero_when_enabled(self):
        self.assertEqual(parse_money("0,00", field_label="Valor", allow_zero=True), 0.0)

    def test_validate_cpf(self):
        raw, digits = validate_cpf("529.982.247-25")
        self.assertEqual(raw, "529.982.247-25")
        self.assertEqual(digits, "52998224725")
        with self.assertRaises(ValueError):
            validate_cpf("111.111.111-11")

    def test_validate_cnpj(self):
        raw, digits = validate_cnpj("45.723.174/0001-10")
        self.assertEqual(raw, "45.723.174/0001-10")
        self.assertEqual(digits, "45723174000110")
        with self.assertRaises(ValueError):
            validate_cnpj("11.111.111/1111-11")

    def test_parse_date_iso_accepts_iso_and_br(self):
        self.assertEqual(
            parse_date_iso("2026-03-18", field_label="Data", required=True, reject_future=False),
            "2026-03-18",
        )
        self.assertEqual(
            parse_date_iso("18/03/2026", field_label="Data", required=True, reject_future=False),
            "2026-03-18",
        )

    def test_parse_date_iso_rejects_future(self):
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        with self.assertRaises(ValueError):
            parse_date_iso(tomorrow, field_label="Data", required=True, reject_future=True)

    def test_normalize_pagamento_payload_cliente(self):
        payload = normalize_pagamento_payload(
            {
                "tipo_pagador": "cliente",
                "cpf": "529.982.247-25",
                "mes_referencia": "JAN/2026",
                "data_pagamento": "2026-03-17",
                "valor_pago": "149,90",
            }
        )
        self.assertEqual(payload["tipo_pagador"], "cliente")
        self.assertEqual(payload["mes_iso"], "2026-01")
        self.assertEqual(payload["cpf"], "529.982.247-25")
        self.assertEqual(payload["data_pagamento"], "2026-03-17")
        self.assertEqual(payload["valor_pago"], 149.9)

    def test_normalize_pagamento_payload_empresa_por_cnpj(self):
        payload = normalize_pagamento_payload(
            {
                "tipo_pagador": "empresa",
                "cnpj": "45.723.174/0001-10",
                "mes_iso": "2026-03",
                "data_pagamento": "2026-03-17",
                "valor_pago": "1500,00",
            }
        )
        self.assertEqual(payload["tipo_pagador"], "empresa")
        self.assertEqual(payload["cnpj"], "45.723.174/0001-10")
        self.assertEqual(payload["mes_iso"], "2026-03")
        self.assertEqual(payload["valor_pago"], 1500.0)

    def test_normalize_cliente_payload_success(self):
        payload = normalize_cliente_payload(
            {
                "modo": "create",
                "matricula": "123",
                "nome": "Ana Silva",
                "cpf": "529.982.247-25",
                "telefone": "(11) 91234-5678",
                "email": "ana@example.com",
                "status": "ativo",
                "pagamento_status": "em_dia",
                "data_inicio": "2026-03-18",
                "observacoes": "",
                "data_nascimento": "1990-01-15",
                "cep": "01001-000",
                "endereco": "Rua X • Centro • Sao Paulo • N 10 • SP",
                "plano": "Classic",
                "dependentes_lista": [
                    {
                        "nome": "Filho 1",
                        "cpf": "111.444.777-35",
                        "data_nascimento": "2015-05-01",
                    }
                ],
                "vencimento_dia": "10",
                "forma_pagamento": "pix",
                "valor_mensal": "149,90",
            }
        )
        self.assertEqual(payload["modo"], "create")
        self.assertEqual(payload["matricula"], 123)
        self.assertEqual(payload["dependentes"], 1)
        self.assertEqual(payload["forma_pagamento"], "Pix")
        self.assertEqual(payload["valor_mensal"], 149.9)

    def test_normalize_cliente_payload_rejects_duplicated_dependente_cpf(self):
        with self.assertRaises(ValueError):
            normalize_cliente_payload(
                {
                    "modo": "create",
                    "matricula": "123",
                    "nome": "Ana Silva",
                    "cpf": "529.982.247-25",
                    "telefone": "(11) 91234-5678",
                    "email": "ana@example.com",
                    "status": "ativo",
                    "pagamento_status": "em_dia",
                    "data_inicio": "2026-03-18",
                    "observacoes": "",
                    "data_nascimento": "1990-01-15",
                    "cep": "01001-000",
                    "endereco": "Rua X • Centro • Sao Paulo • N 10 • SP",
                    "plano": "Classic",
                    "dependentes_lista": [
                        {
                            "nome": "Filho 1",
                            "cpf": "111.444.777-35",
                            "data_nascimento": "2015-05-01",
                        },
                        {
                            "nome": "Filho 2",
                            "cpf": "111.444.777-35",
                            "data_nascimento": "2017-05-01",
                        },
                    ],
                    "vencimento_dia": "10",
                    "forma_pagamento": "pix",
                    "valor_mensal": "149,90",
                }
            )

    def test_normalize_empresa_payload_success(self):
        payload = normalize_empresa_payload(
            {
                "modo": "create",
                "cnpj": "45.723.174/0001-10",
                "nome": "Empresa X",
                "telefone": "(11) 3222-1111",
                "email": "contato@empresa.com",
                "logradouro": "Rua A",
                "numero": "100",
                "bairro": "Centro",
                "cep": "01001-000",
                "cidade": "Sao Paulo",
                "estado": "sp",
                "forma_pagamento": "boleto",
                "status_pagamento": "em_dia",
                "dia_vencimento": "10",
                "valor_mensal": "2500,00",
            }
        )
        self.assertEqual(payload["estado"], "SP")
        self.assertEqual(payload["forma_pagamento"], "boleto")
        self.assertEqual(payload["status_pagamento"], "em_dia")
        self.assertEqual(payload["valor_mensal"], "2500.00")


if __name__ == "__main__":
    unittest.main()
