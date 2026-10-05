"""Configuracion de los tests. La configuracion de la app se lee al importarla: estas variables se fijan
antes de importar jzbill.

Los tests que usan la base corren solo con JZB_TEST_DB=1 y un PostgreSQL de prueba DESCARTABLE en
POSTGRES_HOST/POSTGRES_PORT/POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD: cada test borra el esquema
public entero (por eso POSTGRES_DB tiene que terminar en _test). Ver README, seccion Desarrollo."""

import asyncio
import os

import pytest

os.environ.setdefault("COOKIES_SECURE", "false")   # TestClient habla por http://testserver
os.environ.setdefault("SETUP_TOKEN", "token-de-prueba-123456")
os.environ.setdefault("POSTGRES_DB", "jzbill_test")
os.environ["JZBILL_ENV_FILE"] = os.devnull       # nunca leer el .env de una instalacion

SETUP_TOKEN = os.environ["SETUP_TOKEN"]
CON_BASE = os.getenv("JZB_TEST_DB") == "1"


def _resetear_base() -> None:
    import asyncpg

    from jzbill import config

    if not config.POSTGRES_DB.endswith("_test"):
        raise RuntimeError("Los tests borran la base: POSTGRES_DB tiene que terminar en _test.")

    async def _borrar():
        conn = await asyncpg.connect(host=config.POSTGRES_HOST, port=config.POSTGRES_PORT, database=config.POSTGRES_DB,
                                     user=config.POSTGRES_USER, password=config.POSTGRES_PASSWORD)
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        finally:
            await conn.close()

    asyncio.run(_borrar())


def csrf(cliente) -> dict:
    return {"X-CSRF-Token": cliente.cookies.get("csrf_token", "")}


@pytest.fixture
def nuevo_cliente():
    """Fabrica de clientes HTTP con cookies propias (como dispositivos distintos) contra una base vacia.
    Solo el primero arranca la app (pool y migraciones): los demas usan el mismo pool."""
    if not CON_BASE:
        pytest.skip("Sin base de prueba (JZB_TEST_DB=1).")
    _resetear_base()
    from fastapi.testclient import TestClient

    from jzbill.main import app

    principal = TestClient(app)
    principal.__enter__()
    entregados = []

    def _crear():
        if not entregados:
            c = principal
        else:
            # Mismo loop de eventos que el principal: el pool de asyncpg queda atado al loop en que se creo.
            c = TestClient(app)
            c.portal = principal.portal
        entregados.append(c)
        return c

    yield _crear
    principal.__exit__(None, None, None)


@pytest.fixture
def ejecutar_sql():
    """Corre SQL directo en la base de prueba (para preparar casos, por ejemplo desactivar un usuario)."""
    import asyncpg

    from jzbill import config

    def _ejecutar(sql: str, *args):
        async def _correr():
            conn = await asyncpg.connect(host=config.POSTGRES_HOST, port=config.POSTGRES_PORT,
                                         database=config.POSTGRES_DB, user=config.POSTGRES_USER,
                                         password=config.POSTGRES_PASSWORD)
            try:
                return await conn.fetch(sql, *args)
            finally:
                await conn.close()
        return asyncio.run(_correr())

    return _ejecutar


@pytest.fixture
def admin(nuevo_cliente):
    """Cliente con sesion del administrador inicial (usuario 'admin', clave 'clave-inicial-1')."""
    c = nuevo_cliente()
    r = c.post("/api/auth/setup/admin", json={"token": SETUP_TOKEN, "usuario": "Admin", "nombre": "Administrador",
                                              "clave": "clave-inicial-1"})
    assert r.status_code == 200, r.text
    return c
