"""Denegar por defecto: toda ruta exige sesion salvo las publicas marcadas a proposito en
jzfactura.main.RUTAS_PUBLICAS. No necesita base de datos.

OJO: desde FastAPI 0.141 los routers incluidos aparecen en app.routes como un solo objeto
_IncludedRouter, sin `path` ni `dependant`, y jztech_core.deny_by_default 0.1.5 los saltea: el chequeo
pasaria aunque una ruta de un router quedara abierta. Por eso aca se aplanan las rutas efectivas antes de
pasarselas al core, y test_el_chequeo_detecta_rutas_abiertas prueba que el chequeo realmente detecta una
ruta abierta dentro de un router (si una version nueva de FastAPI cambia esto, ese test falla)."""

from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI
import pytest
from jztech_core.deny_by_default import assert_all_routes_protected

from jzfactura.auth import require_usuario
from jzfactura.main import RUTAS_PUBLICAS, app

# Copia a proposito: agregar una ruta publica obliga a tocar tambien este test (y pensarlo dos veces).
PUBLICAS_ESPERADAS = {
    "/",
    "/panel",
    "/api/health",
    "/api/auth/setup/status",
    "/api/auth/setup/admin",
    "/api/auth/login",
}


def rutas_efectivas(aplicacion) -> list:
    """Rutas de la app con los routers incluidos ya desplegados (path completo y dependencias de router)."""
    salida = []
    for ruta in aplicacion.routes:
        contextos = getattr(ruta, "effective_route_contexts", None)
        salida.extend(contextos() if contextos else [ruta])
    return salida


def verificar(aplicacion, publicas, dependencia) -> None:
    assert_all_routes_protected(SimpleNamespace(routes=rutas_efectivas(aplicacion)), publicas, dependencia)


def test_todas_las_rutas_exigen_sesion():
    verificar(app, RUTAS_PUBLICAS, require_usuario)


def test_el_chequeo_ve_las_rutas_de_los_routers():
    rutas = {getattr(r, "path", None) for r in rutas_efectivas(app)}
    assert {"/api/auth/me", "/api/auth/logout", "/api/auth/clave", "/api/auth/sesiones/cerrar"} <= rutas


def test_el_chequeo_detecta_rutas_abiertas():
    def sesion():
        return 1

    protegido = APIRouter(prefix="/p", dependencies=[Depends(sesion)])
    abierto = APIRouter(prefix="/a")

    @protegido.get("/x")
    def x():
        return 1

    @abierto.get("/y")
    def y():
        return 1

    prueba = FastAPI()
    prueba.include_router(protegido)
    verificar(prueba, [], sesion)   # dependencia a nivel router: cuenta como protegida
    prueba.include_router(abierto, prefix="/v1")
    with pytest.raises(AssertionError, match="/v1/a/y"):
        verificar(prueba, [], sesion)


def test_lista_de_publicas_sin_cambios():
    assert set(RUTAS_PUBLICAS) == PUBLICAS_ESPERADAS


def test_las_publicas_existen():
    """Una ruta publica que ya no existe es una marca vieja: si vuelve a aparecer con otro uso quedaria
    abierta sin que nadie lo decida."""
    rutas = {getattr(r, "path", None) for r in rutas_efectivas(app)}
    assert set(RUTAS_PUBLICAS) <= rutas


def test_sin_documentacion_publica():
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
