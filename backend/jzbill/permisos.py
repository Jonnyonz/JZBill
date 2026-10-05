"""Autorizacion por rol (global por usuario) y por acceso a razon social, modo y punto de venta.

Regla (leccion de la Fase 1 anterior): cada endpoint autoriza por rol Y por razon social. Una razon social a
la que el usuario no tiene acceso responde 404, igual que una que no existe: no se confirma que IDs existen.

Roles: administrador (configura todo y entra a todas las razones sociales), supervisor, cajero y
solo_lectura (entran solo a las razones sociales y modos que les asigne un administrador)."""

import uuid
from typing import Optional

import asyncpg
from fastapi import Depends, HTTPException

from jzbill.auth import require_usuario

ROLES = ("administrador", "supervisor", "cajero", "solo_lectura")
MODOS = ("empresa", "prueba")

NO_ENCONTRADO = "No encontrado."


def require_rol(*roles: str):
    """Dependencia: sesion valida (require_usuario, con CSRF en escrituras) y uno de los roles indicados."""
    desconocidos = set(roles) - set(ROLES)
    if desconocidos:
        raise ValueError(f"Roles desconocidos: {desconocidos}")

    async def _dependencia(usuario: dict = Depends(require_usuario)) -> dict:
        if usuario["rol"] not in roles:
            raise HTTPException(403, "No tiene permiso para esta acción.")
        return usuario

    return _dependencia


require_admin = require_rol("administrador")


def es_admin(usuario: dict) -> bool:
    return usuario["rol"] == "administrador"


def uuid_o_404(valor) -> uuid.UUID:
    try:
        return uuid.UUID(str(valor))
    except ValueError:
        raise HTTPException(404, NO_ENCONTRADO)


async def razon_social_visible(conn: asyncpg.Connection, usuario: dict, razon_social_id) -> asyncpg.Record:
    """La razon social si el usuario puede verla; si no (o no existe), 404."""
    rs_id = uuid_o_404(razon_social_id)
    if es_admin(usuario):
        fila = await conn.fetchrow("SELECT * FROM razones_sociales WHERE id = $1", rs_id)
    else:
        fila = await conn.fetchrow("""
            SELECT rs.* FROM razones_sociales rs
            WHERE rs.id = $1 AND rs.activa
              AND EXISTS (SELECT 1 FROM usuario_accesos a WHERE a.usuario_id = $2 AND a.razon_social_id = rs.id)
        """, rs_id, usuario["id"])
    if fila is None:
        raise HTTPException(404, NO_ENCONTRADO)
    return fila


async def modos_permitidos(conn: asyncpg.Connection, usuario: dict, razon_social_id: uuid.UUID) -> list:
    if es_admin(usuario):
        return list(MODOS)
    filas = await conn.fetch("SELECT modo FROM usuario_accesos WHERE usuario_id = $1 AND razon_social_id = $2",
                             usuario["id"], razon_social_id)
    presentes = {f["modo"] for f in filas}
    return [m for m in MODOS if m in presentes]


async def puntos_venta_visibles(conn: asyncpg.Connection, usuario: dict, razon_social_id: uuid.UUID,
                                solo_activos: bool = False) -> list:
    """Puntos de venta de la razon social que el usuario puede usar. Si el usuario no tiene restriccion por
    punto de venta en esa razon social (o es administrador), todos."""
    if not es_admin(usuario):
        restringidos = await conn.fetch("""
            SELECT pv.* FROM puntos_venta pv
            JOIN usuario_puntos_venta upv ON upv.punto_venta_id = pv.id AND upv.usuario_id = $2
            WHERE pv.razon_social_id = $1
            ORDER BY pv.numero
        """, razon_social_id, usuario["id"])
        if restringidos:
            return [pv for pv in restringidos if pv["activo"] or not solo_activos]
    return list(await conn.fetch(
        "SELECT * FROM puntos_venta WHERE razon_social_id = $1 AND ($2 = false OR activo) ORDER BY numero",
        razon_social_id, solo_activos))


async def razon_social_y_modo(conn: asyncpg.Connection, usuario: dict, razon_social_id,
                              modo: Optional[str]) -> asyncpg.Record:
    """Razon social visible y modo permitido para el usuario; si no, 404 (sin distinguir el motivo)."""
    fila = await razon_social_visible(conn, usuario, razon_social_id)
    if modo not in MODOS or modo not in await modos_permitidos(conn, usuario, fila["id"]):
        raise HTTPException(404, NO_ENCONTRADO)
    return fila
