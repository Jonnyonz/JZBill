"""Formularios de comprobante por punto de venta (solo administrador) y sus contadores por modo.

Electronico: el tipo sale de los parametros de ARCA (FEParamGetTiposCbte), con su nombre y su letra; el contador
de cada modo se sincroniza con FECompUltimoAutorizado ("Consultar ultimo numero en ARCA"), nunca a mano.
No electronico (presupuesto, remito interno): solo numera y guarda, con numeracion propia por modo."""

import asyncio
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill import config
from jzbill.arca import parametros, servicio, soap, wsfev1
from jzbill.arca_api import _error as error_arca
from jzbill.auth import client_ip, registrar
from jzbill.db import get_conn
from jzbill.permisos import razon_social_visible, require_admin, uuid_o_404

router = APIRouter(prefix="/api/razones-sociales/{razon_social_id}/formularios", tags=["Formularios"])

Modo = Literal["empresa", "prueba"]
LETRAS = ("A", "B", "C", "M", "E")


class FormularioNuevo(BaseModel):
    punto_venta_id: str = Field(max_length=40)
    electronico: bool
    codigo_arca: Optional[int] = Field(default=None, ge=1, le=999)
    nombre: str = Field(default="", max_length=80)


class FormularioCambios(BaseModel):
    activo: bool


class ConModo(BaseModel):
    modo: Modo


def letra_de(descripcion: str) -> Optional[str]:
    """Letra del comprobante segun la descripcion de ARCA ("Factura C" -> C); None si no termina en una letra."""
    ultima = descripcion.strip().rsplit(" ", 1)[-1]
    return ultima if ultima in LETRAS else None


async def tipo_arca(conn: asyncpg.Connection, codigo: int) -> dict:
    """El tipo de comprobante en los parametros vigentes (empresa si estan, si no prueba). 400 si no existe."""
    for modo in ("empresa", "prueba"):
        vigentes = await parametros.vigentes(conn, modo)
        if vigentes is None:
            continue
        for item in vigentes["tipos"].get("TiposCbte", []):
            if item["codigo"] == str(codigo):
                return item
        raise HTTPException(400, f"El tipo de comprobante {codigo} no está en los parámetros fiscales de ARCA.")
    raise HTTPException(409, "Faltan los parámetros fiscales de ARCA: actualizalos desde Conexión con ARCA.")


def _salida(fila) -> dict:
    return {"id": str(fila["id"]), "punto_venta_id": str(fila["punto_venta_id"]), "punto_venta": fila["pv_numero"],
            "electronico": fila["electronico"], "codigo_arca": fila["codigo_arca"], "nombre": fila["nombre"],
            "letra": fila["letra"], "activo": fila["activo"],
            "ultimo": {"empresa": fila["ultimo_empresa"], "prueba": fila["ultimo_prueba"]}}


_SELECT = """
    SELECT f.*, pv.numero AS pv_numero,
           (SELECT ultimo_numero FROM contadores WHERE formulario_id = f.id AND modo = 'empresa') AS ultimo_empresa,
           (SELECT ultimo_numero FROM contadores WHERE formulario_id = f.id AND modo = 'prueba') AS ultimo_prueba
    FROM formularios f JOIN puntos_venta pv ON pv.id = f.punto_venta_id
"""


async def _formulario_o_404(conn: asyncpg.Connection, rs, formulario_id: str) -> asyncpg.Record:
    fila = await conn.fetchrow(_SELECT + " WHERE f.id = $1 AND f.razon_social_id = $2",
                               uuid_o_404(formulario_id), rs["id"])
    if fila is None:
        raise HTTPException(404, "No encontrado.")
    return fila


