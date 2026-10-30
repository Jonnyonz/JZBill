"""Reportes (Fase 7): ventas por periodo, libro de IVA ventas, rentabilidad (margen bruto) y cierres de caja.

Todos filtran por la razon social y el modo del contexto (lo de prueba nunca entra en un reporte de empresa) y
por los puntos de venta que el usuario puede ver. Los ve cualquier rol (solo lectura incluido). Cada reporte
tiene su descarga CSV: separador ";", decimales con coma y BOM (lo que abre bien el Excel en espanol), y los
textos que empiezan con = + - @ llevan un apostrofo adelante (inyeccion de formulas).

Rentabilidad: margen bruto = ventas (precio final cobrado) - costo actual del articulo x cantidad. Es un calculo
de ganancia, no contabilidad; el costo es el de hoy (articulos.costo no tiene historial). Las lineas sin articulo
o en otra moneda que pesos quedan "sin costo". Las notas de credito restan."""

import csv
import io
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from jzbill import caja
from jzbill.comprobantes import HORA_AR, es_credito
from jzbill.contexto import contexto_requerido
from jzbill.db import get_conn
from jzbill.permisos import puntos_venta_visibles, uuid_o_404

router = APIRouter(prefix="/api/reportes", tags=["Reportes"])

CERO = Decimal("0.00")
MAX_DIAS = 366


# --- Periodo, puntos de venta y CSV ---
def _rango(desde: Optional[date], hasta: Optional[date]) -> tuple:
    """Por defecto, el mes en curso. Como mucho un ano."""
    hoy = datetime.now(HORA_AR).date()
    desde = desde or hoy.replace(day=1)
    hasta = hasta or hoy
    if hasta < desde:
        raise HTTPException(400, "La fecha final es anterior a la inicial.")
    if (hasta - desde).days > MAX_DIAS:
        raise HTTPException(400, "El período no puede superar un año.")
    return desde, hasta


async def _pvs(conn: asyncpg.Connection, ctx: dict, punto_venta_id: Optional[str]) -> list:
    """Puntos de venta a incluir: los visibles, o solo el pedido si es uno de ellos (si no, 404)."""
    visibles = [pv["id"] for pv in await puntos_venta_visibles(conn, ctx["usuario"], uuid_o_404(ctx["razon_social_id"]))]
    if punto_venta_id:
        pv_id = uuid_o_404(punto_venta_id)
        if pv_id not in visibles:
            raise HTTPException(404, "No encontrado.")
        return [pv_id]
    return visibles


def _signo(nombre: str) -> int:
    return -1 if es_credito(nombre) else 1


def _signado(valor: Decimal, signo: int) -> Decimal:
    """Importe con el signo de la nota; un cero nunca queda como -0.00."""
    return valor * signo if valor else abs(valor)


