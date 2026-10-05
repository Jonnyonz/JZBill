"""Razones sociales (emisores) y sus puntos de venta. Ver: cualquier rol, solo las razones sociales a las
que tiene acceso. Crear y modificar: administrador. El CUIT no se cambia despues del alta (es la identidad
fiscal del emisor; los comprobantes van a quedar atados a el)."""

from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.cuit import formatear_cuit, normalizar_cuit
from jzbill.db import get_conn
from jzbill.permisos import (es_admin, modos_permitidos, puntos_venta_visibles, razon_social_visible,
                             require_admin, uuid_o_404)

router = APIRouter(prefix="/api/razones-sociales", tags=["Razones sociales"])

CondicionIva = Literal["responsable_inscripto", "monotributo", "exento"]
# Paleta para distinguir razones sociales (barra superior del panel): primero los primarios (rojo, azul,
# amarillo), despues los secundarios (verde, naranja, violeta) y otros. Misma lista que la migracion 0003.
PALETA = ("#d32f2f", "#1565c0", "#f9a825", "#2e7d32", "#ef6c00", "#6a1b9a",
          "#0288d1", "#c2185b", "#6d4c41", "#546e7a")
_COLOR = r"^#[0-9a-fA-F]{6}$"


class RazonSocialNueva(BaseModel):
    cuit: str = Field(max_length=20)
    nombre_legal: str = Field(min_length=1, max_length=200)
    nombre_fantasia: str = Field(default="", max_length=200)
    condicion_iva: CondicionIva
    domicilio: str = Field(default="", max_length=300)
    regimen_arba_bsas: bool = False
    color: Optional[str] = Field(default=None, pattern=_COLOR)


class RazonSocialCambios(BaseModel):
    nombre_legal: Optional[str] = Field(default=None, min_length=1, max_length=200)
    nombre_fantasia: Optional[str] = Field(default=None, max_length=200)
    condicion_iva: Optional[CondicionIva] = None
    domicilio: Optional[str] = Field(default=None, max_length=300)
    regimen_arba_bsas: Optional[bool] = None
    activa: Optional[bool] = None
    color: Optional[str] = Field(default=None, pattern=_COLOR)


class PuntoVentaNuevo(BaseModel):
    numero: int = Field(ge=1, le=99999)
    descripcion: str = Field(default="", max_length=120)


class PuntoVentaCambios(BaseModel):
    descripcion: Optional[str] = Field(default=None, max_length=120)
    activo: Optional[bool] = None


def _rs_salida(fila, modos: list) -> dict:
    return {
        "id": str(fila["id"]),
        "cuit": fila["cuit"],
        "cuit_formateado": formatear_cuit(fila["cuit"]),
        "nombre_legal": fila["nombre_legal"],
        "nombre_fantasia": fila["nombre_fantasia"],
        "condicion_iva": fila["condicion_iva"],
        "domicilio": fila["domicilio"],
        "regimen_arba_bsas": fila["regimen_arba_bsas"],
        "activa": fila["activa"],
        "color": fila["color"],
        "modos": modos,
    }


def _pv_salida(fila) -> dict:
    return {"id": str(fila["id"]), "numero": fila["numero"], "descripcion": fila["descripcion"],
            "activo": fila["activo"]}


