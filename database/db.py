from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path
from datetime import date, datetime
from calendar import monthrange
import base64
import os
import sys
import json
import re
import subprocess
import hashlib
import atexit
import threading
import time
import socket
from functools import lru_cache

import bcrypt
import psycopg
from psycopg.conninfo import make_conninfo, conninfo_to_dict
from psycopg.errors import DuplicateColumn
from psycopg.rows import tuple_row
from PySide6.QtCore import QStandardPaths


# =========================
# ENV (.env)
# =========================
def _load_env_file_if_present() -> None:
    """
    Carrega variáveis do arquivo .env local sem sobrescrever variáveis já
    definidas no ambiente do processo.
    """
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        Path.cwd() / ".env.local",
        project_root / ".env.local",
        Path.cwd() / ".env",
        project_root / ".env",
    ]
    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend([exe_dir / ".env.local", exe_dir / ".env"])
        except Exception:
            pass
    seen: set[Path] = set()
    for env_path in candidates:
        try:
            resolved = env_path.resolve()
        except Exception:
            resolved = env_path
        if resolved in seen:
            continue
        seen.add(resolved)

        if not env_path.exists() or not env_path.is_file():
            continue

        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        for raw in lines:
            line = str(raw or "").strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value


_load_env_file_if_present()


# =========================
# CAMINHOS DO APP / BANCO
# =========================
APP_NAME = "MedContract"
LEGACY_DB_FILENAME = "medcontract.db"


def get_app_data_dir() -> Path:
    """
    Retorna uma pasta gravÃ¡vel para o app.
    Ex.: C:\\Users\\SeuUsuario\\AppData\\Local\\MedContract
    """
    base_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base_dir:
        base_dir = str(Path.home() / "AppData" / "Roaming")

    base_path = Path(base_dir)
    # Quando o Qt ainda nÃ£o tem metadados de app definidos, pode devolver
    # apenas "...\AppData\Roaming". ForÃ§amos uma pasta do app para estabilidade.
    if base_path.name.lower() != APP_NAME.lower():
        app_dir = base_path / APP_NAME
    else:
        app_dir = base_path

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_legacy_db_path() -> Path:
    target = get_app_data_dir() / LEGACY_DB_FILENAME
    if target.exists():
        return target

    # Migra automaticamente de caminhos legados usados em versÃµes antigas.
    legacy_candidates = [
        Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / LEGACY_DB_FILENAME,
        Path.home() / "AppData" / "Roaming" / LEGACY_DB_FILENAME,
        Path.home() / "AppData" / "Local" / LEGACY_DB_FILENAME,
        Path(__file__).resolve().parent / LEGACY_DB_FILENAME,
    ]
    for legacy in legacy_candidates:
        try:
            if legacy.exists() and legacy.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, target)
                break
        except Exception:
            continue

    return target


def get_backup_dir() -> Path:
    backup_dir = get_app_data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


LEGACY_DB_PATH = str(get_legacy_db_path())
SCHEMA_VERSION = 10
try:
    DEFAULT_BACKUP_RETENTION = max(1, int((os.getenv("MEDCONTRACT_BACKUP_RETENTION_DAYS") or "30").strip()))
except Exception:
    DEFAULT_BACKUP_RETENTION = 30

DB_INTEGRITY_ERRORS = (psycopg.IntegrityError, sqlite3.IntegrityError)

_DB_BACKEND_LOCK = threading.Lock()
_RUNTIME_DB_BACKEND: str | None = None
_RUNTIME_DB_BACKEND_REASON: str | None = None


# =========================
# CONEXÃƒO
# =========================
def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_backend_name(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"pg", "postgres", "postgresql"}:
        return "postgres"
    if txt in {"sqlite", "sqlite3"}:
        return "sqlite"
    return "auto"


