"""Selector "division empresa" (bajo el avatar): razon social y modo (empresa / prueba) con que trabaja cada
sesion. Se guarda por sesion (cada terminal el suyo) y se vuelve a validar en cada pedido: si un administrador
quita el acceso, deja de valer en el acto. Cambiar de razon social o de modo queda en la auditoria.

contexto_requerido() es la dependencia que van a usar las pantallas que trabajan sobre la razon social
elegida (facturacion, caja, reportes)."""

import hashlib
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.cuit import formatear_cuit
from jzbill.db import get_conn
from jzbill.permisos import MODOS, es_admin, modos_permitidos, razon_social_y_modo

router = APIRouter(prefix="/api/contexto", tags=["Contexto"])


class Eleccion(BaseModel):
    razon_social_id: str = Field(max_length=40)
    modo: Literal["empresa", "prueba"]


def _hash_sesion(token: str) -> str:
    """Mismo hash con que jztech_core guarda la sesion (jztech_sessions.token_hash)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _opciones(conn: asyncpg.Connection, usuario: dict) -> list:
    if es_admin(usuario):
        filas = await conn.fetch(
            "SELECT id, cuit, nombre_legal, nombre_fantasia FROM razones_sociales WHERE activa ORDER BY nombre_legal")
        return [{"razon_social_id": str(f["id"]), "cuit": formatear_cuit(f["cuit"]), "nombre_legal": f["nombre_legal"],
                 "nombre_fantasia": f["nombre_fantasia"], "modos": list(MODOS)} for f in filas]
    filas = await conn.fetch("""
        SELECT rs.id, rs.cuit, rs.nombre_legal, rs.nombre_fantasia, array_agg(a.modo ORDER BY a.modo) AS modos
        FROM usuario_accesos a JOIN razones_sociales rs ON rs.id = a.razon_social_id
        WHERE a.usuario_id = $1 AND rs.activa
        GROUP BY rs.id ORDER BY rs.nombre_legal
    """, usuario["id"])
    return [{"razon_social_id": str(f["id"]), "cuit": formatear_cuit(f["cuit"]), "nombre_legal": f["nombre_legal"],
             "nombre_fantasia": f["nombre_fantasia"], "modos": [m for m in MODOS if m in f["modos"]]} for f in filas]


async def _actual(conn: asyncpg.Connection, usuario: dict):
    """Contexto elegido en esta sesion, solo si sigue permitido (si no, se descarta)."""
    token_hash = _hash_sesion(usuario["token"])
    fila = await conn.fetchrow("""
        SELECT c.razon_social_id, c.modo, rs.cuit, rs.nombre_legal, rs.nombre_fantasia, rs.activa
        FROM sesion_contexto c JOIN razones_sociales rs ON rs.id = c.razon_social_id
        WHERE c.token_hash = $1
    """, token_hash)
    if fila is None:
        return None
    if not fila["activa"] or fila["modo"] not in await modos_permitidos(conn, usuario, fila["razon_social_id"]):
        await conn.execute("DELETE FROM sesion_contexto WHERE token_hash = $1", token_hash)
        return None
    return {"razon_social_id": str(fila["razon_social_id"]), "cuit": formatear_cuit(fila["cuit"]),
            "nombre_legal": fila["nombre_legal"], "nombre_fantasia": fila["nombre_fantasia"], "modo": fila["modo"]}


async def contexto_requerido(usuario: dict = Depends(require_usuario),
                             conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    actual = await _actual(conn, usuario)
    if actual is None:
        raise HTTPException(409, "Elegí una razón social y un modo.")
    return {**actual, "usuario": usuario}


@router.get("")
async def ver(usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    return {"actual": await _actual(conn, usuario), "opciones": await _opciones(conn, usuario)}


@router.put("")
async def elegir(data: Eleccion, request: Request, usuario: dict = Depends(require_usuario),
                 conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_y_modo(conn, usuario, data.razon_social_id, data.modo)
    if not rs["activa"]:
        raise HTTPException(404, "No encontrado.")
    anterior = await _actual(conn, usuario)
    async with conn.transaction():
        await conn.execute("""
            INSERT INTO sesion_contexto (token_hash, razon_social_id, modo) VALUES ($1, $2, $3)
            ON CONFLICT (token_hash) DO UPDATE SET razon_social_id = $2, modo = $3, elegido_en = now()
        """, _hash_sesion(usuario["token"]), rs["id"], data.modo)
        if anterior is None or anterior["razon_social_id"] != str(rs["id"]) or anterior["modo"] != data.modo:
            await registrar(conn, usuario["id"], usuario["usuario"], "CONTEXTO",
                            f"Trabaja en {formatear_cuit(rs['cuit'])}, modo {data.modo}.", client_ip(request), rs["id"])
    return {"actual": await _actual(conn, usuario)}
