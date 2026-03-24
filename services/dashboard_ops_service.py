from __future__ import annotations

from datetime import datetime
from pathlib import Path


def build_operational_summary_text(payload: dict, *, now: datetime | None = None) -> str:
    ts = now or datetime.now()
    generated_at = ts.strftime("%d/%m/%Y %H:%M:%S")
    period_desc = str(payload.get("period_desc") or "-")
    sc = dict(payload.get("status_counts", {}) or {})
    lm = dict(payload.get("live_metrics", {}) or {})
    rs = dict(payload.get("resumo", {}) or {})
    fc = dict(payload.get("finance_forecast", {}) or payload.get("contratos_mes", {}) or {})
    pd = dict(payload.get("pendencias", {}) or {})

    return (
        "MEDCONTRACT - RESUMO OPERACIONAL DIARIO\n"
        f"Gerado em: {generated_at}\n"
        f"Periodo: {period_desc}\n\n"
        "STATUS DE CLIENTES\n"
        f"- Ativos: {int(sc.get('ativos', 0) or 0)}\n"
        f"- Atrasados: {int(sc.get('atrasados', 0) or 0)}\n"
        f"- Inativos: {int(sc.get('inativos', 0) or 0)}\n\n"
        "OPERACAO DO PERIODO\n"
        f"- Total de clientes: {int(lm.get('total_clientes', 0) or 0)}\n"
        f"- Contratos de empresa: {int(lm.get('contratos_empresa_total', 0) or 0)}\n"
        f"- Pagamentos no periodo: {int(lm.get('pagamentos_mes', 0) or 0)}\n"
        f"- Atraso estimado: {float(lm.get('atraso_estimado', 0.0) or 0.0):.2f}\n"
        f"- Novos no periodo: {int(rs.get('novos_mes', 0) or 0)}\n\n"
        "PENDENCIAS\n"
        f"- Pendencias abertas: {int(pd.get('total_pendencias', 0) or 0)}\n"
        f"- Vencendo em 7 dias: {int(pd.get('vencendo_7d', 0) or 0)}\n"
        f"- Valor em risco: {float(pd.get('valor_em_risco', 0.0) or 0.0):.2f}\n\n"
        "PROJECAO 30 DIAS\n"
        f"- Entrada prevista: {float(fc.get('entrada_30d', 0.0) or 0.0):.2f}\n"
        f"- Risco projetado: {float(fc.get('risco_30d', 0.0) or 0.0):.2f}\n"
        f"- Liquido previsto: {float(fc.get('previsao_liquida_30d', 0.0) or 0.0):.2f}\n"
    )


