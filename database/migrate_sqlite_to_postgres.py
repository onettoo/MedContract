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
        description="Migra dados do SQLite legado para PostgreSQL (MedContract)."
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help="Caminho do arquivo .db legado (opcional).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobrescreve dados existentes no PostgreSQL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        db.create_tables()
    except Exception as e:
        print(f"[erro] Nao foi possivel inicializar schema PostgreSQL: {e}")
        return 1

    ok, msg = db.migrate_sqlite_to_postgres(
        sqlite_path=args.sqlite_path,
        overwrite=bool(args.overwrite),
        ensure_schema=False,
    )

    level = "ok" if ok else "aviso"
    print(f"[{level}] {msg}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
