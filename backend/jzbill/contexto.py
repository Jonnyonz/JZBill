"""Contexto de trabajo de cada sesion (cada terminal el suyo): razon social, modo (empresa / prueba), sucursal y
punto de venta. Se cambia desde el selector "division empresa" bajo el avatar.

Eleccion automatica: si la sesion no tiene contexto, se elige solo, para que el cajero entre y cobre sin tocar
nada: la primera razon social del usuario (preferentemente una que facture en su sucursal predeterminada), en
modo empresa si lo tiene, su sucursal predeterminada y el punto de venta predeterminado de esa sucursal para
esa razon social. Todo se vuelve a validar en cada pedido: si un administrador quita un acceso, el contexto deja
de valer en el acto y se vuelve a elegir. Los cambios de contexto quedan en la auditoria.

contexto_requerido() es la dependencia que van a usar las pantallas que trabajan sobre el contexto (facturacion,
caja, reportes)."""

import hashlib
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.cuit import formatear_cuit
from jzbill.db import get_conn
from jzbill.permisos import MODOS, es_admin, modos_permitidos, puntos_venta_visibles, razon_social_y_modo, uuid_o_404

router = APIRouter(prefix="/api/contexto", tags=["Contexto"])


class Eleccion(BaseModel):
    razon_social_id: str = Field(max_length=40)
    modo: Literal["empresa", "prueba"]
    sucursal_id: Optional[str] = Field(default=None, max_length=40)
    punto_venta_id: Optional[str] = Field(default=None, max_length=40)


