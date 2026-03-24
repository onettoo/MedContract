# -*- coding: utf-8 -*-
"""
Controller de Empresas - logica de negocio isolada da camada de UI.
"""
from __future__ import annotations

import database.db as db
from services.validation_service import normalize_empresa_payload


def salvar_empresa(dados: dict) -> tuple[bool, str]:
    """
    Cria ou edita uma empresa conforme `dados['modo']`.
    Retorna (ok, mensagem).
    """
    try:
        payload = normalize_empresa_payload(dict(dados or {}))
    except ValueError as exc:
        return False, str(exc)

    modo = str(payload.get("modo") or "create").strip().lower()

    if modo == "edit":
        empresa_id = payload.get("id")
        if not empresa_id:
            return False, "Empresa invalida para edicao."
        return db.atualizar_empresa(
            empresa_id=int(empresa_id),
            cnpj=payload.get("cnpj"),
            nome=payload.get("nome"),
            telefone=payload.get("telefone"),
            email=payload.get("email"),
            logradouro=payload.get("logradouro"),
            numero=payload.get("numero"),
            bairro=payload.get("bairro"),
            cep=payload.get("cep"),
            cidade=payload.get("cidade"),
            estado=payload.get("estado"),
            forma_pagamento=payload.get("forma_pagamento"),
            status_pagamento=payload.get("status_pagamento"),
            dia_vencimento=payload.get("dia_vencimento"),
            valor_mensal=payload.get("valor_mensal"),
        )

    return db.cadastrar_empresa(
        cnpj=payload.get("cnpj"),
        nome=payload.get("nome"),
        telefone=payload.get("telefone"),
        email=payload.get("email"),
        logradouro=payload.get("logradouro"),
        numero=payload.get("numero"),
        bairro=payload.get("bairro"),
        cep=payload.get("cep"),
        cidade=payload.get("cidade"),
        estado=payload.get("estado"),
        forma_pagamento=payload.get("forma_pagamento"),
        status_pagamento=payload.get("status_pagamento"),
        dia_vencimento=payload.get("dia_vencimento"),
        valor_mensal=payload.get("valor_mensal"),
    )


def excluir_empresa(empresa_id: int) -> tuple[bool, str]:
    ok = db.excluir_empresa(int(empresa_id))
    if ok:
        return True, "Empresa excluida com sucesso."
    return False, "Nao foi possivel excluir a empresa."
