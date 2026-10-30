"""Ofertas (Fase 5, decisiones de Jonny 2026-10-30): reglas de descuento que se aplican encima del precio de lista.

Primera version: porcentaje o monto fijo por unidad; sobre todos los articulos, una categoria o una lista de
articulos; con vigencia (desde / hasta) y opcional por medio de pago (la condicion de venta del comprobante).
Sin "unidad gratis" ni combinaciones: si a un articulo le aplican varias, gana la de mayor descuento.

Al facturar, el sistema PROPONE la oferta en la linea (POST /evaluar); el cajero la ve y puede quitarla. Al emitir,
la linea trae la oferta que quedo y el servidor la vuelve a validar y a calcular: el detalle (precio de lista,
descuento y texto) queda guardado en la linea y lo emitido no depende de la regla actual.

Ver: cualquier rol. Crear y modificar: administrador y supervisor. Una oferta no se borra: se desactiva."""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.db import get_conn
from jzbill.permisos import require_rol, uuid_o_404

router = APIRouter(prefix="/api/ofertas", tags=["Ofertas"])

editor = require_rol("administrador", "supervisor")

CENTAVO = Decimal("0.01")
# RG 1415 Anexo II B, e): condiciones de venta. Es el "medio de pago" de la oferta; los medios de pago con su
# detalle llegan con la caja (Fase 6) y ahi se amplia.
CONDICIONES_VENTA = ("Contado", "Cuenta corriente", "Tarjeta de débito", "Tarjeta de crédito", "Transferencia",
                     "Cheque", "Otra")
MAX_ARTICULOS = 500