def _configured_db_backend() -> str:
    if _env_flag("MEDCONTRACT_FORCE_SQLITE", False):
        return "sqlite"

    direct_url = (os.getenv("MEDCONTRACT_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if direct_url.lower().startswith("sqlite:"):
        return "sqlite"

    return _normalize_backend_name(os.getenv("MEDCONTRACT_DB_BACKEND") or "auto")


def _sqlite_fallback_enabled() -> bool:
    # Em modo "auto", a fallback para SQLite evita indisponibilidade do app
    # quando PostgreSQL local nao estiver rodando.
    return _env_flag("MEDCONTRACT_DB_ALLOW_SQLITE_FALLBACK", True)


def _sqlite_db_path() -> Path:
    raw = (os.getenv("MEDCONTRACT_SQLITE_PATH") or "").strip()
    path = Path(raw) if raw else Path(LEGACY_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _sqlite_busy_timeout_ms() -> int:
    try:
        return max(500, int((os.getenv("MEDCONTRACT_SQLITE_BUSY_TIMEOUT_MS") or "5000").strip()))
    except Exception:
        return 5000


def _set_runtime_backend(backend: str, reason: str | None = None) -> None:
    global _RUNTIME_DB_BACKEND, _RUNTIME_DB_BACKEND_REASON
    backend_norm = _normalize_backend_name(backend)
    if backend_norm == "auto":
        return

    emit_reason = False
    with _DB_BACKEND_LOCK:
        changed = _RUNTIME_DB_BACKEND != backend_norm
        reason_changed = bool(reason and reason != _RUNTIME_DB_BACKEND_REASON)
        _RUNTIME_DB_BACKEND = backend_norm
        if reason:
            _RUNTIME_DB_BACKEND_REASON = reason
        emit_reason = bool(reason and (changed or reason_changed))

    if emit_reason:
        try:
            print(f"[DB][INFO] backend={backend_norm} motivo={reason}")
        except Exception:
            pass


def _get_runtime_backend() -> str | None:
    with _DB_BACKEND_LOCK:
        return _RUNTIME_DB_BACKEND


_STRICT_TLS_SSLMODES = {"require", "verify-ca", "verify-full"}
_WEAK_DB_PASSWORDS = {
    "postgres",
    "password",
    "123456",
    "admin",
    "changeme",
    "medcontract",
}


def _is_production_env() -> bool:
    value = (os.getenv("MEDCONTRACT_ENV") or os.getenv("ENV") or "").strip().lower()
    return value in {"prod", "production", "staging", "homolog", "hml"}


def _parse_db_hosts(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _is_local_db_host(value: str | None) -> bool:
    hosts = _parse_db_hosts(value)
    if not hosts:
        return True

    local_hosts = {"localhost", "127.0.0.1", "::1"}
    for host in hosts:
        host_l = host.lower()
        if host_l in local_hosts:
            continue
        if host.startswith("/"):
            # Unix socket path.
            continue
        return False
    return True


def _parse_db_ports(value: str | None) -> list[int]:
    raw = str(value or "").strip()
    if not raw:
        return [5432]

    out: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            port = int(item)
        except Exception:
            continue
        if 1 <= port <= 65535:
            out.append(port)
    return out or [5432]


def _can_open_tcp(host: str, port: int, timeout_seconds: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            return True
    except Exception:
        return False


def _should_short_circuit_to_sqlite(conn_info: dict[str, str]) -> bool:
    if not _sqlite_fallback_enabled():
        return False

    hosts = _parse_db_hosts(conn_info.get("host"))
    if not hosts:
        hosts = ["localhost"]

    # Fallback antecipada apenas para cenários locais.
    if not _is_local_db_host(",".join(hosts)):
        return False

    ports = _parse_db_ports(conn_info.get("port"))
    for host in hosts:
        if host.startswith("/"):
            # Socket unix nao se aplica ao Windows.
            continue
        for port in ports:
            if _can_open_tcp(host, port):
                return False
    return True


def _apply_pg_security_defaults(conn_info: dict[str, str]) -> None:
    strict_tls = _env_flag("MEDCONTRACT_DB_REQUIRE_STRICT_TLS", _is_production_env())
    is_local = _is_local_db_host(conn_info.get("host"))
    sslmode = str(conn_info.get("sslmode") or "").strip().lower()

    if not sslmode:
        conn_info["sslmode"] = "require" if (strict_tls and not is_local) else "prefer"

    if not str(conn_info.get("connect_timeout") or "").strip():
        conn_info["connect_timeout"] = (os.getenv("MEDCONTRACT_DB_CONNECT_TIMEOUT") or "10").strip()


def _validate_pg_conn_security(conn_info: dict[str, str], *, source: str) -> None:
    strict_tls = _env_flag("MEDCONTRACT_DB_REQUIRE_STRICT_TLS", _is_production_env())
    is_local = _is_local_db_host(conn_info.get("host"))
    sslmode = str(conn_info.get("sslmode") or "").strip().lower()
    password = str(conn_info.get("password") or "").strip()

    if strict_tls and not is_local and sslmode not in _STRICT_TLS_SSLMODES:
        raise RuntimeError(
            f"Conexao PostgreSQL insegura ({source}): defina sslmode como "
            f"{', '.join(sorted(_STRICT_TLS_SSLMODES))}."
        )

    if strict_tls and not is_local and not password:
        raise RuntimeError(
            f"Conexao PostgreSQL insegura ({source}): senha ausente para ambiente nao local."
        )

    if not is_local and password and password.lower() in _WEAK_DB_PASSWORDS:
        raise RuntimeError(
            f"Conexao PostgreSQL insegura ({source}): senha fraca detectada para ambiente nao local."
        )


def _build_pg_dsn() -> str:
    # Preferencia por URL direta.
    url = (os.getenv("MEDCONTRACT_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if url:
        try:
            conn_info = conninfo_to_dict(url)
        except Exception as exc:
            raise RuntimeError("MEDCONTRACT_DATABASE_URL invalida para PostgreSQL.") from exc

        _apply_pg_security_defaults(conn_info)
        _validate_pg_conn_security(conn_info, source="MEDCONTRACT_DATABASE_URL")
        return make_conninfo(**conn_info)

    host = (os.getenv("MEDCONTRACT_DB_HOST") or "localhost").strip()
    port = (os.getenv("MEDCONTRACT_DB_PORT") or "5432").strip()
    dbname = (os.getenv("MEDCONTRACT_DB_NAME") or "medcontract").strip()
    user = (os.getenv("MEDCONTRACT_DB_USER") or "postgres").strip()
    password = (os.getenv("MEDCONTRACT_DB_PASSWORD") or "").strip()
    sslmode = (os.getenv("MEDCONTRACT_DB_SSLMODE") or "").strip()
    connect_timeout = (os.getenv("MEDCONTRACT_DB_CONNECT_TIMEOUT") or "").strip()

    conn_info: dict[str, str] = {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password,
        "sslmode": sslmode,
        "connect_timeout": connect_timeout,
    }
    _apply_pg_security_defaults(conn_info)
    _validate_pg_conn_security(conn_info, source="MEDCONTRACT_DB_*")

    # DSN em formato keyword/value do libpq (com escaping adequado).
    return make_conninfo(**conn_info)


def _build_pg_conn_info() -> dict[str, str]:
    return conninfo_to_dict(_build_pg_dsn())


def _new_sqlite_raw_connection():
    db_path = _sqlite_db_path()
    try:
        timeout_s = max(1.0, float(_sqlite_busy_timeout_ms()) / 1000.0)
    except Exception:
        timeout_s = 5.0
    conn = sqlite3.connect(str(db_path), timeout=timeout_s)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(_sqlite_busy_timeout_ms())}")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass
    return conn


def _is_pg_connect_error(exc: Exception) -> bool:
    if isinstance(exc, psycopg.OperationalError):
        return True
    msg = _safe_str(exc, "").strip().lower()
    return any(
        token in msg
        for token in (
            "connection refused",
            "could not connect",
            "connection timeout",
            "timeout expired",
            "server closed the connection",
            "no such host",
            "network is unreachable",
            "failed",
        )
    )


def _convert_qmark_to_pyformat(query: str) -> str:
    if "?" not in query:
        return query

    out: list[str] = []
    i = 0
    n = len(query)
    in_single = False
    in_double = False

    while i < n:
        ch = query[i]

        if in_single:
            out.append(ch)
            # escape de aspas simples em SQL: ''
            if ch == "'" and i + 1 < n and query[i + 1] == "'":
                i += 1
                out.append(query[i])
            elif ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if ch == "?":
            out.append("%s")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


@lru_cache(maxsize=2048)
def _translate_sql(query: str, backend: str = "postgres") -> str:
    if not query:
        return query
    q = str(query)
    backend_norm = _normalize_backend_name(backend)
    if backend_norm == "sqlite":
        q = re.sub(r"\bILIKE\b", "LIKE", q, flags=re.IGNORECASE)
        q = re.sub(r"'\\[\\]'::json\b", "'[]'", q, flags=re.IGNORECASE)
        q = re.sub(r"::json\b", "", q, flags=re.IGNORECASE)
        return q

    q = re.sub(r"\bCOLLATE\s+NOCASE\b", "", q, flags=re.IGNORECASE)
    return _convert_qmark_to_pyformat(q)


def _slow_query_threshold_ms() -> float:
    try:
        return max(0.0, float(str(os.getenv("MEDCONTRACT_DB_SLOW_QUERY_MS", "0") or "0").strip()))
    except Exception:
        return 0.0


def _slow_connect_threshold_ms() -> float:
    try:
        return max(0.0, float(str(os.getenv("MEDCONTRACT_DB_SLOW_CONNECT_MS", "0") or "0").strip()))
    except Exception:
        return 0.0


def _query_params_count(params) -> int:
    if params is None:
        return 0
    try:
        if isinstance(params, dict):
            return len(params)
        return len(params)
    except Exception:
        return 1


def _compact_sql(sql: str, max_len: int = 220) -> str:
    one_line = re.sub(r"\s+", " ", _safe_str(sql, "")).strip()
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 3] + "..."


def _log_slow_query(elapsed_ms: float, sql: str, params=None, kind: str = "execute") -> None:
    try:
        print(
            f"[DB][SLOW][{kind}] {elapsed_ms:.1f}ms "
            f"params={_query_params_count(params)} sql=\"{_compact_sql(sql)}\""
        )
    except Exception:
        pass


class _CompatCursor:
    def __init__(self, inner, backend: str = "postgres"):
        self._inner = inner
        self._backend = _normalize_backend_name(backend) if backend else "postgres"

    def execute(self, query, params=None):
        raw_sql = str(query)
        sql = _translate_sql(raw_sql, self._backend)
        threshold_ms = _slow_query_threshold_ms()
        if threshold_ms > 0:
            start = time.perf_counter()
            try:
                if params is None:
                    self._inner.execute(sql)
                else:
                    self._inner.execute(sql, params)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                if elapsed_ms >= threshold_ms:
                    _log_slow_query(elapsed_ms, raw_sql, params=params, kind="execute")
        else:
            if params is None:
                self._inner.execute(sql)
            else:
                self._inner.execute(sql, params)
        return self

    def executemany(self, query, seq_of_params):
        raw_sql = str(query)
        sql = _translate_sql(raw_sql, self._backend)
        threshold_ms = _slow_query_threshold_ms()
        if threshold_ms > 0:
            start = time.perf_counter()
            try:
                self._inner.executemany(sql, seq_of_params)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                if elapsed_ms >= threshold_ms:
                    _log_slow_query(elapsed_ms, raw_sql, params=seq_of_params, kind="executemany")
        else:
            self._inner.executemany(sql, seq_of_params)
        return self

    def fetchone(self):
        return self._inner.fetchone()

    def fetchall(self):
        return self._inner.fetchall()

    def __iter__(self):
        return iter(self._inner)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._inner.__exit__(exc_type, exc, tb)


class _CompatConnection:
    def __init__(self, inner, release_fn=None, backend: str = "postgres"):
        self._inner = inner
        self._release_fn = release_fn
        self._closed = False
        self.backend = _normalize_backend_name(backend) if backend else "postgres"

    def cursor(self, *args, **kwargs):
        return _CompatCursor(self._inner.cursor(*args, **kwargs), backend=self.backend)

    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def commit(self):
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._release_fn is not None:
            self._release_fn(self._inner)
            return
        return self._inner.close()

    def __getattr__(self, name):
        return getattr(self._inner, name)


_POOL_LOCK = threading.Lock()
_POOL_IDLE: list = []


def _pool_enabled() -> bool:
    return _env_flag("MEDCONTRACT_DB_POOL_ENABLED", True)


def _pool_max_size() -> int:
    try:
        return max(1, int(os.getenv("MEDCONTRACT_DB_POOL_MAX", "8")))
    except Exception:
        return 8


def _new_raw_connection():
    dsn = _build_pg_dsn()
    threshold_ms = _slow_connect_threshold_ms()
    if threshold_ms > 0:
        start = time.perf_counter()
        conn = psycopg.connect(dsn, row_factory=tuple_row)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms >= threshold_ms:
            try:
                print(f"[DB][SLOW][connect] {elapsed_ms:.1f}ms")
            except Exception:
                pass
        return conn
    return psycopg.connect(dsn, row_factory=tuple_row)


def _acquire_raw_connection():
    if not _pool_enabled():
        return _new_raw_connection()

    with _POOL_LOCK:
        while _POOL_IDLE:
            raw = _POOL_IDLE.pop()
            try:
                if getattr(raw, "closed", False):
                    continue
            except Exception:
                continue
            return raw

    return _new_raw_connection()


def _release_raw_connection(raw):
    if raw is None:
        return

    if not _pool_enabled():
        try:
            raw.close()
        except Exception:
            pass
        return

    try:
        if getattr(raw, "closed", False):
            return
    except Exception:
        return

    # Limpa eventual transacao pendente para o proximo uso.
    try:
        raw.rollback()
    except Exception:
        pass

    with _POOL_LOCK:
        if len(_POOL_IDLE) < _pool_max_size():
            _POOL_IDLE.append(raw)
            return

    try:
        raw.close()
    except Exception:
        pass


def close_connection_pool():
    with _POOL_LOCK:
        conns = list(_POOL_IDLE)
        _POOL_IDLE.clear()
    for raw in conns:
        try:
            raw.close()
        except Exception:
            pass


atexit.register(close_connection_pool)


def connect():
    """
    Conexao de banco compativel com o estilo sqlite3 usado no projeto.
    - placeholders `?` continuam aceitos;
    - fetchone/fetchall retornam tuplas.
    """
    runtime_backend = _get_runtime_backend()
    configured_backend = _configured_db_backend()

    if runtime_backend == "sqlite":
        return _CompatConnection(_new_sqlite_raw_connection(), backend="sqlite")

    if configured_backend == "sqlite":
        _set_runtime_backend("sqlite", "Configuracao MEDCONTRACT_DB_BACKEND=sqlite ativa.")
        return _CompatConnection(_new_sqlite_raw_connection(), backend="sqlite")

    if configured_backend == "auto" and _sqlite_fallback_enabled():
        try:
            conn_info = _build_pg_conn_info()
            if _should_short_circuit_to_sqlite(conn_info):
                host_hint = ",".join(_parse_db_hosts(conn_info.get("host"))) or "localhost"
                port_hint = ",".join(str(p) for p in _parse_db_ports(conn_info.get("port")))
                _set_runtime_backend(
                    "sqlite",
                    f"PostgreSQL local indisponivel em {host_hint}:{port_hint}; fallback para SQLite ativado.",
                )
                return _CompatConnection(_new_sqlite_raw_connection(), backend="sqlite")
        except Exception:
            # Se falhar ao montar DSN/info, seguimos o fluxo normal e deixamos
            # a excecao real de conexao ser tratada abaixo.
            pass

    try:
        raw = _acquire_raw_connection()
    except Exception as exc:
        should_fallback = False
        if configured_backend == "auto" and _sqlite_fallback_enabled() and _is_pg_connect_error(exc):
            try:
                pg_info = _build_pg_conn_info()
                should_fallback = _is_local_db_host(pg_info.get("host"))
            except Exception:
                should_fallback = True

        if should_fallback:
            _set_runtime_backend(
                "sqlite",
                f"Falha ao conectar no PostgreSQL ({exc}); fallback para SQLite ativado.",
            )
            return _CompatConnection(_new_sqlite_raw_connection(), backend="sqlite")
        raise

    _set_runtime_backend("postgres")
    if _pool_enabled():
        return _CompatConnection(raw, release_fn=_release_raw_connection, backend="postgres")
    return _CompatConnection(raw, backend="postgres")


# =========================
# HELPERS
# =========================
def _safe_str(v, default=""):
    if v is None:
        return default
    return str(v)


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_money_float(v, default=0.0):
    if v is None:
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)

    txt = _safe_str(v).strip()
    if not txt:
        return float(default)

    txt = txt.replace("R$", "").replace("r$", "").replace(" ", "")
    if not txt:
        return float(default)

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
        return float(default)


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return int(default)


_PLANOS_META_KEY = "planos_precos_v1"
_DEFAULT_PLANOS_CONFIG = {
    "Classic": {"base": 80.0, "dep": 20.0},
    "Master": {"base": 100.0, "dep": 40.0},
}


def _default_planos_config() -> dict:
    return {
        nome: {
            "base": float(cfg.get("base", 0.0) or 0.0),
            "dep": float(cfg.get("dep", 0.0) or 0.0),
        }
        for nome, cfg in _DEFAULT_PLANOS_CONFIG.items()
    }


def _ensure_meta_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medcontract_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)


def _resolve_reajuste_plano(plano: str) -> tuple[str | None, str]:
    txt = _safe_str(plano, "").strip().lower()
    if txt in {"", "todos", "todas", "all"}:
        return None, "Todos os planos"
    if txt == "classic":
        return "classic", "Classic"
    if txt == "master":
        return "master", "Master"
    raise ValueError("Plano inválido. Use: todos, Classic ou Master.")


def _build_reajuste_where(plano_key: str | None, somente_ativos: bool) -> tuple[str, list]:
    where = ["valor_mensal >= 0"]
    params: list = []
    if bool(somente_ativos):
        where.append("status = 'ativo'")
    if plano_key is not None:
        where.append("LOWER(COALESCE(plano, '')) = ?")
        params.append(plano_key)
    return f"WHERE {' AND '.join(where)}", params


def _normalize_cliente_ids(cliente_ids) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for raw in (cliente_ids or []):
        try:
            cid = int(raw)
        except Exception:
            continue
        if cid <= 0 or cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)
    return ids


def _build_reajuste_ids_where(cliente_ids, somente_ativos: bool) -> tuple[str, list]:
    ids = _normalize_cliente_ids(cliente_ids)
    if not ids:
        raise ValueError("Selecione ao menos um cliente para reajuste.")
    placeholders = ", ".join("?" for _ in ids)
    where = [f"id IN ({placeholders})", "valor_mensal >= 0"]
    params: list = list(ids)
    if bool(somente_ativos):
        where.append("status = 'ativo'")
    return f"WHERE {' AND '.join(where)}", params


def _read_planos_config_from_cursor(cursor) -> dict:
    _ensure_meta_table(cursor)
    cfg = _default_planos_config()

    cursor.execute("SELECT value FROM medcontract_meta WHERE key = ? LIMIT 1", (_PLANOS_META_KEY,))
    row = cursor.fetchone()
    if not row:
        return cfg

    try:
        raw = json.loads(_safe_str(row[0], ""))
    except Exception:
        return cfg
    if not isinstance(raw, dict):
        return cfg

    for nome in cfg.keys():
        item = raw.get(nome)
        if not isinstance(item, dict):
            item = raw.get(nome.lower())
        if not isinstance(item, dict):
            continue
        cfg[nome]["base"] = max(0.0, _safe_float(item.get("base"), cfg[nome]["base"]))
        cfg[nome]["dep"] = max(0.0, _safe_float(item.get("dep"), cfg[nome]["dep"]))
    return cfg


def _write_planos_config_from_cursor(cursor, planos: dict):
    _ensure_meta_table(cursor)
    cfg = _default_planos_config()
    if isinstance(planos, dict):
        for nome in cfg.keys():
            item = planos.get(nome)
            if not isinstance(item, dict):
                item = planos.get(nome.lower())
            if not isinstance(item, dict):
                continue
            cfg[nome]["base"] = round(max(0.0, _safe_float(item.get("base"), cfg[nome]["base"])), 2)
            cfg[nome]["dep"] = round(max(0.0, _safe_float(item.get("dep"), cfg[nome]["dep"])), 2)

    payload = json.dumps(cfg, ensure_ascii=False)
    cursor.execute("""
        INSERT INTO medcontract_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (_PLANOS_META_KEY, payload))
    return cfg


def _preview_reajuste_planos_cursor(cursor, percentual: float, plano: str, somente_ativos: bool) -> dict:
    pct = _safe_float(percentual, 0.0)
    if abs(pct) < 1e-9:
        raise ValueError("Informe um percentual diferente de zero.")
    fator = 1.0 + (pct / 100.0)
    if fator <= 0:
        raise ValueError("Percentual muito negativo. O resultado deve ser maior que zero.")

    plano_key, plano_label = _resolve_reajuste_plano(plano)
    where_sql, where_params = _build_reajuste_where(plano_key, somente_ativos)

    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS qtd,
            COALESCE(SUM(valor_mensal), 0) AS soma
        FROM clientes
        {where_sql}
        """,
        tuple(where_params),
    )
    row = cursor.fetchone() or (0, 0)
    qtd = int(row[0] or 0)
    soma_atual = float(row[1] or 0.0)
    soma_reajustada = round(soma_atual * fator, 2)
    diferenca_total = round(soma_reajustada - soma_atual, 2)

    return {
        "percentual": round(pct, 4),
        "fator": fator,
        "plano_key": "todos" if plano_key is None else plano_key,
        "plano_label": plano_label,
        "somente_ativos": bool(somente_ativos),
        "clientes_afetados": qtd,
        "soma_atual": round(soma_atual, 2),
        "soma_reajustada": soma_reajustada,
        "diferenca_total": diferenca_total,
    }


def _preview_reajuste_clientes_selecionados_cursor(
    cursor,
    percentual: float,
    cliente_ids,
    somente_ativos: bool,
) -> dict:
    pct = _safe_float(percentual, 0.0)
    if abs(pct) < 1e-9:
        raise ValueError("Informe um percentual diferente de zero.")
    fator = 1.0 + (pct / 100.0)
    if fator <= 0:
        raise ValueError("Percentual muito negativo. O resultado deve ser maior que zero.")

    ids = _normalize_cliente_ids(cliente_ids)
    where_sql, where_params = _build_reajuste_ids_where(ids, somente_ativos)

    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS qtd,
            COALESCE(SUM(valor_mensal), 0) AS soma
        FROM clientes
        {where_sql}
        """,
        tuple(where_params),
    )
    row = cursor.fetchone() or (0, 0)
    qtd = int(row[0] or 0)
    soma_atual = float(row[1] or 0.0)
    soma_reajustada = round(soma_atual * fator, 2)
    diferenca_total = round(soma_reajustada - soma_atual, 2)

    return {
        "modo": "selecionados",
        "percentual": round(pct, 4),
        "fator": fator,
        "somente_ativos": bool(somente_ativos),
        "cliente_ids": ids,
        "clientes_solicitados": len(ids),
        "clientes_afetados": qtd,
        "soma_atual": round(soma_atual, 2),
        "soma_reajustada": soma_reajustada,
        "diferenca_total": diferenca_total,
    }


def _preview_reajuste_cliente_especifico_cursor(cursor, cliente_id: int, novo_valor: float) -> dict:
    cid = _safe_int(cliente_id, 0)
    if cid <= 0:
        raise ValueError("Cliente inválido para reajuste individual.")

    novo = round(_safe_float(novo_valor, -1.0), 2)
    if novo < 0:
        raise ValueError("Informe um novo valor mensal válido (>= 0).")

    cursor.execute(
        """
        SELECT id, nome, status, COALESCE(valor_mensal, 0)
        FROM clientes
        WHERE id = ?
        LIMIT 1
        """,
        (cid,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError("Cliente não encontrado para reajuste individual.")

    valor_atual = round(_safe_float(row[3], 0.0), 2)
    diferenca = round(novo - valor_atual, 2)
    if abs(valor_atual) > 1e-9:
        percentual_estimado = round(((novo / valor_atual) - 1.0) * 100.0, 4)
    else:
        percentual_estimado = 0.0 if abs(novo) < 1e-9 else 100.0

    return {
        "modo": "individual",
        "cliente_id": int(row[0] or cid),
        "cliente_nome": _safe_str(row[1], f"MAT {cid}"),
        "status": _safe_str(row[2], "").strip().lower(),
        "valor_atual": valor_atual,
        "novo_valor": novo,
        "percentual_estimado": percentual_estimado,
        "clientes_afetados": 1,
        "soma_atual": valor_atual,
        "soma_reajustada": novo,
        "diferenca_total": diferenca,
    }


def _normalize_cpf(cpf: str) -> str:
    return "".join(ch for ch in _safe_str(cpf, "").strip() if ch.isdigit())


def _normalize_cnpj(cnpj: str) -> str:
    return "".join(ch for ch in _safe_str(cnpj, "").strip() if ch.isdigit())


def _is_valid_cnpj(cnpj: str) -> bool:
    digits = _normalize_cnpj(cnpj)
    if len(digits) != 14:
        return False
    if digits == digits[0] * 14:
        return False

    def _calc_digit(base: str, weights: list[int]) -> int:
        total = sum(int(num) * weight for num, weight in zip(base, weights))
        mod = total % 11
        return 0 if mod < 2 else 11 - mod

    d1 = _calc_digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _calc_digit(digits[:12] + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == f"{d1}{d2}"


def _build_clientes_where_clause(search: str = "", status: str = "",
                                 pagamento: str = "", table_alias: str = "c"):
    """
    Monta WHERE/params para filtros de listagem de clientes.
    Compatível com buscas por MAT, nome e CPF.
    """
    alias = (table_alias or "c").strip()
    where = []
    params = []

    search_txt = _safe_str(search, "").strip()
    if search_txt:
        term = f"%{search_txt}%"
        search_digits = _normalize_cpf(search_txt)
        if search_digits:
            where.append(
                f"(CAST({alias}.id AS TEXT) LIKE ? "
                f"OR {alias}.nome ILIKE ? "
                f"OR {alias}.cpf LIKE ? "
                f"OR {alias}.cpf_norm LIKE ?)"
            )
            params.extend([term, term, term, f"%{search_digits}%"])
        else:
            where.append(
                f"(CAST({alias}.id AS TEXT) LIKE ? "
                f"OR {alias}.nome ILIKE ? "
                f"OR {alias}.cpf LIKE ?)"
            )
            params.extend([term, term, term])

    status_norm = _safe_str(status, "").strip().lower()
    if status_norm in {"ativo", "inativo"}:
        where.append(f"{alias}.status = ?")
        params.append(status_norm)

    pag_norm = _safe_str(pagamento, "").strip().lower()
    if pag_norm in {"em_dia", "atrasado"}:
        where.append(f"{alias}.pagamento_status = ?")
        params.append(pag_norm)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return where_sql, params


def _build_empresas_where_clause(
    search: str = "",
    forma_pagamento: str = "",
    status_pagamento: str = "",
    table_alias: str = "e",
):
    alias = (table_alias or "e").strip()
    where = []
    params = []

    search_txt = _safe_str(search, "").strip()
    if search_txt:
        term = f"%{search_txt}%"
        digits = _normalize_cnpj(search_txt)
        if digits:
            if len(digits) == 14:
                where.append(
                    f"({alias}.nome ILIKE ? "
                    f"OR {alias}.cnpj ILIKE ? "
                    f"OR {alias}.cnpj_norm = ?)"
                )
                params.extend([term, term, digits])
            else:
                where.append(
                    f"({alias}.nome ILIKE ? "
                    f"OR {alias}.cnpj ILIKE ? "
                    f"OR {alias}.cnpj_norm LIKE ?)"
                )
                params.extend([term, term, f"%{digits}%"])
        else:
            where.append(f"({alias}.nome ILIKE ? OR {alias}.cnpj ILIKE ?)")
            params.extend([term, term])

    forma = _safe_str(forma_pagamento, "").strip().lower()
    if forma in {"pix", "boleto", "recepcao"}:
        where.append(f"{alias}.forma_pagamento = ?")
        params.append(forma)

    status = _safe_str(status_pagamento, "").strip().lower()
    if status in {"em_dia", "pendente", "inadimplente"}:
        where.append(f"{alias}.status_pagamento = ?")
        params.append(status)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return where_sql, params


def _get_user_version(cursor) -> int:
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS medcontract_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("SELECT value FROM medcontract_meta WHERE key = 'schema_version' LIMIT 1")
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _set_user_version(cursor, version: int):
    try:
        cursor.execute("""
            INSERT INTO medcontract_meta (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (str(int(version)),))
    except Exception:
        pass


def _current_month_ref() -> str:
    return datetime.now().strftime("%Y-%m")


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


_CONTAS_STATUS = {"pendente", "paga", "vencida"}
_CONTAS_CATEGORIAS = {
    "aluguel",
    "energia",
    "agua",
    "folha de pagamento",
    "impostos",
    "servicos de ti",
    "laboratorio",
    "outros",
}
_CONTAS_FORMAS = {"pix", "boleto", "debito", "credito", "outro"}
_CONTAS_PERIODICIDADES = {"mensal": 1, "bimestral": 2, "trimestral": 3, "anual": 12}


def _month_ref_to_br(mes_ref: str) -> str:
    ref = _safe_str(mes_ref).strip()
    if len(ref) == 7 and ref[4] == "-":
        try:
            year = ref[:4]
            month = int(ref[5:7])
            meses = {
                1: "JAN", 2: "FEV", 3: "MAR", 4: "ABR", 5: "MAI", 6: "JUN",
                7: "JUL", 8: "AGO", 9: "SET", 10: "OUT", 11: "NOV", 12: "DEZ",
            }
            return f"{meses.get(month, ref[5:7])}/{year}"
        except Exception:
            return ref
    return ref


def _normalize_conta_status(value: str, default: str = "Pendente") -> str:
    txt = _safe_str(value, "").strip().lower()
    if txt in {"paga", "pago", "pago(a)", "paid"}:
        return "Paga"
    if txt in {"vencida", "vencido", "atrasada", "atrasado", "overdue"}:
        return "Vencida"
    if txt in {"pendente", "aberta", "open"}:
        return "Pendente"
    return default


def _normalize_conta_categoria(value: str) -> str:
    txt = _safe_str(value, "").strip()
    low = txt.lower()
    if low in _CONTAS_CATEGORIAS:
        return txt.title() if low != "agua" else "Água"
    return txt or "Outros"


def _normalize_conta_forma_pagamento(value: str) -> str:
    txt = _safe_str(value, "").strip().lower()
    if txt in _CONTAS_FORMAS:
        if txt == "debito":
            return "Débito"
        if txt == "credito":
            return "Crédito"
        return txt.title()
    return "Outro"


def _normalize_conta_periodicidade(value: str) -> str:
    txt = _safe_str(value, "").strip().lower()
    if txt in _CONTAS_PERIODICIDADES:
        return txt.title()
    return ""


def _periodicidade_to_months(value: str) -> int:
    return int(_CONTAS_PERIODICIDADES.get(_safe_str(value, "").strip().lower(), 0) or 0)


def _add_months_to_date(date_iso: str, months: int) -> str:
    if months <= 0:
        return _safe_date_iso(date_iso)
    iso = _safe_date_iso(date_iso)
    if not iso:
        return ""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%d").date()
        year = dt.year + ((dt.month - 1 + months) // 12)
        month = ((dt.month - 1 + months) % 12) + 1
        day = min(dt.day, monthrange(year, month)[1])
        return date(year, month, day).strftime("%Y-%m-%d")
    except Exception:
        return iso


def _to_conta_competencia(date_iso: str) -> str:
    iso = _safe_date_iso(date_iso)
    if not iso:
        return _month_ref_to_br(_current_month_ref())
    return _month_ref_to_br(iso[:7])


def _conta_status_from_row(row: dict) -> str:
    status = _normalize_conta_status(row.get("status"), default="Pendente")
    if status != "Pendente":
        return status
    venc = _safe_date_iso(row.get("data_vencimento"))
    if venc and venc < _today_iso():
        return "Vencida"
    return "Pendente"


def _safe_date_iso(v) -> str:
    s = _safe_str(v, "").strip()
    if not s:
        return ""
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        return ""


def _age_from_iso(date_iso: str, default: int = 0) -> int:
    iso = _safe_date_iso(date_iso)
    if not iso:
        return _safe_int(default, 0)
    try:
        born = datetime.strptime(iso, "%Y-%m-%d").date()
        today = datetime.now().date()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return max(age, 0)
    except Exception:
        return _safe_int(default, 0)


# =========================
# HELPERS MIGRAÃ‡ÃƒO
# =========================
def _table_exists(cursor, table_name: str) -> bool:
    try:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ?
            LIMIT 1
            """,
            (table_name,),
        )
        return cursor.fetchone() is not None
    except Exception:
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        )
        return cursor.fetchone() is not None


def _table_columns(cursor, table_name: str) -> set[str]:
    try:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ?
            """,
            (table_name,),
        )
        return {row[0] for row in cursor.fetchall()}
    except Exception:
        cursor.execute(f"PRAGMA table_info({table_name})")
        # PRAGMA table_info retorna: cid, name, type, notnull, dflt_value, pk
        return {row[1] for row in cursor.fetchall()}


def _constraint_exists(cursor, table_name: str, constraint_name: str) -> bool:
    try:
        cursor.execute(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND t.relname = ?
              AND c.conname = ?
            LIMIT 1
            """,
            (table_name, constraint_name),
        )
        return cursor.fetchone() is not None
    except Exception:
        return False


def _safe_add_column(cursor, table: str, col: str, ddl: str):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    except DuplicateColumn:
        return
    except Exception as e:
        msg = str(e).lower()
        if "duplicate column" in msg or "already exists" in msg:
            return
        raise


def _ensure_clientes_columns(cursor):
    if not _table_exists(cursor, "clientes"):
        return

    cols = _table_columns(cursor, "clientes")

    if "data_nascimento" not in cols:
        _safe_add_column(cursor, "clientes", "data_nascimento", "TEXT")
    if "cep" not in cols:
        _safe_add_column(cursor, "clientes", "cep", "TEXT")
    if "endereco" not in cols:
        _safe_add_column(cursor, "clientes", "endereco", "TEXT")
    if "plano" not in cols:
        _safe_add_column(cursor, "clientes", "plano", "TEXT")
    if "dependentes" not in cols:
        _safe_add_column(cursor, "clientes", "dependentes", "INTEGER NOT NULL DEFAULT 0")
    if "vencimento_dia" not in cols:
        _safe_add_column(cursor, "clientes", "vencimento_dia", "INTEGER NOT NULL DEFAULT 10")
    if "forma_pagamento" not in cols:
        _safe_add_column(cursor, "clientes", "forma_pagamento", "TEXT")
    if "cpf_norm" not in cols:
        _safe_add_column(cursor, "clientes", "cpf_norm", "TEXT")


def _ensure_dependentes_columns(cursor):
    if not _table_exists(cursor, "dependentes"):
        return
    cols = _table_columns(cursor, "dependentes")
    if "cpf_norm" not in cols:
        _safe_add_column(cursor, "dependentes", "cpf_norm", "TEXT")
    if "data_nascimento" not in cols:
        _safe_add_column(cursor, "dependentes", "data_nascimento", "TEXT")


def _ensure_empresas_columns(cursor):
    if not _table_exists(cursor, "empresas"):
        return
    cols = _table_columns(cursor, "empresas")
    if "cnpj_norm" not in cols:
        _safe_add_column(cursor, "empresas", "cnpj_norm", "TEXT")


def _ensure_contas_pagar_columns(cursor):
    if not _table_exists(cursor, "contas_pagar"):
        return
    cols = _table_columns(cursor, "contas_pagar")
    required = {
        "descricao": "TEXT",
        "categoria": "TEXT",
        "fornecedor": "TEXT",
        "valor_previsto": "REAL",
        "data_vencimento": "TEXT",
        "data_competencia": "TEXT",
        "forma_pagamento": "TEXT",
        "status": "TEXT",
        "recorrente": "INTEGER NOT NULL DEFAULT 0",
        "periodicidade": "TEXT",
        "parcela_atual": "INTEGER",
        "total_parcelas": "INTEGER",
        "data_pagamento_real": "TEXT",
        "valor_pago": "REAL",
        "observacoes": "TEXT",
        "criado_em": "TEXT",
        "atualizado_em": "TEXT",
    }
    for col, ddl in required.items():
        if col not in cols:
            _safe_add_column(cursor, "contas_pagar", col, ddl)


def _backfill_cpf_norm(cursor):
    try:
        cursor.execute("SELECT id, cpf FROM clientes")
        clientes = cursor.fetchall() or []
        for cid, cpf in clientes:
            cursor.execute(
                "UPDATE clientes SET cpf_norm=? WHERE id=?",
                (_normalize_cpf(cpf), int(cid)),
            )
    except Exception:
        pass

    try:
        cursor.execute("SELECT id, cpf FROM dependentes")
        deps = cursor.fetchall() or []
        for did, cpf in deps:
            cursor.execute(
                "UPDATE dependentes SET cpf_norm=? WHERE id=?",
                (_normalize_cpf(cpf), int(did)),
            )
    except Exception:
        pass


def _backfill_empresas_cnpj_norm(cursor):
    try:
        cursor.execute(
            """
            UPDATE empresas
            SET cnpj_norm = regexp_replace(COALESCE(cnpj, ''), '[^0-9]', '', 'g')
            WHERE COALESCE(cnpj_norm, '') <> regexp_replace(COALESCE(cnpj, ''), '[^0-9]', '', 'g')
            """
        )
        return
    except Exception:
        # Fallback para SQLite (sem regexp_replace nativo).
        pass

    try:
        cursor.execute("SELECT id, cnpj FROM empresas")
        rows = cursor.fetchall() or []
        for rid, cnpj in rows:
            cursor.execute(
                "UPDATE empresas SET cnpj_norm=? WHERE id=?",
                (_normalize_cnpj(cnpj), int(rid)),
            )
    except Exception:
        pass


def _ensure_indexes(cursor):
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dependentes_cliente
        ON dependentes (cliente_id)
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pagamentos_cliente_mes
        ON pagamentos (cliente_id, mes_referencia)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_nome
        ON clientes (nome)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_plano
        ON clientes (plano)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_pagamento_status
        ON clientes (pagamento_status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pagamentos_mes
        ON pagamentos (mes_referencia)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_cpf
        ON clientes (cpf)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_status
        ON clientes (status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_nome_lower
        ON clientes (LOWER(nome))
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_data_inicio
        ON clientes (data_inicio)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pagamentos_mes_data
        ON pagamentos (mes_referencia, data_pagamento DESC, id DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pagamentos_data_pagamento
        ON pagamentos (data_pagamento)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pagamentos_cliente_id_desc
        ON pagamentos (cliente_id, id DESC)
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pagamentos_empresas_empresa_mes
        ON pagamentos_empresas (empresa_id, mes_referencia)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pagamentos_empresas_mes
        ON pagamentos_empresas (mes_referencia)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pagamentos_empresas_empresa_id_desc
        ON pagamentos_empresas (empresa_id, id DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_nome
        ON empresas (nome)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_nome_lower
        ON empresas (LOWER(nome))
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_cnpj
        ON empresas (cnpj)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_cnpj_norm
        ON empresas (cnpj_norm)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_nome_lower_id
        ON empresas (LOWER(nome), id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_forma_status_nome_id
        ON empresas (forma_pagamento, status_pagamento, LOWER(nome), id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_forma_pagamento
        ON empresas (forma_pagamento)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_status_pagamento
        ON empresas (status_pagamento)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_empresas_data_cadastro
        ON empresas (data_cadastro)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contas_pagar_vencimento
        ON contas_pagar (data_vencimento)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contas_pagar_competencia
        ON contas_pagar (data_competencia)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contas_pagar_status
        ON contas_pagar (status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contas_pagar_categoria
        ON contas_pagar (categoria)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contas_pagar_fornecedor_lower
        ON contas_pagar (LOWER(fornecedor))
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contas_pagar_descricao_lower
        ON contas_pagar (LOWER(descricao))
    """)

    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_cpf_norm_uniq
            ON clientes (cpf_norm)
            WHERE cpf_norm IS NOT NULL AND cpf_norm <> ''
        """)
    except Exception:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_clientes_cpf_norm
            ON clientes (cpf_norm)
        """)

    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_dependentes_cliente_cpf_norm_uniq
            ON dependentes (cliente_id, cpf_norm)
            WHERE cpf_norm IS NOT NULL AND cpf_norm <> ''
        """)
    except Exception:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dependentes_cliente_cpf_norm
            ON dependentes (cliente_id, cpf_norm)
        """)

    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_cnpj_norm_uniq
            ON empresas (cnpj_norm)
            WHERE cnpj_norm IS NOT NULL AND cnpj_norm <> ''
        """)
    except Exception:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_empresas_cnpj_norm_fallback
            ON empresas (cnpj_norm)
        """)


