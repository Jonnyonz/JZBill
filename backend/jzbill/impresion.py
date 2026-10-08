"""Comprobante para imprimir o guardar como PDF desde el navegador (decision de Jonny 2026-10-08: sin biblioteca de
PDF). HTML armado en el servidor con TODO el texto escapado (html.escape) y CSP estricta: estilos y script en
archivos de /static, nada inline. El QR sigue la especificacion oficial de ARCA (referencias/arca/QR-especificaciones):
https://www.arca.gob.ar/fe/qr/?p=<JSON version 1 en Base64>, generado como SVG con segno."""

import base64
import json
from datetime import date
from decimal import Decimal
from html import escape

import asyncpg
import segno
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from jzbill import __version__
from jzbill.comprobantes import comprobante_visible
from jzbill.contexto import contexto_requerido
from jzbill.cuit import formatear_cuit
from jzbill.db import get_conn

router = APIRouter(tags=["Comprobantes"])

URL_QR = "https://www.arca.gob.ar/fe/qr/?p="
CONDICIONES_EMISOR = {"responsable_inscripto": "IVA Responsable Inscripto", "monotributo": "Responsable Monotributo",
                      "exento": "IVA Exento"}


def texto_qr(cuit: str, fecha: date, punto_venta: int, tipo: int, numero: int, total: Decimal, moneda: str,
             cotizacion: Decimal, doc_tipo: int, doc_nro: int, cae: str) -> str:
    """Texto que codifica el QR (especificacion version 1). Importe y cotizacion como numeros JSON exactos (sin
    float); receptor solo si esta identificado ("de corresponder")."""
    campos = [("ver", "1"), ("fecha", json.dumps(fecha.isoformat())), ("cuit", str(int(cuit))),
              ("ptoVta", str(punto_venta)), ("tipoCmp", str(tipo)), ("nroCmp", str(numero)),
              ("importe", format(total, "f")), ("moneda", json.dumps(moneda)), ("ctz", format(cotizacion.normalize(), "f"))]
    if doc_nro:
        campos += [("tipoDocRec", str(doc_tipo)), ("nroDocRec", str(doc_nro))]
    campos += [("tipoCodAut", json.dumps("E")), ("codAut", str(int(cae)))]
    datos = "{" + ",".join(f'"{k}":{v}' for k, v in campos) + "}"
    return URL_QR + base64.b64encode(datos.encode("utf-8")).decode("ascii")


def _importe(valor: Decimal) -> str:
    """1234.5 -> 1.234,50 (formato argentino)."""
    entero, decimales = f"{valor:,.2f}".split(".")
    return entero.replace(",", ".") + "," + decimales


def _cantidad(valor: Decimal) -> str:
    texto = format(valor.normalize(), "f")
    return texto.replace(".", ",")


def _fecha(d) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


async def _descripcion(conn: asyncpg.Connection, version_id, tipo: str, codigo) -> str:
    if version_id is None:
        return str(codigo)
    valor = await conn.fetchval("SELECT descripcion FROM parametros_fiscales WHERE version_id = $1 AND tipo = $2 "
                                "AND codigo = $3", version_id, tipo, str(codigo))
    return valor or str(codigo)


