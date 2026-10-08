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
# RG 1415 Anexo II A, I.a.5: leyenda literal de la condicion frente al IVA del emisor (la norma escribe "INSCRITO").
CONDICIONES_EMISOR = {"responsable_inscripto": "IVA RESPONSABLE INSCRITO", "monotributo": "RESPONSABLE MONOTRIBUTO",
                      "exento": "IVA EXENTO"}


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


def _es_consumidor_final(descripcion: str) -> bool:
    return " ".join(descripcion.lower().split()) == "consumidor final"


@router.get("/comprobantes/{comprobante_id}/imprimir", response_class=HTMLResponse)
async def imprimir(comprobante_id: str, ctx: dict = Depends(contexto_requerido),
                   conn: asyncpg.Connection = Depends(get_conn)):
    """Representacion impresa segun la RG 1415 Anexo II (aplicada por la RG 4291 art. 14): emisor arriba a la
    izquierda, letra con "Codigo N." al centro, numero, fecha, CUIT, ingresos brutos e inicio de actividades arriba a
    la derecha; receptor; detalle; condiciones de venta; "C.A.E. N." y "Fecha Vto.:" (12 puntos o mas) con el QR."""
    c = await comprobante_visible(conn, ctx, comprobante_id)
    rs = await conn.fetchrow("SELECT * FROM razones_sociales WHERE id = $1", c["razon_social_id"])
    lineas = await conn.fetch("SELECT * FROM comprobante_lineas WHERE comprobante_id = $1 ORDER BY orden", c["id"])
    version = c["parametros_version_id"]
    doc = await _descripcion(conn, version, "TiposDoc", c["receptor_doc_tipo"])
    condicion = await _descripcion(conn, version, "CondicionIvaReceptor", c["condicion_iva_receptor"])
    concepto = await _descripcion(conn, version, "TiposConcepto", c["concepto"])
    e = escape
    # Datos del emisor guardados al emitir (los comprobantes anteriores a la 0006 toman los actuales).
    domicilio = c["emisor_domicilio"] if c["emisor_domicilio"] is not None else rs["domicilio"]
    ingresos_brutos = c["emisor_ingresos_brutos"] if c["emisor_ingresos_brutos"] is not None else rs["ingresos_brutos"]
    inicio_actividades = c["emisor_inicio_actividades"] or rs["inicio_actividades"]
    numero = f"{c['punto_venta']:05d}-{c['numero']:08d}"
    titulo = c["nombre"][:-2] if c["letra"] and c["nombre"].endswith(" " + c["letra"]) else c["nombre"]
    filas = "".join(
        f"<tr><td>{e(l['descripcion'])}</td><td class=\"num\">{e(_cantidad(l['cantidad']))}</td>"
        f"<td class=\"num\">{e(_importe(l['precio_unitario']))}</td><td class=\"num\">{e(_importe(l['importe']))}</td></tr>"
        for l in lineas)

    consumidor_final = (not c["condicion_iva_receptor"]) or _es_consumidor_final(condicion)
    receptor = []
    if consumidor_final:
        receptor.append("<p><strong>A CONSUMIDOR FINAL</strong></p>")
        if c["receptor_nombre"]:
            receptor.append(f"<p>{e(c['receptor_nombre'])}</p>")
    else:
        receptor.append(f"<p><strong>{e(c['receptor_nombre'] or 'Sin nombre')}</strong></p>")
        receptor.append(f"<p>Condición frente al IVA: {e(condicion.upper())}</p>")
    if c["receptor_doc_nro"]:
        receptor.append(f"<p>{e(doc)}: <span class=\"mono\">{e(str(c['receptor_doc_nro']))}</span></p>")
    if c["receptor_domicilio"]:
        receptor.append(f"<p>Domicilio: {e(c['receptor_domicilio'])}</p>")
    if c["concepto"] in (2, 3):
        receptor.append(f"<p>Período facturado: {_fecha(c['servicio_desde'])} al {_fecha(c['servicio_hasta'])}. "
                        f"Vencimiento del pago: {_fecha(c['vencimiento_pago'])}.</p>")

    moneda = ""
    if c["moneda"] != "PES":
        moneda = f"<p>Moneda: {e(c['moneda'])}. Tipo de cambio utilizado: {e(_cantidad(c['cotizacion']))}.</p>"
    # Modo prueba: leyenda discreta junto a la autorizacion (decision de Jonny 2026-10-08), siempre presente.
    prueba = "<p class=\"leyenda-prueba\">Homologación ARCA, sin validez fiscal.</p>" if c["modo"] == "prueba" else ""
    if c["electronico"]:
        qr = segno.make(texto_qr(rs["cuit"], c["fecha"], c["punto_venta"], c["codigo_arca"], c["numero"],
                                 c["importe_total"], c["moneda"], c["cotizacion"], c["receptor_doc_tipo"],
                                 c["receptor_doc_nro"], c["cae"]), error="m")
        pie = (f"<div class=\"qr\">{qr.svg_inline(border=2, omitsize=True, title='Código QR de ARCA')}</div>"
               f"<div class=\"autorizacion\"><p class=\"cae\">C.A.E. N° <span class=\"mono\">{e(c['cae'])}</span></p>"
               f"<p class=\"cae\">Fecha Vto.: {_fecha(c['cae_vencimiento'])}</p>{prueba}</div>")
    else:
        pie = f"<div class=\"autorizacion\"><p class=\"autorizado\">Documento no válido como factura.</p>{prueba}</div>"
    fantasia = f"<h2>{e(rs['nombre_fantasia'])}</h2>" if rs["nombre_fantasia"] else ""
    datos_derecha = [f"<p>N.º <span class=\"mono\">{numero}</span></p>",
                     f"<p>Fecha de emisión: {_fecha(c['fecha'])}</p>",
                     f"<p>CUIT: <span class=\"mono\">{formatear_cuit(rs['cuit'])}</span></p>"]
    if ingresos_brutos:
        datos_derecha.append(f"<p>Ingresos Brutos: {e(ingresos_brutos)}</p>")
    if inicio_actividades:
        datos_derecha.append(f"<p>INICIO DE ACTIVIDADES: {_fecha(inicio_actividades)}</p>")
    codigo = f"<small>Código N° {c['codigo_arca']:03d}</small>" if c["codigo_arca"] else ""
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
<header class="cabecera">
<div class="emisor">
{fantasia}
<p class="razon-social">{e(rs['nombre_legal'])}</p>
<p>{e(domicilio)}</p>
<p>{e(CONDICIONES_EMISOR.get(rs['condicion_iva'], rs['condicion_iva']))}</p>
</div>
<div class="letra"><span>{e(c['letra'] or 'X')}</span>{codigo}</div>
<div class="datos-comprobante">
<h1>{e(titulo)}</h1>
{"".join(datos_derecha)}
</div>
</header>
<section class="receptor">
{"".join(receptor)}
<p>Concepto: {e(concepto)}. Condiciones de venta: {e(c['condicion_venta'])}.</p>
</section>
<section class="detalle">
<table class="lineas">
<thead><tr><th>Descripción</th><th class="num">Cantidad</th><th class="num">Precio unitario</th><th class="num">Importe</th></tr></thead>
<tbody>{filas}</tbody>
</table>
</section>
<section class="totales">
{moneda}
<p class="total">Total: {e(c['moneda'])} {_importe(c['importe_total'])}</p>
</section>
<footer class="pie">{pie}</footer>
</article>
</body>
</html>"""
    return HTMLResponse(html)