def build_jobs_status(
    *,
    now: datetime,
    resumo: dict | None,
    backup_dir: Path,
    reports_dir: Path,
    export_history: list[dict] | None,
    last_auto_export_key: str,
    last_operational_summary_date: str,
    auto_export_enabled: bool,
    auto_export_hour: int,
) -> dict:
    today_key = now.strftime("%Y-%m-%d")
    today_br = now.strftime("%d/%m")
    resumo_map = dict(resumo or {})
    history = list(export_history or [])

    jobs = {
        "backup": {"text": "nenhum backup encontrado", "level": "warn"},
        "resumo": {"text": "pendente para hoje", "level": "warn"},
        "lembrete": {"text": "pendente para hoje", "level": "warn"},
        "autoexport": {"text": "desativado", "level": "muted"},
    }

    latest_backup_dt = None
    try:
        if backup_dir.exists():
            latest_mtime = None
            for p in backup_dir.glob("medcontract_backup_*.*"):
                if not p.is_file() or p.suffix.lower() not in {".db", ".sql", ".json", ".dump"}:
                    continue
                try:
                    mtime = p.stat().st_mtime
                except Exception:
                    continue
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
            if latest_mtime is not None:
                latest_backup_dt = datetime.fromtimestamp(latest_mtime)
    except Exception:
        latest_backup_dt = None

    if latest_backup_dt is not None:
        age_hours = max(0.0, (now - latest_backup_dt).total_seconds() / 3600.0)
        stamp = latest_backup_dt.strftime("%d/%m %H:%M")
        if age_hours <= 24:
            jobs["backup"] = {"text": f"ok ({stamp})", "level": "ok"}
        elif age_hours <= 72:
            jobs["backup"] = {"text": f"desatualizado ({stamp})", "level": "warn"}
        else:
            jobs["backup"] = {"text": f"atrasado ({stamp})", "level": "warn"}
    else:
        backup_hint = str(resumo_map.get("ultimo_backup") or "").strip()
        if backup_hint and backup_hint not in {"-", "—"}:
            jobs["backup"] = {"text": f"último em {backup_hint}", "level": "warn"}

    try:
        summary_path = reports_dir / f"resumo_operacional_{today_key}.txt"
        if summary_path.exists():
            try:
                ts = datetime.fromtimestamp(summary_path.stat().st_mtime).strftime("%H:%M")
                jobs["resumo"] = {"text": f"gerado hoje às {ts}", "level": "ok"}
            except Exception:
                jobs["resumo"] = {"text": "gerado hoje", "level": "ok"}
        elif last_operational_summary_date == today_key:
            jobs["resumo"] = {"text": "gerado hoje", "level": "ok"}
        else:
            jobs["resumo"] = {"text": "pendente para hoje", "level": "warn"}
    except Exception:
        jobs["resumo"] = {"text": "não foi possível verificar", "level": "warn"}

    try:
        due_path = reports_dir / f"lembrete_vencimentos_{today_key}.txt"
        if due_path.exists():
            try:
                ts = datetime.fromtimestamp(due_path.stat().st_mtime).strftime("%H:%M")
                jobs["lembrete"] = {"text": f"gerado hoje as {ts}", "level": "ok"}
            except Exception:
                jobs["lembrete"] = {"text": "gerado hoje", "level": "ok"}
        else:
            jobs["lembrete"] = {"text": "pendente para hoje", "level": "warn"}
    except Exception:
        jobs["lembrete"] = {"text": "nao foi possivel verificar", "level": "warn"}

    if auto_export_enabled:
        run_hour = max(0, min(23, int(auto_export_hour)))
        auto_event = None
        for item in history:
            action_txt = str(item.get("action", "") or "").strip().lower()
            if action_txt.startswith("autoexport"):
                auto_event = item
                break

        if last_auto_export_key == today_key:
            if auto_event and not bool(auto_event.get("ok", True)):
                when_txt = str(auto_event.get("when", "") or "").strip()
                jobs["autoexport"] = {
                    "text": f"falhou {when_txt}" if when_txt else "falhou hoje",
                    "level": "warn",
                }
            else:
                when_txt = str((auto_event or {}).get("when", "") or "").strip()
                jobs["autoexport"] = {
                    "text": f"concluído {when_txt}" if when_txt else "concluído hoje",
                    "level": "ok",
                }
        else:
            if auto_event and not bool(auto_event.get("ok", True)):
                when_txt = str(auto_event.get("when", "") or "").strip()
                is_today = bool(when_txt) and when_txt.startswith(today_br)
                if is_today:
                    jobs["autoexport"] = {"text": f"falhou {when_txt}", "level": "warn"}
                elif now.hour < run_hour:
                    jobs["autoexport"] = {"text": f"agendado para {run_hour:02d}:00", "level": "muted"}
                else:
                    jobs["autoexport"] = {"text": "pendente de execução hoje", "level": "warn"}
            elif now.hour < run_hour:
                jobs["autoexport"] = {"text": f"agendado para {run_hour:02d}:00", "level": "muted"}
            else:
                jobs["autoexport"] = {"text": "pendente de execução hoje", "level": "warn"}

    return jobs
