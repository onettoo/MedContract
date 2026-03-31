import sys
import os
import traceback
import ctypes
import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import Qt, QLockFile, QStandardPaths
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from main_window import MainWindow
import database.db as db
from styles.theme import build_app_qss


APP_NAME = "MedContract"
APP_ID = "medcontract.app.2.0"
SINGLE_INSTANCE_KEY = "MedContract_SINGLE_INSTANCE_v2"
APP_ORG_NAME = "MedContract"
APP_ORG_DOMAIN = "medcontract.local"

_LOG_FILE_PATH: Path | None = None


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _is_placeholder_secret(value: str) -> bool:
    txt = str(value or "").strip().upper()
    if not txt:
        return True
    return txt.startswith("TROQUE_") or txt.startswith("DEFINA_") or "CHANGE_THIS" in txt


def _is_strict_sslmode(value: str) -> bool:
    mode = str(value or "").strip().lower()
    return mode in {"require", "verify-ca", "verify-full"}


def run_security_preflight() -> tuple[list[str], list[str]]:
    """
    Valida configurações de hardening antes da inicialização completa.
    Retorna (erros_criticos, avisos).
    """
    errors: list[str] = []
    warns: list[str] = []

    env = str(os.getenv("MEDCONTRACT_ENV") or "").strip().lower()
    is_prod = env in {"prod", "production", "staging", "homolog", "hml"}

    db_backend = str(os.getenv("MEDCONTRACT_DB_BACKEND") or "auto").strip().lower()
    db_url = str(os.getenv("MEDCONTRACT_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    db_pwd = str(os.getenv("MEDCONTRACT_DB_PASSWORD") or "").strip()
    db_sslmode = str(os.getenv("MEDCONTRACT_DB_SSLMODE") or "").strip().lower()

    if is_prod:
        if _env_flag("MEDCONTRACT_DB_ALLOW_SQLITE_FALLBACK", True):
            errors.append("MEDCONTRACT_DB_ALLOW_SQLITE_FALLBACK deve ser 0 em produção.")

        if db_backend in {"postgres", "pg", "postgresql"} or db_url.lower().startswith("postgres"):
            if db_url and ("sslmode=" not in db_url.lower()):
                warns.append("DATABASE_URL sem sslmode explícito. Recomendado: sslmode=require.")
            if db_sslmode and not _is_strict_sslmode(db_sslmode):
                errors.append("MEDCONTRACT_DB_SSLMODE deve ser require/verify-ca/verify-full em produção.")
            if not db_url and not db_pwd:
                errors.append("Defina MEDCONTRACT_DATABASE_URL ou MEDCONTRACT_DB_PASSWORD para conexão segura.")

        default_admin_pwd = str(os.getenv("MEDCONTRACT_DEFAULT_ADMIN_PASSWORD") or "").strip()
        if _is_placeholder_secret(default_admin_pwd):
            errors.append("MEDCONTRACT_DEFAULT_ADMIN_PASSWORD não pode ficar como placeholder em produção.")

    backup_key = str(os.getenv("MEDCONTRACT_BACKUP_ENCRYPTION_KEY") or "").strip()
    if not backup_key:
        warns.append("Backups sem criptografia em repouso (defina MEDCONTRACT_BACKUP_ENCRYPTION_KEY).")

    if not _env_flag("MEDCONTRACT_ALLOW_JSON_BACKUP_FALLBACK", False):
        logging.info("Fallback JSON de backup desabilitado (recomendado).")

    return errors, warns


def _load_env_file(path: Path, *, overwrite: bool = False) -> int:
    """
    Carrega variáveis de um arquivo .env simples (KEY=VALUE).
    Retorna quantas variáveis novas foram aplicadas.
    """
    if not path.exists() or not path.is_file():
        return 0

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0

    loaded = 0
    for raw in lines:
        line = (raw or "").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and (
            (value[0] == value[-1] == '"')
            or (value[0] == value[-1] == "'")
        ):
            value = value[1:-1]

        if overwrite or key not in os.environ:
            os.environ[key] = value
            loaded += 1

    return loaded


def load_env_files() -> list[tuple[Path, int]]:
    """
    Carrega .env e .env.local de diretórios prováveis do app.
    - DEV: pasta do projeto (main.py)
    - EXE (PyInstaller): pasta do executável e fallback interno
    """
    roots: list[Path] = [Path(__file__).resolve().parent]
    if is_frozen():
        try:
            roots.append(Path(sys.executable).resolve().parent)
        except Exception:
            pass

    # Em build one-folder, __file__ pode apontar para "...\\_internal".
    for root in list(roots):
        try:
            if root.name.lower() == "_internal":
                roots.append(root.parent)
        except Exception:
            continue

    unique_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_roots.append(root)

    candidates: list[Path] = []
    for root in unique_roots:
        candidates.append(root / ".env")
        candidates.append(root / ".env.local")
    results: list[tuple[Path, int]] = []

    for env_path in candidates:
        if env_path.exists():
            # .env.local deve sobrescrever .env para credenciais locais.
            overwrite = env_path.name.lower() == ".env.local"
            loaded = _load_env_file(env_path, overwrite=overwrite)
            results.append((env_path, loaded))

    return results


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def resource_path(relative_path: str) -> str:
    """
    Resolve caminho em DEV e no PyInstaller.
    - DEV: relativo ao arquivo main.py
    - PyInstaller: relativo ao _MEIPASS
    """
    try:
        if is_frozen():
            base_path = Path(getattr(sys, "_MEIPASS"))
        else:
            base_path = Path(__file__).resolve().parent
        return str(base_path / relative_path)
    except Exception:
        return relative_path


def get_writable_app_dir() -> Path:
    """
    Diretório gravável do app (AppData no Windows).
    """
    base = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    base.mkdir(parents=True, exist_ok=True)
    return base


def setup_logging() -> Path:
    """
    Log em arquivo para diagnosticar erros quando o app roda fora do terminal.
    Salva em pasta gravável do usuário (AppData).
    """
    logs_dir = get_writable_app_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "app.log"

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[file_handler, stream_handler],
        force=True,
    )
    logging.info("Iniciando %s", APP_NAME)
    logging.info("Log: %s", str(log_file))
    return log_file


def excepthook(exc_type, exc_value, exc_tb):
    """
    Mostra erro amigável em produção + registra stacktrace no log.
    """
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error("Erro inesperado:\n%s", msg)
    log_hint = str(_LOG_FILE_PATH) if _LOG_FILE_PATH else "logs/app.log"

    try:
        QMessageBox.critical(
            None,
            "Erro inesperado",
            "Ocorreu um erro inesperado no sistema.\n\n"
            f"O erro foi registrado em:\n{log_hint}\n\n"
            f"{exc_value}"
        )
    except Exception:
        pass


def thread_excepthook(args: threading.ExceptHookArgs):
    excepthook(args.exc_type, args.exc_value, args.exc_traceback)


def center_on_screen(window):
    screen = window.screen() if hasattr(window, "screen") else None
    if not screen:
        screen = QGuiApplication.primaryScreen()
    if not screen:
        return
    geo = screen.availableGeometry()
    x = geo.x() + (geo.width() - window.width()) // 2
    y = geo.y() + (geo.height() - window.height()) // 2
    window.move(x, y)


def ensure_single_instance() -> QLockFile | None:
    """
    Impede múltiplas instâncias do app.
    """
    lock_path = get_writable_app_dir() / f"{SINGLE_INSTANCE_KEY}.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(60_000)

    if lock.tryLock(100):
        return lock

    # Tenta limpar lock obsoleto e tenta novamente uma vez.
    if lock.removeStaleLockFile() and lock.tryLock(100):
        logging.warning("Lock obsoleto removido: %s", lock_path)
        return lock

    logging.info("Outra instância em execução (lock: %s).", lock_path)
    return None


def apply_global_qss(app: QApplication):
    """
    Carrega um tema global se existir.
    """
    try:
        qss = build_app_qss("assets/theme.qss")
        if qss.strip():
            app.setStyleSheet(qss)
            logging.info("Tema global carregado (base + extras).")
            return
    except Exception as e:
        logging.warning("Falha ao montar tema global: %s", e)

    qss_path = resource_path("assets/theme.qss")
    if os.path.exists(qss_path):
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            logging.info("Fallback de tema carregado: %s", qss_path)
        except Exception as e:
            logging.warning("Falha ao carregar fallback theme.qss: %s", e)
    else:
        logging.info("Nenhum tema global encontrado em assets/theme.qss")


def load_app_icon() -> QIcon | None:
    """
    Tenta carregar o ícone do app.
    Prioridade:
    1. assets/icon.ico
    2. assets/icon.png
    """
    icon_candidates = [
        resource_path("assets/icon.ico"),
        resource_path("assets/icon.png"),
    ]

    for path in icon_candidates:
        try:
            if os.path.exists(path):
                icon = QIcon(path)
                if not icon.isNull():
                    logging.info("Ícone carregado: %s", path)
                    return icon
                logging.warning("Arquivo de ícone encontrado, mas inválido: %s", path)
        except Exception as e:
            logging.warning("Falha ao carregar ícone %s: %s", path, e)

    logging.warning("Nenhum ícone válido encontrado em assets/icon.ico ou assets/icon.png")
    return None


def _create_startup_backup():
    """
    Cria um backup automático ao iniciar o app.
    """
    try:
        path = db.backup_db()
        logging.info("Backup automático criado com sucesso: %s", path)
    except Exception as e:
        logging.warning("Falha ao criar backup automático na inicialização: %s", e)


def _create_startup_backup_async():
    t = threading.Thread(target=_create_startup_backup, name="startup-backup", daemon=True)
    t.start()


def main():
    global _LOG_FILE_PATH

    env_results = load_env_files()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG_NAME)
    app.setOrganizationDomain(APP_ORG_DOMAIN)

    _LOG_FILE_PATH = setup_logging()

    if env_results:
        for env_path, loaded in env_results:
            logging.info(".env carregado: %s (%s variaveis novas)", env_path, loaded)

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook

    preflight_errors, preflight_warns = run_security_preflight()
    for w in preflight_warns:
        logging.warning("[PRECHECK] %s", w)
    strict_precheck = _env_flag("MEDCONTRACT_SECURITY_PREFLIGHT_STRICT", is_frozen())
    if preflight_errors and strict_precheck:
        err_text = "\n- " + "\n- ".join(preflight_errors)
        logging.error("Falha no preflight de segurança:%s", err_text)
        QMessageBox.critical(
            None,
            "Configuração insegura",
            "A inicialização foi bloqueada por configurações críticas de segurança:\n"
            f"{err_text}\n\n"
            "Ajuste o .env/.env.local e tente novamente."
        )
        return 1
    if preflight_errors:
        err_text = "\n- " + "\n- ".join(preflight_errors)
        logging.warning("Preflight com pendências críticas (modo não estrito):%s", err_text)

    # Identidade no Windows (ajuda ícone fixo na barra)
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
            logging.info("AppUserModelID aplicado: %s", APP_ID)
        except Exception as e:
            logging.warning("Não foi possível aplicar AppUserModelID: %s", e)

    # Instância única
    app_lock = ensure_single_instance()
    if app_lock is None:
        QMessageBox.information(None, APP_NAME, "O MedContract já está aberto.")
        return 0

    # Ícone global
    icon = load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    # Tema global
    apply_global_qss(app)

    # Garante estrutura do banco
    try:
        db.create_tables()
        if hasattr(db, "create_default_users"):
            db.create_default_users(required_if_empty=True)
        else:
            db.create_default_admin()
        try:
            alerta_dias_env = str(os.getenv("MEDCONTRACT_CONTAS_ALERTA_DIAS") or "").strip()
            if alerta_dias_env:
                out_alerta = db.salvar_contas_alerta_config(alerta_dias_env)
                if bool(out_alerta.get("ok")):
                    logging.info(
                        "Configuração de alertas de contas aplicada por env: dias=%s.",
                        ",".join(str(v) for v in (out_alerta.get("dias") or [])),
                    )
                else:
                    logging.warning(
                        "Falha ao aplicar MEDCONTRACT_CONTAS_ALERTA_DIAS: %s",
                        str(out_alerta.get("erro", "") or "erro desconhecido"),
                    )
        except Exception as alert_exc:
            logging.warning("Falha ao aplicar configuração de alertas de contas no startup: %s", alert_exc)
        try:
            force_norm = _env_flag("MEDCONTRACT_FORCE_MONTH_REF_NORMALIZE_ON_STARTUP", False)
            norm_out = db.normalizar_mes_referencia_pagamentos_startup(force=bool(force_norm))
            if bool(norm_out.get("ok")):
                if bool(norm_out.get("executed")):
                    logging.info(
                        "Normalizacao de mes_referencia no startup concluida: alteracoes=%s, motivo=%s.",
                        int(norm_out.get("total_alteracoes", 0) or 0),
                        str(norm_out.get("reason", "") or "scheduled"),
                    )
                else:
                    logging.info(
                        "Normalizacao de mes_referencia no startup ignorada: %s.",
                        str(norm_out.get("reason", "already_ran_today") or "already_ran_today"),
                    )
            else:
                logging.warning(
                    "Falha na normalizacao de mes_referencia no startup: %s",
                    str(norm_out.get("erro", "erro desconhecido") or "erro desconhecido"),
                )
        except Exception as norm_exc:
            logging.warning("Falha ao executar normalizacao de mes_referencia no startup: %s", norm_exc)
        logging.info("Banco inicializado com sucesso.")
    except Exception as e:
        logging.error("Erro ao inicializar banco: %s", e)
        QMessageBox.critical(
            None,
            "Erro no banco de dados",
            f"Não foi possível inicializar o banco de dados.\n\n{e}"
        )
        return 1

    # Backup automático ao iniciar (opt-in por segurança)
    if _env_flag("MEDCONTRACT_AUTO_BACKUP_ON_STARTUP", False):
        _create_startup_backup_async()
    else:
        logging.info("Backup automatico na inicializacao desabilitado (MEDCONTRACT_AUTO_BACKUP_ON_STARTUP=0).")

    # Janela principal
    window = MainWindow()
    if icon is not None:
        window.setWindowIcon(icon)

    window.setMinimumSize(1200, 760)
    window.show()
    center_on_screen(window)

    rc = app.exec()
    _ = app_lock  # mantém lock ativo até o fim
    logging.info("Encerrando %s (code=%s)", APP_NAME, rc)
    return rc

if __name__ == "__main__":
    raise SystemExit(main())    
