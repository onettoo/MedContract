from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import database.db as db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configura MEDCONTRACT_DATABASE_URL no .env e prepara PostgreSQL em nuvem."
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="URL PostgreSQL completa (ex.: postgresql://user:pass@host/db?sslmode=require).",
    )
    parser.add_argument(
        "--env-file",
        default=str(ROOT_DIR / ".env"),
        help="Arquivo .env de destino.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=str(ROOT_DIR / "database" / "medcontract.db"),
        help="Caminho do SQLite legado para migrar dados.",
    )
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Não migra dados do SQLite (apenas conecta e cria schema).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobrescreve dados existentes no PostgreSQL durante migração.",
    )
    return parser.parse_args()


def upsert_env_var(env_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    found = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)

    if not found:
        out.append(f"{key}={value}")

    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    env_path = Path(args.env_file)
    env_path.parent.mkdir(parents=True, exist_ok=True)

    upsert_env_var(env_path, "MEDCONTRACT_DATABASE_URL", args.database_url.strip())
    upsert_env_var(env_path, "MEDCONTRACT_AUTO_MIGRATE_SQLITE", "0")
    print(f"[ok] .env atualizado: {env_path}")

    # Exporta no processo atual para os próximos passos.
    import os
    os.environ["MEDCONTRACT_DATABASE_URL"] = args.database_url.strip()

    try:
        conn = db.connect()
        conn.close()
        print("[ok] conexão PostgreSQL validada")
    except Exception as e:
        print(f"[erro] falha na conexão PostgreSQL: {e}")
        return 1

    try:
        db.create_tables()
        print("[ok] schema PostgreSQL criado/validado")
    except Exception as e:
        print(f"[erro] falha ao criar schema: {e}")
        return 1

    if args.skip_migration:
        print("[ok] migração de dados ignorada (--skip-migration)")
        return 0

    ok, msg = db.migrate_sqlite_to_postgres(
        sqlite_path=args.sqlite_path,
        overwrite=bool(args.overwrite),
        ensure_schema=False,
    )
    print(("[ok] " if ok else "[erro] ") + msg)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