def _ensure_triggers(cursor):
    if _get_runtime_backend() == "sqlite":
        _ensure_sqlite_triggers(cursor)
        return

    # MantÃ©m contagem de dependentes sincronizada.
    cursor.execute("""
        CREATE OR REPLACE FUNCTION medcontract_sync_dependentes_count()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE clientes
                SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = NEW.cliente_id)
                WHERE id = NEW.cliente_id;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE clientes
                SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = OLD.cliente_id)
                WHERE id = OLD.cliente_id;
                RETURN OLD;
            ELSE
                UPDATE clientes
                SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = OLD.cliente_id)
                WHERE id = OLD.cliente_id;
                UPDATE clientes
                SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = NEW.cliente_id)
                WHERE id = NEW.cliente_id;
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql
    """)

    cursor.execute("DROP TRIGGER IF EXISTS trg_dependentes_count_ai ON dependentes")
    cursor.execute("""
        CREATE TRIGGER trg_dependentes_count_ai
        AFTER INSERT ON dependentes
        FOR EACH ROW
        EXECUTE FUNCTION medcontract_sync_dependentes_count()
    """)

    cursor.execute("DROP TRIGGER IF EXISTS trg_dependentes_count_ad ON dependentes")
    cursor.execute("""
        CREATE TRIGGER trg_dependentes_count_ad
        AFTER DELETE ON dependentes
        FOR EACH ROW
        EXECUTE FUNCTION medcontract_sync_dependentes_count()
    """)

    cursor.execute("DROP TRIGGER IF EXISTS trg_dependentes_count_au ON dependentes")
    cursor.execute("""
        CREATE TRIGGER trg_dependentes_count_au
        AFTER UPDATE OF cliente_id ON dependentes
        FOR EACH ROW
        EXECUTE FUNCTION medcontract_sync_dependentes_count()
    """)


