from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta


def _log_debug(log_debug, message: str) -> None:
    try:
        if callable(log_debug):
            log_debug(str(message or ""))
    except Exception:
        return


def compute_dashboard_payload(
    db_module,
    period: str = "month",
    *,
    iso_to_mes_ref_br_fn=None,
    log_debug=None,
    alert_user: str | None = None,
) -> dict:
    now = datetime.now()
    today = now.date()
    mes_iso = now.strftime("%Y-%m")
    iso_to_mes_ref_br = iso_to_mes_ref_br_fn or (lambda value: str(value or ""))

    period_key = (period or "month").strip().lower()
    if period_key not in {"month", "7d", "today"}:
        period_key = "month"

    if period_key == "today":
        start_date = today
        end_date = today
        period_desc = "Hoje"
        period_chart_label = "hoje"
    elif period_key == "7d":
        start_date = today - timedelta(days=6)
        end_date = today
        period_desc = "Últimos 7 dias"
        period_chart_label = "7 dias"
    else:
        start_date = today.replace(day=1)
        end_date = today
        period_desc = f"Mês {iso_to_mes_ref_br(mes_iso)}"
        period_chart_label = f"mês {iso_to_mes_ref_br(mes_iso)}"

    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()

    span_days = (end_date - start_date).days + 1
    prev_end_date = start_date - timedelta(days=1)
    prev_start_date = prev_end_date - timedelta(days=max(span_days - 1, 0))
    prev_start_iso = prev_start_date.isoformat()
    prev_end_iso = prev_end_date.isoformat()

    def _last_day(year: int, month: int) -> int:
        return int(monthrange(year, month)[1])

    def _next_due_date(ref_date, due_day: int):
        year = int(ref_date.year)
        month = int(ref_date.month)
        day = min(int(due_day), _last_day(year, month))
        candidate = ref_date.replace(year=year, month=month, day=day)
        if candidate < ref_date:
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            day = min(int(due_day), _last_day(year, month))
            candidate = ref_date.replace(year=year, month=month, day=day)
        return candidate

    def _money_to_float(v) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        txt = str(v).strip()
        if not txt:
            return 0.0
        txt = txt.replace("R$", "").replace("r$", "").replace(" ", "")
        if not txt:
            return 0.0
        if "," in txt and "." in txt:
            if txt.rfind(",") > txt.rfind("."):
                txt = txt.replace(".", "").replace(",", ".")
            else:
                txt = txt.replace(",", "")
        elif "," in txt:
            txt = txt.replace(".", "").replace(",", ".")
        try:
            return float(txt)
        except Exception:
            return 0.0

    status_counts = {"ativos": 0, "atrasados": 0, "inativos": 0}
    total_clientes = 0
    atraso_estimado = 0.0
    pagamentos_mes = 0
    pagamentos_prev = 0
    pagamentos_hoje = 0
    fechados_mes = 0
    fechados_prev = 0
    hoje_qtd = 0
    contratos_empresa = {
        "total_empresas": 0,
        "novos_periodo": 0,
        "ativos": 0,
        "atrasados": 0,
        "inativos": 0,
    }
    entrada_7d_clientes = 0.0
    entrada_15d_clientes = 0.0
    entrada_30d_clientes = 0.0
    qtd_7d_clientes = 0
    qtd_15d_clientes = 0
    qtd_30d_clientes = 0
    entrada_7d_empresas = 0.0
    entrada_15d_empresas = 0.0
    entrada_30d_empresas = 0.0
    qtd_7d_empresas = 0
    qtd_15d_empresas = 0
    qtd_30d_empresas = 0
    vencendo_hoje_clientes = 0
    vencendo_hoje_empresas = 0
    entrada_7d = 0.0
    entrada_15d = 0.0
    entrada_30d = 0.0
    qtd_7d = 0
    qtd_15d = 0
    qtd_30d = 0
    contas_pagar_hoje = 0
    contas_pagar_semana = 0
    contas_pagar_vencidas = 0
    contas_alerta_dias = [0, 3, 7]
    contas_alerta_janela = 7
    clientes_base = 0
    clientes_atrasados = 0
    empresas_base = 0
    empresas_em_risco = 0
    valor_atraso_empresas = 0.0
    base_total = 0
    em_risco_total = 0
    taxa_inadimplencia = 0.0
    taxa_inadimplencia_clientes = 0.0
    taxa_inadimplencia_empresas = 0.0
    risco_7d = 0.0
    risco_15d = 0.0
    risco_30d = 0.0
    previsao_liquida_7d = 0.0
    previsao_liquida_15d = 0.0
    previsao_liquida_30d = 0.0
    risco_nivel = "baixo"
    conn = None
    try:
        conn = db_module.connect()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_clientes,
                COALESCE(SUM(CASE WHEN status = 'ativo' THEN 1 ELSE 0 END), 0) AS ativos,
                COALESCE(SUM(CASE WHEN status = 'inativo' THEN 1 ELSE 0 END), 0) AS inativos,
                COALESCE(SUM(CASE WHEN data_inicio BETWEEN ? AND ? THEN 1 ELSE 0 END), 0) AS fechados_periodo,
                COALESCE(SUM(CASE WHEN data_inicio BETWEEN ? AND ? THEN 1 ELSE 0 END), 0) AS fechados_prev,
                COALESCE(SUM(CASE WHEN data_inicio = ? THEN 1 ELSE 0 END), 0) AS fechados_hoje
            FROM clientes
            """,
            (start_iso, end_iso, prev_start_iso, prev_end_iso, today.isoformat()),
        )
        row = cur.fetchone() or (0, 0, 0, 0, 0, 0)
        total_clientes = int(row[0] or 0)
        status_counts = {
            "ativos": int(row[1] or 0),
            "atrasados": 0,
            "inativos": int(row[2] or 0),
        }
        atraso_estimado = 0.0
        fechados_mes = int(row[3] or 0)
        fechados_prev = int(row[4] or 0)
        hoje_qtd = int(row[5] or 0)

        cur.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN data_pagamento BETWEEN ? AND ? THEN 1 ELSE 0 END), 0) AS pagamentos_periodo,
                COALESCE(SUM(CASE WHEN data_pagamento BETWEEN ? AND ? THEN 1 ELSE 0 END), 0) AS pagamentos_prev,
                COALESCE(SUM(CASE WHEN data_pagamento = ? THEN 1 ELSE 0 END), 0) AS pagamentos_hoje
            FROM pagamentos
            """,
            (start_iso, end_iso, prev_start_iso, prev_end_iso, today.isoformat()),
        )
        pay_row = cur.fetchone() or (0, 0, 0)
        pagamentos_mes = int(pay_row[0] or 0)
        pagamentos_prev = int(pay_row[1] or 0)
        pagamentos_hoje = int(pay_row[2] or 0)

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_empresas,
                COALESCE(SUM(CASE WHEN data_cadastro BETWEEN ? AND ? THEN 1 ELSE 0 END), 0) AS novos_periodo
            FROM empresas
            """,
            (start_iso, end_iso),
        )
        company_row = cur.fetchone() or (0, 0)
        contratos_empresa = {
            "total_empresas": int(company_row[0] or 0),
            "novos_periodo": int(company_row[1] or 0),
            "ativos": 0,
            "atrasados": 0,
            "inativos": 0,
        }

        alert_cfg_kwargs = {}
        if str(alert_user or "").strip():
            alert_cfg_kwargs["usuario"] = str(alert_user or "").strip()
        try:
            try:
                alertas_cfg = db_module.obter_contas_alerta_config(**alert_cfg_kwargs) or {}
            except TypeError:
                alertas_cfg = db_module.obter_contas_alerta_config() or {}
            contas_alerta_dias = [int(v) for v in (alertas_cfg.get("dias") or [0, 3, 7])]
            contas_alerta_janela = int(
                alertas_cfg.get("janela_max", max(contas_alerta_dias) if contas_alerta_dias else 7) or 7
            )
            try:
                alertas_resumo = db_module.resumo_alertas_contas_vencimento(
                    today.isoformat(),
                    dias=contas_alerta_dias,
                    **alert_cfg_kwargs,
                ) or {}
            except TypeError:
                alertas_resumo = db_module.resumo_alertas_contas_vencimento(
                    today.isoformat(),
                    dias=contas_alerta_dias,
                ) or {}
            by_day = dict(alertas_resumo.get("alertas_por_dia") or {})
            contas_pagar_hoje = int(by_day.get(0, 0) or 0)
            contas_pagar_semana = int(alertas_resumo.get("dentro_janela", 0) or 0)
            contas_pagar_vencidas = int(alertas_resumo.get("vencidas", 0) or 0)
        except Exception:
            try:
                hoje_iso = today.isoformat()
                fim_semana_iso = (today + timedelta(days=7)).isoformat()
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(CASE
                            WHEN LOWER(COALESCE(status, '')) <> 'paga'
                             AND data_vencimento = ?
                            THEN 1 ELSE 0 END), 0) AS hoje,
                        COALESCE(SUM(CASE
                            WHEN LOWER(COALESCE(status, '')) <> 'paga'
                             AND data_vencimento > ?
                             AND data_vencimento <= ?
                            THEN 1 ELSE 0 END), 0) AS semana,
                        COALESCE(SUM(CASE
                            WHEN LOWER(COALESCE(status, '')) = 'vencida'
                              OR (
                                  LOWER(COALESCE(status, '')) <> 'paga'
                                  AND data_vencimento < ?
                              )
                            THEN 1 ELSE 0 END), 0) AS vencidas
                    FROM contas_pagar
                    """,
                    (hoje_iso, hoje_iso, fim_semana_iso, hoje_iso),
                )
                contas_row = cur.fetchone() or (0, 0, 0)
                contas_pagar_hoje = int(contas_row[0] or 0)
                contas_pagar_semana = int(contas_row[1] or 0)
                contas_pagar_vencidas = int(contas_row[2] or 0)
            except Exception:
                _log_debug(log_debug, "Falha ao calcular alertas de contas a pagar para dashboard.")

        clientes_pagos_mes = db_module.cliente_ids_pagamento_mes_cursor(cur, mes_iso)

        cur.execute(
            """
            SELECT
                id,
                COALESCE(nome, '') AS nome,
                COALESCE(vencimento_dia, 10) AS vencimento_dia,
                COALESCE(valor_mensal, 0) AS valor_mensal
            FROM clientes
            WHERE status <> 'inativo'
            """
        )
        forecast_rows = cur.fetchall() or []
        clientes_base = 0

        for cliente_id_raw, _cliente_nome_raw, venc_raw, valor_raw in forecast_rows:
            try:
                valor = float(valor_raw or 0.0)
            except Exception:
                valor = 0.0

            cliente_id = int(cliente_id_raw or 0)
            try:
                vencimento_dia = int(venc_raw or 10)
            except Exception:
                vencimento_dia = 10
            vencimento_dia = max(1, min(31, vencimento_dia))

            status_cliente = db_module.calcular_status_pagamento(
                {
                    "vencimento_dia": vencimento_dia,
                    "pagamento_mes_atual": cliente_id in clientes_pagos_mes,
                },
                hoje=today,
            )
            if status_cliente == "em_atraso":
                status_counts["atrasados"] += 1
                if valor > 0:
                    clientes_atrasados += 1
                    atraso_estimado += valor

            if valor <= 0:
                continue
            clientes_base += 1

            proximo_vencimento = _next_due_date(today, vencimento_dia)
            dias_ate_vencimento = int((proximo_vencimento - today).days)

            if dias_ate_vencimento == 0:
                vencendo_hoje_clientes += 1
            if dias_ate_vencimento <= 7:
                entrada_7d_clientes += valor
                qtd_7d_clientes += 1
            if dias_ate_vencimento <= 15:
                entrada_15d_clientes += valor
                qtd_15d_clientes += 1
            if dias_ate_vencimento <= 30:
                entrada_30d_clientes += valor
                qtd_30d_clientes += 1

        empresas_pagas_mes = db_module.empresa_ids_pagamento_mes_cursor(cur, mes_iso)

        cur.execute(
            """
            SELECT
                id,
                COALESCE(nome, '') AS nome,
                COALESCE(dia_vencimento, 10) AS dia_vencimento,
                COALESCE(valor_mensal, '0') AS valor_mensal
            FROM empresas
            """
        )
        empresas_rows = cur.fetchall() or []
        for empresa_id_raw, _empresa_nome_raw, venc_raw, valor_raw in empresas_rows:
            empresa_id = int(empresa_id_raw or 0)
            try:
                vencimento_dia = int(venc_raw or 10)
            except Exception:
                vencimento_dia = 10
            vencimento_dia = max(1, min(31, vencimento_dia))

            status_emp = db_module.calcular_status_pagamento(
                {
                    "dia_vencimento": vencimento_dia,
                    "pagamento_mes_atual": empresa_id in empresas_pagas_mes,
                },
                hoje=today,
            )
            if status_emp == "em_dia":
                contratos_empresa["ativos"] += 1
            elif status_emp == "em_atraso":
                contratos_empresa["atrasados"] += 1
            else:
                contratos_empresa["inativos"] += 1

            valor = _money_to_float(valor_raw)
            if valor <= 0:
                continue

            empresas_base += 1
            if status_emp == "em_atraso":
                empresas_em_risco += 1
                valor_atraso_empresas += valor

            proximo_vencimento = _next_due_date(today, vencimento_dia)
            dias_ate_vencimento = int((proximo_vencimento - today).days)

            # Não projeta novas entradas para empresas já em atraso no mês atual.
            if status_emp != "em_atraso":
                if dias_ate_vencimento == 0:
                    vencendo_hoje_empresas += 1
                if dias_ate_vencimento <= 7:
                    entrada_7d_empresas += valor
                    qtd_7d_empresas += 1
                if dias_ate_vencimento <= 15:
                    entrada_15d_empresas += valor
                    qtd_15d_empresas += 1
                if dias_ate_vencimento <= 30:
                    entrada_30d_empresas += valor
                    qtd_30d_empresas += 1

        entrada_7d = float(entrada_7d_clientes + entrada_7d_empresas)
        entrada_15d = float(entrada_15d_clientes + entrada_15d_empresas)
        entrada_30d = float(entrada_30d_clientes + entrada_30d_empresas)
        qtd_7d = int(qtd_7d_clientes + qtd_7d_empresas)
        qtd_15d = int(qtd_15d_clientes + qtd_15d_empresas)
        qtd_30d = int(qtd_30d_clientes + qtd_30d_empresas)

        base_total = int(clientes_base + empresas_base)
        em_risco_total = int(clientes_atrasados + empresas_em_risco)
        if clientes_base > 0:
            taxa_inadimplencia_clientes = float(clientes_atrasados) / float(clientes_base)
        if empresas_base > 0:
            taxa_inadimplencia_empresas = float(empresas_em_risco) / float(empresas_base)
        if base_total > 0:
            taxa_inadimplencia = float(em_risco_total) / float(base_total)
            risco_7d = entrada_7d * taxa_inadimplencia
            risco_15d = entrada_15d * taxa_inadimplencia
            risco_30d = entrada_30d * taxa_inadimplencia

        previsao_liquida_7d = max(0.0, entrada_7d - risco_7d)
        previsao_liquida_15d = max(0.0, entrada_15d - risco_15d)
        previsao_liquida_30d = max(0.0, entrada_30d - risco_30d)

        if taxa_inadimplencia <= 0.05:
            risco_nivel = "baixo"
        elif taxa_inadimplencia <= 0.12:
            risco_nivel = "medio"
        elif taxa_inadimplencia <= 0.20:
            risco_nivel = "alto"
        else:
            risco_nivel = "critico"
    except Exception:
        _log_debug(log_debug, "Falha ao calcular payload principal do dashboard.")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    forecast_end_30d = today + timedelta(days=30)
    contratos_payload = {
        "mes_ref": mes_iso,
        "periodo_desc": period_desc,
        "janela_inicio": today.isoformat(),
        "janela_fim_30d": forecast_end_30d.isoformat(),
        "janela_fim_30d_br": forecast_end_30d.strftime("%d/%m/%Y"),
        "entrada_7d": round(float(entrada_7d), 2),
        "entrada_15d": round(float(entrada_15d), 2),
        "entrada_30d": round(float(entrada_30d), 2),
        "qtd_7d": int(qtd_7d),
        "qtd_15d": int(qtd_15d),
        "qtd_30d": int(qtd_30d),
        "entrada_7d_clientes": round(float(entrada_7d_clientes), 2),
        "entrada_15d_clientes": round(float(entrada_15d_clientes), 2),
        "entrada_30d_clientes": round(float(entrada_30d_clientes), 2),
        "qtd_7d_clientes": int(qtd_7d_clientes),
        "qtd_15d_clientes": int(qtd_15d_clientes),
        "qtd_30d_clientes": int(qtd_30d_clientes),
        "entrada_7d_empresas": round(float(entrada_7d_empresas), 2),
        "entrada_15d_empresas": round(float(entrada_15d_empresas), 2),
        "entrada_30d_empresas": round(float(entrada_30d_empresas), 2),
        "qtd_7d_empresas": int(qtd_7d_empresas),
        "qtd_15d_empresas": int(qtd_15d_empresas),
        "qtd_30d_empresas": int(qtd_30d_empresas),
        "clientes_base": int(clientes_base),
        "clientes_atrasados": int(clientes_atrasados),
        "empresas_base": int(empresas_base),
        "empresas_em_risco": int(empresas_em_risco),
        "base_total": int(base_total),
        "em_risco_total": int(em_risco_total),
        "taxa_inadimplencia": float(taxa_inadimplencia),
        "taxa_inadimplencia_clientes": float(taxa_inadimplencia_clientes),
        "taxa_inadimplencia_empresas": float(taxa_inadimplencia_empresas),
        "risco_nivel": str(risco_nivel),
        "risco_7d": round(float(risco_7d), 2),
        "risco_15d": round(float(risco_15d), 2),
        "risco_30d": round(float(risco_30d), 2),
        "previsao_liquida_7d": round(float(previsao_liquida_7d), 2),
        "previsao_liquida_15d": round(float(previsao_liquida_15d), 2),
        "previsao_liquida_30d": round(float(previsao_liquida_30d), 2),
        "valor_em_atraso_clientes": round(float(atraso_estimado), 2),
        "valor_em_atraso_empresas": round(float(valor_atraso_empresas), 2),
        "valor_em_atraso_atual": round(float(atraso_estimado + valor_atraso_empresas), 2),
    }
    cobertura_pagamentos_pct = (float(pagamentos_mes) / float(base_total) * 100.0) if base_total > 0 else 0.0
    meta_cobertura_pagamentos_pct = 85.0
    atraso_total_carteira = float(atraso_estimado + valor_atraso_empresas)
    if entrada_30d > 0:
        atraso_ratio_pct = (atraso_total_carteira / float(entrada_30d)) * 100.0
    else:
        atraso_ratio_pct = 100.0 if atraso_total_carteira > 0 else 0.0
    meta_atraso_pct = 10.0

    live_metrics = {
        "mes_ref": mes_iso,
        "total_clientes": total_clientes,
        "pagamentos_mes": pagamentos_mes,
        "pagamentos_prev": pagamentos_prev,
        "atraso_estimado": atraso_estimado,
        "contratos_mes": fechados_mes,
        "contratos_prev": fechados_prev,
        "contratos_empresa_total": int(contratos_empresa.get("total_empresas", 0) or 0),
        "contratos_empresa_ativos": int(contratos_empresa.get("ativos", 0) or 0),
        "contratos_empresa_atrasados": int(contratos_empresa.get("atrasados", 0) or 0),
        "ativos": int(status_counts.get("ativos", 0) or 0),
        "atrasados": int(status_counts.get("atrasados", 0) or 0),
        "inativos": int(status_counts.get("inativos", 0) or 0),
        "cobertura_pagamentos_pct": round(float(cobertura_pagamentos_pct), 1),
        "meta_cobertura_pagamentos_pct": float(meta_cobertura_pagamentos_pct),
        "atraso_ratio_pct": round(float(atraso_ratio_pct), 1),
        "meta_atraso_pct": float(meta_atraso_pct),
        "periodo_desc": period_desc,
    }

    series = []
    vencendo_hoje_total = int(vencendo_hoje_clientes + vencendo_hoje_empresas)
    tarefas_hoje = int(pagamentos_hoje + hoje_qtd + vencendo_hoje_total)

    resumo = {
        "pagamentos_periodo": int((pagamentos_hoje if period_key == "today" else pagamentos_mes) or 0),
        "pagamentos_label": "Pagamentos hoje" if period_key == "today" else "Pagamentos no período",
        "novos_mes": int(fechados_mes or 0),
        "ultimo_backup": "-",
        "ultima_export": "-",
        "vencendo_hoje": vencendo_hoje_total,
        "vencendo_7d": int(qtd_7d),
        "tarefas_hoje": tarefas_hoje,
        "contas_pagar_hoje": int(contas_pagar_hoje),
        "contas_pagar_semana": int(contas_pagar_semana),
        "contas_pagar_vencidas": int(contas_pagar_vencidas),
        "contas_alerta_dias": list(contas_alerta_dias),
        "contas_alerta_janela": int(contas_alerta_janela),
        "pendencias_operacionais": [],
    }
    pendencias: list[str] = []
    if int(contas_pagar_vencidas) > 0:
        pendencias.append(f"{int(contas_pagar_vencidas)} conta(s) a pagar vencida(s).")
    if int(status_counts.get("atrasados", 0) or 0) > 0:
        pendencias.append(f"{int(status_counts.get('atrasados', 0) or 0)} cliente(s) em atraso para cobrança.")
    if int(contas_pagar_hoje) > 0:
        pendencias.append(f"{int(contas_pagar_hoje)} conta(s) vencem hoje.")
    if int(qtd_7d) > 0:
        pendencias.append(f"{int(qtd_7d)} vencimento(s) previsto(s) em até 7 dias.")
    if str(risco_nivel or "").lower() in {"alto", "critico"}:
        pendencias.append(f"Risco de inadimplência {str(risco_nivel).lower()} no mês atual.")
    if not pendencias:
        pendencias.append("Sem pendências críticas no momento.")
    resumo["pendencias_operacionais"] = pendencias[:4]

    try:
        bkp_dir = db_module.get_backup_dir()
        if bkp_dir.exists():
            latest_mtime = None
            for p in bkp_dir.glob("medcontract_backup_*.*"):
                if not p.is_file() or p.suffix.lower() not in {".db", ".sql", ".json", ".dump"}:
                    continue
                try:
                    mtime = p.stat().st_mtime
                except Exception:
                    continue
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
            if latest_mtime is not None:
                resumo["ultimo_backup"] = datetime.fromtimestamp(latest_mtime).strftime("%d/%m %H:%M")
    except Exception:
        pass

    return {
        "status_counts": status_counts,
        "live_metrics": live_metrics,
        "series": series,
        "resumo": resumo,
        "contratos_mes": contratos_payload,
        "finance_forecast": contratos_payload,
        "period_desc": period_desc,
        "period_chart_label": period_chart_label,
        "period_key": period_key,
    }
