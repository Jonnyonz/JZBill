"""Sucursales: locales fisicos, compartidos por varias razones sociales. En cada sucursal, cada razon social
que factura ahi tiene un punto de venta predeterminado (el que se elige solo al entrar a cobrar). Un punto de
venta esta en un solo local. Crear y modificar: administrador. Ver: el administrador todas; los demas, las
sucursales que tienen asignadas (y en ellas solo las razones sociales a las que acceden).

Las listas de precios y las promociones por sucursal llegan en la Fase 5 (articulos y ofertas)."""

from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.db import get_conn
from jzbill.permisos import es_admin, require_admin, uuid_o_404

router = APIRouter(prefix="/api/sucursales", tags=["Sucursales"])


class SucursalNueva(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    domicilio: str = Field(default="", max_length=300)


class SucursalCambios(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=120)
    domicilio: Optional[str] = Field(default=None, max_length=300)
    activa: Optional[bool] = None


class Predeterminado(BaseModel):
    razon_social_id: str = Field(max_length=40)
    punto_venta_id: str = Field(max_length=40)


class Predeterminados(BaseModel):
    puntos_venta: List[Predeterminado] = Field(max_length=200)


async def _predeterminados(conn: asyncpg.Connection, sucursal_id, usuario: dict) -> list:
    filas = await conn.fetch("""
        SELECT spv.razon_social_id, rs.nombre_legal, rs.nombre_fantasia, rs.color, spv.punto_venta_id, pv.numero
        FROM sucursal_puntos_venta spv
        JOIN razones_sociales rs ON rs.id = spv.razon_social_id
        JOIN puntos_venta pv ON pv.id = spv.punto_venta_id
        WHERE spv.sucursal_id = $1
          AND ($2 OR (rs.activa AND EXISTS (SELECT 1 FROM usuario_accesos a
                                            WHERE a.usuario_id = $3 AND a.razon_social_id = rs.id)))
        ORDER BY rs.nombre_legal
    """, sucursal_id, es_admin(usuario), usuario["id"])
    return [{"razon_social_id": str(f["razon_social_id"]), "nombre_legal": f["nombre_legal"],
             "nombre_fantasia": f["nombre_fantasia"], "color": f["color"],
             "punto_venta_id": str(f["punto_venta_id"]), "numero": f["numero"]} for f in filas]


async def _salida(conn: asyncpg.Connection, fila, usuario: dict) -> dict:
    return {"id": str(fila["id"]), "nombre": fila["nombre"], "domicilio": fila["domicilio"], "activa": fila["activa"],
            "puntos_venta": await _predeterminados(conn, fila["id"], usuario)}


async def sucursal_visible(conn: asyncpg.Connection, usuario: dict, sucursal_id) -> asyncpg.Record:
    """La sucursal si el usuario puede verla; si no (o no existe), 404."""
    s_id = uuid_o_404(sucursal_id)
    if es_admin(usuario):
        fila = await conn.fetchrow("SELECT * FROM sucursales WHERE id = $1", s_id)
    else:
        fila = await conn.fetchrow("""
            SELECT s.* FROM sucursales s JOIN usuario_sucursales us ON us.sucursal_id = s.id AND us.usuario_id = $2
            WHERE s.id = $1 AND s.activa
        """, s_id, usuario["id"])
    if fila is None:
        raise HTTPException(404, "No encontrado.")
    return fila


@router.get("")
async def listar(usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    if es_admin(usuario):
        filas = await conn.fetch("SELECT * FROM sucursales ORDER BY nombre")
    else:
        filas = await conn.fetch("""
            SELECT s.* FROM sucursales s JOIN usuario_sucursales us ON us.sucursal_id = s.id AND us.usuario_id = $1
            WHERE s.activa ORDER BY s.nombre
        """, usuario["id"])
    return [await _salida(conn, f, usuario) for f in filas]


@router.post("", status_code=201)
async def crear(data: SucursalNueva, request: Request, admin: dict = Depends(require_admin),
                conn: asyncpg.Connection = Depends(get_conn)):
    nombre = data.nombre.strip()
    if not nombre:
        raise HTTPException(400, "Falta el nombre.")
    async with conn.transaction():
        try:
            fila = await conn.fetchrow("INSERT INTO sucursales (nombre, domicilio) VALUES ($1, $2) RETURNING *",
                                       nombre, data.domicilio.strip())
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe una sucursal con ese nombre.")
        await registrar(conn, admin["id"], admin["usuario"], "SUCURSAL_ALTA", f"Alta de la sucursal {nombre}.",
                        client_ip(request))
    return await _salida(conn, fila, admin)


@router.get("/{sucursal_id}")
async def ver(sucursal_id: str, usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    return await _salida(conn, await sucursal_visible(conn, usuario, sucursal_id), usuario)


@router.put("/{sucursal_id}")
async def modificar(sucursal_id: str, data: SucursalCambios, request: Request, admin: dict = Depends(require_admin),
                    conn: asyncpg.Connection = Depends(get_conn)):
    actual = await sucursal_visible(conn, admin, sucursal_id)
    nombre = actual["nombre"] if data.nombre is None else data.nombre.strip()
    if not nombre:
        raise HTTPException(400, "Falta el nombre.")
    domicilio = actual["domicilio"] if data.domicilio is None else data.domicilio.strip()
    activa = actual["activa"] if data.activa is None else data.activa
    async with conn.transaction():
        try:
            fila = await conn.fetchrow("""
                UPDATE sucursales SET nombre = $2, domicilio = $3, activa = $4, actualizado_en = now()
                WHERE id = $1 RETURNING *
            """, actual["id"], nombre, domicilio, activa)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe una sucursal con ese nombre.")
        await registrar(conn, admin["id"], admin["usuario"], "SUCURSAL_CAMBIO", f"Sucursal {nombre}.",
                        client_ip(request))
    return await _salida(conn, fila, admin)


@router.put("/{sucursal_id}/puntos-venta")
async def asignar_puntos_venta(sucursal_id: str, data: Predeterminados, request: Request,
                               admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    """Reemplaza las razones sociales que facturan en la sucursal y su punto de venta predeterminado."""
    sucursal = await sucursal_visible(conn, admin, sucursal_id)
    filas, vistas = [], set()
    for item in data.puntos_venta:
        rs_id, pv_id = uuid_o_404(item.razon_social_id), uuid_o_404(item.punto_venta_id)
        if rs_id in vistas:
            raise HTTPException(400, "Una razón social aparece dos veces.")
        vistas.add(rs_id)
        if not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM puntos_venta WHERE id = $1 AND razon_social_id = $2)",
                                   pv_id, rs_id):
            raise HTTPException(400, "Un punto de venta no pertenece a su razón social.")
        filas.append((sucursal["id"], rs_id, pv_id))
    async with conn.transaction():
        await conn.execute("DELETE FROM sucursal_puntos_venta WHERE sucursal_id = $1", sucursal["id"])
        try:
            if filas:
                await conn.executemany("""
                    INSERT INTO sucursal_puntos_venta (sucursal_id, razon_social_id, punto_venta_id) VALUES ($1, $2, $3)
                """, filas)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Un punto de venta ya es el predeterminado de otra sucursal.")
        await registrar(conn, admin["id"], admin["usuario"], "SUCURSAL_PUNTOS_VENTA",
                        f"Sucursal {sucursal['nombre']}: {len(filas)} razones sociales.", client_ip(request))
    return await _salida(conn, sucursal, admin)
