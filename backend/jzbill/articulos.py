"""Articulos (Fase 5): SKU global unico, costo de referencia y precios de venta con vigencia.

Ver: cualquier rol. Crear, modificar y poner precios: administrador y supervisor (el diseno asigna precios y ofertas
al supervisor). El precio es el final, con IVA incluido; la alicuota es un codigo de ARCA (FEParamGetTiposIva)
validado contra los parametros vigentes y guardado como dato. El costo nunca participa del comprobante."""

from datetime import date
from decimal import Decimal
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jzbill.arca import parametros
from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.db import get_conn
from jzbill.permisos import require_rol, uuid_o_404

router = APIRouter(prefix="/api/articulos", tags=["Articulos"])

editor = require_rol("administrador", "supervisor")


class ArticuloDatos(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    descripcion: str = Field(min_length=1, max_length=200)
    categoria: str = Field(default="", max_length=80)
    alicuota_iva: int = Field(ge=1, le=99)
    costo: Decimal = Field(default=Decimal("0"), ge=0, max_digits=15, decimal_places=2)


class ArticuloNuevo(ArticuloDatos):
    # Precio inicial opcional, vigente desde hoy.
    precio: Optional[Decimal] = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    moneda: str = Field(default="PES", min_length=3, max_length=3)


class ArticuloCambios(ArticuloDatos):
    activo: bool = True


class PrecioNuevo(BaseModel):
    importe: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    moneda: str = Field(default="PES", min_length=3, max_length=3)
    vigencia_desde: Optional[date] = None   # sin fecha: desde hoy


async def _vigentes(conn: asyncpg.Connection) -> Optional[dict]:
    for modo in ("empresa", "prueba"):
        v = await parametros.vigentes(conn, modo)
        if v is not None:
            return v
    return None


def _codigos(vigentes: Optional[dict], tipo: str) -> list:
    return [] if vigentes is None else vigentes["tipos"].get(tipo, [])


async def _validar(conn: asyncpg.Connection, data: ArticuloDatos, moneda: Optional[str] = None) -> str:
    """Devuelve el SKU normalizado. 400 si algo no corresponde a los parametros de ARCA."""
    vigentes = await _vigentes(conn)
    if vigentes is None:
        raise HTTPException(409, "Faltan los parámetros fiscales de ARCA: un administrador tiene que actualizarlos.")
    if not any(i["codigo"] == str(data.alicuota_iva) for i in _codigos(vigentes, "TiposIva")):
        raise HTTPException(400, "Alícuota de IVA desconocida para ARCA.")
    if moneda is not None and not any(i["codigo"] == moneda for i in _codigos(vigentes, "TiposMonedas")):
        raise HTTPException(400, "Moneda desconocida para ARCA.")
    sku = data.sku.strip()
    if not sku or any(c.isspace() for c in sku):
        raise HTTPException(400, "El SKU no puede tener espacios.")
    if not data.descripcion.strip():
        raise HTTPException(400, "Poné una descripción.")
    return sku


_SELECT = """
    SELECT a.*, p.importe AS precio, p.moneda AS precio_moneda, p.vigencia_desde AS precio_desde
    FROM articulos a
    LEFT JOIN LATERAL (
        SELECT importe, moneda, vigencia_desde FROM articulos_precios
        WHERE articulo_id = a.id AND moneda = 'PES' AND vigencia_desde <= CURRENT_DATE
        ORDER BY vigencia_desde DESC LIMIT 1
    ) p ON true
"""


def _salida(fila, precios=None) -> dict:
    d = {"id": str(fila["id"]), "sku": fila["sku"], "descripcion": fila["descripcion"], "categoria": fila["categoria"],
         "alicuota_iva": fila["alicuota_iva"], "costo": str(fila["costo"]), "activo": fila["activo"],
         "origen": fila["origen"],
         "precio": str(fila["precio"]) if fila["precio"] is not None else None,
         "precio_desde": fila["precio_desde"].isoformat() if fila["precio_desde"] else None}
    if precios is not None:
        d["precios"] = [{"id": str(p["id"]), "moneda": p["moneda"], "importe": str(p["importe"]),
                         "vigencia_desde": p["vigencia_desde"].isoformat(),
                         "vigente": p["moneda"] == "PES" and p["vigencia_desde"] == fila["precio_desde"]}
                        for p in precios]
    return d


async def _articulo_o_404(conn: asyncpg.Connection, articulo_id: str, con_precios: bool = False) -> dict:
    fila = await conn.fetchrow(_SELECT + " WHERE a.id = $1", uuid_o_404(articulo_id))
    if fila is None:
        raise HTTPException(404, "No encontrado.")
    precios = None
    if con_precios:
        precios = await conn.fetch("""
            SELECT id, moneda, importe, vigencia_desde FROM articulos_precios WHERE articulo_id = $1
            ORDER BY moneda, vigencia_desde DESC LIMIT 100
        """, fila["id"])
    return _salida(fila, precios)


@router.get("/opciones")
async def opciones(usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    """Alicuotas de IVA y monedas de ARCA para los formularios."""
    vigentes = await _vigentes(conn)
    simple = lambda tipo: [{"codigo": i["codigo"], "descripcion": i["descripcion"]} for i in _codigos(vigentes, tipo)]
    return {"alicuotas": simple("TiposIva"), "monedas": simple("TiposMonedas")}


@router.get("")
async def buscar(q: str = Query("", max_length=100), limite: int = Query(20, ge=1, le=200),
                 incluir_inactivos: bool = False, usuario: dict = Depends(require_usuario),
                 conn: asyncpg.Connection = Depends(get_conn)):
    """Por SKU (empieza con) o descripcion (contiene). Sin texto: los ultimos modificados."""
    texto = q.strip().replace("%", "").replace("_", "")
    filas = await conn.fetch(_SELECT + """
        WHERE ($1 OR a.activo)
          AND ($2 = '' OR upper(a.sku) LIKE upper($2) || '%' OR lower(a.descripcion) LIKE '%' || lower($2) || '%')
        ORDER BY (CASE WHEN upper(a.sku) = upper($2) THEN 0 ELSE 1 END), a.actualizado_en DESC
        LIMIT $3
    """, incluir_inactivos, texto, limite)
    return [_salida(f) for f in filas]


@router.get("/{articulo_id}")
async def ver(articulo_id: str, usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    return await _articulo_o_404(conn, articulo_id, con_precios=True)


@router.post("", status_code=201)
async def crear(data: ArticuloNuevo, request: Request, usuario: dict = Depends(editor),
                conn: asyncpg.Connection = Depends(get_conn)):
    sku = await _validar(conn, data, data.moneda if data.precio is not None else None)
    try:
        async with conn.transaction():
            nuevo = await conn.fetchval("""
                INSERT INTO articulos (sku, descripcion, categoria, alicuota_iva, costo, creado_por)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """, sku, data.descripcion.strip(), data.categoria.strip(), data.alicuota_iva, data.costo, usuario["id"])
            if data.precio is not None:
                await conn.execute("""
                    INSERT INTO articulos_precios (articulo_id, moneda, importe, vigencia_desde, creado_por)
                    VALUES ($1, $2, $3, CURRENT_DATE, $4)
                """, nuevo, data.moneda, data.precio, usuario["id"])
            await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULO_ALTA",
                            f"{sku}: {data.descripcion.strip()[:80]}"
                            + (f", precio {data.moneda} {data.precio}." if data.precio is not None else "."),
                            client_ip(request))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un artículo con ese SKU.")
    return await _articulo_o_404(conn, str(nuevo), con_precios=True)


@router.put("/{articulo_id}")
async def modificar(articulo_id: str, data: ArticuloCambios, request: Request, usuario: dict = Depends(editor),
                    conn: asyncpg.Connection = Depends(get_conn)):
    actual = await _articulo_o_404(conn, articulo_id)
    sku = await _validar(conn, data)
    try:
        async with conn.transaction():
            await conn.execute("""
                UPDATE articulos SET sku = $2, descripcion = $3, categoria = $4, alicuota_iva = $5, costo = $6,
                       activo = $7, actualizado_en = now()
                WHERE id = $1
            """, uuid_o_404(actual["id"]), sku, data.descripcion.strip(), data.categoria.strip(), data.alicuota_iva,
                data.costo, data.activo)
            await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULO_CAMBIO",
                            f"{sku}: {data.descripcion.strip()[:80]}" + ("" if data.activo else " (inactivo)") + ".",
                            client_ip(request))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un artículo con ese SKU.")
    return await _articulo_o_404(conn, articulo_id, con_precios=True)


@router.post("/{articulo_id}/precios", status_code=201)
async def poner_precio(articulo_id: str, data: PrecioNuevo, request: Request, usuario: dict = Depends(editor),
                       conn: asyncpg.Connection = Depends(get_conn)):
    """Precio nuevo con vigencia. Uno por (moneda, fecha): repetir la fecha lo reemplaza, asi un error de tipeo se
    corrige sin dejar basura en el historial."""
    actual = await _articulo_o_404(conn, articulo_id)
    vigentes = await _vigentes(conn)
    if not any(i["codigo"] == data.moneda for i in _codigos(vigentes, "TiposMonedas")):
        raise HTTPException(400, "Moneda desconocida para ARCA.")
    desde = data.vigencia_desde or date.today()
    async with conn.transaction():
        await conn.execute("""
            INSERT INTO articulos_precios (articulo_id, moneda, importe, vigencia_desde, creado_por)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (articulo_id, moneda, vigencia_desde) DO UPDATE SET importe = EXCLUDED.importe,
                creado_por = EXCLUDED.creado_por, creado_en = now()
        """, uuid_o_404(actual["id"]), data.moneda, data.importe, desde, usuario["id"])
        await conn.execute("UPDATE articulos SET actualizado_en = now() WHERE id = $1", uuid_o_404(actual["id"]))
        await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULO_PRECIO",
                        f"{actual['sku']}: {data.moneda} {data.importe} desde {desde.isoformat()}.", client_ip(request))
    return await _articulo_o_404(conn, articulo_id, con_precios=True)
