"""Conexion con ARCA por razon social y modo (solo administrador): estado de los servidores (FEDummy) y del
ticket, prueba de conexion (pide el ticket al WSAA), desbloqueo despues de corregir un rechazo, actualizacion de
los parametros fiscales (FEParamGet*) y ultimo comprobante autorizado de un punto de venta.

Los errores de ARCA se informan con su codigo (por ejemplo coe.notAuthorized) para que el administrador sepa que
corregir; nunca con token, sign ni contenido de certificados."""

import asyncio
import logging
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from jzbill import config
from jzbill.arca import parametros, servicio, soap, wsfev1
from jzbill.auth import client_ip, registrar
from jzbill.db import get_conn
from jzbill.permisos import razon_social_visible, require_admin, uuid_o_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/razones-sociales/{razon_social_id}/arca", tags=["ARCA"])
router_parametros = APIRouter(prefix="/api/parametros-fiscales", tags=["ARCA"])

Modo = Literal["empresa", "prueba"]


class ConModo(BaseModel):
    modo: Modo


def _error(e: soap.ErrorArca) -> HTTPException:
    if isinstance(e, servicio.SinCertificado):
        return HTTPException(409, e.mensaje)
    if isinstance(e, servicio.Bloqueado):
        return HTTPException(429, f"{e.mensaje} Último error: {e.codigo}.")
    if isinstance(e, soap.ErrorRed):
        return HTTPException(502, f"No se pudo hablar con ARCA ({e.codigo}).")
    return HTTPException(502, f"ARCA respondió: {e.mensaje} ({e.codigo}).")


@router.get("/estado")
async def estado(razon_social_id: str, modo: Modo = Query(...), admin: dict = Depends(require_admin),
                 conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    try:
        servidores = await asyncio.to_thread(wsfev1.dummy, config.ARCA_URLS[modo]["wsfe"])
    except soap.ErrorArca as e:
        servidores = {"error": e.codigo}
    return {"modo": modo, "servidores": servidores, **await servicio.estado(conn, rs["id"], modo)}


@router.post("/conectar")
async def conectar(razon_social_id: str, data: ConModo, request: Request, admin: dict = Depends(require_admin),
                   conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    try:
        await servicio.credenciales(conn, rs, data.modo)
    except soap.ErrorArca as e:
        await registrar(conn, admin["id"], admin["usuario"], "ARCA_CONEXION",
                        f"Modo {data.modo}: rechazada ({e.codigo}).", client_ip(request), rs["id"])
        raise _error(e)
    await registrar(conn, admin["id"], admin["usuario"], "ARCA_CONEXION", f"Modo {data.modo}: correcta.",
                    client_ip(request), rs["id"])
    return await servicio.estado(conn, rs["id"], data.modo)


@router.post("/desbloquear")
async def desbloquear(razon_social_id: str, data: ConModo, request: Request, admin: dict = Depends(require_admin),
                      conn: asyncpg.Connection = Depends(get_conn)):
    """Despues de corregir en ARCA la causa de un rechazo (por ejemplo, asociar el certificado al servicio)."""
    rs = await razon_social_visible(conn, admin, razon_social_id)
    await servicio.desbloquear(conn, rs["id"], data.modo)
    await registrar(conn, admin["id"], admin["usuario"], "ARCA_DESBLOQUEO", f"Modo {data.modo}.",
                    client_ip(request), rs["id"])
    return await servicio.estado(conn, rs["id"], data.modo)


@router.post("/parametros")
async def actualizar_parametros(razon_social_id: str, data: ConModo, request: Request,
                                admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    try:
        resultado = await parametros.actualizar(conn, rs, data.modo, admin)
    except soap.ErrorArca as e:
        raise _error(e)
    await registrar(conn, admin["id"], admin["usuario"], "PARAMETROS_FISCALES",
                    f"Modo {data.modo}: version {resultado['version']}"
                    + (" (nueva)." if resultado["nueva"] else " (sin cambios)."), client_ip(request), rs["id"])
    return resultado


@router.get("/ultimo-autorizado")
async def ultimo_autorizado(razon_social_id: str, modo: Modo = Query(...), punto_venta_id: str = Query(..., max_length=40),
                            tipo_comprobante: int = Query(..., ge=1, le=999), admin: dict = Depends(require_admin),
                            conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    numero_pv = await conn.fetchval("SELECT numero FROM puntos_venta WHERE id = $1 AND razon_social_id = $2",
                                    uuid_o_404(punto_venta_id), rs["id"])
    if numero_pv is None:
        raise HTTPException(404, "No encontrado.")
    try:
        credenciales = await servicio.credenciales(conn, rs, modo)
        numero = await asyncio.to_thread(wsfev1.ultimo_autorizado, config.ARCA_URLS[modo]["wsfe"], credenciales,
                                         numero_pv, tipo_comprobante)
    except soap.ErrorArca as e:
        raise _error(e)
    return {"punto_venta": numero_pv, "tipo_comprobante": tipo_comprobante, "ultimo_numero": numero}


@router_parametros.get("")
async def parametros_vigentes(modo: Modo = Query(...), admin: dict = Depends(require_admin),
                              conn: asyncpg.Connection = Depends(get_conn)):
    vigentes = await parametros.vigentes(conn, modo)
    if vigentes is None:
        raise HTTPException(404, "Todavía no se leyeron los parámetros fiscales de ARCA para este modo.")
    return vigentes