def _ensure_sqlite_triggers(cursor):
    cursor.execute("DROP TRIGGER IF EXISTS trg_dependentes_count_ai")
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_dependentes_count_ai
        AFTER INSERT ON dependentes
        FOR EACH ROW
        BEGIN
            UPDATE clientes
            SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = NEW.cliente_id)
            WHERE id = NEW.cliente_id;
        END
    """)

    cursor.execute("DROP TRIGGER IF EXISTS trg_dependentes_count_ad")
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_dependentes_count_ad
        AFTER DELETE ON dependentes
        FOR EACH ROW
        BEGIN
            UPDATE clientes
            SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = OLD.cliente_id)
            WHERE id = OLD.cliente_id;
        END
    """)

    cursor.execute("DROP TRIGGER IF EXISTS trg_dependentes_count_au")
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_dependentes_count_au
        AFTER UPDATE OF cliente_id ON dependentes
        FOR EACH ROW
        BEGIN
            UPDATE clientes
            SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = OLD.cliente_id)
            WHERE id = OLD.cliente_id;
            UPDATE clientes
            SET dependentes = (SELECT COUNT(*) FROM dependentes WHERE cliente_id = NEW.cliente_id)
            WHERE id = NEW.cliente_id;
        END
    """)


def _sync_dependentes_count(cursor):
    cursor.execute("""
        UPDATE clientes
        SET dependentes = (
            SELECT COUNT(*) FROM dependentes d WHERE d.cliente_id = clientes.id
        )
    """)


def _sync_id_sequence(cursor, table_name: str, col_name: str = "id"):
    cursor.execute(f"""
        WITH seq_data AS (
            SELECT COALESCE(MAX({col_name}), 0) AS max_id
            FROM {table_name}
        )
        SELECT setval(
            pg_get_serial_sequence('{table_name}', '{col_name}'),
            (SELECT CASE WHEN max_id > 0 THEN max_id ELSE 1 END FROM seq_data),
            (SELECT max_id > 0 FROM seq_data)
        )
    """)


def _prune_old_backups(backup_dir_path: Path, keep_last: int | None):
    if keep_last is None:
        return
    keep = max(1, int(keep_last))
    files = sorted(
        [p for p in backup_dir_path.glob("medcontract_backup_*.*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink(missing_ok=True)
        except Exception:
            pass


def _build_fernet_key(raw_key: str) -> bytes:
    token = _safe_str(raw_key).strip()
    if not token:
        raise ValueError("Chave de backup vazia.")
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8"))
        if len(decoded) == 32:
            return token.encode("utf-8")
    except Exception:
        pass
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt_backup_file_if_enabled(path: Path) -> Path:
    raw_key = _safe_str(os.getenv("MEDCONTRACT_BACKUP_ENCRYPTION_KEY"), "").strip()
    if not raw_key:
        return path

    try:
        from cryptography.fernet import Fernet  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Criptografia de backup habilitada, mas dependência ausente. "
            "Instale com: pip install cryptography"
        ) from exc

    key = _build_fernet_key(raw_key)
    fernet = Fernet(key)
    src_bytes = path.read_bytes()
    encrypted = fernet.encrypt(src_bytes)

    dst = path.with_suffix(path.suffix + ".enc")
    dst.write_bytes(encrypted)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        os.chmod(dst, 0o600)
    except Exception:
        pass
    return dst


def _create_tables_sqlite(cursor):
    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password BLOB NOT NULL,
            nivel TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cpf TEXT UNIQUE NOT NULL,
            cpf_norm TEXT,
            telefone TEXT NOT NULL,
            email TEXT NOT NULL,
            data_inicio TEXT NOT NULL,
            valor_mensal REAL NOT NULL CHECK (valor_mensal >= 0),
            status TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
            pagamento_status TEXT NOT NULL DEFAULT 'em_dia' CHECK (pagamento_status IN ('em_dia', 'atrasado')),
            observacoes TEXT,
            data_nascimento TEXT,
            cep TEXT,
            endereco TEXT,
            plano TEXT,
            dependentes INTEGER NOT NULL DEFAULT 0 CHECK (dependentes >= 0),
            vencimento_dia INTEGER NOT NULL DEFAULT 10 CHECK (vencimento_dia BETWEEN 1 AND 31),
            forma_pagamento TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dependentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            cpf TEXT NOT NULL,
            cpf_norm TEXT,
            data_nascimento TEXT,
            idade INTEGER NOT NULL CHECK (idade >= 0),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
            UNIQUE (cliente_id, cpf)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            mes_referencia TEXT NOT NULL,
            data_pagamento TEXT NOT NULL,
            valor_pago REAL NOT NULL CHECK (valor_pago > 0),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj TEXT UNIQUE NOT NULL,
            cnpj_norm TEXT,
            nome TEXT NOT NULL,
            telefone TEXT NOT NULL,
            email TEXT NOT NULL,
            logradouro TEXT NOT NULL,
            numero TEXT NOT NULL,
            bairro TEXT NOT NULL,
            cep TEXT NOT NULL,
            cidade TEXT NOT NULL,
            estado TEXT NOT NULL,
            forma_pagamento TEXT NOT NULL CHECK (forma_pagamento IN ('pix', 'boleto', 'recepcao')),
            status_pagamento TEXT NOT NULL CHECK (status_pagamento IN ('em_dia', 'pendente', 'inadimplente')),
            dia_vencimento INTEGER NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 31),
            valor_mensal TEXT NOT NULL,
            data_cadastro TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pagamentos_empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL,
            mes_referencia TEXT NOT NULL,
            data_pagamento TEXT NOT NULL,
            valor_pago REAL NOT NULL CHECK (valor_pago > 0),
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contas_pagar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            categoria TEXT NOT NULL DEFAULT 'Outros',
            fornecedor TEXT,
            valor_previsto REAL NOT NULL CHECK (valor_previsto >= 0),
            data_vencimento TEXT NOT NULL,
            data_competencia TEXT NOT NULL,
            forma_pagamento TEXT,
            status TEXT NOT NULL DEFAULT 'Pendente' CHECK (status IN ('Pendente', 'Paga', 'Vencida')),
            recorrente INTEGER NOT NULL DEFAULT 0,
            periodicidade TEXT,
            parcela_atual INTEGER,
            total_parcelas INTEGER,
            data_pagamento_real TEXT,
            valor_pago REAL,
            observacoes TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now')),
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    _ensure_clientes_columns(cursor)
    _ensure_dependentes_columns(cursor)
    _ensure_empresas_columns(cursor)
    _ensure_contas_pagar_columns(cursor)
    _backfill_cpf_norm(cursor)
    _backfill_empresas_cnpj_norm(cursor)
    _ensure_indexes(cursor)
    _ensure_sqlite_triggers(cursor)
    _sync_dependentes_count(cursor)


# =========================
# CRIAÃ‡ÃƒO DE TABELAS
# =========================
def create_tables():
    conn = connect()
    try:
        cursor = conn.cursor()
        backend = getattr(conn, "backend", "postgres")

        if backend == "sqlite":
            current_version = _get_user_version(cursor)
            _create_tables_sqlite(cursor)
            if current_version < SCHEMA_VERSION:
                _set_user_version(cursor, SCHEMA_VERSION)
            conn.commit()
            return

        current_version = _get_user_version(cursor)
        force_schema_check = _env_flag("MEDCONTRACT_FORCE_SCHEMA_CHECK", False)
        schema_ready = (
            current_version >= SCHEMA_VERSION
            and _table_exists(cursor, "usuarios")
            and _table_exists(cursor, "clientes")
            and _table_exists(cursor, "dependentes")
            and _table_exists(cursor, "pagamentos")
            and _table_exists(cursor, "pagamentos_empresas")
            and _table_exists(cursor, "empresas")
            and _table_exists(cursor, "contas_pagar")
        )
        if schema_ready and not force_schema_check:
            return

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id BIGSERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password BYTEA NOT NULL,
                nivel TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id BIGSERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                cpf TEXT UNIQUE NOT NULL,
                cpf_norm TEXT,
                telefone TEXT NOT NULL,
                email TEXT NOT NULL,
                data_inicio TEXT NOT NULL,
                valor_mensal DOUBLE PRECISION NOT NULL
                    CONSTRAINT chk_clientes_valor_mensal_nonneg CHECK (valor_mensal >= 0),
                status TEXT NOT NULL DEFAULT 'ativo'
                    CONSTRAINT chk_clientes_status CHECK (status IN ('ativo', 'inativo')),
                pagamento_status TEXT NOT NULL DEFAULT 'em_dia'
                    CONSTRAINT chk_clientes_pagamento_status CHECK (pagamento_status IN ('em_dia', 'atrasado')),
                observacoes TEXT,
                data_nascimento TEXT,
                cep TEXT,
                endereco TEXT,
                plano TEXT,
                dependentes INTEGER NOT NULL DEFAULT 0
                    CONSTRAINT chk_clientes_dependentes_nonneg CHECK (dependentes >= 0),
                vencimento_dia INTEGER NOT NULL DEFAULT 10
                    CONSTRAINT chk_clientes_vencimento_range CHECK (vencimento_dia BETWEEN 1 AND 31),
                forma_pagamento TEXT
            )
        """)

        _ensure_clientes_columns(cursor)
        _ensure_dependentes_columns(cursor)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dependentes (
                id BIGSERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                cpf TEXT NOT NULL,
                cpf_norm TEXT,
                data_nascimento TEXT,
                idade INTEGER NOT NULL CHECK (idade >= 0),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
                UNIQUE (cliente_id, cpf)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pagamentos (
                id BIGSERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                mes_referencia TEXT NOT NULL,
                data_pagamento TEXT NOT NULL,
                valor_pago DOUBLE PRECISION NOT NULL CHECK(valor_pago > 0),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS empresas (
                id BIGSERIAL PRIMARY KEY,
                cnpj TEXT UNIQUE NOT NULL,
                cnpj_norm TEXT,
                nome TEXT NOT NULL,
                telefone TEXT NOT NULL,
                email TEXT NOT NULL,
                logradouro TEXT NOT NULL,
                numero TEXT NOT NULL,
                bairro TEXT NOT NULL,
                cep TEXT NOT NULL,
                cidade TEXT NOT NULL,
                estado TEXT NOT NULL,
                forma_pagamento TEXT NOT NULL
                    CONSTRAINT chk_empresas_forma_pagamento
                    CHECK (forma_pagamento IN ('pix', 'boleto', 'recepcao')),
                status_pagamento TEXT NOT NULL
                    CONSTRAINT chk_empresas_status_pagamento
                    CHECK (status_pagamento IN ('em_dia', 'pendente', 'inadimplente')),
                dia_vencimento INTEGER NOT NULL
                    CONSTRAINT chk_empresas_vencimento_range CHECK (dia_vencimento BETWEEN 1 AND 31),
                valor_mensal TEXT NOT NULL,
                data_cadastro TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pagamentos_empresas (
                id BIGSERIAL PRIMARY KEY,
                empresa_id INTEGER NOT NULL,
                mes_referencia TEXT NOT NULL,
                data_pagamento TEXT NOT NULL,
                valor_pago DOUBLE PRECISION NOT NULL CHECK(valor_pago > 0),
                FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contas_pagar (
                id BIGSERIAL PRIMARY KEY,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL DEFAULT 'Outros',
                fornecedor TEXT,
                valor_previsto DOUBLE PRECISION NOT NULL CHECK (valor_previsto >= 0),
                data_vencimento TEXT NOT NULL,
                data_competencia TEXT NOT NULL,
                forma_pagamento TEXT,
                status TEXT NOT NULL DEFAULT 'Pendente'
                    CONSTRAINT chk_contas_pagar_status CHECK (status IN ('Pendente', 'Paga', 'Vencida')),
                recorrente BOOLEAN NOT NULL DEFAULT FALSE,
                periodicidade TEXT,
                parcela_atual INTEGER,
                total_parcelas INTEGER,
                data_pagamento_real TEXT,
                valor_pago DOUBLE PRECISION,
                observacoes TEXT,
                criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        if not _constraint_exists(cursor, "clientes", "chk_clientes_data_inicio_fmt"):
            cursor.execute("""
                ALTER TABLE clientes
                ADD CONSTRAINT chk_clientes_data_inicio_fmt
                CHECK (data_inicio ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
            """)
        if not _constraint_exists(cursor, "pagamentos", "chk_pagamentos_mes_ref_fmt"):
            cursor.execute("""
                ALTER TABLE pagamentos
                ADD CONSTRAINT chk_pagamentos_mes_ref_fmt
                CHECK (mes_referencia ~ '^[0-9]{4}-[0-9]{2}$')
            """)
        if not _constraint_exists(cursor, "pagamentos", "chk_pagamentos_data_fmt"):
            cursor.execute("""
                ALTER TABLE pagamentos
                ADD CONSTRAINT chk_pagamentos_data_fmt
                CHECK (data_pagamento ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
            """)
        if not _constraint_exists(cursor, "pagamentos_empresas", "chk_pagamentos_empresas_mes_ref_fmt"):
            cursor.execute("""
                ALTER TABLE pagamentos_empresas
                ADD CONSTRAINT chk_pagamentos_empresas_mes_ref_fmt
                CHECK (mes_referencia ~ '^[0-9]{4}-[0-9]{2}$')
            """)
        if not _constraint_exists(cursor, "pagamentos_empresas", "chk_pagamentos_empresas_data_fmt"):
            cursor.execute("""
                ALTER TABLE pagamentos_empresas
                ADD CONSTRAINT chk_pagamentos_empresas_data_fmt
                CHECK (data_pagamento ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
            """)

        _ensure_empresas_columns(cursor)
        _ensure_contas_pagar_columns(cursor)
        _backfill_cpf_norm(cursor)
        _backfill_empresas_cnpj_norm(cursor)
        _ensure_indexes(cursor)
        _ensure_triggers(cursor)
        _sync_dependentes_count(cursor)
        for table_name in ("usuarios", "clientes", "dependentes", "pagamentos", "pagamentos_empresas", "empresas", "contas_pagar"):
            try:
                _sync_id_sequence(cursor, table_name)
            except Exception:
                pass
        if current_version < SCHEMA_VERSION:
            _set_user_version(cursor, SCHEMA_VERSION)
        conn.commit()
    finally:
        conn.close()

    if _env_flag("MEDCONTRACT_AUTO_MIGRATE_SQLITE", False):
        try:
            ok, msg = migrate_sqlite_to_postgres_if_needed()
            print(msg if msg else ("Migracao automatica concluida." if ok else "Migracao automatica nao executada."))
        except Exception as e:
            print("Falha na migracao automatica SQLite->PostgreSQL:", e)


# =========================
# ADMIN PADRÃƒO
# =========================
def _default_admin_user() -> str:
    return (os.getenv("MEDCONTRACT_DEFAULT_ADMIN_USER") or "admin").strip()


def _is_placeholder_secret(value: str) -> bool:
    txt = _safe_str(value).strip().upper()
    if not txt:
        return True
    return txt.startswith("TROQUE_") or txt.startswith("DEFINA_") or "CHANGE_THIS" in txt


def _bootstrap_user_specs() -> list[tuple[str, str, str]]:
    specs: list[tuple[str, str, str]] = []

    admin_user = _default_admin_user()
    admin_pwd = (os.getenv("MEDCONTRACT_DEFAULT_ADMIN_PASSWORD") or "").strip()
    if admin_user and not _is_placeholder_secret(admin_pwd):
        specs.append((admin_user, admin_pwd, "admin"))

    recepcao_user = (os.getenv("MEDCONTRACT_DEFAULT_RECEPCAO_USER") or "recepcao").strip()
    recepcao_pwd = (os.getenv("MEDCONTRACT_DEFAULT_RECEPCAO_PASSWORD") or "").strip()
    if recepcao_user and not _is_placeholder_secret(recepcao_pwd):
        specs.append((recepcao_user, recepcao_pwd, "recepcao"))

    return specs


def create_default_admin():
    create_default_users(required_if_empty=False)


def create_default_recepcao():
    create_default_users(required_if_empty=False)


def _ensure_default_user(cursor, username: str, password: str, nivel: str) -> bool:
    user = (username or "").strip()
    if not user:
        return False

    cursor.execute(
        "SELECT 1 FROM usuarios WHERE LOWER(username) = LOWER(?) LIMIT 1",
        (user,),
    )
    if cursor.fetchone():
        return False

    pwd = (password or "").strip()
    if not pwd:
        return False
    senha_hash = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt())
    cursor.execute(
        """
        INSERT INTO usuarios (username, password, nivel)
        VALUES (?, ?, ?)
        """,
        (user, senha_hash, nivel),
    )
    return True


def create_default_users(required_if_empty: bool | None = None):
    if required_if_empty is None:
        required_if_empty = _env_flag("MEDCONTRACT_REQUIRE_BOOTSTRAP_USERS", True)

    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM usuarios")
        users_count = int((cursor.fetchone() or [0])[0] or 0)

        specs = _bootstrap_user_specs()
        if users_count == 0 and required_if_empty and not specs:
            raise RuntimeError(
                "Nenhum usuario inicial encontrado. Defina MEDCONTRACT_DEFAULT_ADMIN_PASSWORD "
                "com valor forte (nao-placeholder) antes da primeira execucao."
            )

        changed = False

        for username, password, nivel in specs:
            if _ensure_default_user(cursor, username, password, nivel):
                changed = True

        if changed:
            conn.commit()
    finally:
        conn.close()


# =========================
# LOGIN
# =========================
def _login_lockout_max_attempts() -> int:
    try:
        return max(3, int((os.getenv("MEDCONTRACT_LOGIN_MAX_ATTEMPTS") or "5").strip()))
    except Exception:
        return 5


def _login_lockout_secs() -> int:
    try:
        return max(15, int((os.getenv("MEDCONTRACT_LOGIN_LOCKOUT_SECS") or "60").strip()))
    except Exception:
        return 60


def _ensure_login_guard_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS login_guard (
            username TEXT PRIMARY KEY,
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _get_login_guard(cursor, username: str) -> tuple[int, int]:
    cursor.execute(
        "SELECT failed_count, locked_until FROM login_guard WHERE LOWER(username) = LOWER(?) LIMIT 1",
        (username,),
    )
    row = cursor.fetchone()
    if not row:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)


def _set_login_guard(cursor, username: str, failed_count: int, locked_until: int) -> None:
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO login_guard (username, failed_count, locked_until, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (username) DO UPDATE SET
            failed_count = EXCLUDED.failed_count,
            locked_until = EXCLUDED.locked_until,
            updated_at = EXCLUDED.updated_at
        """,
        (username, int(failed_count), int(locked_until), now_iso),
    )


def _register_failed_login(cursor, username: str) -> None:
    max_attempts = _login_lockout_max_attempts()
    lock_secs = _login_lockout_secs()
    now_ts = int(time.time())
    failed_count, locked_until = _get_login_guard(cursor, username)
    if locked_until <= now_ts:
        locked_until = 0
    failed_count = max(0, failed_count) + 1
    if failed_count >= max_attempts:
        locked_until = now_ts + lock_secs
        failed_count = 0
    _set_login_guard(cursor, username, failed_count, locked_until)


def _clear_login_guard(cursor, username: str) -> None:
    _set_login_guard(cursor, username, 0, 0)


def validate_user(username, password):
    username = _safe_str(username).strip()
    password = _safe_str(password)
    if not username or not password:
        return False, None

    conn = connect()
    try:
        cursor = conn.cursor()
        _ensure_login_guard_table(cursor)

        now_ts = int(time.time())
        _, locked_until = _get_login_guard(cursor, username)
        if locked_until > now_ts:
            return False, None

        cursor.execute(
            "SELECT username, password, nivel FROM usuarios WHERE LOWER(username) = LOWER(?) LIMIT 1",
            (username,),
        )
        user = cursor.fetchone()

        if not user:
            _register_failed_login(cursor, username)
            conn.commit()
            return False, None

        db_username = _safe_str(user[0]).strip()
        stored_password = user[1]
        nivel = user[2]
        plain_bytes = password.encode()

        # Fluxo normal: hash bcrypt (bytes/blob)
        if isinstance(stored_password, memoryview):
            stored_password = stored_password.tobytes()
        if isinstance(stored_password, bytearray):
            stored_password = bytes(stored_password)

        if isinstance(stored_password, (bytes, bytearray)):
            try:
                if bcrypt.checkpw(plain_bytes, bytes(stored_password)):
                    _clear_login_guard(cursor, db_username or username)
                    conn.commit()
                    return True, nivel
                _register_failed_login(cursor, db_username or username)
                conn.commit()
                return False, None
            except Exception:
                # Cai para fallback abaixo (legado invÃ¡lido)
                pass

        # Fallback legado (opcional): senha salva em texto puro.
        allow_plaintext_login = _env_flag("MEDCONTRACT_ALLOW_LEGACY_PLAINTEXT_LOGIN", False)
        stored_text = _safe_str(stored_password)
        if allow_plaintext_login and stored_text == password:
            try:
                new_hash = bcrypt.hashpw(plain_bytes, bcrypt.gensalt())
                cursor.execute(
                    "UPDATE usuarios SET password = ? WHERE username = ?",
                    (new_hash, db_username),
                )
                _clear_login_guard(cursor, db_username or username)
                conn.commit()
            except Exception:
                pass
            return True, nivel

        _register_failed_login(cursor, db_username or username)
        conn.commit()
        return False, None
    finally:
        conn.close()


# =========================
# BACKUP
# =========================
def backup_db(backup_dir: str | None = None, keep_last: int | None = DEFAULT_BACKUP_RETENTION) -> str:
    backup_dir_path = get_backup_dir() if backup_dir is None else Path(backup_dir)
    backup_dir_path.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    active_backend = _get_runtime_backend() or _configured_db_backend()
    if active_backend == "auto":
        conn_probe = connect()
        try:
            active_backend = getattr(conn_probe, "backend", "postgres")
        finally:
            conn_probe.close()

    if active_backend == "sqlite":
        src_path = _sqlite_db_path()
        dst_path = backup_dir_path / f"medcontract_backup_{stamp}.db"
        if src_path.exists():
            shutil.copy2(src_path, dst_path)
        else:
            # Garante um arquivo válido mesmo sem base prévia.
            sqlite3.connect(str(dst_path)).close()
        try:
            _prune_old_backups(backup_dir_path, keep_last)
        except Exception:
            pass
        dst_path = _encrypt_backup_file_if_enabled(dst_path)
        return str(dst_path)

    dsn = _build_pg_dsn()
    pg_dump_bin = shutil.which("pg_dump")

    if pg_dump_bin:
        dst_path = backup_dir_path / f"medcontract_backup_{stamp}.sql"
        conn_info = conninfo_to_dict(dsn)
        pg_password = _safe_str(conn_info.pop("password", ""))
        safe_dsn = make_conninfo(**conn_info)

        cmd = [
            pg_dump_bin,
            f"--dbname={safe_dsn}",
            "--format=plain",
            "--no-owner",
            "--no-privileges",
            f"--file={str(dst_path)}",
        ]
        env = os.environ.copy()
        if pg_password:
            env["PGPASSWORD"] = pg_password
        subprocess.run(cmd, check=True, env=env)
    else:
        if not _env_flag("MEDCONTRACT_ALLOW_JSON_BACKUP_FALLBACK", False):
            raise RuntimeError(
                "pg_dump nao encontrado. Por seguranca, o fallback JSON esta desabilitado "
                "(defina MEDCONTRACT_ALLOW_JSON_BACKUP_FALLBACK=1 para habilitar)."
            )
        # Fallback sem pg_dump: snapshot em JSON (estruturas e dados principais).
        dst_path = backup_dir_path / f"medcontract_backup_{stamp}.json"
        conn = connect()
        try:
            cur = conn.cursor()
            payload: dict[str, object] = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "database_dsn_hint": (os.getenv("MEDCONTRACT_DB_NAME") or "medcontract"),
                "tables": {},
            }
            for table in ("usuarios", "clientes", "dependentes", "pagamentos", "pagamentos_empresas", "empresas"):
                cur.execute(f"""
                    SELECT COALESCE(json_agg(t), '[]'::json)
                    FROM (SELECT * FROM {table} ORDER BY id ASC) t
                """)
                rows = cur.fetchone()
                payload["tables"][table] = (rows[0] if rows and rows[0] is not None else [])

            with open(dst_path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
        finally:
            conn.close()

    dst_path = _encrypt_backup_file_if_enabled(dst_path)
    try:
        _prune_old_backups(backup_dir_path, keep_last)
    except Exception:
        pass

    return str(dst_path)


def integrity_check() -> tuple[bool, str]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM dependentes d
            LEFT JOIN clientes c ON c.id = d.cliente_id
            WHERE c.id IS NULL
        """)
        deps_orfaos = int((cur.fetchone() or [0])[0] or 0)

        cur.execute("""
            SELECT COUNT(*)
            FROM pagamentos p
            LEFT JOIN clientes c ON c.id = p.cliente_id
            WHERE c.id IS NULL
        """)
        pag_orfaos = int((cur.fetchone() or [0])[0] or 0)

        cur.execute("""
            SELECT COUNT(*)
            FROM pagamentos_empresas pe
            LEFT JOIN empresas e ON e.id = pe.empresa_id
            WHERE e.id IS NULL
        """)
        pag_emp_orfaos = int((cur.fetchone() or [0])[0] or 0)

        if deps_orfaos == 0 and pag_orfaos == 0 and pag_emp_orfaos == 0:
            return True, "ok"
        return False, (
            f"Integridade inválida: dependentes_orfaos={deps_orfaos}, "
            f"pagamentos_orfaos={pag_orfaos}, pagamentos_empresas_orfaos={pag_emp_orfaos}"
        )
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


# =========================
# CLIENTES
# =========================
def matricula_existe(matricula: int) -> bool:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM clientes WHERE id = ? LIMIT 1", (int(matricula),))
        return cur.fetchone() is not None
    finally:
        conn.close()


def cadastrar_cliente(
    nome, cpf, telefone, email,
    data_inicio, valor_mensal,
    observacoes="",
    status="ativo", pagamento_status="em_dia",
    data_nascimento=None,
    cep=None,
    endereco=None,
    plano=None,
    dependentes=0,
    vencimento_dia=10,
    forma_pagamento=None,
    matricula=None
):
    """
    Se 'matricula' vier preenchida, usa como id manual.
    SenÃ£o, usa a sequence padrÃ£o do PostgreSQL.
    """
    conn = connect()
    try:
        cursor = conn.cursor()
        cpf_raw = _safe_str(cpf).strip()
        cpf_norm = _normalize_cpf(cpf_raw)
        if len(cpf_norm) != 11:
            return False, "CPF invalido."
        cursor.execute("SELECT 1 FROM clientes WHERE cpf_norm = ? LIMIT 1", (cpf_norm,))
        if cursor.fetchone():
            return False, "CPF ja cadastrado."

        if matricula not in (None, "", 0):
            matricula = int(matricula)

            cursor.execute("SELECT 1 FROM clientes WHERE id = ? LIMIT 1", (matricula,))
            if cursor.fetchone():
                return False, "JÃ¡ existe cliente com essa matrÃ­cula."

            cursor.execute("""
                INSERT INTO clientes
                (id, nome, cpf, cpf_norm, telefone, email, data_inicio,
                 valor_mensal, status, pagamento_status, observacoes,
                 data_nascimento, cep, endereco, plano, dependentes, vencimento_dia, forma_pagamento)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                matricula,
                _safe_str(nome).strip(),
                cpf_raw,
                cpf_norm,
                _safe_str(telefone).strip(),
                _safe_str(email).strip(),
                _safe_str(data_inicio).strip(),
                _safe_float(valor_mensal),
                _safe_str(status).strip() or "ativo",
                _safe_str(pagamento_status).strip() or "em_dia",
                _safe_str(observacoes),
                _safe_str(data_nascimento, None),
                _safe_str(cep, None),
                _safe_str(endereco, None),
                _safe_str(plano, None),
                _safe_int(dependentes, 0),
                _safe_int(vencimento_dia, 10),
                _safe_str(forma_pagamento, None),
            ))
        else:
            cursor.execute("""
                INSERT INTO clientes
                (nome, cpf, cpf_norm, telefone, email, data_inicio,
                 valor_mensal, status, pagamento_status, observacoes,
                 data_nascimento, cep, endereco, plano, dependentes, vencimento_dia, forma_pagamento)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                _safe_str(nome).strip(),
                cpf_raw,
                cpf_norm,
                _safe_str(telefone).strip(),
                _safe_str(email).strip(),
                _safe_str(data_inicio).strip(),
                _safe_float(valor_mensal),
                _safe_str(status).strip() or "ativo",
                _safe_str(pagamento_status).strip() or "em_dia",
                _safe_str(observacoes),
                _safe_str(data_nascimento, None),
                _safe_str(cep, None),
                _safe_str(endereco, None),
                _safe_str(plano, None),
                _safe_int(dependentes, 0),
                _safe_int(vencimento_dia, 10),
                _safe_str(forma_pagamento, None),
            ))

        if matricula not in (None, "", 0):
            try:
                _sync_id_sequence(cursor, "clientes")
            except Exception:
                pass
        conn.commit()
        return True, "Cliente cadastrado com sucesso."

    except DB_INTEGRITY_ERRORS as erro:
        try:
            conn.rollback()
        except Exception:
            pass

        msg = str(erro).lower()
        if (
            "clientes.cpf" in msg
            or "clientes.cpf_norm" in msg
            or "unique constraint failed: clientes.cpf" in msg
            or "unique constraint failed: clientes.cpf_norm" in msg
            or "clientes_cpf_key" in msg
            or "idx_clientes_cpf_norm_uniq" in msg
        ):
            return False, "CPF jÃ¡ cadastrado."
        if "clientes.id" in msg or "unique constraint failed: clientes.id" in msg or "clientes_pkey" in msg:
            return False, "MatrÃ­cula jÃ¡ cadastrada."
        if "valor_mensal invalido" in msg or "chk_clientes_valor_mensal_nonneg" in msg:
            return False, "Valor mensal invÃ¡lido."
        if "vencimento_dia invalido" in msg or "chk_clientes_vencimento_range" in msg:
            return False, "Dia de vencimento invÃ¡lido."
        if "data_inicio invalida" in msg or "chk_clientes_data_inicio_fmt" in msg:
            return False, "Data de inÃ­cio invÃ¡lida."
        return False, "NÃ£o foi possÃ­vel cadastrar o cliente."

    except Exception as erro:
        print("Erro ao cadastrar cliente:", erro)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, "Erro ao cadastrar cliente."
    finally:
        conn.close()


def listar_clientes():
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clientes ORDER BY LOWER(nome), id")
        return cursor.fetchall()
    finally:
        conn.close()


def listar_clientes_com_ultimo_pagamento(limit=50, offset=0, search="",
                                         status="", pagamento=""):
    conn = connect()
    try:
        cursor = conn.cursor()
        where_sql, params = _build_clientes_where_clause(
            search=search,
            status=status,
            pagamento=pagamento,
            table_alias="c",
        )

        query = f"""
            WITH base AS (
                SELECT
                    c.id, c.nome, c.cpf, c.telefone, c.email,
                    c.data_inicio, c.valor_mensal,
                    c.status, c.pagamento_status, c.observacoes,
                    c.data_nascimento, c.cep, c.endereco,
                    c.plano, c.dependentes, c.vencimento_dia, c.forma_pagamento
                FROM clientes c
                {where_sql}
                ORDER BY LOWER(c.nome), c.id
                LIMIT ? OFFSET ?
            )
            SELECT
                b.id, b.nome, b.cpf, b.telefone, b.email,
                b.data_inicio, b.valor_mensal,
                b.status, b.pagamento_status, b.observacoes,
                b.data_nascimento, b.cep, b.endereco,
                b.plano, b.dependentes, b.vencimento_dia, b.forma_pagamento,
                p.mes_referencia, p.data_pagamento, p.valor_pago
            FROM base b
            LEFT JOIN pagamentos p
                ON p.id = (
                    SELECT MAX(p2.id)
                    FROM pagamentos p2
                    WHERE p2.cliente_id = b.id
                )
            ORDER BY LOWER(b.nome), b.id
        """
        cursor.execute(query, tuple(params + [int(limit), int(offset)]))

        return cursor.fetchall()
    finally:
        conn.close()


def listar_clientes_export_ultimo_pagamento(
    limit: int = 5000,
    offset: int = 0,
    pagamento_status: str = "",
):
    """
    Lista clientes para exportação com último pagamento, trazendo apenas colunas
    necessárias para reduzir custo de leitura e memória.
    """
    conn = connect()
    try:
        cursor = conn.cursor()
        where = []
        params = []

        pag_norm = _safe_str(pagamento_status, "").strip().lower()
        if pag_norm in {"em_dia", "atrasado"}:
            where.append("c.pagamento_status = ?")
            params.append(pag_norm)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        cursor.execute(
            f"""
            WITH base AS (
                SELECT
                    c.id, c.nome, c.cpf, c.status, c.pagamento_status
                FROM clientes c
                {where_sql}
                ORDER BY LOWER(c.nome), c.id
                LIMIT ? OFFSET ?
            )
            SELECT
                b.id, b.nome, b.cpf,
                b.status, b.pagamento_status,
                p.mes_referencia, p.data_pagamento, p.valor_pago
            FROM base b
            LEFT JOIN pagamentos p
                ON p.id = (
                    SELECT MAX(p2.id)
                    FROM pagamentos p2
                    WHERE p2.cliente_id = b.id
                )
            ORDER BY LOWER(b.nome), b.id
            """,
            tuple(params + [_safe_int(limit, 5000), _safe_int(offset, 0)]),
        )
        return cursor.fetchall() or []
    finally:
        conn.close()


def contar_clientes(search="", status="", pagamento=""):
    conn = connect()
    try:
        cursor = conn.cursor()
        where_sql, params = _build_clientes_where_clause(
            search=search,
            status=status,
            pagamento=pagamento,
            table_alias="c",
        )
        query = f"SELECT COUNT(*) FROM clientes c {where_sql}"
        cursor.execute(query, tuple(params))
        return cursor.fetchone()[0]
    finally:
        conn.close()


def buscar_cliente_por_id(cliente_id):
    conn = connect()
    try:
        cursor = conn.cursor()
        # Retorna colunas explícitas em ordem estável para evitar quebra por
        # mudanças de schema (ex.: adição de cpf_norm).
        cursor.execute("""
            SELECT
                id, nome, cpf, telefone, email, data_inicio, valor_mensal,
                status, pagamento_status, observacoes,
                data_nascimento, cep, endereco, plano,
                dependentes, vencimento_dia, forma_pagamento
            FROM clientes
            WHERE id = ?
        """, (int(cliente_id),))
        return cursor.fetchone()
    finally:
        conn.close()


def buscar_cliente_por_cpf(cpf):
    conn = connect()
    try:
        cpf_raw = _safe_str(cpf).strip()
        cpf_norm = _normalize_cpf(cpf_raw)
        if not cpf_raw and not cpf_norm:
            return None
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nome, status, pagamento_status
            FROM clientes
            WHERE cpf_norm = ? OR cpf = ?
            LIMIT 1
        """, (cpf_norm, cpf_raw))
        return cursor.fetchone()
    finally:
        conn.close()


def buscar_cliente_preview_por_cpf(cpf: str) -> dict | None:
    """
    Retorna preview rico para a tela de pagamento, incluindo dependentes.
    """
    cpf_raw = _safe_str(cpf).strip()
    cpf_norm = _normalize_cpf(cpf_raw)
    if not cpf_raw and not cpf_norm:
        return None

    conn = connect()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                c.id, c.nome, c.cpf, c.status, c.pagamento_status,
                c.plano, c.dependentes, c.valor_mensal
            FROM clientes c
            WHERE c.cpf_norm = ? OR c.cpf = ?
            LIMIT 1
        """, (cpf_norm, cpf_raw))
        row = cur.fetchone()

        if not row:
            return None

        cliente_id = int(row[0])

        preview = {
            "id": cliente_id,
            "nome": row[1],
            "cpf": row[2],
            "status": row[3],
            "pagamento_status": row[4],
            "plano": row[5],
            "dependentes": _safe_int(row[6], 0),
            "valor_mensal": _safe_float(row[7], 0.0),
            "dependentes_lista": [],
            "ultimo_pagamento": None,
        }

        cur.execute("""
            SELECT nome, cpf, data_nascimento, idade
            FROM dependentes
            WHERE cliente_id = ?
            ORDER BY id ASC
        """, (cliente_id,))
        deps = cur.fetchall()

        for d in deps:
            dn_iso = _safe_date_iso(d[2])
            item = {
                "nome": d[0],
                "cpf": d[1],
                "idade": _age_from_iso(dn_iso, default=_safe_int(d[3], 0)),
            }
            if dn_iso:
                item["data_nascimento"] = dn_iso
            preview["dependentes_lista"].append(item)

        cur.execute("""
            SELECT mes_referencia, data_pagamento, valor_pago
            FROM pagamentos
            WHERE cliente_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (cliente_id,))
        p = cur.fetchone()

        if p:
            preview["ultimo_pagamento"] = {
                "mes_referencia": p[0],
                "data_pagamento": p[1],
                "valor_pago": _safe_float(p[2], 0.0),
            }

        return preview
    finally:
        conn.close()


def buscar_clientes_por_nome(nome: str, limit: int = 20):
    nome = (nome or "").strip()
    if not nome:
        return []

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, cpf
            FROM clientes
            WHERE nome ILIKE ?
            ORDER BY LOWER(nome), id
            LIMIT ?
        """, (f"%{nome}%", int(limit)))
        return cur.fetchall()
    finally:
        conn.close()


def obter_planos_config() -> dict:
    conn = connect()
    try:
        cur = conn.cursor()
        return _read_planos_config_from_cursor(cur)
    finally:
        conn.close()


def salvar_planos_config(planos: dict) -> bool:
    conn = connect()
    try:
        cur = conn.cursor()
        _write_planos_config_from_cursor(cur, planos or {})
        conn.commit()
        return True
    except Exception as e:
        print("Erro ao salvar configuracao de planos:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def prever_reajuste_planos(percentual: float, plano: str = "todos", somente_ativos: bool = True) -> dict:
    conn = connect()
    try:
        cur = conn.cursor()
        return _preview_reajuste_planos_cursor(
            cur,
            percentual=percentual,
            plano=plano,
            somente_ativos=somente_ativos,
        )
    finally:
        conn.close()


def aplicar_reajuste_planos(percentual: float, plano: str = "todos", somente_ativos: bool = True) -> tuple[bool, str, dict]:
    conn = connect()
    try:
        cur = conn.cursor()
        prev = _preview_reajuste_planos_cursor(
            cur,
            percentual=percentual,
            plano=plano,
            somente_ativos=somente_ativos,
        )

        plano_key = None if prev.get("plano_key") == "todos" else prev.get("plano_key")
        where_sql, where_params = _build_reajuste_where(plano_key, bool(prev.get("somente_ativos")))
        fator = _safe_float(prev.get("fator"), 1.0)

        cur.execute(
            f"""
            UPDATE clientes
            SET valor_mensal = ROUND(CAST(valor_mensal * ? AS numeric), 2)
            {where_sql}
            """,
            tuple([fator] + where_params),
        )
        clientes_atualizados = int(getattr(cur, "rowcount", 0) or 0)

        conn.commit()

        info = dict(prev)
        info["clientes_atualizados"] = clientes_atualizados

        if clientes_atualizados > 0:
            msg = (
                f"Reajuste de {prev.get('percentual', 0)}% aplicado em "
                f"{clientes_atualizados} cliente(s)."
            )
        else:
            msg = "Nenhum cliente foi afetado pelos filtros selecionados."
        return True, msg, info
    except Exception as e:
        print("Erro ao aplicar reajuste de planos:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Nao foi possivel aplicar reajuste: {e}", {}
    finally:
        conn.close()


def prever_reajuste_clientes_selecionados(
    percentual: float,
    cliente_ids,
    somente_ativos: bool = False,
) -> dict:
    conn = connect()
    try:
        cur = conn.cursor()
        return _preview_reajuste_clientes_selecionados_cursor(
            cur,
            percentual=percentual,
            cliente_ids=cliente_ids,
            somente_ativos=somente_ativos,
        )
    finally:
        conn.close()


def aplicar_reajuste_clientes_selecionados(
    percentual: float,
    cliente_ids,
    somente_ativos: bool = False,
) -> tuple[bool, str, dict]:
    conn = connect()
    try:
        cur = conn.cursor()
        prev = _preview_reajuste_clientes_selecionados_cursor(
            cur,
            percentual=percentual,
            cliente_ids=cliente_ids,
            somente_ativos=somente_ativos,
        )

        where_sql, where_params = _build_reajuste_ids_where(
            prev.get("cliente_ids", []),
            bool(prev.get("somente_ativos", False)),
        )
        fator = _safe_float(prev.get("fator"), 1.0)

        cur.execute(
            f"""
            UPDATE clientes
            SET valor_mensal = ROUND(CAST(valor_mensal * ? AS numeric), 2)
            {where_sql}
            """,
            tuple([fator] + where_params),
        )
        clientes_atualizados = int(getattr(cur, "rowcount", 0) or 0)
        conn.commit()

        info = dict(prev)
        info["clientes_atualizados"] = clientes_atualizados

        if clientes_atualizados > 0:
            msg = (
                f"Reajuste de {prev.get('percentual', 0)}% aplicado em "
                f"{clientes_atualizados} cliente(s) selecionado(s)."
            )
        else:
            msg = "Nenhum cliente selecionado foi afetado pelos critérios informados."
        return True, msg, info
    except Exception as e:
        print("Erro ao aplicar reajuste em clientes selecionados:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Nao foi possivel aplicar reajuste: {e}", {}
    finally:
        conn.close()


def prever_reajuste_cliente_especifico(cliente_id: int, novo_valor: float) -> dict:
    conn = connect()
    try:
        cur = conn.cursor()
        return _preview_reajuste_cliente_especifico_cursor(
            cur,
            cliente_id=cliente_id,
            novo_valor=novo_valor,
        )
    finally:
        conn.close()


def aplicar_reajuste_cliente_especifico(cliente_id: int, novo_valor: float) -> tuple[bool, str, dict]:
    conn = connect()
    try:
        cur = conn.cursor()
        prev = _preview_reajuste_cliente_especifico_cursor(
            cur,
            cliente_id=cliente_id,
            novo_valor=novo_valor,
        )

        cur.execute(
            """
            UPDATE clientes
            SET valor_mensal = ?
            WHERE id = ?
            """,
            (float(prev.get("novo_valor", 0.0) or 0.0), int(prev.get("cliente_id", 0) or 0)),
        )
        clientes_atualizados = int(getattr(cur, "rowcount", 0) or 0)
        conn.commit()

        info = dict(prev)
        info["clientes_atualizados"] = clientes_atualizados

        if clientes_atualizados > 0:
            msg = (
                f"Valor mensal atualizado para {info.get('cliente_nome', 'cliente')} "
                f"(MAT {info.get('cliente_id', '-')})."
            )
        else:
            msg = "Nenhum cliente foi atualizado no reajuste individual."
        return True, msg, info
    except Exception as e:
        print("Erro ao aplicar reajuste individual do cliente:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Nao foi possivel aplicar reajuste: {e}", {}
    finally:
        conn.close()


def atualizar_cliente(
    cliente_id, nome, cpf, telefone, email,
    data_inicio, valor_mensal, status,
    pagamento_status, observacoes="",
    data_nascimento=None,
    cep=None,
    endereco=None,
    plano=None,
    dependentes=0,
    vencimento_dia=10,
    forma_pagamento=None
):
    conn = connect()
    try:
        cursor = conn.cursor()
        cpf_raw = _safe_str(cpf).strip()
        cpf_norm = _normalize_cpf(cpf_raw)
        if len(cpf_norm) != 11:
            return False
        cursor.execute(
            "SELECT id FROM clientes WHERE cpf_norm = ? AND id <> ? LIMIT 1",
            (cpf_norm, int(cliente_id)),
        )
        if cursor.fetchone():
            return False

        cursor.execute("""
            UPDATE clientes SET
                nome=?, cpf=?, cpf_norm=?, telefone=?, email=?,
                data_inicio=?, valor_mensal=?,
                status=?, pagamento_status=?, observacoes=?,
                data_nascimento=?, cep=?, endereco=?,
                plano=?, dependentes=?, vencimento_dia=?, forma_pagamento=?
            WHERE id=?
        """, (
            _safe_str(nome).strip(),
            cpf_raw,
            cpf_norm,
            _safe_str(telefone).strip(),
            _safe_str(email).strip(),
            _safe_str(data_inicio).strip(),
            _safe_float(valor_mensal),
            _safe_str(status).strip() or "ativo",
            _safe_str(pagamento_status).strip() or "em_dia",
            _safe_str(observacoes),
            _safe_str(data_nascimento, None),
            _safe_str(cep, None),
            _safe_str(endereco, None),
            _safe_str(plano, None),
            _safe_int(dependentes, 0),
            _safe_int(vencimento_dia, 10),
            _safe_str(forma_pagamento, None),
            int(cliente_id),
        ))

        conn.commit()
        return True

    except DB_INTEGRITY_ERRORS:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    except Exception as e:
        print("Erro ao atualizar cliente:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def cancelar_plano_cliente(cliente_id):
    conn = connect()
    try:
        cursor = conn.cursor()
        cid = int(cliente_id)

        cursor.execute("SELECT status FROM clientes WHERE id = ? LIMIT 1", (cid,))
        row = cursor.fetchone()
        if not row:
            return False, "Cliente nao encontrado."

        status_atual = _safe_str(row[0]).strip().lower()
        if status_atual == "inativo":
            return True, "Cliente ja esta inativo."

        cursor.execute("""
            UPDATE clientes
            SET status = 'inativo',
                pagamento_status = 'em_dia'
            WHERE id = ?
        """, (cid,))

        conn.commit()
        return True, "Plano cancelado com sucesso."
    except Exception as e:
        print("Erro ao cancelar plano do cliente:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, "Erro ao cancelar plano."
    finally:
        conn.close()


def excluir_cliente(cliente_id):
    conn = connect()
    try:
        cursor = conn.cursor()
        cid = int(cliente_id)

        # ON DELETE CASCADE limpa dependentes/pagamentos automaticamente.
        cursor.execute("DELETE FROM clientes WHERE id = ?", (cid,))

        conn.commit()
        return True
    except Exception as e:
        print("Erro ao excluir cliente:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


# =========================
# EMPRESAS
# =========================
def cadastrar_empresa(
    cnpj,
    nome,
    telefone,
    email,
    logradouro,
    numero,
    bairro,
    cep,
    cidade,
    estado,
    forma_pagamento,
    status_pagamento,
    dia_vencimento,
    valor_mensal,
    data_cadastro=None,
):
    conn = connect()
    try:
        cur = conn.cursor()

        cnpj_txt = _safe_str(cnpj).strip()
        cnpj_digits = _normalize_cnpj(cnpj_txt)
        if not _is_valid_cnpj(cnpj_txt):
            return False, "CNPJ invalido."

        cur.execute(
            """
            SELECT 1
            FROM empresas
            WHERE cnpj_norm = ?
            LIMIT 1
            """,
            (cnpj_digits,),
        )
        if cur.fetchone():
            return False, "CNPJ ja cadastrado."

        forma = _safe_str(forma_pagamento).strip().lower()
        if forma not in {"pix", "boleto", "recepcao"}:
            return False, "Forma de pagamento invalida."

        status = _safe_str(status_pagamento).strip().lower()
        if status not in {"em_dia", "pendente", "inadimplente"}:
            return False, "Status de pagamento invalido."

        dia = _safe_int(dia_vencimento, 0)
        if dia < 1 or dia > 31:
            return False, "Dia de vencimento invalido."

        valor_txt = _safe_str(valor_mensal).strip()
        if not valor_txt:
            return False, "Valor mensal obrigatorio."

        cadastro = _safe_str(data_cadastro).strip() or _today_iso()
        if not _safe_date_iso(cadastro):
            return False, "Data de cadastro invalida."

        cur.execute(
            """
            INSERT INTO empresas (
                cnpj, cnpj_norm, nome, telefone, email,
                logradouro, numero, bairro, cep, cidade, estado,
                forma_pagamento, status_pagamento, dia_vencimento,
                valor_mensal, data_cadastro
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cnpj_txt,
                cnpj_digits,
                _safe_str(nome).strip(),
                _safe_str(telefone).strip(),
                _safe_str(email).strip(),
                _safe_str(logradouro).strip(),
                _safe_str(numero).strip(),
                _safe_str(bairro).strip(),
                _safe_str(cep).strip(),
                _safe_str(cidade).strip(),
                _safe_str(estado).strip(),
                forma,
                status,
                dia,
                valor_txt,
                cadastro,
            ),
        )
        conn.commit()
        return True, "Empresa cadastrada com sucesso."
    except DB_INTEGRITY_ERRORS as e:
        try:
            conn.rollback()
        except Exception:
            pass
        msg = str(e).lower()
        if "empresas.cnpj" in msg or "idx_empresas_cnpj" in msg or "idx_empresas_cnpj_norm_uniq" in msg:
            return False, "CNPJ ja cadastrado."
        return False, "Nao foi possivel cadastrar a empresa."
    except Exception as e:
        print("Erro ao cadastrar empresa:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, "Erro ao cadastrar empresa."
    finally:
        conn.close()


def atualizar_empresa(
    empresa_id,
    cnpj,
    nome,
    telefone,
    email,
    logradouro,
    numero,
    bairro,
    cep,
    cidade,
    estado,
    forma_pagamento,
    status_pagamento,
    dia_vencimento,
    valor_mensal,
):
    conn = connect()
    try:
        cur = conn.cursor()

        eid = int(empresa_id)
        cnpj_txt = _safe_str(cnpj).strip()
        cnpj_digits = _normalize_cnpj(cnpj_txt)
        if not _is_valid_cnpj(cnpj_txt):
            return False, "CNPJ invalido."

        cur.execute(
            """
            SELECT 1
            FROM empresas
            WHERE cnpj_norm = ?
              AND id <> ?
            LIMIT 1
            """,
            (cnpj_digits, eid),
        )
        if cur.fetchone():
            return False, "CNPJ ja cadastrado."

        forma = _safe_str(forma_pagamento).strip().lower()
        if forma not in {"pix", "boleto", "recepcao"}:
            return False, "Forma de pagamento invalida."

        status = _safe_str(status_pagamento).strip().lower()
        if status not in {"em_dia", "pendente", "inadimplente"}:
            return False, "Status de pagamento invalido."

        dia = _safe_int(dia_vencimento, 0)
        if dia < 1 or dia > 31:
            return False, "Dia de vencimento invalido."

        valor_txt = _safe_str(valor_mensal).strip()
        if not valor_txt:
            return False, "Valor mensal obrigatorio."

        cur.execute(
            """
            UPDATE empresas
            SET
                cnpj = ?, cnpj_norm = ?, nome = ?, telefone = ?, email = ?,
                logradouro = ?, numero = ?, bairro = ?, cep = ?, cidade = ?, estado = ?,
                forma_pagamento = ?, status_pagamento = ?, dia_vencimento = ?, valor_mensal = ?
            WHERE id = ?
            """,
            (
                cnpj_txt,
                cnpj_digits,
                _safe_str(nome).strip(),
                _safe_str(telefone).strip(),
                _safe_str(email).strip(),
                _safe_str(logradouro).strip(),
                _safe_str(numero).strip(),
                _safe_str(bairro).strip(),
                _safe_str(cep).strip(),
                _safe_str(cidade).strip(),
                _safe_str(estado).strip(),
                forma,
                status,
                dia,
                valor_txt,
                eid,
            ),
        )
        conn.commit()
        return True, "Empresa atualizada com sucesso."
    except DB_INTEGRITY_ERRORS as e:
        try:
            conn.rollback()
        except Exception:
            pass
        msg = str(e).lower()
        if "empresas.cnpj" in msg or "idx_empresas_cnpj" in msg or "idx_empresas_cnpj_norm_uniq" in msg:
            return False, "CNPJ ja cadastrado."
        return False, "Nao foi possivel atualizar a empresa."
    except Exception as e:
        print("Erro ao atualizar empresa:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, "Erro ao atualizar empresa."
    finally:
        conn.close()


def excluir_empresa(empresa_id):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM empresas WHERE id = ?", (int(empresa_id),))
        conn.commit()
        return True
    except Exception as e:
        print("Erro ao excluir empresa:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def buscar_empresa_por_id(empresa_id):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, cnpj, nome, telefone, email,
                logradouro, numero, bairro, cep, cidade, estado,
                forma_pagamento, status_pagamento, dia_vencimento,
                valor_mensal, data_cadastro
            FROM empresas
            WHERE id = ?
            LIMIT 1
            """,
            (int(empresa_id),),
        )
        return cur.fetchone()
    finally:
        conn.close()


def buscar_empresa_por_cnpj(cnpj):
    cnpj_txt = _safe_str(cnpj).strip()
    cnpj_digits = _normalize_cnpj(cnpj_txt)
    if not cnpj_txt and not cnpj_digits:
        return None

    conn = connect()
    try:
        cur = conn.cursor()
        if cnpj_digits:
            cur.execute(
                """
                SELECT
                    id, cnpj, nome, telefone, email,
                    forma_pagamento, status_pagamento, dia_vencimento, valor_mensal
                FROM empresas
                WHERE cnpj_norm = ?
                LIMIT 1
                """,
                (cnpj_digits,),
            )
            row = cur.fetchone()
            if row:
                return row

        if cnpj_txt:
            cur.execute(
                """
                SELECT
                    id, cnpj, nome, telefone, email,
                    forma_pagamento, status_pagamento, dia_vencimento, valor_mensal
                FROM empresas
                WHERE cnpj = ?
                LIMIT 1
                """,
                (cnpj_txt,),
            )
            return cur.fetchone()
        return None
    finally:
        conn.close()


def buscar_empresa_preview_por_cnpj(cnpj: str) -> dict | None:
    cnpj_txt = _safe_str(cnpj).strip()
    cnpj_digits = _normalize_cnpj(cnpj_txt)
    if not cnpj_txt and not cnpj_digits:
        return None

    conn = connect()
    try:
        cur = conn.cursor()
        row = None
        if cnpj_digits:
            cur.execute(
                """
                SELECT
                    e.id, e.nome, e.cnpj, e.forma_pagamento,
                    e.status_pagamento, e.dia_vencimento, e.valor_mensal
                FROM empresas e
                WHERE e.cnpj_norm = ?
                LIMIT 1
                """,
                (cnpj_digits,),
            )
            row = cur.fetchone()

        if not row and cnpj_txt:
            cur.execute(
                """
                SELECT
                    e.id, e.nome, e.cnpj, e.forma_pagamento,
                    e.status_pagamento, e.dia_vencimento, e.valor_mensal
                FROM empresas e
                WHERE e.cnpj = ?
                LIMIT 1
                """,
                (cnpj_txt,),
            )
            row = cur.fetchone()
        if not row:
            return None

        empresa_id = int(row[0])
        preview = {
            "id": empresa_id,
            "nome": row[1],
            "cnpj": row[2],
            "forma_pagamento": row[3],
            "status_pagamento": row[4],
            "dia_vencimento": _safe_int(row[5], 0),
            "valor_mensal": _safe_money_float(row[6], 0.0),
            "ultimo_pagamento": None,
        }

        cur.execute(
            """
            SELECT mes_referencia, data_pagamento, valor_pago
            FROM pagamentos_empresas
            WHERE empresa_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (empresa_id,),
        )
        last = cur.fetchone()
        if last:
            preview["ultimo_pagamento"] = {
                "mes_referencia": last[0],
                "data_pagamento": last[1],
                "valor_pago": _safe_float(last[2], 0.0),
            }

        return preview
    finally:
        conn.close()


def buscar_empresas_por_nome(nome: str, limit: int = 20):
    nome_txt = _safe_str(nome).strip()
    if not nome_txt:
        return []

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, nome, cnpj
            FROM empresas
            WHERE nome ILIKE ?
            ORDER BY LOWER(nome), id
            LIMIT ?
            """,
            (f"%{nome_txt}%", int(limit)),
        )
        return cur.fetchall()
    finally:
        conn.close()


def listar_empresas_payload(page=0, limit=50, search="", forma_pagamento="", status_pagamento="") -> dict:
    page_size = max(1, _safe_int(limit, 50))
    requested_page = max(0, _safe_int(page, 0))

    conn = connect()
    try:
        cur = conn.cursor()

        where_rows_sql, params_rows = _build_empresas_where_clause(
            search=search,
            forma_pagamento=forma_pagamento,
            status_pagamento=status_pagamento,
            table_alias="e",
        )
        where_status_sql, params_status = _build_empresas_where_clause(
            search=search,
            forma_pagamento=forma_pagamento,
            status_pagamento="",
            table_alias="e",
        )

        query_metrics = f"""
            WITH status_base AS (
                SELECT e.status_pagamento
                FROM empresas e
                {where_status_sql}
            )
            SELECT
                (SELECT COUNT(*) FROM empresas e {where_rows_sql}) AS total,
                COALESCE(SUM(CASE WHEN status_pagamento = 'em_dia' THEN 1 ELSE 0 END), 0) AS em_dia,
                COALESCE(SUM(CASE WHEN status_pagamento = 'pendente' THEN 1 ELSE 0 END), 0) AS pendente,
                COALESCE(SUM(CASE WHEN status_pagamento = 'inadimplente' THEN 1 ELSE 0 END), 0) AS inadimplente
            FROM status_base
        """
        cur.execute(query_metrics, tuple(params_status + params_rows))
        metrics = cur.fetchone() or (0, 0, 0, 0)
        total = int(metrics[0] or 0)
        status_counts = {
            "em_dia": int(metrics[1] or 0),
            "pendente": int(metrics[2] or 0),
            "inadimplente": int(metrics[3] or 0),
        }

        max_page = max(0, (max(0, total) - 1) // page_size)
        page_safe = min(requested_page, max_page)
        offset = page_safe * page_size

        query_rows = f"""
            SELECT
                e.id, e.cnpj, e.nome, e.telefone, e.email,
                e.logradouro, e.numero, e.bairro, e.cep, e.cidade, e.estado,
                e.forma_pagamento, e.status_pagamento, e.dia_vencimento,
                e.valor_mensal, e.data_cadastro
            FROM empresas e
            {where_rows_sql}
            ORDER BY LOWER(e.nome), e.id
            LIMIT ? OFFSET ?
        """
        cur.execute(query_rows, tuple(params_rows + [page_size, offset]))
        rows = cur.fetchall() or []

        return {
            "total": total,
            "page_safe": page_safe,
            "rows": rows,
            "status_counts": status_counts,
        }
    finally:
        conn.close()


def listar_empresas(limit=50, offset=0, search="", forma_pagamento="", status_pagamento=""):
    conn = connect()
    try:
        cur = conn.cursor()
        where_sql, params = _build_empresas_where_clause(
            search=search,
            forma_pagamento=forma_pagamento,
            status_pagamento=status_pagamento,
            table_alias="e",
        )
        query = f"""
            SELECT
                e.id, e.cnpj, e.nome, e.telefone, e.email,
                e.logradouro, e.numero, e.bairro, e.cep, e.cidade, e.estado,
                e.forma_pagamento, e.status_pagamento, e.dia_vencimento,
                e.valor_mensal, e.data_cadastro
            FROM empresas e
            {where_sql}
            ORDER BY LOWER(e.nome), e.id
            LIMIT ? OFFSET ?
        """
        cur.execute(query, tuple(params + [int(limit), int(offset)]))
        return cur.fetchall()
    finally:
        conn.close()


def contar_empresas(search="", forma_pagamento="", status_pagamento=""):
    conn = connect()
    try:
        cur = conn.cursor()
        where_sql, params = _build_empresas_where_clause(
            search=search,
            forma_pagamento=forma_pagamento,
            status_pagamento=status_pagamento,
            table_alias="e",
        )
        query = f"SELECT COUNT(*) FROM empresas e {where_sql}"
        cur.execute(query, tuple(params))
        row = cur.fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def contar_empresas_por_status(search="", forma_pagamento="") -> dict:
    """
    Retorna contagem agregada por status de pagamento para empresas,
    aplicando os mesmos filtros de busca/forma da listagem.
    """
    conn = connect()
    try:
        cur = conn.cursor()
        where_sql, params = _build_empresas_where_clause(
            search=search,
            forma_pagamento=forma_pagamento,
            status_pagamento="",
            table_alias="e",
        )
        query = f"""
            SELECT e.status_pagamento, COUNT(*)
            FROM empresas e
            {where_sql}
            GROUP BY e.status_pagamento
        """
        cur.execute(query, tuple(params))

        counts = {"em_dia": 0, "pendente": 0, "inadimplente": 0}
        for row in cur.fetchall() or []:
            key = _safe_str(row[0], "").strip().lower()
            if key in counts:
                counts[key] = int(row[1] or 0)
        return counts
    finally:
        conn.close()


# =========================
# PAGAMENTOS
# =========================
def pagamento_existe(cliente_id: int, mes_referencia: str) -> tuple[bool, dict | None]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, data_pagamento, valor_pago
            FROM pagamentos
            WHERE cliente_id = ? AND mes_referencia = ?
            LIMIT 1
        """, (int(cliente_id), _safe_str(mes_referencia).strip()))
        row = cur.fetchone()
        if not row:
            return False, None
        return True, {
            "id": int(row[0]),
            "data_pagamento": row[1],
            "valor_pago": _safe_float(row[2]),
        }
    finally:
        conn.close()


def pagamento_empresa_existe(empresa_id: int, mes_referencia: str) -> tuple[bool, dict | None]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, data_pagamento, valor_pago
            FROM pagamentos_empresas
            WHERE empresa_id = ? AND mes_referencia = ?
            LIMIT 1
            """,
            (int(empresa_id), _safe_str(mes_referencia).strip()),
        )
        row = cur.fetchone()
        if not row:
            return False, None
        return True, {
            "id": int(row[0]),
            "data_pagamento": row[1],
            "valor_pago": _safe_float(row[2]),
        }
    finally:
        conn.close()


def registrar_pagamento_com_data(cliente_id, mes_referencia, data_pagamento_iso, valor_pago):
    conn = connect()
    try:
        cursor = conn.cursor()
        mes_ref = _safe_str(mes_referencia).strip()
        data_pag = _safe_str(data_pagamento_iso).strip()
        valor = _safe_float(valor_pago)
        if len(mes_ref) != 7 or mes_ref[4] != "-":
            return False
        if len(data_pag) != 10 or data_pag[4] != "-" or data_pag[7] != "-":
            return False
        if valor <= 0:
            return False

        cursor.execute("""
            INSERT INTO pagamentos
            (cliente_id, mes_referencia, data_pagamento, valor_pago)
            VALUES (?, ?, ?, ?)
        """, (
            int(cliente_id),
            mes_ref,
            data_pag,
            valor,
        ))

        cursor.execute("""
            UPDATE clientes
            SET pagamento_status = 'em_dia'
            WHERE id = ?
        """, (int(cliente_id),))

        conn.commit()
        return True

    except Exception as e:
        print("Erro ao registrar pagamento:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def registrar_pagamento_com_data_safe(cliente_id, mes_referencia, data_pagamento_iso, valor_pago):
    conn = connect()
    try:
        cursor = conn.cursor()
        mes_ref = _safe_str(mes_referencia).strip()
        data_pag = _safe_str(data_pagamento_iso).strip()
        valor = _safe_float(valor_pago)
        if len(mes_ref) != 7 or mes_ref[4] != "-":
            return False, "Mes de referencia invalido."
        if len(data_pag) != 10 or data_pag[4] != "-" or data_pag[7] != "-":
            return False, "Data de pagamento invalida."
        if valor <= 0:
            return False, "Valor do pagamento deve ser maior que zero."

        cursor.execute("""
            SELECT id FROM pagamentos
            WHERE cliente_id = ? AND mes_referencia = ?
            LIMIT 1
        """, (int(cliente_id), mes_ref))
        row = cursor.fetchone()

        if row:
            pagamento_id = int(row[0])
            cursor.execute("""
                UPDATE pagamentos
                SET data_pagamento = ?, valor_pago = ?
                WHERE id = ?
            """, (
                data_pag,
                valor,
                pagamento_id,
            ))
            msg = "Pagamento do mes atualizado com sucesso."
        else:
            cursor.execute("""
                INSERT INTO pagamentos (cliente_id, mes_referencia, data_pagamento, valor_pago)
                VALUES (?, ?, ?, ?)
            """, (
                int(cliente_id),
                mes_ref,
                data_pag,
                valor,
            ))
            msg = "Pagamento registrado com sucesso."

        cursor.execute("""
            UPDATE clientes
            SET pagamento_status = 'em_dia'
            WHERE id = ?
        """, (int(cliente_id),))

        conn.commit()
        return True, msg

    except DB_INTEGRITY_ERRORS as e:
        try:
            conn.rollback()
        except Exception:
            pass
        msg = str(e).lower()
        if "valor_pago invalido" in msg or "valor_pago" in msg:
            return False, "Valor do pagamento deve ser maior que zero."
        if "data_pagamento invalida" in msg or "chk_pagamentos_data_fmt" in msg:
            return False, "Data de pagamento invalida."
        if "mes_referencia invalida" in msg or "chk_pagamentos_mes_ref_fmt" in msg:
            return False, "Mes de referencia invalido."
        if "pagamentos.cliente_id" in msg or "pagamentos_cliente_id_fkey" in msg:
            return False, "Cliente nao encontrado para registrar pagamento."
        if "idx_pagamentos_cliente_mes" in msg or "mes_referencia" in msg:
            return False, "Ja existe pagamento para este mes."
        return False, "Nao foi possivel registrar pagamento."
    except Exception as e:
        print("Erro ao registrar pagamento (safe):", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, "Erro ao registrar pagamento."
    finally:
        conn.close()


def buscar_ultimo_pagamento(cliente_id):
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT mes_referencia, data_pagamento, valor_pago
            FROM pagamentos
            WHERE cliente_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (int(cliente_id),))
        return cursor.fetchone()
    finally:
        conn.close()


def pagamentos_do_mes(mes_iso: str) -> list[dict]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT cliente_id, mes_referencia, data_pagamento, valor_pago
            FROM pagamentos
            WHERE mes_referencia = ?
            ORDER BY data_pagamento ASC, id ASC
        """, (_safe_str(mes_iso).strip(),))
        rows = cur.fetchall()

        out = []
        for r in rows:
            out.append({
                "cliente_id": int(r[0]),
                "mes_referencia": r[1],
                "data_pagamento": r[2],
                "valor_pago": _safe_float(r[3]),
            })
        return out
    finally:
        conn.close()


def listar_pagamentos_detalhados_mes(
    mes_iso: str,
    limit: int = 5000,
    offset: int = 0,
) -> list[dict]:
    """
    Lista pagamentos de um mês com dados do cliente para exportações/relatórios.
    """
    ref = _safe_str(mes_iso).strip()
    if len(ref) != 7 or ref[4] != "-":
        return []

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                c.id, c.nome, c.cpf, c.status, c.pagamento_status,
                p.mes_referencia, p.data_pagamento, p.valor_pago
            FROM pagamentos p
            JOIN clientes c ON c.id = p.cliente_id
            WHERE p.mes_referencia = ?
            ORDER BY p.data_pagamento DESC, p.id DESC
            LIMIT ? OFFSET ?
            """,
            (ref, _safe_int(limit, 5000), _safe_int(offset, 0)),
        )
        raw = cur.fetchall() or []
        out: list[dict] = []
        for r in raw:
            out.append(
                {
                    "mat": _safe_int(r[0], 0),
                    "nome": _safe_str(r[1]).strip(),
                    "cpf": _safe_str(r[2]).strip(),
                    "status": _safe_str(r[3]).strip(),
                    "pagamento_status": _safe_str(r[4]).strip(),
                    "mes_referencia": _safe_str(r[5]).strip(),
                    "data_pagamento": _safe_str(r[6]).strip(),
                    "valor_pago": _safe_float(r[7], 0.0),
                }
            )
        return out
    finally:
        conn.close()


def _build_financeiro_where_clause(
    mes_iso: str,
    search_doc: str = "",
    search_name: str = "",
    status_key: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    only_atrasados: bool = False,
    above_ticket: bool = False,
    ticket_ref: float = 0.0,
    only_today: bool = False,
) -> tuple[str, list]:
    ref = _safe_str(mes_iso).strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = _current_month_ref()

    where = ["p.mes_referencia = ?"]
    params: list = [ref]

    doc_txt = _safe_str(search_doc).strip()
    if doc_txt:
        term = f"%{doc_txt}%"
        digits = _normalize_cpf(doc_txt)
        if digits:
            where.append(
                "(CAST(c.id AS TEXT) LIKE ? OR c.cpf ILIKE ? OR c.cpf_norm LIKE ?)"
            )
            params.extend([term, term, f"%{digits}%"])
        else:
            where.append("(CAST(c.id AS TEXT) LIKE ? OR c.cpf ILIKE ?)")
            params.extend([term, term])

    name_txt = _safe_str(search_name).strip()
    if name_txt:
        where.append("c.nome ILIKE ?")
        params.append(f"%{name_txt}%")

    status_norm = _safe_str(status_key).strip().lower()
    if status_norm in {"ativo", "inativo"}:
        where.append("c.status = ?")
        params.append(status_norm)
    elif status_norm in {"em_dia", "atrasado"}:
        where.append("c.pagamento_status = ?")
        params.append(status_norm)

    if bool(only_atrasados):
        where.append("c.pagamento_status = 'atrasado'")

    if bool(only_today):
        where.append("p.data_pagamento = ?")
        params.append(_today_iso())

    min_num = None if min_value is None else _safe_float(min_value, 0.0)
    max_num = None if max_value is None else _safe_float(max_value, 0.0)
    if min_num is not None and max_num is not None and min_num > max_num:
        min_num, max_num = max_num, min_num
    if min_num is not None:
        where.append("p.valor_pago >= ?")
        params.append(float(min_num))
    if max_num is not None:
        where.append("p.valor_pago <= ?")
        params.append(float(max_num))

    if bool(above_ticket):
        threshold = _safe_float(ticket_ref, 0.0)
        if threshold > 0:
            where.append("p.valor_pago >= ?")
            params.append(threshold)

    return f"WHERE {' AND '.join(where)}", params


def listar_financeiro_detalhado_payload(
    mes_iso: str,
    page: int = 0,
    limit: int = 50,
    search_doc: str = "",
    search_name: str = "",
    status_key: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    only_atrasados: bool = False,
    above_ticket: bool = False,
    ticket_ref: float = 0.0,
    only_today: bool = False,
    sort_key: str = "data_pagamento",
    sort_dir: str = "desc",
) -> dict:
    ref = _safe_str(mes_iso).strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = _current_month_ref()

    page_size = max(1, _safe_int(limit, 50))
    requested_page = max(0, _safe_int(page, 0))
    where_sql, params = _build_financeiro_where_clause(
        mes_iso=ref,
        search_doc=search_doc,
        search_name=search_name,
        status_key=status_key,
        min_value=min_value,
        max_value=max_value,
        only_atrasados=only_atrasados,
        above_ticket=above_ticket,
        ticket_ref=ticket_ref,
        only_today=only_today,
    )

    sort_map = {
        "data_pagamento": "p.data_pagamento",
        "mat": "c.id",
        "nome": "LOWER(c.nome)",
        "cpf": "c.cpf_norm",
        "status": "c.status",
        "pagamento_status": "c.pagamento_status",
        "valor_pago": "p.valor_pago",
        "mes_referencia": "p.mes_referencia",
    }
    sort_col = sort_map.get(_safe_str(sort_key).strip().lower(), "p.data_pagamento")
    sort_dir_norm = "ASC" if _safe_str(sort_dir).strip().lower() == "asc" else "DESC"
    tie_dir = "ASC" if sort_dir_norm == "ASC" else "DESC"

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(p.valor_pago), 0)
            FROM pagamentos p
            JOIN clientes c ON c.id = p.cliente_id
            {where_sql}
            """,
            tuple(params),
        )
        metric = cur.fetchone() or (0, 0.0)
        total = _safe_int(metric[0], 0)
        total_valor = _safe_float(metric[1], 0.0)

        pages = max(1, ((max(0, total) - 1) // page_size) + 1) if total > 0 else 1
        max_page = max(0, pages - 1)
        page_safe = min(requested_page, max_page)
        offset = page_safe * page_size

        cur.execute(
            f"""
            SELECT
                c.id, c.nome, c.cpf, c.status, c.pagamento_status,
                p.mes_referencia, p.data_pagamento, p.valor_pago
            FROM pagamentos p
            JOIN clientes c ON c.id = p.cliente_id
            {where_sql}
            ORDER BY {sort_col} {sort_dir_norm}, p.id {tie_dir}
            LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, offset]),
        )
        raw = cur.fetchall() or []
        rows: list[dict] = []
        for r in raw:
            rows.append(
                {
                    "mat": _safe_int(r[0], 0),
                    "nome": _safe_str(r[1]).strip(),
                    "cpf": _safe_str(r[2]).strip(),
                    "status": _safe_str(r[3]).strip(),
                    "pagamento_status": _safe_str(r[4]).strip(),
                    "mes_referencia": _safe_str(r[5]).strip() or ref,
                    "data_pagamento": _safe_str(r[6]).strip(),
                    "valor_pago": _safe_float(r[7], 0.0),
                }
            )

        return {
            "mes_ref": ref,
            "rows": rows,
            "total": total,
            "total_valor": total_valor,
            "page_safe": page_safe,
            "pages": pages,
            "page_size": page_size,
            "sort_key": _safe_str(sort_key).strip().lower() or "data_pagamento",
            "sort_dir": "asc" if sort_dir_norm == "ASC" else "desc",
        }
    finally:
        conn.close()


def carregar_financeiro_mes(mes_iso: str, detail_limit: int = 500) -> dict:
    """
    Carrega payload base do painel financeiro com poucas consultas:
    - totais do mês (receita, quantidade, ticket)
    - série diária agregada
    - linhas detalhadas para tabela
    - métricas de atraso (clientes)
    """
    ref = _safe_str(mes_iso).strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = _current_month_ref()

    lim = _safe_int(detail_limit, 500)
    if lim <= 0:
        lim = 500

    conn = connect()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT COALESCE(SUM(valor_pago), 0), COUNT(*)
            FROM pagamentos
            WHERE mes_referencia = ?
            """,
            (ref,),
        )
        total_row = cur.fetchone() or (0, 0)
        receita_total = _safe_float(total_row[0], 0.0)
        pagamentos = _safe_int(total_row[1], 0)
        ticket_medio = (receita_total / pagamentos) if pagamentos else 0.0

        cur.execute(
            """
            SELECT CAST(substr(data_pagamento, 9, 2) AS INTEGER) AS dia,
                   COALESCE(SUM(valor_pago), 0) AS total
            FROM pagamentos
            WHERE mes_referencia = ?
            GROUP BY dia
            ORDER BY dia ASC
            """,
            (ref,),
        )
        daily_rows = cur.fetchall() or []
        daily_totals = []
        for r in daily_rows:
            day = _safe_int(r[0], 0)
            if day > 0:
                daily_totals.append((day, _safe_float(r[1], 0.0)))

        cur.execute(
            """
            SELECT
                c.id, c.nome, c.cpf, c.status, c.pagamento_status,
                p.data_pagamento, p.valor_pago, p.mes_referencia
            FROM pagamentos p
            JOIN clientes c ON c.id = p.cliente_id
            WHERE p.mes_referencia = ?
            ORDER BY p.data_pagamento DESC, p.id DESC
            LIMIT ?
            """,
            (ref, lim),
        )
        raw = cur.fetchall() or []
        rows = []
        for r in raw:
            rows.append(
                {
                    "mat": _safe_int(r[0], 0),
                    "nome": _safe_str(r[1]).strip(),
                    "cpf": _safe_str(r[2]).strip(),
                    "status": _safe_str(r[3]).strip(),
                    "pagamento_status": _safe_str(r[4]).strip(),
                    "data_pagamento": _safe_str(r[5]).strip(),
                    "valor_pago": _safe_float(r[6], 0.0),
                    "mes_referencia": _safe_str(r[7]).strip() or ref,
                }
            )

        # Mantém semântica atual:
        # - atraso_estimado considera apenas clientes não inativos
        # - atrasados_count considera todo cliente com pagamento_status='atrasado'
        cur.execute(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN status <> 'inativo' AND pagamento_status = 'atrasado'
                        THEN valor_mensal
                        ELSE 0
                    END
                ), 0) AS atraso_estimado,
                COALESCE(SUM(
                    CASE
                        WHEN pagamento_status = 'atrasado' THEN 1 ELSE 0
                    END
                ), 0) AS atrasados_count
            FROM clientes
            """
        )
        atraso_row = cur.fetchone() or (0, 0)
        atraso_estimado = _safe_float(atraso_row[0], 0.0)
        atrasados_count = _safe_int(atraso_row[1], 0)

        return {
            "mes_ref": ref,
            "receita_total": receita_total,
            "pagamentos": pagamentos,
            "ticket_medio": ticket_medio,
            "atraso_estimado": atraso_estimado,
            "atrasados_count": atrasados_count,
            "daily_totals": daily_totals,
            "rows": rows,
        }
    finally:
        conn.close()


def pagamentos_de_hoje() -> int:
    hoje = _today_iso()
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM pagamentos
            WHERE data_pagamento = ?
        """, (hoje,))
        return int(cur.fetchone()[0] or 0)
    finally:
        conn.close()


def _conta_row_to_dict(row) -> dict:
    return {
        "id": _safe_int(row[0], 0),
        "descricao": _safe_str(row[1], "").strip(),
        "categoria": _safe_str(row[2], "").strip(),
        "fornecedor": _safe_str(row[3], "").strip(),
        "valor_previsto": _safe_float(row[4], 0.0),
        "data_vencimento": _safe_str(row[5], "").strip(),
        "data_competencia": _safe_str(row[6], "").strip(),
        "forma_pagamento": _safe_str(row[7], "").strip(),
        "status": _normalize_conta_status(row[8], default="Pendente"),
        "recorrente": bool(row[9]),
        "periodicidade": _safe_str(row[10], "").strip(),
        "parcela_atual": _safe_int(row[11], 0) if row[11] is not None else None,
        "total_parcelas": _safe_int(row[12], 0) if row[12] is not None else None,
        "data_pagamento_real": _safe_str(row[13], "").strip(),
        "valor_pago": _safe_float(row[14], 0.0) if row[14] is not None else None,
        "observacoes": _safe_str(row[15], "").strip(),
        "criado_em": _safe_str(row[16], "").strip(),
        "atualizado_em": _safe_str(row[17], "").strip(),
    }


def _load_contas_pagar_rows() -> list[dict]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                id, descricao, categoria, fornecedor, valor_previsto,
                data_vencimento, data_competencia, forma_pagamento, status,
                recorrente, periodicidade, parcela_atual, total_parcelas,
                data_pagamento_real, valor_pago, observacoes, criado_em, atualizado_em
            FROM contas_pagar
            ORDER BY data_vencimento DESC, id DESC
        """)
        rows = cur.fetchall() or []
        out = [_conta_row_to_dict(row) for row in rows]
        for item in out:
            if item["status"] == "Pendente":
                venc = _safe_date_iso(item.get("data_vencimento"))
                if venc and venc < _today_iso():
                    item["status"] = "Vencida"
        return out
    finally:
        conn.close()


def _filter_contas_pagar_rows(
    rows: list[dict],
    *,
    mes_iso: str,
    search: str = "",
    status: str = "",
    categoria: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    only_vencidas: bool = False,
    vencem_hoje: bool = False,
    vencem_7d: bool = False,
) -> list[dict]:
    ref = _safe_str(mes_iso).strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = _current_month_ref()
    today = _today_iso()
    try:
        today_dt = datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        today_dt = datetime.now().date()

    search_txt = _safe_str(search).strip().lower()
    status_txt = _normalize_conta_status(status, default="")
    status_key = status_txt.lower()
    categoria_txt = _safe_str(categoria).strip().lower()

    min_num = None if min_value is None else _safe_float(min_value, 0.0)
    max_num = None if max_value is None else _safe_float(max_value, 0.0)
    if min_num is not None and max_num is not None and min_num > max_num:
        min_num, max_num = max_num, min_num

    out: list[dict] = []
    for row in rows:
        venc = _safe_date_iso(row.get("data_vencimento"))
        if not venc or venc[:7] != ref:
            continue
        eff_status = _conta_status_from_row(row)
        categoria_row = _safe_str(row.get("categoria"), "").strip().lower()
        if status_key and eff_status.lower() != status_key:
            continue
        if categoria_txt and categoria_txt != "todas" and categoria_row != categoria_txt:
            continue
        if search_txt:
            hay = " ".join([
                _safe_str(row.get("descricao"), "").lower(),
                _safe_str(row.get("fornecedor"), "").lower(),
            ])
            if search_txt not in hay:
                continue
        valor = _safe_float(row.get("valor_previsto"), 0.0)
        if min_num is not None and valor < min_num:
            continue
        if max_num is not None and valor > max_num:
            continue
        if only_vencidas and eff_status.lower() != "vencida":
            continue
        if vencem_hoje and venc != today:
            continue
        if vencem_7d:
            try:
                diff = (datetime.strptime(venc, "%Y-%m-%d").date() - today_dt).days
            except Exception:
                continue
            if diff < 0 or diff > 7:
                continue
        item = dict(row)
        item["status"] = eff_status
        item["data_competencia"] = _safe_str(item.get("data_competencia") or _month_ref_to_br(venc[:7])).strip()
        out.append(item)
    return out


def carregar_contas_pagar_mes(mes_iso: str, detail_limit: int = 500) -> dict:
    ref = _safe_str(mes_iso).strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = _current_month_ref()

    rows = _load_contas_pagar_rows()
    filtered = [r for r in rows if _safe_date_iso(r.get("data_vencimento"))[:7] == ref]

    total = len(filtered)
    total_valor = round(sum(_safe_float(r.get("valor_previsto"), 0.0) for r in filtered), 2)
    pagas = [r for r in filtered if _conta_status_from_row(r) == "Paga"]
    pendentes = [r for r in filtered if _conta_status_from_row(r) == "Pendente"]
    vencidas = [r for r in filtered if _conta_status_from_row(r) == "Vencida"]
    vencem_hoje = 0
    vencem_7d = 0
    for r in filtered:
        venc = _safe_date_iso(r.get("data_vencimento"))
        if not venc:
            continue
        if venc == today:
            vencem_hoje += 1
        try:
            diff = (datetime.strptime(venc, "%Y-%m-%d").date() - today_dt).days
        except Exception:
            continue
        if 0 <= diff <= 7:
            vencem_7d += 1

    daily_map: dict[int, float] = {}
    for r in filtered:
        venc = _safe_date_iso(r.get("data_vencimento"))
        if not venc:
            continue
        try:
            day = int(venc[8:10])
        except Exception:
            continue
        daily_map[day] = round(daily_map.get(day, 0.0) + _safe_float(r.get("valor_previsto"), 0.0), 2)

    try:
        year = int(ref[:4])
        month = int(ref[5:7])
        next_year = year + (1 if month == 12 else 0)
        next_month = 1 if month == 12 else month + 1
        days_in_month = (datetime(next_year, next_month, 1) - datetime(year, month, 1)).days
    except Exception:
        days_in_month = 31

    daily_series = [(f"{day:02d}", float(daily_map.get(day, 0.0))) for day in range(1, days_in_month + 1)]
    pico_dia = max(daily_series, key=lambda x: float(x[1] or 0.0)) if daily_series else ("01", 0.0)
    media = total_valor / total if total else 0.0

    return {
        "mes_ref": ref,
        "despesas_total": total_valor,
        "contas_total": total,
        "contas_pagas": len(pagas),
        "valor_pago_total": round(sum(_safe_float(r.get("valor_pago") or r.get("valor_previsto"), 0.0) for r in pagas), 2),
        "contas_pendentes": len(pendentes),
        "valor_pendente": round(sum(_safe_float(r.get("valor_previsto"), 0.0) for r in pendentes), 2),
        "contas_vencidas": len(vencidas),
        "valor_vencido": round(sum(_safe_float(r.get("valor_previsto"), 0.0) for r in vencidas), 2),
        "contas_vencem_hoje": int(vencem_hoje),
        "contas_vencem_7d": int(vencem_7d),
        "daily_series": daily_series[: max(1, int(detail_limit or 500))] if detail_limit else daily_series,
        "pico_dia": pico_dia[0],
        "pico_valor": float(pico_dia[1] or 0.0),
        "media_diaria": float(media),
        "rows": filtered[: max(1, int(detail_limit or 500))] if detail_limit else filtered,
        "rows_total": total,
    }


def listar_contas_pagar_detalhado_payload(
    mes_iso: str,
    page: int = 0,
    limit: int = 50,
    search: str = "",
    status: str = "",
    categoria: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    only_vencidas: bool = False,
    vencem_hoje: bool = False,
    vencem_7d: bool = False,
    sort_key: str = "data_vencimento",
    sort_dir: str = "asc",
) -> dict:
    ref = _safe_str(mes_iso).strip()
    if len(ref) != 7 or ref[4] != "-":
        ref = _current_month_ref()
    page_size = max(1, _safe_int(limit, 50))
    requested_page = max(0, _safe_int(page, 0))

    rows = _filter_contas_pagar_rows(
        _load_contas_pagar_rows(),
        mes_iso=ref,
        search=search,
        status=status,
        categoria=categoria,
        min_value=min_value,
        max_value=max_value,
        only_vencidas=only_vencidas,
        vencem_hoje=vencem_hoje,
        vencem_7d=vencem_7d,
    )

    sort_map = {
        "data_vencimento": lambda r: _safe_date_iso(r.get("data_vencimento")),
        "descricao": lambda r: _safe_str(r.get("descricao"), "").lower(),
        "categoria": lambda r: _safe_str(r.get("categoria"), "").lower(),
        "fornecedor": lambda r: _safe_str(r.get("fornecedor"), "").lower(),
        "forma_pagamento": lambda r: _safe_str(r.get("forma_pagamento"), "").lower(),
        "status": lambda r: _safe_str(r.get("status"), "").lower(),
        "valor_previsto": lambda r: _safe_float(r.get("valor_previsto"), 0.0),
        "data_pagamento_real": lambda r: _safe_date_iso(r.get("data_pagamento_real")),
    }
    key = _safe_str(sort_key).strip().lower() or "data_vencimento"
    reverse = _safe_str(sort_dir).strip().lower() == "desc"
    rows.sort(key=sort_map.get(key, sort_map["data_vencimento"]), reverse=reverse)

    total = len(rows)
    pages = max(1, ((max(0, total) - 1) // page_size) + 1) if total > 0 else 1
    max_page = max(0, pages - 1)
    page_safe = min(requested_page, max_page)
    offset = page_safe * page_size
    page_rows = rows[offset: offset + page_size]
    total_valor = round(sum(_safe_float(r.get("valor_previsto"), 0.0) for r in rows), 2)

    return {
        "mes_ref": ref,
        "rows": page_rows,
        "total": total,
        "total_valor": total_valor,
        "page_safe": page_safe,
        "pages": pages,
        "page_size": page_size,
        "sort_key": key,
        "sort_dir": "desc" if reverse else "asc",
    }


def _insert_conta_pagar_row(cursor, payload: dict) -> int:
    cursor.execute(
        """
        INSERT INTO contas_pagar (
            descricao, categoria, fornecedor, valor_previsto, data_vencimento,
            data_competencia, forma_pagamento, status, recorrente, periodicidade,
            parcela_atual, total_parcelas, data_pagamento_real, valor_pago,
            observacoes, criado_em, atualizado_em
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_str(payload.get("descricao"), "").strip(),
            _normalize_conta_categoria(payload.get("categoria")),
            _safe_str(payload.get("fornecedor"), "").strip(),
            float(payload.get("valor_previsto", 0.0) or 0.0),
            _safe_date_iso(payload.get("data_vencimento")) or _today_iso(),
            _safe_str(payload.get("data_competencia"), "").strip() or _to_conta_competencia(payload.get("data_vencimento")),
            _normalize_conta_forma_pagamento(payload.get("forma_pagamento")),
            _normalize_conta_status(payload.get("status"), default="Pendente"),
            1 if bool(payload.get("recorrente")) else 0,
            _normalize_conta_periodicidade(payload.get("periodicidade")) or None,
            _safe_int(payload.get("parcela_atual"), 0) or None,
            _safe_int(payload.get("total_parcelas"), 0) or None,
            _safe_date_iso(payload.get("data_pagamento_real")) or None,
            _safe_float(payload.get("valor_pago"), 0.0) if payload.get("valor_pago") is not None else None,
            _safe_str(payload.get("observacoes"), "").strip() or None,
            _safe_str(payload.get("criado_em"), "").strip() or datetime.now().isoformat(timespec="seconds"),
            _safe_str(payload.get("atualizado_em"), "").strip() or datetime.now().isoformat(timespec="seconds"),
        ),
    )
    try:
        return int(getattr(cursor, "lastrowid", 0) or 0)
    except Exception:
        return 0


def salvar_conta_pagar(payload: dict) -> tuple[bool, str, dict]:
    data = dict(payload or {})
    descricao = _safe_str(data.get("descricao"), "").strip()
    valor_previsto = _safe_float(data.get("valor_previsto"), 0.0)
    data_vencimento = _safe_date_iso(data.get("data_vencimento"))
    if not descricao:
        return False, "Descrição obrigatória.", {}
    if valor_previsto < 0:
        return False, "Valor previsto inválido.", {}
    if not data_vencimento:
        return False, "Data de vencimento obrigatória.", {}

    recurrent = bool(data.get("recorrente"))
    total_parcelas = max(1, _safe_int(data.get("total_parcelas"), 1))
    periodicidade = _normalize_conta_periodicidade(data.get("periodicidade"))
    months_step = _periodicidade_to_months(periodicidade) if recurrent else 0
    if recurrent and months_step <= 0:
        return False, "Periodicidade inválida para recorrência.", {}

    conn = connect()
    try:
        cur = conn.cursor()
        conn.commit()  # garante estado limpo caso o backend seja PostgreSQL em pool
        if _safe_int(data.get("id"), 0) > 0:
            conta_id = _safe_int(data.get("id"), 0)
            cur.execute("DELETE FROM contas_pagar WHERE id = ?", (conta_id,))
            base_count = 1
        else:
            base_count = total_parcelas if recurrent else 1

        generated_ids: list[int] = []
        for idx in range(base_count):
            current_due = _add_months_to_date(data_vencimento, months_step * idx)
            if not current_due:
                continue
            row_payload = dict(data)
            row_payload["descricao"] = descricao
            row_payload["valor_previsto"] = valor_previsto
            row_payload["data_vencimento"] = current_due
            row_payload["data_competencia"] = _to_conta_competencia(current_due)
            row_payload["status"] = _normalize_conta_status(data.get("status"), default="Pendente")
            row_payload["recorrente"] = recurrent
            row_payload["periodicidade"] = periodicidade or None
            row_payload["parcela_atual"] = idx + 1 if recurrent else None
            row_payload["total_parcelas"] = base_count if recurrent else None
            if row_payload["status"] != "Paga":
                row_payload["data_pagamento_real"] = None
                row_payload["valor_pago"] = None
            new_id = _insert_conta_pagar_row(cur, row_payload)
            generated_ids.append(new_id)

        conn.commit()
        if not generated_ids:
            return False, "Nao foi possivel salvar a conta.", {}
        return True, "Conta(s) salva(s) com sucesso.", {"ids": generated_ids, "count": len(generated_ids)}
    except DB_INTEGRITY_ERRORS as e:
        try:
            conn.rollback()
        except Exception:
            pass
        msg = str(e).lower()
        if "descricao" in msg:
            return False, "Descrição obrigatória.", {}
        if "valor_previsto" in msg:
            return False, "Valor previsto inválido.", {}
        if "data_vencimento" in msg:
            return False, "Data de vencimento inválida.", {}
        return False, "Nao foi possivel salvar a conta.", {}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Erro ao salvar conta: {e}", {}
    finally:
        conn.close()


def atualizar_conta_pagar(conta_id: int, payload: dict) -> tuple[bool, str, dict]:
    cid = _safe_int(conta_id, 0)
    if cid <= 0:
        return False, "Conta inválida.", {}
    data = dict(payload or {})
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, descricao, categoria, fornecedor, valor_previsto,
                data_vencimento, data_competencia, forma_pagamento, status,
                recorrente, periodicidade, parcela_atual, total_parcelas,
                data_pagamento_real, valor_pago, observacoes, criado_em, atualizado_em
            FROM contas_pagar
            WHERE id = ?
            LIMIT 1
            """,
            (cid,),
        )
        row = cur.fetchone()
        if not row:
            return False, "Conta não encontrada.", {}

        atual = _conta_row_to_dict(row)
        merged = dict(atual)
        merged.update(data)
        merged["descricao"] = _safe_str(merged.get("descricao"), "").strip()
        merged["valor_previsto"] = _safe_float(merged.get("valor_previsto"), 0.0)
        merged["data_vencimento"] = _safe_date_iso(merged.get("data_vencimento")) or atual.get("data_vencimento")
        merged["data_competencia"] = _safe_str(merged.get("data_competencia"), "").strip() or _to_conta_competencia(merged["data_vencimento"])
        merged["status"] = _normalize_conta_status(merged.get("status"), default=atual.get("status", "Pendente"))
        merged["categoria"] = _normalize_conta_categoria(merged.get("categoria"))
        merged["forma_pagamento"] = _normalize_conta_forma_pagamento(merged.get("forma_pagamento"))
        merged["fornecedor"] = _safe_str(merged.get("fornecedor"), "").strip()
        merged["recorrente"] = bool(merged.get("recorrente", False))
        merged["periodicidade"] = _normalize_conta_periodicidade(merged.get("periodicidade")) or None
        merged["parcela_atual"] = _safe_int(merged.get("parcela_atual"), 0) or None
        merged["total_parcelas"] = _safe_int(merged.get("total_parcelas"), 0) or None

        if merged["status"] == "Paga":
            merged["data_pagamento_real"] = _safe_date_iso(merged.get("data_pagamento_real")) or atual.get("data_pagamento_real") or _today_iso()
            merged["valor_pago"] = _safe_float(merged.get("valor_pago"), merged["valor_previsto"])
        else:
            merged["data_pagamento_real"] = None
            merged["valor_pago"] = None

        cur.execute(
            """
            UPDATE contas_pagar
            SET descricao = ?,
                categoria = ?,
                fornecedor = ?,
                valor_previsto = ?,
                data_vencimento = ?,
                data_competencia = ?,
                forma_pagamento = ?,
                status = ?,
                recorrente = ?,
                periodicidade = ?,
                parcela_atual = ?,
                total_parcelas = ?,
                data_pagamento_real = ?,
                valor_pago = ?,
                observacoes = ?,
                atualizado_em = ?
            WHERE id = ?
            """,
            (
                merged["descricao"],
                merged["categoria"],
                merged["fornecedor"],
                float(merged["valor_previsto"] or 0.0),
                merged["data_vencimento"],
                merged["data_competencia"],
                merged["forma_pagamento"],
                merged["status"],
                1 if bool(merged.get("recorrente")) else 0,
                merged["periodicidade"],
                merged["parcela_atual"],
                merged["total_parcelas"],
                merged["data_pagamento_real"],
                merged["valor_pago"],
                _safe_str(merged.get("observacoes"), "").strip() or None,
                datetime.now().isoformat(timespec="seconds"),
                cid,
            ),
        )
        conn.commit()
        return True, "Conta atualizada com sucesso.", {"id": cid}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Erro ao atualizar conta: {e}", {}
    finally:
        conn.close()


def marcar_conta_paga(conta_id: int, data_pagamento_real: str | None = None, valor_pago: float | None = None) -> tuple[bool, str, dict]:
    cid = _safe_int(conta_id, 0)
    if cid <= 0:
        return False, "Conta inválida.", {}
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, descricao, valor_previsto, data_vencimento, data_competencia,
                   forma_pagamento, status, recorrente, periodicidade, parcela_atual,
                   total_parcelas, observacoes
            FROM contas_pagar
            WHERE id = ?
            LIMIT 1
            """,
            (cid,),
        )
        row = cur.fetchone()
        if not row:
            return False, "Conta não encontrada.", {}
        pago = _safe_date_iso(data_pagamento_real) or _today_iso()
        valor = _safe_float(valor_pago, _safe_float(row[2], 0.0))
        cur.execute(
            """
            UPDATE contas_pagar
            SET status = 'Paga',
                data_pagamento_real = ?,
                valor_pago = ?,
                atualizado_em = ?
            WHERE id = ?
            """,
            (pago, valor, datetime.now().isoformat(timespec="seconds"), cid),
        )
        conn.commit()
        return True, "Conta marcada como paga.", {"id": cid, "data_pagamento_real": pago, "valor_pago": valor}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Erro ao marcar conta como paga: {e}", {}
    finally:
        conn.close()


def excluir_conta_pagar(conta_id: int) -> tuple[bool, str]:
    cid = _safe_int(conta_id, 0)
    if cid <= 0:
        return False, "Conta inválida."
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM contas_pagar WHERE id = ?", (cid,))
        conn.commit()
        if int(getattr(cur, "rowcount", 0) or 0) <= 0:
            return False, "Conta não encontrada."
        return True, "Conta excluída com sucesso."
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Erro ao excluir conta: {e}"
    finally:
        conn.close()


# =========================
# MÃ‰TRICAS
# =========================
def metricas_clientes():
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status = 'ativo' THEN 1 ELSE 0 END), 0) AS ativos,
                COALESCE(SUM(CASE WHEN pagamento_status = 'atrasado' THEN 1 ELSE 0 END), 0) AS atrasados,
                COALESCE(SUM(CASE WHEN status = 'inativo' THEN 1 ELSE 0 END), 0) AS inativos
            FROM clientes
            """
        )
        row = cursor.fetchone() or (0, 0, 0)
        ativos = int(row[0] or 0)
        atrasados = int(row[1] or 0)
        inativos = int(row[2] or 0)
        return {"ativos": ativos, "atrasados": atrasados, "inativos": inativos}
    finally:
        conn.close()


def contratos_mes_metricas(mes_ref: str | None = None) -> dict:
    mes_ref = (mes_ref or _current_month_ref()).strip()
    hoje = _today_iso()

    conn = connect()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*) as qtd,
                COALESCE(SUM(valor_mensal), 0) as soma,
                COALESCE(AVG(valor_mensal), 0) as avg
            FROM clientes
            WHERE substr(data_inicio, 1, 7) = ?
        """, (mes_ref,))
        qtd, soma, avg = cur.fetchone() or (0, 0, 0)

        cur.execute("""
            SELECT COUNT(*)
            FROM clientes
            WHERE data_inicio = ?
        """, (hoje,))
        hoje_qtd = (cur.fetchone() or [0])[0]

        return {
            "mes_ref": mes_ref,
            "fechados_mes": int(qtd or 0),
            "fechados_hoje": int(hoje_qtd or 0),
            "receita_adicionada_mes": float(soma or 0.0),
            "ticket_medio_mes": float(avg or 0.0),
        }
    finally:
        conn.close()


def receita_mes_por_dia(mes_iso: str) -> list[tuple[int, float]]:
    mes_iso = _safe_str(mes_iso).strip()
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT CAST(substr(data_pagamento, 9, 2) AS INTEGER) AS dia,
                   COALESCE(SUM(valor_pago), 0) AS total
            FROM pagamentos
            WHERE substr(data_pagamento, 1, 7) = ?
            GROUP BY dia
            ORDER BY dia ASC
        """, (mes_iso,))
        rows = cur.fetchall() or []
        return [(int(r[0]), float(r[1] or 0.0)) for r in rows]
    finally:
        conn.close()


# =========================
# DEPENDENTES
# =========================
def listar_dependentes(cliente_id: int):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, cpf, data_nascimento, idade
            FROM dependentes
            WHERE cliente_id = ?
            ORDER BY id ASC
        """, (int(cliente_id),))
        rows = cur.fetchall() or []
        out = []
        for r in rows:
            dn_iso = _safe_date_iso(r[3])
            idade = _age_from_iso(dn_iso, default=_safe_int(r[4], 0))
            out.append((r[0], r[1], r[2], idade, dn_iso))
        return out
    finally:
        conn.close()


def registrar_pagamento_empresa_com_data_safe(empresa_id, mes_referencia, data_pagamento_iso, valor_pago):
    conn = connect()
    try:
        cursor = conn.cursor()
        mes_ref = _safe_str(mes_referencia).strip()
        data_pag = _safe_str(data_pagamento_iso).strip()
        valor = _safe_float(valor_pago)
        if len(mes_ref) != 7 or mes_ref[4] != "-":
            return False, "Mes de referencia invalido."
        if len(data_pag) != 10 or data_pag[4] != "-" or data_pag[7] != "-":
            return False, "Data de pagamento invalida."
        if valor <= 0:
            return False, "Valor do pagamento deve ser maior que zero."

        empresa_id_i = int(empresa_id)
        cursor.execute("SELECT id FROM empresas WHERE id = ? LIMIT 1", (empresa_id_i,))
        if not cursor.fetchone():
            return False, "Empresa nao encontrada para registrar pagamento."

        cursor.execute(
            """
            SELECT id FROM pagamentos_empresas
            WHERE empresa_id = ? AND mes_referencia = ?
            LIMIT 1
            """,
            (empresa_id_i, mes_ref),
        )
        row = cursor.fetchone()

        if row:
            pagamento_id = int(row[0])
            cursor.execute(
                """
                UPDATE pagamentos_empresas
                SET data_pagamento = ?, valor_pago = ?
                WHERE id = ?
                """,
                (data_pag, valor, pagamento_id),
            )
            msg = "Pagamento da empresa atualizado com sucesso."
        else:
            cursor.execute(
                """
                INSERT INTO pagamentos_empresas (empresa_id, mes_referencia, data_pagamento, valor_pago)
                VALUES (?, ?, ?, ?)
                """,
                (empresa_id_i, mes_ref, data_pag, valor),
            )
            msg = "Pagamento da empresa registrado com sucesso."

        cursor.execute(
            """
            UPDATE empresas
            SET status_pagamento = 'em_dia'
            WHERE id = ?
            """,
            (empresa_id_i,),
        )

        conn.commit()
        return True, msg

    except DB_INTEGRITY_ERRORS as e:
        try:
            conn.rollback()
        except Exception:
            pass
        msg = str(e).lower()
        if "valor_pago invalido" in msg or "valor_pago" in msg:
            return False, "Valor do pagamento deve ser maior que zero."
        if "data_pagamento invalida" in msg or "chk_pagamentos_empresas_data_fmt" in msg:
            return False, "Data de pagamento invalida."
        if "mes_referencia invalida" in msg or "chk_pagamentos_empresas_mes_ref_fmt" in msg:
            return False, "Mes de referencia invalido."
        if "pagamentos_empresas.empresa_id" in msg or "pagamentos_empresas_empresa_id_fkey" in msg:
            return False, "Empresa nao encontrada para registrar pagamento."
        if "idx_pagamentos_empresas_empresa_mes" in msg or "mes_referencia" in msg:
            return False, "Ja existe pagamento da empresa para este mes."
        return False, "Nao foi possivel registrar pagamento da empresa."
    except Exception as e:
        print("Erro ao registrar pagamento da empresa (safe):", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, "Erro ao registrar pagamento da empresa."
    finally:
        conn.close()


def substituir_dependentes(cliente_id: int, dependentes: list[dict]) -> bool:
    conn = connect()
    try:
        cur = conn.cursor()

        cur.execute("DELETE FROM dependentes WHERE cliente_id = ?", (int(cliente_id),))
        vistos: set[str] = set()

        for d in dependentes or []:
            nome = _safe_str(d.get("nome")).strip()
            cpf = _safe_str(d.get("cpf")).strip()
            cpf_norm = _normalize_cpf(cpf)
            data_nascimento = _safe_date_iso(d.get("data_nascimento"))
            idade = _safe_int(d.get("idade"), -1)

            if data_nascimento:
                idade = _age_from_iso(data_nascimento, default=idade if idade >= 0 else 0)

            if not nome or len(cpf_norm) != 11:
                continue
            if not data_nascimento and idade < 0:
                continue
            if cpf_norm in vistos:
                continue
            vistos.add(cpf_norm)

            if idade < 0:
                idade = 0

            cur.execute("""
                INSERT INTO dependentes (cliente_id, nome, cpf, cpf_norm, data_nascimento, idade)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (int(cliente_id), nome, cpf, cpf_norm, data_nascimento, idade))

        conn.commit()
        return True

    except Exception as e:
        print("Erro ao substituir dependentes:", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


# =========================
# MIGRACAO SQLITE -> POSTGRESQL
# =========================
def _find_legacy_sqlite_path(sqlite_path: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if sqlite_path:
        candidates.append(Path(sqlite_path))
    candidates.extend([
        Path(LEGACY_DB_PATH),
        Path(__file__).resolve().parent / LEGACY_DB_FILENAME,
        Path(__file__).resolve().parent / "backups",
    ])

    for p in candidates:
        try:
            if p.is_dir():
                dbs = sorted([x for x in p.glob("*.db") if x.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
                if dbs:
                    return dbs[0]
            elif p.exists() and p.is_file():
                return p
        except Exception:
            continue
    return None


def _sqlite_select_all(conn_sqlite: sqlite3.Connection, table_name: str) -> tuple[list[str], list[tuple]]:
    cur = conn_sqlite.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    )
    if not cur.fetchone():
        return [], []

    cur.execute(f"SELECT * FROM {table_name}")
    rows = cur.fetchall() or []
    cols = [d[0] for d in (cur.description or [])]
    return cols, rows


def migrate_sqlite_to_postgres(
    sqlite_path: str | None = None,
    *,
    overwrite: bool = False,
    ensure_schema: bool = True,
) -> tuple[bool, str]:
    """
    Migra dados do SQLite legado para o PostgreSQL atual.
    Retorna (sucesso, mensagem).
    """
    src = _find_legacy_sqlite_path(sqlite_path)
    if not src or not src.exists():
        return False, "Arquivo SQLite legado nao encontrado."

    if ensure_schema:
        create_tables()

    sqlite_conn = sqlite3.connect(str(src))
    pg_conn = connect()
    try:
        cur_pg = pg_conn.cursor()

        cur_pg.execute("SELECT COUNT(*) FROM clientes")
        pg_clientes = int((cur_pg.fetchone() or [0])[0] or 0)
        cur_pg.execute("SELECT COUNT(*) FROM pagamentos")
        pg_pagamentos = int((cur_pg.fetchone() or [0])[0] or 0)
        cur_pg.execute("SELECT COUNT(*) FROM pagamentos_empresas")
        pg_pagamentos_empresas = int((cur_pg.fetchone() or [0])[0] or 0)
        cur_pg.execute("SELECT COUNT(*) FROM empresas")
        pg_empresas = int((cur_pg.fetchone() or [0])[0] or 0)

        if not overwrite and (pg_clientes > 0 or pg_pagamentos > 0 or pg_pagamentos_empresas > 0 or pg_empresas > 0):
            return False, "PostgreSQL ja possui dados; use overwrite=True para sobrescrever."

        if overwrite:
            cur_pg.execute(
                "TRUNCATE TABLE pagamentos_empresas, empresas, pagamentos, dependentes, clientes, usuarios "
                "RESTART IDENTITY CASCADE"
            )

        # usuarios
        cols_u, rows_u = _sqlite_select_all(sqlite_conn, "usuarios")
        if cols_u and rows_u:
            idx = {c: i for i, c in enumerate(cols_u)}
            for row in rows_u:
                pwd = row[idx.get("password", -1)] if "password" in idx else b""
                if isinstance(pwd, memoryview):
                    pwd = pwd.tobytes()
                if isinstance(pwd, bytearray):
                    pwd = bytes(pwd)
                if isinstance(pwd, str):
                    pwd = pwd.encode()
                cur_pg.execute(
                    """
                    INSERT INTO usuarios (id, username, password, nivel)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (username) DO UPDATE
                    SET password = EXCLUDED.password, nivel = EXCLUDED.nivel
                    """,
                    (
                        int(row[idx.get("id", 0)]),
                        _safe_str(row[idx.get("username", 0)]).strip(),
                        pwd,
                        _safe_str(row[idx.get("nivel", 0)]).strip() or "recepcao",
                    ),
                )

        # clientes
        cols_c, rows_c = _sqlite_select_all(sqlite_conn, "clientes")
        source_client_ids: set[int] = set()
        inserted_clientes = 0
        inserted_dependentes = 0
        inserted_pagamentos = 0
        inserted_empresas = 0
        inserted_pagamentos_empresas = 0
        skipped_dependentes_fk = 0
        skipped_pagamentos_fk = 0
        skipped_pagamentos_empresas_fk = 0
        if cols_c and rows_c:
            idx = {c: i for i, c in enumerate(cols_c)}
            for row in rows_c:
                cpf_raw = _safe_str(row[idx.get("cpf", 0)]).strip()
                cid = int(row[idx.get("id", 0)])
                source_client_ids.add(cid)
                cur_pg.execute(
                    """
                    INSERT INTO clientes
                    (id, nome, cpf, cpf_norm, telefone, email, data_inicio, valor_mensal,
                     status, pagamento_status, observacoes, data_nascimento, cep, endereco,
                     plano, dependentes, vencimento_dia, forma_pagamento)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        cid,
                        _safe_str(row[idx.get("nome", 0)]).strip(),
                        cpf_raw,
                        _normalize_cpf(row[idx.get("cpf_norm", -1)] if "cpf_norm" in idx else cpf_raw),
                        _safe_str(row[idx.get("telefone", 0)]).strip(),
                        _safe_str(row[idx.get("email", 0)]).strip(),
                        _safe_str(row[idx.get("data_inicio", 0)]).strip(),
                        _safe_float(row[idx.get("valor_mensal", 0)], 0.0),
                        (_safe_str(row[idx.get("status", -1)] if "status" in idx else "ativo").strip() or "ativo"),
                        (_safe_str(row[idx.get("pagamento_status", -1)] if "pagamento_status" in idx else "em_dia").strip() or "em_dia"),
                        _safe_str(row[idx.get("observacoes", -1)] if "observacoes" in idx else ""),
                        _safe_str(row[idx.get("data_nascimento", -1)] if "data_nascimento" in idx else None),
                        _safe_str(row[idx.get("cep", -1)] if "cep" in idx else None),
                        _safe_str(row[idx.get("endereco", -1)] if "endereco" in idx else None),
                        _safe_str(row[idx.get("plano", -1)] if "plano" in idx else None),
                        _safe_int(row[idx.get("dependentes", -1)] if "dependentes" in idx else 0, 0),
                        _safe_int(row[idx.get("vencimento_dia", -1)] if "vencimento_dia" in idx else 10, 10),
                        _safe_str(row[idx.get("forma_pagamento", -1)] if "forma_pagamento" in idx else None),
                    ),
                )
                if getattr(cur_pg, "rowcount", 0) > 0:
                    inserted_clientes += 1

        # dependentes
        cols_d, rows_d = _sqlite_select_all(sqlite_conn, "dependentes")
        if cols_d and rows_d:
            idx = {c: i for i, c in enumerate(cols_d)}
            for row in rows_d:
                cpf_raw = _safe_str(row[idx.get("cpf", 0)]).strip()
                cliente_id = _safe_int(row[idx.get("cliente_id", 0)], 0)
                if cliente_id not in source_client_ids:
                    skipped_dependentes_fk += 1
                    continue
                cur_pg.execute(
                    """
                    INSERT INTO dependentes
                    (id, cliente_id, nome, cpf, cpf_norm, data_nascimento, idade)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        int(row[idx.get("id", 0)]),
                        cliente_id,
                        _safe_str(row[idx.get("nome", 0)]).strip(),
                        cpf_raw,
                        _normalize_cpf(row[idx.get("cpf_norm", -1)] if "cpf_norm" in idx else cpf_raw),
                        _safe_str(row[idx.get("data_nascimento", -1)] if "data_nascimento" in idx else None),
                        max(0, _safe_int(row[idx.get("idade", -1)] if "idade" in idx else 0, 0)),
                    ),
                )
                if getattr(cur_pg, "rowcount", 0) > 0:
                    inserted_dependentes += 1

        # pagamentos
        cols_p, rows_p = _sqlite_select_all(sqlite_conn, "pagamentos")
        if cols_p and rows_p:
            idx = {c: i for i, c in enumerate(cols_p)}
            for row in rows_p:
                cliente_id = _safe_int(row[idx.get("cliente_id", 0)], 0)
                if cliente_id not in source_client_ids:
                    skipped_pagamentos_fk += 1
                    continue
                cur_pg.execute(
                    """
                    INSERT INTO pagamentos
                    (id, cliente_id, mes_referencia, data_pagamento, valor_pago)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        int(row[idx.get("id", 0)]),
                        cliente_id,
                        _safe_str(row[idx.get("mes_referencia", 0)]).strip(),
                        _safe_str(row[idx.get("data_pagamento", 0)]).strip(),
                        _safe_float(row[idx.get("valor_pago", 0)], 0.0),
                    ),
                )
                if getattr(cur_pg, "rowcount", 0) > 0:
                    inserted_pagamentos += 1

        # empresas
        cols_e, rows_e = _sqlite_select_all(sqlite_conn, "empresas")
        source_empresa_ids: set[int] = set()
        if cols_e and rows_e:
            idx = {c: i for i, c in enumerate(cols_e)}
            for row in rows_e:
                eid = _safe_int(row[idx.get("id", 0)], 0)
                if eid <= 0:
                    continue

                cnpj_raw = _safe_str(row[idx.get("cnpj", -1)] if "cnpj" in idx else "").strip()
                cnpj_norm = _normalize_cnpj(
                    row[idx.get("cnpj_norm", -1)] if "cnpj_norm" in idx else cnpj_raw
                )
                if not cnpj_raw:
                    continue

                forma = _safe_str(row[idx.get("forma_pagamento", -1)] if "forma_pagamento" in idx else "").strip().lower()
                if forma not in {"pix", "boleto", "recepcao"}:
                    forma = "boleto"

                status = _safe_str(row[idx.get("status_pagamento", -1)] if "status_pagamento" in idx else "").strip().lower()
                if status not in {"em_dia", "pendente", "inadimplente"}:
                    status = "em_dia"

                dia_venc = _safe_int(row[idx.get("dia_vencimento", -1)] if "dia_vencimento" in idx else 10, 10)
                dia_venc = max(1, min(31, dia_venc))

                data_cadastro = _safe_str(
                    row[idx.get("data_cadastro", -1)] if "data_cadastro" in idx else _today_iso()
                ).strip()
                if not _safe_date_iso(data_cadastro):
                    data_cadastro = _today_iso()

                cur_pg.execute(
                    """
                    INSERT INTO empresas
                    (id, cnpj, cnpj_norm, nome, telefone, email, logradouro, numero, bairro, cep,
                     cidade, estado, forma_pagamento, status_pagamento, dia_vencimento, valor_mensal, data_cadastro)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        eid,
                        cnpj_raw,
                        cnpj_norm,
                        _safe_str(row[idx.get("nome", -1)] if "nome" in idx else "").strip(),
                        _safe_str(row[idx.get("telefone", -1)] if "telefone" in idx else "").strip(),
                        _safe_str(row[idx.get("email", -1)] if "email" in idx else "").strip(),
                        _safe_str(row[idx.get("logradouro", -1)] if "logradouro" in idx else "").strip(),
                        _safe_str(row[idx.get("numero", -1)] if "numero" in idx else "").strip(),
                        _safe_str(row[idx.get("bairro", -1)] if "bairro" in idx else "").strip(),
                        _safe_str(row[idx.get("cep", -1)] if "cep" in idx else "").strip(),
                        _safe_str(row[idx.get("cidade", -1)] if "cidade" in idx else "").strip(),
                        _safe_str(row[idx.get("estado", -1)] if "estado" in idx else "").strip(),
                        forma,
                        status,
                        dia_venc,
                        _safe_str(row[idx.get("valor_mensal", -1)] if "valor_mensal" in idx else "0").strip() or "0",
                        data_cadastro,
                    ),
                )
                if getattr(cur_pg, "rowcount", 0) > 0:
                    source_empresa_ids.add(eid)
                    inserted_empresas += 1

        # pagamentos_empresas
        cols_pe, rows_pe = _sqlite_select_all(sqlite_conn, "pagamentos_empresas")
        if cols_pe and rows_pe:
            idx = {c: i for i, c in enumerate(cols_pe)}
            for row in rows_pe:
                empresa_id = _safe_int(row[idx.get("empresa_id", 0)], 0)
                if empresa_id <= 0 or empresa_id not in source_empresa_ids:
                    skipped_pagamentos_empresas_fk += 1
                    continue

                valor_pago = _safe_float(row[idx.get("valor_pago", 0)], 0.0)
                if valor_pago <= 0:
                    continue

                mes_ref = _safe_str(row[idx.get("mes_referencia", 0)]).strip()
                data_pag = _safe_str(row[idx.get("data_pagamento", 0)]).strip()
                if not mes_ref or not data_pag:
                    continue

                cur_pg.execute(
                    """
                    INSERT INTO pagamentos_empresas
                    (empresa_id, mes_referencia, data_pagamento, valor_pago)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (empresa_id, mes_ref, data_pag, valor_pago),
                )
                if getattr(cur_pg, "rowcount", 0) > 0:
                    inserted_pagamentos_empresas += 1

        _backfill_cpf_norm(cur_pg)
        _backfill_empresas_cnpj_norm(cur_pg)
        _sync_dependentes_count(cur_pg)
        for table_name in ("usuarios", "clientes", "dependentes", "pagamentos", "pagamentos_empresas", "empresas"):
            try:
                _sync_id_sequence(cur_pg, table_name)
            except Exception:
                pass
        _set_user_version(cur_pg, SCHEMA_VERSION)
        pg_conn.commit()

        cur_pg.execute("SELECT COUNT(*) FROM clientes")
        cli_total = int((cur_pg.fetchone() or [0])[0] or 0)
        cur_pg.execute("SELECT COUNT(*) FROM pagamentos")
        pag_total = int((cur_pg.fetchone() or [0])[0] or 0)
        cur_pg.execute("SELECT COUNT(*) FROM empresas")
        emp_total = int((cur_pg.fetchone() or [0])[0] or 0)
        cur_pg.execute("SELECT COUNT(*) FROM pagamentos_empresas")
        pag_emp_total = int((cur_pg.fetchone() or [0])[0] or 0)
        return True, (
            f"Migracao concluida: clientes={cli_total}, pagamentos={pag_total}, "
            f"empresas={emp_total}, pagamentos_empresas={pag_emp_total}, origem='{src}', "
            f"inseridos(clientes={inserted_clientes}, dependentes={inserted_dependentes}, "
            f"pagamentos={inserted_pagamentos}, empresas={inserted_empresas}, "
            f"pagamentos_empresas={inserted_pagamentos_empresas}), "
            f"pulados_fk(dependentes={skipped_dependentes_fk}, pagamentos={skipped_pagamentos_fk}, "
            f"pagamentos_empresas={skipped_pagamentos_empresas_fk})."
        )
    except Exception as e:
        try:
            pg_conn.rollback()
        except Exception:
            pass
        return False, f"Falha na migracao SQLite->PostgreSQL: {e}"
    finally:
        try:
            sqlite_conn.close()
        except Exception:
            pass
        try:
            pg_conn.close()
        except Exception:
            pass


def migrate_sqlite_to_postgres_if_needed(sqlite_path: str | None = None) -> tuple[bool, str]:
    src = _find_legacy_sqlite_path(sqlite_path)
    if not src or not src.exists():
        return False, "SQLite legado nao encontrado; nada para migrar."

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM clientes")
        cli = int((cur.fetchone() or [0])[0] or 0)
        cur.execute("SELECT COUNT(*) FROM pagamentos")
        pag = int((cur.fetchone() or [0])[0] or 0)
        cur.execute("SELECT COUNT(*) FROM pagamentos_empresas")
        pag_emp = int((cur.fetchone() or [0])[0] or 0)
        cur.execute("SELECT COUNT(*) FROM empresas")
        emp = int((cur.fetchone() or [0])[0] or 0)
    finally:
        conn.close()

    if cli > 0 or pag > 0 or pag_emp > 0 or emp > 0:
        return False, "PostgreSQL ja possui dados; migracao automatica ignorada."

    return migrate_sqlite_to_postgres(str(src), overwrite=False, ensure_schema=False)