def _pct(parte: Decimal, total: Decimal) -> Optional[str]:
    if not total:
        return None
    return str((parte * 100 / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _celda(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return str(valor).replace(".", ",")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor)
    # Inyeccion de formulas en planillas de calculo: lo que empieza con = + - @ (o tab/CR) va como texto.
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def csv_respuesta(nombre: str, encabezados: list, filas: list) -> Response:
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(encabezados)
    for fila in filas:
        w.writerow([_celda(v) for v in fila])
    return Response(("﻿" + salida.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _nombre_csv(base: str, desde: date, hasta: date) -> str:
    return f"{base}_{desde.isoformat()}_{hasta.isoformat()}.csv"


@router.get("/opciones")
async def opciones(ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    pvs = await puntos_venta_visibles(conn, ctx["usuario"], uuid_o_404(ctx["razon_social_id"]))
    return {"puntos_venta": [{"id": str(pv["id"]), "numero": pv["numero"], "descripcion": pv["descripcion"]} for pv in pvs],
            "modo": ctx["modo"]}


# --- Ventas ---
async def _comprobantes(conn: asyncpg.Connection, ctx: dict, desde: date, hasta: date, pvs: list, solo_fiscales: bool = False) -> list:
    return await conn.fetch("""
        SELECT c.*, f.punto_venta_id FROM comprobantes c JOIN formularios f ON f.id = c.formulario_id
        WHERE c.razon_social_id = $1 AND c.modo = $2 AND c.fecha BETWEEN $3 AND $4 AND f.punto_venta_id = ANY($5::uuid[])
          AND ($6 = false OR c.electronico)
        ORDER BY c.fecha, c.punto_venta, c.codigo_arca, c.numero
    """, uuid_o_404(ctx["razon_social_id"]), ctx["modo"], desde, hasta, pvs, solo_fiscales)


def _acumular(grupos: dict, clave, extra: dict, importe: Decimal) -> None:
    g = grupos.setdefault(clave, {**extra, "cantidad": 0, "total": CERO})
    g["cantidad"] += 1
    g["total"] += importe


def _ordenado(grupos: dict) -> list:
    return [{**g, "total": str(g["total"])} for _, g in sorted(grupos.items(), key=lambda kv: str(kv[0]))]


@router.get("/ventas")
async def ventas(desde: Optional[date] = None, hasta: Optional[date] = None, punto_venta_id: Optional[str] = Query(None, max_length=40),
                 ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    desde, hasta = _rango(desde, hasta)
    filas = await _comprobantes(conn, ctx, desde, hasta, await _pvs(conn, ctx, punto_venta_id))
    totales, por_tipo, por_dia, por_pv, por_condicion = {}, {}, {}, {}, {}
    for c in filas:
        signo = _signo(c["nombre"])
        importe = c["importe_total"] * signo
        t = totales.setdefault(c["moneda"], {"moneda": c["moneda"], "comprobantes": 0, "facturado": CERO, "notas_credito": CERO, "neto": CERO})
        t["comprobantes"] += 1
        t["facturado" if signo > 0 else "notas_credito"] += c["importe_total"]
        t["neto"] += importe
        _acumular(por_tipo, (c["nombre"], c["moneda"]), {"nombre": c["nombre"], "letra": c["letra"], "moneda": c["moneda"]}, importe)
        _acumular(por_dia, (c["fecha"].isoformat(), c["moneda"]), {"fecha": c["fecha"].isoformat(), "moneda": c["moneda"]}, importe)
        _acumular(por_pv, (f"{c['punto_venta']:05d}", c["moneda"]), {"punto_venta": c["punto_venta"], "moneda": c["moneda"]}, importe)
        _acumular(por_condicion, (c["condicion_venta"], c["moneda"]), {"condicion_venta": c["condicion_venta"], "moneda": c["moneda"]}, importe)
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "modo": ctx["modo"],
            "totales": [{**t, "facturado": str(t["facturado"]), "notas_credito": str(t["notas_credito"]), "neto": str(t["neto"])}
                        for t in sorted(totales.values(), key=lambda t: t["moneda"])],
            "por_tipo": _ordenado(por_tipo), "por_dia": _ordenado(por_dia), "por_punto_venta": _ordenado(por_pv),
            "por_condicion_venta": _ordenado(por_condicion)}


@router.get("/ventas.csv")
async def ventas_csv(desde: Optional[date] = None, hasta: Optional[date] = None, punto_venta_id: Optional[str] = Query(None, max_length=40),
                     ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    desde, hasta = _rango(desde, hasta)
    filas = await _comprobantes(conn, ctx, desde, hasta, await _pvs(conn, ctx, punto_venta_id))
    return csv_respuesta(_nombre_csv("ventas", desde, hasta),
                         ["Fecha", "Comprobante", "Letra", "Punto de venta", "Número", "Receptor", "Tipo doc.", "Documento",
                          "Condición de venta", "Moneda", "Cotización", "Total", "CAE", "Modo"],
                         [(c["fecha"], c["nombre"], c["letra"] or "", f"{c['punto_venta']:05d}", f"{c['numero']:08d}", c["receptor_nombre"],
                           c["receptor_doc_tipo"], str(c["receptor_doc_nro"]), c["condicion_venta"], c["moneda"], c["cotizacion"],
                           c["importe_total"] * _signo(c["nombre"]), c["cae"] or "", c["modo"]) for c in filas])


# --- Libro de IVA ventas ---
def _fila_libro(c) -> dict:
    s = _signo(c["nombre"])
    return {"fecha": c["fecha"].isoformat(), "comprobante": c["nombre"], "letra": c["letra"], "codigo_arca": c["codigo_arca"],
            "punto_venta": c["punto_venta"], "numero": c["numero"], "receptor": c["receptor_nombre"] or "Consumidor final",
            "doc_tipo": c["receptor_doc_tipo"], "doc_nro": str(c["receptor_doc_nro"]), "condicion_iva": c["condicion_iva_receptor"],
            "moneda": c["moneda"], "cotizacion": str(c["cotizacion"]),
            "neto": str(_signado(c["importe_neto"], s)), "no_gravado": str(_signado(c["importe_no_gravado"], s)), "exento": str(_signado(c["importe_exento"], s)),
            "iva": str(_signado(c["importe_iva"], s)), "tributos": str(_signado(c["importe_tributos"], s)), "total": str(_signado(c["importe_total"], s)),
            "cae": c["cae"]}


@router.get("/libro-iva")
async def libro_iva(desde: Optional[date] = None, hasta: Optional[date] = None, punto_venta_id: Optional[str] = Query(None, max_length=40),
                    ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    """Comprobantes electronicos del periodo con sus importes (notas de credito en negativo), por moneda."""
    desde, hasta = _rango(desde, hasta)
    filas = await _comprobantes(conn, ctx, desde, hasta, await _pvs(conn, ctx, punto_venta_id), solo_fiscales=True)
    totales = {}
    for c in filas:
        s = _signo(c["nombre"])
        t = totales.setdefault(c["moneda"], {"moneda": c["moneda"], "comprobantes": 0, "neto": CERO, "no_gravado": CERO, "exento": CERO,
                                             "iva": CERO, "tributos": CERO, "total": CERO})
        t["comprobantes"] += 1
        for campo, columna in (("neto", "importe_neto"), ("no_gravado", "importe_no_gravado"), ("exento", "importe_exento"),
                               ("iva", "importe_iva"), ("tributos", "importe_tributos"), ("total", "importe_total")):
            t[campo] += _signado(c[columna], s)
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "modo": ctx["modo"],
            "filas": [_fila_libro(c) for c in filas],
            "totales": [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in t.items()} for t in sorted(totales.values(), key=lambda t: t["moneda"])]}


@router.get("/libro-iva.csv")
async def libro_iva_csv(desde: Optional[date] = None, hasta: Optional[date] = None, punto_venta_id: Optional[str] = Query(None, max_length=40),
                        ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    desde, hasta = _rango(desde, hasta)
    filas = await _comprobantes(conn, ctx, desde, hasta, await _pvs(conn, ctx, punto_venta_id), solo_fiscales=True)
    salida = []
    for c in filas:
        s = _signo(c["nombre"])
        salida.append((c["fecha"], c["nombre"], c["letra"] or "", c["codigo_arca"], f"{c['punto_venta']:05d}", f"{c['numero']:08d}",
                       c["receptor_nombre"] or "Consumidor final", c["receptor_doc_tipo"], str(c["receptor_doc_nro"]),
                       c["condicion_iva_receptor"], c["moneda"], c["cotizacion"], _signado(c["importe_neto"], s), _signado(c["importe_no_gravado"], s),
                       _signado(c["importe_exento"], s), _signado(c["importe_iva"], s), _signado(c["importe_tributos"], s), _signado(c["importe_total"], s), c["cae"] or ""))
    return csv_respuesta(_nombre_csv("libro_iva_ventas", desde, hasta),
                         ["Fecha", "Comprobante", "Letra", "Código ARCA", "Punto de venta", "Número", "Receptor", "Tipo doc.", "Documento",
                          "Cond. IVA receptor", "Moneda", "Cotización", "Neto gravado", "No gravado", "Exento", "IVA", "Tributos", "Total", "CAE"],
                         salida)


# --- Rentabilidad ---
Agrupar = Literal["articulo", "categoria", "punto_venta", "dia"]
SIN_ARTICULO = "Sin artículo"


async def _lineas(conn: asyncpg.Connection, ctx: dict, desde: date, hasta: date, pvs: list) -> list:
    return await conn.fetch("""
        SELECT l.cantidad, l.importe, l.sku, l.descripcion AS linea, a.id AS articulo_id, a.sku AS sku_actual, a.descripcion, a.categoria, a.costo,
               c.nombre, c.moneda, c.fecha, c.punto_venta
        FROM comprobante_lineas l
        JOIN comprobantes c ON c.id = l.comprobante_id
        JOIN formularios f ON f.id = c.formulario_id
        LEFT JOIN articulos a ON a.id = l.articulo_id
        WHERE c.razon_social_id = $1 AND c.modo = $2 AND c.fecha BETWEEN $3 AND $4 AND f.punto_venta_id = ANY($5::uuid[])
        ORDER BY c.fecha, c.punto_venta, c.numero, l.orden
    """, uuid_o_404(ctx["razon_social_id"]), ctx["modo"], desde, hasta, pvs)


def _rentabilidad(lineas: list, agrupar: str) -> list:
    grupos = {}
    for l in lineas:
        con_articulo = l["articulo_id"] is not None
        if agrupar == "articulo":
            clave, descripcion = (l["sku_actual"] if con_articulo else SIN_ARTICULO), (l["descripcion"] if con_articulo else "Líneas con descripción libre")
        elif agrupar == "categoria":
            clave, descripcion = (l["categoria"] or "Sin categoría") if con_articulo else SIN_ARTICULO, ""
        elif agrupar == "punto_venta":
            clave, descripcion = f"{l['punto_venta']:05d}", ""
        else:
            clave, descripcion = l["fecha"].isoformat(), ""
        g = grupos.setdefault((clave, l["moneda"]), {"clave": clave, "descripcion": descripcion, "moneda": l["moneda"], "cantidad": Decimal("0"),
                                                      "ventas": CERO, "costo": CERO, "lineas_sin_costo": 0})
        s = _signo(l["nombre"])
        g["cantidad"] += l["cantidad"] * s
        g["ventas"] += l["importe"] * s
        if con_articulo and l["moneda"] == "PES":
            g["costo"] += _signado((l["cantidad"] * l["costo"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), s)
        else:
            g["lineas_sin_costo"] += 1
    salida = []
    for g in sorted(grupos.values(), key=lambda g: (g["moneda"], g["clave"])):
        margen = g["ventas"] - g["costo"]
        salida.append({**g, "cantidad": str(g["cantidad"].normalize()), "ventas": str(g["ventas"]), "costo": str(g["costo"]), "margen": str(margen),
                       "porcentaje": _pct(margen, g["ventas"]) if not g["lineas_sin_costo"] else None})
    return salida


@router.get("/rentabilidad")
async def rentabilidad(desde: Optional[date] = None, hasta: Optional[date] = None, agrupar: Agrupar = "articulo",
                       punto_venta_id: Optional[str] = Query(None, max_length=40),
                       ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    desde, hasta = _rango(desde, hasta)
    filas = _rentabilidad(await _lineas(conn, ctx, desde, hasta, await _pvs(conn, ctx, punto_venta_id)), agrupar)
    totales = {}
    for f in filas:
        t = totales.setdefault(f["moneda"], {"moneda": f["moneda"], "ventas": CERO, "costo": CERO, "lineas_sin_costo": 0})
        t["ventas"] += Decimal(f["ventas"])
        t["costo"] += Decimal(f["costo"])
        t["lineas_sin_costo"] += f["lineas_sin_costo"]
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "modo": ctx["modo"], "agrupar": agrupar, "filas": filas,
            "totales": [{**t, "ventas": str(t["ventas"]), "costo": str(t["costo"]), "margen": str(t["ventas"] - t["costo"]),
                         "porcentaje": _pct(t["ventas"] - t["costo"], t["ventas"]) if not t["lineas_sin_costo"] else None}
                        for t in sorted(totales.values(), key=lambda t: t["moneda"])]}


@router.get("/rentabilidad.csv")
async def rentabilidad_csv(desde: Optional[date] = None, hasta: Optional[date] = None, agrupar: Agrupar = "articulo",
                           punto_venta_id: Optional[str] = Query(None, max_length=40),
                           ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    desde, hasta = _rango(desde, hasta)
    filas = _rentabilidad(await _lineas(conn, ctx, desde, hasta, await _pvs(conn, ctx, punto_venta_id)), agrupar)
    return csv_respuesta(_nombre_csv(f"rentabilidad_{agrupar}", desde, hasta),
                         [{"articulo": "SKU", "categoria": "Categoría", "punto_venta": "Punto de venta", "dia": "Fecha"}[agrupar], "Descripción",
                          "Moneda", "Cantidad", "Ventas", "Costo", "Margen", "Margen %", "Líneas sin costo"],
                         [(f["clave"], f["descripcion"], f["moneda"], Decimal(f["cantidad"]), Decimal(f["ventas"]), Decimal(f["costo"]),
                           Decimal(f["margen"]), Decimal(f["porcentaje"]) if f["porcentaje"] is not None else None, f["lineas_sin_costo"]) for f in filas])


# --- Cierres de caja ---
async def _planillas(conn: asyncpg.Connection, ctx: dict, desde: date, hasta: date) -> list:
    planillas = await conn.fetch("""
        SELECT p.*, c.nombre AS caja_nombre, c.tipo AS caja_tipo, c.razon_social_id,
               ua.usuario AS abierta_por_nombre, uc.usuario AS cerrada_por_nombre
        FROM caja_planillas p JOIN cajas c ON c.id = p.caja_id
        LEFT JOIN usuarios ua ON ua.id = p.abierta_por LEFT JOIN usuarios uc ON uc.id = p.cerrada_por
        WHERE c.razon_social_id = $1 AND p.modo = $2 AND p.fecha BETWEEN $3 AND $4
        ORDER BY p.fecha, c.nombre, p.abierta_en
    """, uuid_o_404(ctx["razon_social_id"]), ctx["modo"], desde, hasta)
    salida = []
    for p in planillas:
        movimientos = await caja._movimientos(conn, p["id"])
        por_medio, por_categoria = await caja._totales(conn, p, movimientos)
        arqueo = {(a["medio_pago_id"], a["moneda"]): a for a in await conn.fetch("SELECT * FROM caja_arqueos WHERE planilla_id = $1", p["id"])}
        medios = []
        for t in por_medio:
            a = arqueo.get((t["medio_pago_id"], t["moneda"]))
            contado = a["contado"] if a is not None else None
            medios.append({"medio": t["medio"], "moneda": t["moneda"], "fondo": t["fondo"], "entradas": t["entradas"], "salidas": t["salidas"],
                           "saldo": t["saldo"], "contado": contado, "diferencia": (contado - t["saldo"]) if contado is not None else None})
        salida.append({"planilla": caja._planilla_resumen(p), "medios": medios, "categorias": por_categoria})
    return salida


def _dec(v) -> Optional[str]:
    return None if v is None else str(v)


@router.get("/caja")
async def cierres_caja(desde: Optional[date] = None, hasta: Optional[date] = None, ctx: dict = Depends(contexto_requerido),
                       conn: asyncpg.Connection = Depends(get_conn)):
    """Planillas del periodo (abiertas y cerradas) con sus totales por medio de pago y el arqueo, y el acumulado
    del periodo por medio de pago y por categoria."""
    desde, hasta = _rango(desde, hasta)
    datos = await _planillas(conn, ctx, desde, hasta)
    acumulado_medio, acumulado_categoria = {}, {}
    for d in datos:
        for m in d["medios"]:
            t = acumulado_medio.setdefault((m["medio"], m["moneda"]), {"medio": m["medio"], "moneda": m["moneda"], "entradas": CERO, "salidas": CERO,
                                                                       "diferencia": CERO, "planillas": 0})
            t["entradas"] += m["entradas"]
            t["salidas"] += m["salidas"]
            t["diferencia"] += m["diferencia"] or CERO
            t["planillas"] += 1
        for c in d["categorias"]:
            t = acumulado_categoria.setdefault((c["categoria"], c["moneda"]), {"categoria": c["categoria"], "moneda": c["moneda"], "entradas": CERO, "salidas": CERO})
            t["entradas"] += c["entradas"]
            t["salidas"] += c["salidas"]
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "modo": ctx["modo"],
            "planillas": [{**d["planilla"],
                           "medios": [{k: (_dec(v) if isinstance(v, Decimal) or v is None else v) for k, v in m.items()} for m in d["medios"]],
                           "categorias": [{**c, "entradas": str(c["entradas"]), "salidas": str(c["salidas"])} for c in d["categorias"]]}
                          for d in datos],
            "por_medio": [{**t, "entradas": str(t["entradas"]), "salidas": str(t["salidas"]), "diferencia": str(t["diferencia"])}
                          for t in sorted(acumulado_medio.values(), key=lambda t: (t["moneda"], t["medio"]))],
            "por_categoria": [{**t, "entradas": str(t["entradas"]), "salidas": str(t["salidas"])}
                              for t in sorted(acumulado_categoria.values(), key=lambda t: (t["moneda"], t["categoria"]))]}


@router.get("/caja.csv")
async def cierres_caja_csv(desde: Optional[date] = None, hasta: Optional[date] = None, ctx: dict = Depends(contexto_requerido),
                           conn: asyncpg.Connection = Depends(get_conn)):
    desde, hasta = _rango(desde, hasta)
    filas = []
    for d in await _planillas(conn, ctx, desde, hasta):
        p = d["planilla"]
        for m in d["medios"]:
            filas.append((date.fromisoformat(p["fecha"]), p["caja"], "Abierta" if p["estado"] == "abierta" else "Cerrada", p["abierta_por"] or "",
                          p["cerrada_por"] or "", m["medio"], m["moneda"], m["fondo"], m["entradas"], m["salidas"], m["saldo"], m["contado"],
                          m["diferencia"], p["observaciones"]))
    return csv_respuesta(_nombre_csv("cierres_caja", desde, hasta),
                         ["Fecha", "Caja", "Estado", "Abrió", "Cerró", "Medio de pago", "Moneda", "Fondo", "Entradas", "Salidas", "Saldo esperado",
                          "Contado", "Diferencia", "Observaciones"], filas)