def _hash_sesion(token: str) -> str:
    """Mismo hash con que jztech_core guarda la sesion (jztech_sessions.token_hash)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _opciones(conn: asyncpg.Connection, usuario: dict) -> list:
    """Razones sociales activas a las que el usuario puede entrar, con sus modos."""
    filas = await conn.fetch("""
        SELECT rs.id, rs.cuit, rs.nombre_legal, rs.nombre_fantasia, rs.color,
               COALESCE((SELECT array_agg(a.modo ORDER BY a.modo) FROM usuario_accesos a
                         WHERE a.usuario_id = $1 AND a.razon_social_id = rs.id), '{}') AS modos
        FROM razones_sociales rs
        WHERE rs.activa AND ($2 OR EXISTS (SELECT 1 FROM usuario_accesos a
                                           WHERE a.usuario_id = $1 AND a.razon_social_id = rs.id))
        ORDER BY rs.nombre_legal
    """, usuario["id"], es_admin(usuario))
    return [{"razon_social_id": str(f["id"]), "cuit": formatear_cuit(f["cuit"]), "nombre_legal": f["nombre_legal"],
             "nombre_fantasia": f["nombre_fantasia"], "color": f["color"],
             "modos": list(MODOS) if es_admin(usuario) else [m for m in MODOS if m in f["modos"]]} for f in filas]


async def _sucursales(conn: asyncpg.Connection, usuario: dict) -> list:
    """Sucursales activas del usuario (administrador: todas), con las razones sociales que facturan en cada una."""
    filas = await conn.fetch("""
        SELECT s.id, s.nombre, COALESCE(us.predeterminada, false) AS predeterminada,
               COALESCE((SELECT array_agg(spv.razon_social_id::text) FROM sucursal_puntos_venta spv
                         WHERE spv.sucursal_id = s.id), '{}') AS razones
        FROM sucursales s LEFT JOIN usuario_sucursales us ON us.sucursal_id = s.id AND us.usuario_id = $1
        WHERE s.activa AND ($2 OR us.usuario_id IS NOT NULL)
        ORDER BY COALESCE(us.predeterminada, false) DESC, s.nombre
    """, usuario["id"], es_admin(usuario))
    return [{"sucursal_id": str(f["id"]), "nombre": f["nombre"], "predeterminada": f["predeterminada"],
             "razones_sociales": list(f["razones"])} for f in filas]


async def _punto_venta_para(conn: asyncpg.Connection, usuario: dict, rs_id, sucursal_id) -> Optional[asyncpg.Record]:
    """Punto de venta predeterminado de la sucursal para la razon social, si el usuario puede usarlo. Si no hay y
    el usuario tiene un solo punto de venta activo posible en esa razon social, ese."""
    visibles = await puntos_venta_visibles(conn, usuario, rs_id, solo_activos=True)
    if sucursal_id is not None:
        pv_id = await conn.fetchval(
            "SELECT punto_venta_id FROM sucursal_puntos_venta WHERE sucursal_id = $1 AND razon_social_id = $2",
            sucursal_id, rs_id)
        elegido = next((pv for pv in visibles if pv["id"] == pv_id), None)
        if elegido is not None:
            return elegido
    return visibles[0] if len(visibles) == 1 else None


async def _guardar(conn: asyncpg.Connection, usuario: dict, rs_id, modo: str, sucursal_id, pv) -> None:
    await conn.execute("""
        INSERT INTO sesion_contexto (token_hash, razon_social_id, modo, sucursal_id, punto_venta_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (token_hash) DO UPDATE SET razon_social_id = $2, modo = $3, sucursal_id = $4,
                                               punto_venta_id = $5, elegido_en = now()
    """, _hash_sesion(usuario["token"]), rs_id, modo, sucursal_id, pv["id"] if pv else None)


async def _autoelegir(conn: asyncpg.Connection, usuario: dict, ip: str) -> bool:
    opciones = [o for o in await _opciones(conn, usuario) if o["modos"]]
    if not opciones:
        return False
    sucursales = await _sucursales(conn, usuario)
    predeterminada = next((s for s in sucursales if s["predeterminada"]), None)
    opcion = opciones[0]
    if predeterminada:
        opcion = next((o for o in opciones if o["razon_social_id"] in predeterminada["razones_sociales"]), opcion)
    modo = "empresa" if "empresa" in opcion["modos"] else opcion["modos"][0]
    rs_id = uuid_o_404(opcion["razon_social_id"])
    sucursal_id = uuid_o_404(predeterminada["sucursal_id"]) if predeterminada else None
    pv = await _punto_venta_para(conn, usuario, rs_id, sucursal_id)
    async with conn.transaction():
        await _guardar(conn, usuario, rs_id, modo, sucursal_id, pv)
        await registrar(conn, usuario["id"], usuario["usuario"], "CONTEXTO",
                        f"Elegido automáticamente: {opcion['cuit']}, modo {modo}.", ip, rs_id)
    return True


async def _leer(conn: asyncpg.Connection, usuario: dict):
    """Contexto guardado de esta sesion si sigue siendo valido; si dejo de serlo, se borra y devuelve None."""
    token_hash = _hash_sesion(usuario["token"])
    fila = await conn.fetchrow("""
        SELECT c.razon_social_id, c.modo, c.sucursal_id, c.punto_venta_id, rs.cuit, rs.nombre_legal, rs.nombre_fantasia,
               rs.color, rs.activa, s.nombre AS sucursal_nombre, s.activa AS sucursal_activa, pv.numero
        FROM sesion_contexto c
        JOIN razones_sociales rs ON rs.id = c.razon_social_id
        LEFT JOIN sucursales s ON s.id = c.sucursal_id
        LEFT JOIN puntos_venta pv ON pv.id = c.punto_venta_id
        WHERE c.token_hash = $1
    """, token_hash)
    if fila is None:
        return None
    valido = fila["activa"] and fila["modo"] in await modos_permitidos(conn, usuario, fila["razon_social_id"])
    if valido and fila["sucursal_id"] is not None:
        valido = fila["sucursal_activa"] and (es_admin(usuario) or await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM usuario_sucursales WHERE usuario_id = $1 AND sucursal_id = $2)",
            usuario["id"], fila["sucursal_id"]))
    if valido and fila["punto_venta_id"] is not None:
        visibles = await puntos_venta_visibles(conn, usuario, fila["razon_social_id"], solo_activos=True)
        valido = any(pv["id"] == fila["punto_venta_id"] for pv in visibles)
    if not valido:
        await conn.execute("DELETE FROM sesion_contexto WHERE token_hash = $1", token_hash)
        return None
    return {"razon_social_id": str(fila["razon_social_id"]), "cuit": formatear_cuit(fila["cuit"]),
            "nombre_legal": fila["nombre_legal"], "nombre_fantasia": fila["nombre_fantasia"], "color": fila["color"],
            "modo": fila["modo"],
            "sucursal_id": str(fila["sucursal_id"]) if fila["sucursal_id"] else None,
            "sucursal_nombre": fila["sucursal_nombre"],
            "punto_venta_id": str(fila["punto_venta_id"]) if fila["punto_venta_id"] else None,
            "punto_venta_numero": fila["numero"]}


async def _actual(conn: asyncpg.Connection, usuario: dict, ip: str = ""):
    actual = await _leer(conn, usuario)
    if actual is None and await _autoelegir(conn, usuario, ip):
        actual = await _leer(conn, usuario)
    if actual is not None and actual["punto_venta_id"] is None:
        # El contexto se eligio cuando no habia punto de venta posible (por ejemplo, antes de que el administrador lo
        # creara): si ahora hay uno que corresponde, se completa solo, sin volver a elegir desde el avatar.
        pv = await _punto_venta_para(conn, usuario, uuid_o_404(actual["razon_social_id"]),
                                     uuid_o_404(actual["sucursal_id"]) if actual["sucursal_id"] else None)
        if pv is not None:
            await conn.execute("UPDATE sesion_contexto SET punto_venta_id = $2 WHERE token_hash = $1",
                               _hash_sesion(usuario["token"]), pv["id"])
            actual = await _leer(conn, usuario)
    return actual


async def contexto_requerido(request: Request, usuario: dict = Depends(require_usuario),
                             conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    actual = await _actual(conn, usuario, client_ip(request))
    if actual is None:
        raise HTTPException(409, "No tiene razones sociales asignadas.")
    return {**actual, "usuario": usuario}


@router.get("")
async def ver(request: Request, usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    return {"actual": await _actual(conn, usuario, client_ip(request)), "opciones": await _opciones(conn, usuario),
            "sucursales": await _sucursales(conn, usuario)}


@router.put("")
async def elegir(data: Eleccion, request: Request, usuario: dict = Depends(require_usuario),
                 conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_y_modo(conn, usuario, data.razon_social_id, data.modo)
    if not rs["activa"]:
        raise HTTPException(404, "No encontrado.")
    sucursales = await _sucursales(conn, usuario)
    if data.sucursal_id:
        sucursal = next((s for s in sucursales if s["sucursal_id"] == str(uuid_o_404(data.sucursal_id))), None)
        if sucursal is None:
            raise HTTPException(404, "No encontrado.")
    else:
        sucursal = next((s for s in sucursales if s["predeterminada"]), None)
    sucursal_id = uuid_o_404(sucursal["sucursal_id"]) if sucursal else None
    if data.punto_venta_id:
        pv_id = uuid_o_404(data.punto_venta_id)
        pv = next((p for p in await puntos_venta_visibles(conn, usuario, rs["id"], solo_activos=True) if p["id"] == pv_id),
                  None)
        if pv is None:
            raise HTTPException(404, "No encontrado.")
    else:
        pv = await _punto_venta_para(conn, usuario, rs["id"], sucursal_id)
    anterior = await _leer(conn, usuario)
    async with conn.transaction():
        await _guardar(conn, usuario, rs["id"], data.modo, sucursal_id, pv)
        nuevo = (str(rs["id"]), data.modo, str(sucursal_id) if sucursal_id else None, str(pv["id"]) if pv else None)
        previo = (anterior["razon_social_id"], anterior["modo"], anterior["sucursal_id"], anterior["punto_venta_id"]) \
            if anterior else None
        if previo != nuevo:
            detalle = f"Trabaja en {formatear_cuit(rs['cuit'])}, modo {data.modo}"
            if sucursal:
                detalle += f", sucursal {sucursal['nombre']}"
            if pv:
                detalle += f", punto de venta {pv['numero']:05d}"
            await registrar(conn, usuario["id"], usuario["usuario"], "CONTEXTO", detalle + ".", client_ip(request), rs["id"])
    return {"actual": await _leer(conn, usuario)}
