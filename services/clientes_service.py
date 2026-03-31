from __future__ import annotations

import controllers.cliente_controller as cliente_controller
import database.db as db


def salvar_cliente(dados: dict) -> dict:
    ok, msg, cliente_id = cliente_controller.salvar_cliente(dict(dados or {}))
    return {
        "ok": bool(ok),
        "cliente_id": cliente_id,
        "msg": str(msg or ("Cliente salvo com sucesso." if ok else "Nao foi possivel salvar o cliente.")),
    }


def excluir_cliente(mat: int) -> dict:
    ok = db.excluir_cliente(int(mat))
    return {"ok": bool(ok)}


def cancelar_plano_cliente(mat: int) -> dict:
    ok, msg = db.cancelar_plano_cliente(int(mat))
    return {"ok": bool(ok), "msg": str(msg or "")}


def renovar_contrato_cliente(mat: int) -> dict:
    ok, msg, info = db.renovar_contrato_cliente(int(mat))
    return {"ok": bool(ok), "msg": str(msg or ""), "info": dict(info or {})}


def renovar_contratos_clientes(mats: list[int]) -> dict:
    ok, msg, info = db.renovar_contratos_clientes(list(mats or []))
    return {"ok": bool(ok), "msg": str(msg or ""), "info": dict(info or {})}


def aplicar_reajuste(payload: dict) -> dict:
    src = dict(payload or {})
    try:
        percentual = float(src.get("percentual", 0.0) or 0.0)
    except Exception:
        percentual = 0.0
    modo = str(src.get("modo", "filtros") or "filtros").strip().lower()
    plano = str(src.get("plano", "todos") or "todos")
    somente_ativos = bool(src.get("somente_ativos", True))

    if modo == "selecionados":
        cliente_ids = src.get("cliente_ids", []) or []
        ok, msg, info = db.aplicar_reajuste_clientes_selecionados(
            percentual=percentual,
            cliente_ids=cliente_ids,
            somente_ativos=somente_ativos,
        )
    elif modo == "individual":
        try:
            cliente_id = int(src.get("cliente_id", 0) or 0)
        except Exception:
            cliente_id = 0
        try:
            novo_valor = float(src.get("novo_valor", 0.0) or 0.0)
        except Exception:
            novo_valor = 0.0
        ok, msg, info = db.aplicar_reajuste_cliente_especifico(
            cliente_id=cliente_id,
            novo_valor=novo_valor,
        )
    else:
        ok, msg, info = db.aplicar_reajuste_planos(
            percentual=percentual,
            plano=plano,
            somente_ativos=somente_ativos,
        )

    return {
        "ok": bool(ok),
        "msg": str(msg or ""),
        "info": dict(info or {}),
        "modo": modo,
    }