class OfertaDatos(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    tipo: Literal["porcentaje", "monto"] = "porcentaje"
    valor: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    alcance: Literal["todo", "categoria", "articulos"] = "todo"
    categoria: str = Field(default="", max_length=80)
    articulos: List[str] = Field(default_factory=list, max_length=MAX_ARTICULOS)   # ids, si alcance = articulos
    condicion_venta: Optional[str] = Field(default=None, max_length=40)   # None: cualquier medio de pago
    vigencia_desde: Optional[date] = None   # sin fecha: hoy
    vigencia_hasta: Optional[date] = None   # sin fecha: sin fin
    activa: bool = True


class LineaEvaluar(BaseModel):
    articulo_id: Optional[str] = Field(default=None, max_length=40)
    precio_unitario: Decimal = Field(ge=0, max_digits=15, decimal_places=2)


class Evaluar(BaseModel):
    condicion_venta: str = Field(max_length=40)
    moneda: str = Field(default="PES", min_length=3, max_length=3)
    lineas: List[LineaEvaluar] = Field(max_length=100)


# ===== Motor =====

def _valor(o) -> str:
    return format(o["valor"].normalize(), "f")


def detalle(o) -> str:
    """Texto que queda en la linea: "Semana del bazar: 10% de descuento" / "...: $50 de descuento por unidad"."""
    if o["tipo"] == "porcentaje":
        return f"{o['nombre']}: {_valor(o)}% de descuento"
    return f"{o['nombre']}: ${_valor(o)} de descuento por unidad"


def precio_con_oferta(o, precio_lista: Decimal) -> Decimal:
    """Precio final por unidad, redondeado a centavos (mitad hacia arriba); nunca por debajo de cero."""
    if o["tipo"] == "porcentaje":
        final = precio_lista * (Decimal(100) - o["valor"]) / Decimal(100)
    else:
        final = precio_lista - o["valor"]
    return max(final, Decimal(0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def aplica(o, articulo, moneda: str) -> bool:
    """Un monto fijo esta en pesos: con otra moneda solo aplican los porcentajes."""
    if o["tipo"] == "monto" and moneda != "PES":
        return False
    if o["alcance"] == "todo":
        return True
    if o["alcance"] == "categoria":
        return articulo["categoria"].lower() == o["categoria"].lower()
    return articulo["id"] in o["articulos"]


async def vigentes(conn: asyncpg.Connection, hoy: date, condicion_venta: str) -> list:
    """Ofertas activas y vigentes hoy para ese medio de pago, con el conjunto de articulos de las de alcance
    por articulos."""
    filas = await conn.fetch("""
        SELECT o.*, COALESCE(array_agg(oa.articulo_id) FILTER (WHERE oa.articulo_id IS NOT NULL), '{}') AS articulos
        FROM ofertas o LEFT JOIN ofertas_articulos oa ON oa.oferta_id = o.id
        WHERE o.activa AND o.vigencia_desde <= $1 AND (o.vigencia_hasta IS NULL OR o.vigencia_hasta >= $1)
          AND (o.condicion_venta IS NULL OR o.condicion_venta = $2)
        GROUP BY o.id
    """, hoy, condicion_venta)
    return [dict(f, articulos=set(f["articulos"])) for f in filas]


def mejor(ofertas: list, articulo, precio_lista: Decimal, moneda: str) -> Optional[tuple]:
    """(oferta, precio final) de mayor descuento; empate: por nombre. None si ninguna aplica o no descuenta."""
    candidatas = [(precio_con_oferta(o, precio_lista), o["nombre"].lower(), o) for o in ofertas if aplica(o, articulo, moneda)]
    candidatas = [c for c in candidatas if c[0] < precio_lista]
    if not candidatas:
        return None
    final, _, o = min(candidatas, key=lambda c: (c[0], c[1]))
    return o, final


async def aplicar(conn: asyncpg.Connection, lineas: list, articulos: dict, condicion_venta: str, moneda: str,
                  hoy: date) -> None:
    """Al emitir: las lineas (dicts de comprobantes.calcular, con articulo_id ya validado) que traen oferta_id
    pasan a precio final, con precio_lista, descuento y oferta_detalle guardados. 400 si la oferta ya no aplica."""
    if not any(l["oferta_id"] for l in lineas):
        return
    por_id = {o["id"]: o for o in await vigentes(conn, hoy, condicion_venta)}
    for l in lineas:
        if not l["oferta_id"]:
            continue
        try:
            o = por_id.get(uuid.UUID(str(l["oferta_id"])))
        except ValueError:
            o = None
        a = articulos.get(l["articulo_id"]) if l["articulo_id"] else None
        if o is None or a is None or not aplica(o, a, moneda):
            raise HTTPException(400, f"La oferta de la línea {l['orden']} ya no aplica: quitala o volvé a agregar "
                                     "el artículo.")
        final = precio_con_oferta(o, l["precio_unitario"])
        l["precio_lista"], l["precio_unitario"] = l["precio_unitario"], final
        l["importe"] = (l["cantidad"] * final).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        l["descuento"] = (l["cantidad"] * (l["precio_lista"] - final)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        l["oferta_id"], l["oferta_detalle"] = o["id"], detalle(o)[:120]


# ===== API =====

def _estado(o, hoy: date) -> str:
    if not o["activa"]:
        return "inactiva"
    if o["vigencia_desde"] > hoy:
        return "futura"
    if o["vigencia_hasta"] is not None and o["vigencia_hasta"] < hoy:
        return "vencida"
    return "vigente"


def _salida(o, articulos=None) -> dict:
    d = {"id": str(o["id"]), "nombre": o["nombre"], "tipo": o["tipo"], "valor": str(o["valor"]), "alcance": o["alcance"],
         "categoria": o["categoria"], "condicion_venta": o["condicion_venta"],
         "vigencia_desde": o["vigencia_desde"].isoformat(),
         "vigencia_hasta": o["vigencia_hasta"].isoformat() if o["vigencia_hasta"] else None,
         "activa": o["activa"], "detalle": detalle(o), "estado": _estado(o, date.today()),
         "cantidad_articulos": o["n_articulos"]}
    if articulos is not None:
        d["articulos"] = [{"id": str(a["id"]), "sku": a["sku"], "descripcion": a["descripcion"]} for a in articulos]
    return d


_SELECT = "SELECT o.*, (SELECT count(*) FROM ofertas_articulos oa WHERE oa.oferta_id = o.id) AS n_articulos FROM ofertas o"


async def _oferta_o_404(conn: asyncpg.Connection, oferta_id: str) -> dict:
    o = await conn.fetchrow(_SELECT + " WHERE o.id = $1", uuid_o_404(oferta_id))
    if o is None:
        raise HTTPException(404, "No encontrado.")
    articulos = await conn.fetch("""
        SELECT a.id, a.sku, a.descripcion FROM ofertas_articulos oa JOIN articulos a ON a.id = oa.articulo_id
        WHERE oa.oferta_id = $1 ORDER BY a.sku
    """, o["id"])
    return _salida(o, articulos)


async def _validar(conn: asyncpg.Connection, data: OfertaDatos) -> tuple:
    """(nombre, categoria, ids de articulos, desde). 400 si algo no cierra."""
    nombre = " ".join(data.nombre.split())
    if not nombre:
        raise HTTPException(400, "Poné un nombre.")
    if data.tipo == "porcentaje" and data.valor > 100:
        raise HTTPException(400, "Un porcentaje de descuento va de 0 a 100.")
    if data.condicion_venta is not None and data.condicion_venta not in CONDICIONES_VENTA:
        raise HTTPException(400, "Medio de pago desconocido.")
    categoria = data.categoria.strip() if data.alcance == "categoria" else ""
    if data.alcance == "categoria" and not categoria:
        raise HTTPException(400, "Elegí la categoría.")
    ids = []
    if data.alcance == "articulos":
        try:
            pedidos = list(dict.fromkeys(uuid.UUID(str(i)) for i in data.articulos))
        except ValueError:
            raise HTTPException(400, "Artículo inválido.")
        if not pedidos:
            raise HTTPException(400, "Elegí al menos un artículo.")
        ids = [f["id"] for f in await conn.fetch("SELECT id FROM articulos WHERE id = ANY($1::uuid[])", pedidos)]
        if len(ids) != len(pedidos):
            raise HTTPException(400, "Alguno de los artículos no existe.")
    desde = data.vigencia_desde or date.today()
    if data.vigencia_hasta is not None and data.vigencia_hasta < desde:
        raise HTTPException(400, "La fecha de fin tiene que ser igual o posterior a la de inicio.")
    return nombre, categoria, ids, desde


@router.get("")
async def listar(incluir_inactivas: bool = False, usuario: dict = Depends(require_usuario),
                 conn: asyncpg.Connection = Depends(get_conn)):
    filas = await conn.fetch(_SELECT + " WHERE ($1 OR o.activa) ORDER BY o.activa DESC, o.vigencia_desde DESC, lower(o.nombre) LIMIT 200",
                             incluir_inactivas)
    return [_salida(o) for o in filas]


@router.post("/evaluar")
async def evaluar(data: Evaluar, usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    """Para la pantalla Facturar: por cada linea, la mejor oferta vigente hoy para ese medio de pago y moneda (o
    null). No guarda nada; al emitir se vuelve a validar."""
    ids = []
    for l in data.lineas:
        if l.articulo_id:
            try:
                ids.append(uuid.UUID(str(l.articulo_id)))
            except ValueError:
                pass
    articulos = {a["id"]: a for a in await conn.fetch("SELECT id, categoria FROM articulos WHERE activo AND id = ANY($1::uuid[])", ids)} if ids else {}
    ofertas = await vigentes(conn, date.today(), data.condicion_venta) if articulos else []
    salida = []
    for l in data.lineas:
        a = None
        if l.articulo_id:
            try:
                a = articulos.get(uuid.UUID(str(l.articulo_id)))
            except ValueError:
                a = None
        m = mejor(ofertas, a, l.precio_unitario, data.moneda) if a is not None else None
        salida.append(None if m is None else {"oferta_id": str(m[0]["id"]), "detalle": detalle(m[0]),
                                              "precio_lista": str(l.precio_unitario), "precio_final": str(m[1])})
    return salida


@router.get("/{oferta_id}")
async def ver(oferta_id: str, usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    return await _oferta_o_404(conn, oferta_id)


@router.post("", status_code=201)
async def crear(data: OfertaDatos, request: Request, usuario: dict = Depends(editor),
                conn: asyncpg.Connection = Depends(get_conn)):
    nombre, categoria, ids, desde = await _validar(conn, data)
    async with conn.transaction():
        nuevo = await conn.fetchval("""
            INSERT INTO ofertas (nombre, tipo, valor, alcance, categoria, condicion_venta, vigencia_desde, vigencia_hasta, activa, creado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
        """, nombre, data.tipo, data.valor, data.alcance, categoria, data.condicion_venta, desde, data.vigencia_hasta,
            data.activa, usuario["id"])
        if ids:
            await conn.executemany("INSERT INTO ofertas_articulos (oferta_id, articulo_id) VALUES ($1, $2)", [(nuevo, i) for i in ids])
        await registrar(conn, usuario["id"], usuario["usuario"], "OFERTA_ALTA",
                        f"{detalle({'nombre': nombre, 'tipo': data.tipo, 'valor': data.valor})} ({data.alcance}"
                        f"{', ' + categoria if categoria else ''}{', ' + str(len(ids)) + ' artículos' if ids else ''}), "
                        f"desde {desde.isoformat()}{' hasta ' + data.vigencia_hasta.isoformat() if data.vigencia_hasta else ''}"
                        f"{', ' + data.condicion_venta if data.condicion_venta else ''}.", client_ip(request))
    return await _oferta_o_404(conn, str(nuevo))


@router.put("/{oferta_id}")
async def modificar(oferta_id: str, data: OfertaDatos, request: Request, usuario: dict = Depends(editor),
                    conn: asyncpg.Connection = Depends(get_conn)):
    actual = await _oferta_o_404(conn, oferta_id)
    nombre, categoria, ids, desde = await _validar(conn, data)
    async with conn.transaction():
        await conn.execute("""
            UPDATE ofertas SET nombre = $2, tipo = $3, valor = $4, alcance = $5, categoria = $6, condicion_venta = $7,
                   vigencia_desde = $8, vigencia_hasta = $9, activa = $10, actualizado_en = now()
            WHERE id = $1
        """, uuid_o_404(actual["id"]), nombre, data.tipo, data.valor, data.alcance, categoria, data.condicion_venta, desde,
            data.vigencia_hasta, data.activa)
        await conn.execute("DELETE FROM ofertas_articulos WHERE oferta_id = $1", uuid_o_404(actual["id"]))
        if ids:
            await conn.executemany("INSERT INTO ofertas_articulos (oferta_id, articulo_id) VALUES ($1, $2)",
                                   [(uuid_o_404(actual["id"]), i) for i in ids])
        await registrar(conn, usuario["id"], usuario["usuario"], "OFERTA_CAMBIO",
                        f"{detalle({'nombre': nombre, 'tipo': data.tipo, 'valor': data.valor})} ({data.alcance}), "
                        f"desde {desde.isoformat()}{' hasta ' + data.vigencia_hasta.isoformat() if data.vigencia_hasta else ''}"
                        + ("" if data.activa else ", inactiva") + ".", client_ip(request))
    return await _oferta_o_404(conn, oferta_id)