@router.get("")
async def listar(usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    if es_admin(usuario):
        filas = await conn.fetch("SELECT * FROM razones_sociales ORDER BY nombre_legal")
    else:
        filas = await conn.fetch("""
            SELECT rs.* FROM razones_sociales rs
            WHERE rs.activa AND EXISTS (SELECT 1 FROM usuario_accesos a
                                        WHERE a.usuario_id = $1 AND a.razon_social_id = rs.id)
            ORDER BY rs.nombre_legal
        """, usuario["id"])
    return [_rs_salida(f, await modos_permitidos(conn, usuario, f["id"])) for f in filas]


@router.post("", status_code=201)
async def crear(data: RazonSocialNueva, request: Request, admin: dict = Depends(require_admin),
                conn: asyncpg.Connection = Depends(get_conn)):
    cuit = normalizar_cuit(data.cuit)
    if cuit is None:
        raise HTTPException(400, "CUIT inválido.")
    nombre = data.nombre_legal.strip()
    if not nombre:
        raise HTTPException(400, "Falta el nombre legal.")
    async with conn.transaction():
        color = data.color.lower() if data.color else PALETA[
            await conn.fetchval("SELECT count(*) FROM razones_sociales") % len(PALETA)]
        try:
            fila = await conn.fetchrow("""
                INSERT INTO razones_sociales (cuit, nombre_legal, nombre_fantasia, condicion_iva, domicilio,
                                              regimen_arba_bsas, color)
                VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *
            """, cuit, nombre, data.nombre_fantasia.strip(), data.condicion_iva, data.domicilio.strip(),
                data.regimen_arba_bsas, color)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe una razón social con ese CUIT.")
        await registrar(conn, admin["id"], admin["usuario"], "RAZON_SOCIAL_ALTA",
                        f"Alta de {formatear_cuit(cuit)}.", client_ip(request), fila["id"])
    return _rs_salida(fila, await modos_permitidos(conn, admin, fila["id"]))


@router.get("/{razon_social_id}")
async def ver(razon_social_id: str, usuario: dict = Depends(require_usuario),
              conn: asyncpg.Connection = Depends(get_conn)):
    fila = await razon_social_visible(conn, usuario, razon_social_id)
    return _rs_salida(fila, await modos_permitidos(conn, usuario, fila["id"]))


@router.put("/{razon_social_id}")
async def modificar(razon_social_id: str, data: RazonSocialCambios, request: Request,
                    admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    actual = await razon_social_visible(conn, admin, razon_social_id)
    cambios = data.model_dump(exclude_none=True)
    if "nombre_legal" in cambios:
        cambios["nombre_legal"] = cambios["nombre_legal"].strip()
        if not cambios["nombre_legal"]:
            raise HTTPException(400, "Falta el nombre legal.")
    for campo in ("nombre_fantasia", "domicilio"):
        if campo in cambios:
            cambios[campo] = cambios[campo].strip()
    if "color" in cambios:
        cambios["color"] = cambios["color"].lower()
    nuevo = {**dict(actual), **cambios}
    async with conn.transaction():
        fila = await conn.fetchrow("""
            UPDATE razones_sociales SET nombre_legal = $2, nombre_fantasia = $3, condicion_iva = $4,
                   domicilio = $5, regimen_arba_bsas = $6, activa = $7, color = $8, actualizado_en = now()
            WHERE id = $1 RETURNING *
        """, actual["id"], nuevo["nombre_legal"], nuevo["nombre_fantasia"], nuevo["condicion_iva"],
            nuevo["domicilio"], nuevo["regimen_arba_bsas"], nuevo["activa"], nuevo["color"])
        modificados = sorted(k for k in cambios if actual[k] != fila[k])
        if modificados:
            await registrar(conn, admin["id"], admin["usuario"], "RAZON_SOCIAL_CAMBIO",
                            "Campos: " + ", ".join(modificados) + ".", client_ip(request), fila["id"])
    return _rs_salida(fila, await modos_permitidos(conn, admin, fila["id"]))


@router.get("/{razon_social_id}/puntos-venta")
async def listar_puntos_venta(razon_social_id: str, usuario: dict = Depends(require_usuario),
                              conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, usuario, razon_social_id)
    return [_pv_salida(pv) for pv in await puntos_venta_visibles(conn, usuario, rs["id"])]


@router.post("/{razon_social_id}/puntos-venta", status_code=201)
async def crear_punto_venta(razon_social_id: str, data: PuntoVentaNuevo, request: Request,
                            admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    async with conn.transaction():
        try:
            fila = await conn.fetchrow("""
                INSERT INTO puntos_venta (razon_social_id, numero, descripcion) VALUES ($1, $2, $3) RETURNING *
            """, rs["id"], data.numero, data.descripcion.strip())
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ese número de punto de venta ya existe en la razón social.")
        await registrar(conn, admin["id"], admin["usuario"], "PUNTO_VENTA_ALTA",
                        f"Punto de venta {data.numero:05d}.", client_ip(request), rs["id"])
    return _pv_salida(fila)


@router.put("/{razon_social_id}/puntos-venta/{punto_venta_id}")
async def modificar_punto_venta(razon_social_id: str, punto_venta_id: str, data: PuntoVentaCambios,
                                request: Request, admin: dict = Depends(require_admin),
                                conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    actual = await conn.fetchrow("SELECT * FROM puntos_venta WHERE id = $1 AND razon_social_id = $2",
                                 uuid_o_404(punto_venta_id), rs["id"])
    if actual is None:
        raise HTTPException(404, "No encontrado.")
    descripcion = actual["descripcion"] if data.descripcion is None else data.descripcion.strip()
    activo = actual["activo"] if data.activo is None else data.activo
    async with conn.transaction():
        fila = await conn.fetchrow(
            "UPDATE puntos_venta SET descripcion = $2, activo = $3 WHERE id = $1 RETURNING *",
            actual["id"], descripcion, activo)
        await registrar(conn, admin["id"], admin["usuario"], "PUNTO_VENTA_CAMBIO",
                        f"Punto de venta {actual['numero']:05d}.", client_ip(request), rs["id"])
    return _pv_salida(fila)