@router.get("")
async def listar(razon_social_id: str, admin: dict = Depends(require_admin),
                 conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    filas = await conn.fetch(_SELECT + " WHERE f.razon_social_id = $1 ORDER BY pv.numero, f.electronico DESC, "
                                       "f.codigo_arca, f.nombre", rs["id"])
    return [_salida(f) for f in filas]


@router.post("", status_code=201)
async def crear(razon_social_id: str, data: FormularioNuevo, request: Request, admin: dict = Depends(require_admin),
                conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    pv = await conn.fetchrow("SELECT id, numero FROM puntos_venta WHERE id = $1 AND razon_social_id = $2",
                             uuid_o_404(data.punto_venta_id), rs["id"])
    if pv is None:
        raise HTTPException(404, "No encontrado.")
    if data.electronico:
        if data.codigo_arca is None:
            raise HTTPException(400, "Elegí el tipo de comprobante de ARCA.")
        tipo = await tipo_arca(conn, data.codigo_arca)
        nombre, letra, codigo = tipo["descripcion"][:80], letra_de(tipo["descripcion"]), data.codigo_arca
    else:
        nombre = data.nombre.strip()
        if not nombre:
            raise HTTPException(400, "Poné un nombre al formulario (por ejemplo, Presupuesto).")
        letra, codigo = None, None
    try:
        async with conn.transaction():
            fila = await conn.fetchrow("""
                INSERT INTO formularios (razon_social_id, punto_venta_id, electronico, codigo_arca, nombre, letra)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """, rs["id"], pv["id"], data.electronico, codigo, nombre, letra)
            await conn.execute("INSERT INTO contadores (formulario_id, modo) VALUES ($1, 'empresa'), ($1, 'prueba')",
                               fila["id"])
            await registrar(conn, admin["id"], admin["usuario"], "FORMULARIO_ALTA",
                            f"{nombre} en el punto de venta {pv['numero']}"
                            + (" (electrónico)." if data.electronico else " (no electrónico)."),
                            client_ip(request), rs["id"])
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ese formulario ya existe en ese punto de venta.")
    return _salida(await _formulario_o_404(conn, rs, str(fila["id"])))


@router.patch("/{formulario_id}")
async def cambiar(razon_social_id: str, formulario_id: str, data: FormularioCambios, request: Request,
                  admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    f = await _formulario_o_404(conn, rs, formulario_id)
    await conn.execute("UPDATE formularios SET activo = $2 WHERE id = $1", f["id"], data.activo)
    await registrar(conn, admin["id"], admin["usuario"], "FORMULARIO_CAMBIO",
                    f"{f['nombre']} PV {f['pv_numero']}: {'activo' if data.activo else 'inactivo'}.",
                    client_ip(request), rs["id"])
    return _salida(await _formulario_o_404(conn, rs, formulario_id))


@router.post("/{formulario_id}/sincronizar")
async def sincronizar(razon_social_id: str, formulario_id: str, data: ConModo, request: Request,
                      admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    """Deja el contador del modo igual al ultimo numero autorizado en ARCA. Si JZBill tenia otro, queda en la
    auditoria (por ejemplo, comprobantes emitidos fuera de JZBill en ese punto de venta)."""
    rs = await razon_social_visible(conn, admin, razon_social_id)
    f = await _formulario_o_404(conn, rs, formulario_id)
    if not f["electronico"]:
        raise HTTPException(409, "Los formularios no electrónicos no se sincronizan con ARCA.")
    try:
        cred = await servicio.credenciales(conn, rs, data.modo)
        ultimo = await asyncio.to_thread(wsfev1.ultimo_autorizado, config.ARCA_URLS[data.modo]["wsfe"], cred,
                                         f["pv_numero"], f["codigo_arca"])
    except soap.ErrorArca as e:
        raise error_arca(e)
    anterior = f["ultimo_" + data.modo]
    await conn.execute("UPDATE contadores SET ultimo_numero = $3, actualizado_en = now() "
                       "WHERE formulario_id = $1 AND modo = $2", f["id"], data.modo, ultimo)
    await registrar(conn, admin["id"], admin["usuario"], "FORMULARIO_SINCRONIZADO",
                    f"{f['nombre']} PV {f['pv_numero']}, modo {data.modo}: último en ARCA {ultimo}"
                    + (f" (JZBill tenía {anterior})." if anterior != ultimo else "."), client_ip(request), rs["id"])
    return _salida(await _formulario_o_404(conn, rs, formulario_id))
