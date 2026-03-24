# -*- coding: utf-8 -*-
"""
Controller de Pagamentos - logica de negocio isolada da camada de UI.
"""
from __future__ import annotations

import database.db as db
from services.validation_service import normalize_pagamento_payload


def registrar_pagamento(dados: dict) -> tuple[bool, str]:
    """
    Registra pagamento de cliente ou empresa.
    Retorna (ok, mensagem).
    """
    try:
        payload = normalize_pagamento_payload(dict(dados or {}))
    except ValueError as exc:
        return False, str(exc)

    tipo_pagador = str(payload.get("tipo_pagador") or "cliente").strip().lower()
    mes_iso = payload.get("mes_iso")
    data_pag = payload.get("data_pagamento")
    valor = payload.get("valor_pago")

    if tipo_pagador == "empresa":
        empresa_id = payload.get("empresa_id")
        if not empresa_id:
            empresa = db.buscar_empresa_por_cnpj(payload.get("cnpj", ""))
            if not empresa:
                return False, "CNPJ nao encontrado."
            empresa_id = int(empresa[0])
        else:
            empresa_id = int(empresa_id)

        return db.registrar_pagamento_empresa_com_data_safe(
            empresa_id=empresa_id,
            mes_referencia=str(mes_iso),
            data_pagamento_iso=str(data_pag),
            valor_pago=float(valor),
        )

    cliente_id = payload.get("cliente_id")
    if not cliente_id:
        cliente = db.buscar_cliente_por_cpf(payload.get("cpf", ""))
        if not cliente:
            return False, "CPF nao encontrado."
        cliente_id = int(cliente[0])
    else:
        cliente_id = int(cliente_id)

    return db.registrar_pagamento_com_data_safe(
        cliente_id=cliente_id,
        mes_referencia=str(mes_iso),
        data_pagamento_iso=str(data_pag),
        valor_pago=float(valor),
    )