@router.get("/comprobantes/{comprobante_id}/imprimir", response_class=HTMLResponse)
async def imprimir(comprobante_id: str, ctx: dict = Depends(contexto_requerido),
                   conn: asyncpg.Connection = Depends(get_conn)):
    c = await comprobante_visible(conn, ctx, comprobante_id)
    rs = await conn.fetchrow("SELECT * FROM razones_sociales WHERE id = $1", c["razon_social_id"])
    lineas = await conn.fetch("SELECT * FROM comprobante_lineas WHERE comprobante_id = $1 ORDER BY orden", c["id"])
    version = c["parametros_version_id"]
    doc = await _descripcion(conn, version, "TiposDoc", c["receptor_doc_tipo"])
    condicion = await _descripcion(conn, version, "CondicionIvaReceptor", c["condicion_iva_receptor"])
    concepto = await _descripcion(conn, version, "TiposConcepto", c["concepto"])
    e = escape
    numero = f"{c['punto_venta']:05d}-{c['numero']:08d}"
    titulo = c["nombre"][:-2] if c["letra"] and c["nombre"].endswith(" " + c["letra"]) else c["nombre"]
    filas = "".join(
        f"<tr><td>{e(l['descripcion'])}</td><td class=\"num\">{e(_cantidad(l['cantidad']))}</td>"
        f"<td class=\"num\">{e(_importe(l['precio_unitario']))}</td><td class=\"num\">{e(_importe(l['importe']))}</td></tr>"
        for l in lineas)
    receptor = e(c["receptor_nombre"]) if c["receptor_nombre"] else "Consumidor final"
    documento = f"{e(doc)} {e(str(c['receptor_doc_nro']))}" if c["receptor_doc_nro"] else ""
    periodo = ""
    if c["concepto"] in (2, 3):
        periodo = (f"<p>Período facturado: {_fecha(c['servicio_desde'])} al {_fecha(c['servicio_hasta'])}. "
                   f"Vencimiento del pago: {_fecha(c['vencimiento_pago'])}.</p>")
    moneda = ""
    if c["moneda"] != "PES":
        moneda = f"<p>Moneda: {e(c['moneda'])}. Cotización: {e(_cantidad(c['cotizacion']))}.</p>"
    if c["electronico"]:
        qr = segno.make(texto_qr(rs["cuit"], c["fecha"], c["punto_venta"], c["codigo_arca"], c["numero"],
                                 c["importe_total"], c["moneda"], c["cotizacion"], c["receptor_doc_tipo"],
                                 c["receptor_doc_nro"], c["cae"]), error="m")
        pie = (f"<div class=\"qr\">{qr.svg_inline(scale=3, border=2, title='Código QR de ARCA')}</div>"
               f"<div><p class=\"autorizado\">Comprobante autorizado por ARCA</p>"
               f"<p>CAE: <span class=\"mono\">{e(c['cae'])}</span></p>"
               f"<p>Vencimiento del CAE: {_fecha(c['cae_vencimiento'])}</p></div>")
    else:
        pie = "<div><p class=\"autorizado\">Documento no válido como factura.</p></div>"
    prueba = ""
    if c["modo"] == "prueba":
        prueba = ("<p class=\"aviso-prueba\">Comprobante de PRUEBA (homologación de ARCA): sin validez fiscal.</p>")
    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c['nombre'])} {numero}</title>
<link rel="stylesheet" href="/static/css/impresion.css?v={__version__}">
<script src="/static/js/impresion.js?v={__version__}" defer></script>
</head>
<body>
<div class="barra-impresion"><button id="imprimir" type="button">Imprimir o guardar como PDF</button></div>
<article class="comprobante">
{prueba}
<header class="cabecera">
<div class="emisor">
<h2>{e(rs['nombre_fantasia'] or rs['nombre_legal'])}</h2>
<p>{e(rs['nombre_legal'])}</p>
<p>{e(rs['domicilio'])}</p>
<p>{e(CONDICIONES_EMISOR.get(rs['condicion_iva'], rs['condicion_iva']))}</p>
</div>
<div class="letra"><span>{e(c['letra'] or 'X')}</span>{f"<small>Cód. {c['codigo_arca']:03d}</small>" if c['codigo_arca'] else ''}</div>
<div class="datos-comprobante">
<h1>{e(titulo)}</h1>
<p>N.º <span class="mono">{numero}</span></p>
<p>Fecha: {_fecha(c['fecha'])}</p>
<p>CUIT: <span class="mono">{formatear_cuit(rs['cuit'])}</span></p>
</div>
</header>
<section class="receptor">
<p><strong>{receptor}</strong> {documento}</p>
<p>{f"Condición frente al IVA: {e(condicion)}. " if c['condicion_iva_receptor'] else ""}Concepto: {e(concepto)}.</p>
{periodo}
</section>
<table class="lineas">
<thead><tr><th>Descripción</th><th class="num">Cantidad</th><th class="num">Precio unitario</th><th class="num">Importe</th></tr></thead>
<tbody>{filas}</tbody>
</table>
<section class="totales">
{moneda}
<p class="total">Total: {e(c['moneda'])} {_importe(c['importe_total'])}</p>
</section>
<footer class="pie">{pie}</footer>
</article>
</body>
</html>"""
    return HTMLResponse(html)
