from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.engine import Engine


def _bootstrap_path() -> Path:
    current = Path(__file__).resolve()
    backend_root = current.parents[1]
    project_root = current.parents[2]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return backend_root


BACKEND_ROOT = _bootstrap_path()

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402


def _load_source_engine(source_path: Path) -> Engine:
    return create_engine(f"sqlite:///{source_path.as_posix()}")


def _load_target_engine() -> Engine:
    if not settings.database_url.startswith("mysql"):
        raise RuntimeError(f"Target DB is not MySQL: {settings.database_url}")
    return create_engine(settings.database_url, pool_pre_ping=True)


def _ensure_mysql_database_exists() -> None:
    url = settings.database_url
    # mysql+pymysql://user:pass@host:port/dbname?charset=utf8mb4
    if not url.startswith("mysql+pymysql://"):
        return
    after_scheme = url[len("mysql+pymysql://") :]
    auth_host, db_part = after_scheme.split("/", 1)
    db_name = db_part.split("?", 1)[0]
    admin_url = f"mysql+pymysql://{auth_host}/?charset=utf8mb4"
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )


def _clear_target_tables(target_engine: Engine) -> None:
    metadata = MetaData()
    metadata.reflect(bind=target_engine)
    with target_engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM `{table.name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def _default_for_missing_column(column) -> object:
    name = column.name.lower()
    if name == "storage_provider":
        return "minio"
    if name == "file_size":
        return 0

    default = getattr(column, "default", None)
    if default is not None and getattr(default, "is_scalar", False):
        return default.arg

    python_type = None
    try:
        python_type = column.type.python_type
    except Exception:
        python_type = None

    if python_type is int:
        return 0
    if python_type is float:
        return 0.0
    if python_type is bool:
        return False
    if python_type is str:
        return ""
    if python_type is datetime:
        return datetime.utcnow()

    # Final fallback for non-nullable unknown types.
    return ""


def migrate(source_path: Path, batch_size: int = 1000) -> None:
    if not source_path.exists():
        raise FileNotFoundError(f"Source sqlite db not found: {source_path}")

    _ensure_mysql_database_exists()
    target_engine = _load_target_engine()

    # Ensure target tables exist from ORM metadata.
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=target_engine)
    _clear_target_tables(target_engine)

    source_engine = _load_source_engine(source_path)
    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)
    target_meta = MetaData()
    target_meta.reflect(bind=target_engine)

    migrated_total = 0
    with source_engine.connect() as src_conn, target_engine.begin() as tgt_conn:
        tgt_conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for src_table in source_meta.sorted_tables:
            table_name = src_table.name
            if table_name not in target_meta.tables:
                print(f"[SKIP] {table_name}: target table not found")
                continue
            tgt_table: Table = target_meta.tables[table_name]
            src_cols = [c.name for c in src_table.columns]
            tgt_cols = {c.name for c in tgt_table.columns}
            common_cols = [c for c in src_cols if c in tgt_cols]
            if not common_cols:
                print(f"[SKIP] {table_name}: no common columns")
                continue
            missing_required_cols = [
                c
                for c in tgt_table.columns
                if c.name not in common_cols
                and not c.nullable
                and not c.primary_key
                and getattr(c, "autoincrement", False) is not True
            ]
            if missing_required_cols:
                print(
                    f"[INFO] {table_name}: filling missing required columns "
                    + ", ".join(c.name for c in missing_required_cols)
                )

            count = 0
            offset = 0
            while True:
                rows = src_conn.execute(
                    select(*[src_table.c[c] for c in common_cols]).offset(offset).limit(batch_size)
                ).mappings().all()
                if not rows:
                    break
                payload = []
                for r in rows:
                    record = dict(r)
                    for c in missing_required_cols:
                        record[c.name] = _default_for_missing_column(c)
                    payload.append(record)
                tgt_conn.execute(tgt_table.insert(), payload)
                count += len(payload)
                offset += batch_size
            migrated_total += count
            print(f"[OK] {table_name}: {count} rows")
        tgt_conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    print(f"\nMigration completed. Total rows migrated: {migrated_total}")


def main() -> None:
    default_source = BACKEND_ROOT / "carbon_ai.db"
    parser = argparse.ArgumentParser(description="Migrate SQLite data to MySQL")
    parser.add_argument(
        "--source",
        type=Path,
        default=default_source,
        help=f"SQLite file path (default: {default_source})",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    migrate(source_path=args.source.resolve(), batch_size=args.batch_size)


if __name__ == "__main__":
    main()
