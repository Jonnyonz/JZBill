"""Pool de PostgreSQL y migraciones versionadas (db/NNNN_descripcion.sql en la raiz del repo, jztech_core)."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import asyncpg
from fastapi import HTTPException
from jztech_core.migrations import apply_migrations

from jzfactura import config

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db"


class DB:
    pool: Optional[asyncpg.Pool] = None


class ConexionComoPool:
    """Las funciones de jztech_core piden un pool; asi usan la conexion que ya tiene el request."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


async def iniciar() -> None:
    """Conecta (reintenta: Postgres puede tardar en arrancar) y aplica las migraciones. Si una migracion
    falla, el arranque se corta con el error en el log."""
    for intento in range(10):
        try:
            DB.pool = await asyncpg.create_pool(
                host=config.POSTGRES_HOST, port=config.POSTGRES_PORT, database=config.POSTGRES_DB,
                user=config.POSTGRES_USER, password=config.POSTGRES_PASSWORD, min_size=1, max_size=config.DB_POOL_MAX)
            break
        except (OSError, asyncpg.PostgresError) as e:
            logger.warning(f"[DB] Intento {intento + 1}/10 de conexion a PostgreSQL fallido: {e!r}")
            await asyncio.sleep(2)
    if DB.pool is None:
        raise RuntimeError("No se pudo conectar a PostgreSQL.")
    async with DB.pool.acquire() as conn:
        aplicadas = await apply_migrations(ConexionComoPool(conn), MIGRATIONS_DIR)
    if aplicadas:
        logger.info(f"[DB] Migraciones aplicadas: {aplicadas}")


async def cerrar() -> None:
    if DB.pool is not None:
        await DB.pool.close()
        DB.pool = None


async def get_conn():
    if DB.pool is None:
        raise HTTPException(503, "La base de datos no está disponible.")
    async with DB.pool.acquire() as conn:
        yield conn
