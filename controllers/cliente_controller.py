# -*- coding: utf-8 -*-
"""
Controller de Clientes - logica de negocio isolada da camada de UI.
"""
from __future__ import annotations

import logging

import database.db as db
from services.validation_service import normalize_cliente_payload

logger = logging.getLogger(__name__)


def salvar_cliente(dados: dict) -> tuple[bool, str, int | None]:
    """
    Cria ou edita um cliente conforme `dados['modo']`.
    Retorna (ok, mensagem, cliente_id).
    """
    try:
        payload = normalize_cliente_payload(dict(dados or {}))
    except ValueError as exc:
        return False, str(exc), None

    modo = str(payload.get("modo") or "create").strip().lower()
    deps_lista = payload.get("dependentes_lista", []) or []

    if modo == "edit":
        cliente_id = payload.get("id")
        if not cliente_id:
            return False, "ID do cliente invalido para edicao.", None

        try:
            row = db.buscar_cliente_por_cpf(payload.get("cpf", ""))
            if row and int(row[0]) != int(cliente_id):
                return False, "CPF ja cadastrado.", None
        except Exception:
            logger.warning("Falha ao verificar CPF duplicado no update do cliente.", exc_info=True)

        ok = db.atualizar_cliente(
            cliente_id=int(cliente_id),
            nome=payload.get("nome"),
            cpf=payload.get("cpf"),
            telefone=payload.get("telefone"),
            email=payload.get("email"),
            data_inicio=payload.get("data_inicio"),
            valor_mensal=payload.get("valor_mensal"),
            status=payload.get("status"),
            pagamento_status=payload.get("pagamento_status"),
            observacoes=payload.get("observacoes"),
            data_nascimento=payload.get("data_nascimento"),
            cep=payload.get("cep"),
            endereco=payload.get("endereco"),
            plano=payload.get("plano"),
            dependentes=payload.get("dependentes", 0),
            vencimento_dia=payload.get("vencimento_dia", 10),
            forma_pagamento=payload.get("forma_pagamento"),
        )
        if ok:
            _salvar_dependentes(int(cliente_id), deps_lista)
            return True, "Cliente atualizado com sucesso.", int(cliente_id)
        return False, "Nao foi possivel salvar alteracoes (verifique CPF/DB).", None

    ok, msg = db.cadastrar_cliente(
        nome=payload.get("nome"),
        cpf=payload.get("cpf"),
        telefone=payload.get("telefone"),
        email=payload.get("email"),
        data_inicio=payload.get("data_inicio"),
        valor_mensal=payload.get("valor_mensal"),
        observacoes=payload.get("observacoes"),
        status=payload.get("status"),
        pagamento_status=payload.get("pagamento_status"),
        data_nascimento=payload.get("data_nascimento"),
        cep=payload.get("cep"),
        endereco=payload.get("endereco"),
        plano=payload.get("plano"),
        dependentes=payload.get("dependentes", 0),
        vencimento_dia=payload.get("vencimento_dia", 10),
        forma_pagamento=payload.get("forma_pagamento"),
        matricula=payload.get("matricula"),
    )
    if not ok:
        return False, str(msg or "Nao foi possivel salvar."), None

    saved_id = None
    try:
        row = db.buscar_cliente_por_cpf(payload.get("cpf", ""))
        if row:
            saved_id = int(row[0])
            _salvar_dependentes(saved_id, deps_lista)
    except Exception:
        logger.warning("Nao foi possivel salvar dependentes apos cadastro.", exc_info=True)

    if saved_id is None:
        matricula = payload.get("matricula")
        try:
            saved_id = int(matricula)
        except Exception:
            saved_id = None

    return True, str(msg or "Cliente cadastrado com sucesso."), saved_id


def _salvar_dependentes(cliente_id: int, deps_lista: list) -> None:
    try:
        db.substituir_dependentes(int(cliente_id), deps_lista or [])
    except Exception:
        logger.warning("Falha ao substituir dependentes do cliente %s.", cliente_id, exc_info=True)


def excluir_cliente(mat: int) -> tuple[bool, str]:
    ok = db.excluir_cliente(int(mat))
    if ok:
        return True, "Cliente excluido com sucesso."
    return False, "Nao foi possivel excluir o cliente."


def cancelar_plano(mat: int) -> tuple[bool, str]:
    row = db.buscar_cliente_por_id(int(mat))
    if not row:
        return False, "Cliente nao encontrado."
    status_atual = str(row[7] if len(row) > 7 else "").strip().lower()
    if status_atual == "inativo":
        return False, "Cliente ja esta com plano cancelado."
    return db.cancelar_plano_cliente(int(mat))


def aplicar_reajuste(payload: dict) -> tuple[bool, str, dict]:
    try:
        percentual = float(payload.get("percentual", 0.0) or 0.0)
    except Exception:
        percentual = 0.0

    modo = str(payload.get("modo", "filtros") or "filtros").strip().lower()
    plano = str(payload.get("plano", "todos") or "todos")
    somente_ativos = bool(payload.get("somente_ativos", True))

    if modo == "selecionados":
        return db.aplicar_reajuste_clientes_selecionados(
            percentual=percentual,
            cliente_ids=payload.get("cliente_ids", []) or [],
            somente_ativos=somente_ativos,
        )
    if modo == "individual":
        try:
            cliente_id = int(payload.get("cliente_id", 0) or 0)
            novo_valor = float(payload.get("novo_valor", 0.0) or 0.0)
        except Exception:
            return False, "Dados invalidos para reajuste individual.", {}
        return db.aplicar_reajuste_cliente_especifico(
            cliente_id=cliente_id,
            novo_valor=novo_valor,
        )

    return db.aplicar_reajuste_planos(
        percentual=percentual,
        plano=plano,
        somente_ativos=somente_ativos,
    )
