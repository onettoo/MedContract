from __future__ import annotations

from datetime import datetime
import logging


logger = logging.getLogger(__name__)


def compute_financeiro_payload(db_module, mes_iso: str, query: dict | None = None) -> dict:
    ref = (mes_iso or "").strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = datetime.now().strftime("%Y-%m")
    q = dict(query or {})

    base = {}
    try:
        base = db_module.carregar_financeiro_mes(ref, detail_limit=1) or {}
    except Exception:
        logger.debug("Falha ao carregar resumo financeiro do mês %s.", ref, exc_info=True)
        base = {}

    details = {}
    try:
        details = db_module.listar_financeiro_detalhado_payload(
            ref,
            page=int(q.get("page", 0) or 0),
            limit=int(q.get("page_size", 50) or 50),
            search_doc=str(q.get("search_doc", "") or ""),
            search_name=str(q.get("search_name", "") or ""),
            status_key=str(q.get("status_key", "") or ""),
            min_value=q.get("min_value"),
            max_value=q.get("max_value"),
            only_atrasados=bool(q.get("only_atrasados", False)),
            above_ticket=bool(q.get("above_ticket", False)),
            ticket_ref=float(q.get("ticket_ref", 0.0) or 0.0),
            only_today=bool(q.get("only_today", False)),
            sort_key=str(q.get("sort_key", "data_pagamento") or "data_pagamento"),
            sort_dir=str(q.get("sort_dir", "desc") or "desc"),
        ) or {}
    except Exception:
        logger.debug("Falha ao carregar listagem detalhada do financeiro para %s.", ref, exc_info=True)
        details = {
            "rows": [],
            "total": 0,
            "total_valor": 0.0,
            "page_safe": 0,
            "pages": 1,
            "page_size": int(q.get("page_size", 50) or 50),
        }

    receita_total = float(base.get("receita_total", 0.0) or 0.0)
    pagamentos = int(base.get("pagamentos", 0) or 0)
    ticket_medio = float(base.get("ticket_medio", 0.0) or 0.0)
    atraso_estimado = float(base.get("atraso_estimado", 0.0) or 0.0)
    atrasados_count = int(base.get("atrasados_count", 0) or 0)

    daily_totals: dict[int, float] = {}
    for item in list(base.get("daily_totals", []) or []):
        try:
            day = int(item[0])
            value = float(item[1] or 0.0)
        except Exception:
            continue
        if day > 0:
            daily_totals[day] = value

    try:
        year = int(ref[:4])
        month = int(ref[5:7])
        next_year = year + (1 if month == 12 else 0)
        next_month = 1 if month == 12 else month + 1
        days_in_month = (datetime(next_year, next_month, 1) - datetime(year, month, 1)).days
    except Exception:
        days_in_month = 31

    daily_series: list[tuple[str, float]] = []
    for day in range(1, days_in_month + 1):
        daily_series.append((f"{day:02d}", float(daily_totals.get(day, 0.0))))

    rows = list(details.get("rows", []) or [])

    return {
        "mes_ref": ref,
        "receita_total": receita_total,
        "pagamentos": pagamentos,
        "ticket_medio": ticket_medio,
        "atraso_estimado": atraso_estimado,
        "atrasados_count": atrasados_count,
        "daily_series": daily_series,
        "rows": rows,
        "rows_total": int(details.get("total", len(rows)) or 0),
        "rows_total_valor": float(details.get("total_valor", 0.0) or 0.0),
        "rows_page": int(details.get("page_safe", int(q.get("page", 0) or 0)) or 0),
        "rows_pages": int(details.get("pages", 1) or 1),
        "rows_page_size": int(details.get("page_size", int(q.get("page_size", 50) or 50)) or 50),
        "sort_key": str(details.get("sort_key", q.get("sort_key", "data_pagamento")) or "data_pagamento"),
        "sort_dir": str(details.get("sort_dir", q.get("sort_dir", "desc")) or "desc"),
        "query": q,
    }


def compute_contas_pagar_payload(db_module, mes_iso: str, query: dict | None = None) -> dict:
    ref = (mes_iso or "").strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = datetime.now().strftime("%Y-%m")
    q = dict(query or {})
    try:
        base = db_module.carregar_contas_pagar_mes(ref, detail_limit=1) or {}
    except Exception:
        logger.debug("Falha ao carregar resumo de contas a pagar do mês %s.", ref, exc_info=True)
        base = {}
    try:
        details = db_module.listar_contas_pagar_detalhado_payload(
            ref,
            page=int(q.get("page", 0) or 0),
            limit=int(q.get("page_size", 50) or 50),
            search=str(q.get("search", "") or ""),
            status=str(q.get("status", "") or ""),
            categoria=str(q.get("categoria", "") or ""),
            min_value=q.get("min_value"),
            max_value=q.get("max_value"),
            only_vencidas=bool(q.get("only_vencidas", False)),
            vencem_hoje=bool(q.get("vencem_hoje", False)),
            vencem_7d=bool(q.get("vencem_7d", False)),
            sort_key=str(q.get("sort_key", "data_vencimento") or "data_vencimento"),
            sort_dir=str(q.get("sort_dir", "asc") or "asc"),
        ) or {}
    except Exception:
        logger.debug("Falha ao carregar listagem de contas a pagar para %s.", ref, exc_info=True)
        details = {
            "rows": [],
            "total": 0,
            "total_valor": 0.0,
            "page_safe": 0,
            "pages": 1,
            "page_size": int(q.get("page_size", 50) or 50),
        }

    rows = list(details.get("rows", []) or [])
    return {
        "mes_ref": ref,
        "despesas_total": float(base.get("despesas_total", 0.0) or 0.0),
        "contas_total": int(base.get("contas_total", 0) or 0),
        "contas_pagas": int(base.get("contas_pagas", 0) or 0),
        "valor_pago_total": float(base.get("valor_pago_total", 0.0) or 0.0),
        "contas_pendentes": int(base.get("contas_pendentes", 0) or 0),
        "valor_pendente": float(base.get("valor_pendente", 0.0) or 0.0),
        "contas_vencidas": int(base.get("contas_vencidas", 0) or 0),
        "valor_vencido": float(base.get("valor_vencido", 0.0) or 0.0),
        "contas_vencem_hoje": int(base.get("contas_vencem_hoje", 0) or 0),
        "contas_vencem_7d": int(base.get("contas_vencem_7d", 0) or 0),
        "daily_series": list(base.get("daily_series", []) or []),
        "rows": rows,
        "total": int(details.get("total", len(rows)) or 0),
        "total_valor": float(details.get("total_valor", 0.0) or 0.0),
        "page_safe": int(details.get("page_safe", int(q.get("page", 0) or 0)) or 0),
        "pages": int(details.get("pages", 1) or 1),
        "page_size": int(details.get("page_size", int(q.get("page_size", 50) or 50)) or 50),
        "sort_key": str(details.get("sort_key", q.get("sort_key", "data_vencimento")) or "data_vencimento"),
        "sort_dir": str(details.get("sort_dir", q.get("sort_dir", "asc")) or "asc"),
        "query": q,
    }
