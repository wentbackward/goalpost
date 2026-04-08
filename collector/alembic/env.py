import asyncio
import os
import sys
from pathlib import Path

# Ensure the project root (/app) is on sys.path so `src` is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from src.models import Base

target_metadata = Base.metadata

# Use env var, fall back to alembic.ini
db_url = os.getenv(
    "COLLECTOR_DATABASE_URL",
    "postgresql+asyncpg://social:changeme@localhost:5432/social_analytics",
)


def run_migrations_offline():
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="analytics",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="analytics",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    engine = create_async_engine(db_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
        await connection.commit()
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
