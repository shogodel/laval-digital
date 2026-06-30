"""Alembic environment config — supports both SQLite and PostgreSQL backends.

Reads ``DATABASE_URL`` env var (same logic as ``core/database.py``)
to determine which database backend to connect to.
"""
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_db_url() -> str:
    """Mirror of ``core.database._resolve_db_url()`` for Alembic standalone use."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    path = os.environ.get(
        "SHOPIFY_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "shopify.db"),
    )
    return f"sqlite:///{Path(path).as_posix()}"


db_url = _resolve_db_url()
is_sqlite = db_url.startswith("sqlite://")

config.set_main_option("sqlalchemy.url", db_url)

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
            transaction_per_migration=not is_sqlite,
        )
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
