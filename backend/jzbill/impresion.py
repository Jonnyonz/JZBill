"""Representacion impresa del comprobante: HTML para imprimir desde el navegador y PDF (adjunto del correo y
descarga). Las dos salidas comparten los datos (`datos_impresion`). HTML con TODO el texto escapado (html.escape)
y CSP estricta: estilos y script en archivos de /static, nada inline. PDF con `pdf.py` (biblioteca estandar, sin
fpdf2 ni Pillow). El QR sigue la especificacion oficial de ARCA (referencias/arca/QR-especificaciones):
https://www.arca.gob.ar/fe/qr/?p=<JSON version 1 en Base64>, generado con segno (SVG en el HTML, rectangulos en
el PDF)."""

import base64
import json
import unicodedata
from datetime import date
from decimal import Decimal
from html import escape
from urllib.parse import quote

import asyncpg
import segno
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response

from jzbill import __version__, caja, pdf
from jzbill.comprobantes import comprobante_visible
from jzbill.contexto import contexto_requerido
from jzbill.cuit import formatear_cuit
from jzbill.db import get_conn

router = APIRouter(tags=["Comprobantes"])

URL_QR = "https://www.arca.gob.ar/fe/qr/?p="
# RG 1415 Anexo II A, I.a.5: leyenda literal de la condicion frente al IVA del emisor (la norma escribe "INSCRITO").
CONDICIONES_EMISOR = {"responsable_inscripto": "IVA RESPONSABLE INSCRITO", "monotributo": "RESPONSABLE MONOTRIBUTO",
                      "exento": "IVA EXENTO"}
LEYENDA_PRUEBA = "Homologación ARCA, sin validez fiscal."
NO_VALIDO = "Documento no válido como factura."


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


def nombre_archivo(c, numero: str) -> str:
    return f"{c['nombre']} {numero}.pdf"


async def datos_impresion(conn: asyncpg.Connection, c) -> dict:
    """Todo lo que lleva la representacion impresa (RG 1415 Anexo II), comun al HTML, al PDF y al correo."""
    rs = await conn.fetchrow("SELECT * FROM razones_sociales WHERE id = $1", c["razon_social_id"])
    lineas = await conn.fetch("SELECT * FROM comprobante_lineas WHERE comprobante_id = $1 ORDER BY orden", c["id"])
    version = c["parametros_version_id"]
    condicion = await _descripcion(conn, version, "CondicionIvaReceptor", c["condicion_iva_receptor"])
    qr = None
    if c["electronico"]:
        qr = segno.make(texto_qr(rs["cuit"], c["fecha"], c["punto_venta"], c["codigo_arca"], c["numero"],
                                 c["importe_total"], c["moneda"], c["cotizacion"], c["receptor_doc_tipo"],
                                 c["receptor_doc_nro"], c["cae"]), error="m")
    return {
        "c": c, "rs": rs, "lineas": lineas, "condicion": condicion,
        "doc": await _descripcion(conn, version, "TiposDoc", c["receptor_doc_tipo"]),
        "concepto": await _descripcion(conn, version, "TiposConcepto", c["concepto"]),
        # Datos del emisor guardados al emitir (los comprobantes anteriores a la 0006 toman los actuales).
        "domicilio": c["emisor_domicilio"] if c["emisor_domicilio"] is not None else rs["domicilio"],
        "ingresos_brutos": c["emisor_ingresos_brutos"] if c["emisor_ingresos_brutos"] is not None else rs["ingresos_brutos"],
        "inicio_actividades": c["emisor_inicio_actividades"] or rs["inicio_actividades"],
        "condicion_emisor": CONDICIONES_EMISOR.get(rs["condicion_iva"], rs["condicion_iva"]),
        "numero": f"{c['punto_venta']:05d}-{c['numero']:08d}",
        "titulo": c["nombre"][:-2] if c["letra"] and c["nombre"].endswith(" " + c["letra"]) else c["nombre"],
        "consumidor_final": (not c["condicion_iva_receptor"]) or _es_consumidor_final(condicion),
        "pagos": await caja.pagos_de(conn, c["id"]),
        "qr": qr,
        "prueba": c["modo"] == "prueba",   # leyenda discreta junto a la autorizacion (decision de Jonny 2026-10-08)
    }


def _forma_pago(d) -> str:
    return "Forma de pago: " + "; ".join(f"{p['medio']} {_importe(Decimal(p['importe']))}" for p in d["pagos"]) + "."


def _moneda(d) -> str:
    c = d["c"]
    return f"Moneda: {c['moneda']}. Tipo de cambio utilizado: {_cantidad(c['cotizacion'])}."


def _periodo(c) -> str:
    return (f"Período facturado: {_fecha(c['servicio_desde'])} al {_fecha(c['servicio_hasta'])}. "
            f"Vencimiento del pago: {_fecha(c['vencimiento_pago'])}.")


@router.get("/comprobantes/{comprobante_id}/imprimir", response_class=HTMLResponse)
async def imprimir(comprobante_id: str, ctx: dict = Depends(contexto_requerido),
                   conn: asyncpg.Connection = Depends(get_conn)):
    """Representacion impresa segun la RG 1415 Anexo II (aplicada por la RG 4291 art. 14): emisor arriba a la
    izquierda, letra con "Codigo N." al centro, numero, fecha, CUIT, ingresos brutos e inicio de actividades arriba a
    la derecha; receptor; detalle; condiciones de venta; "C.A.E. N." y "Fecha Vto.:" (12 puntos o mas) con el QR."""
    c = await comprobante_visible(conn, ctx, comprobante_id)
    d = await datos_impresion(conn, c)
    rs, numero = d["rs"], d["numero"]
    e = escape
    filas = "".join(
        f"<tr><td>{e(l['descripcion'])}"
        + (f"<br><small>{e(l['oferta_detalle'])} (precio de lista {e(_importe(l['precio_lista']))})</small>" if l["oferta_detalle"] else "")
        + f"</td><td class=\"num\">{e(_cantidad(l['cantidad']))}</td>"
        f"<td class=\"num\">{e(_importe(l['precio_unitario']))}</td><td class=\"num\">{e(_importe(l['importe']))}</td></tr>"
        for l in d["lineas"])

    receptor = []
    if d["consumidor_final"]:
        receptor.append("<p><strong>A CONSUMIDOR FINAL</strong></p>")
        if c["receptor_nombre"]:
            receptor.append(f"<p>{e(c['receptor_nombre'])}</p>")
    else:
        receptor.append(f"<p><strong>{e(c['receptor_nombre'] or 'Sin nombre')}</strong></p>")
        receptor.append(f"<p>Condición frente al IVA: {e(d['condicion'].upper())}</p>")
    if c["receptor_doc_nro"]:
        receptor.append(f"<p>{e(d['doc'])}: <span class=\"mono\">{e(str(c['receptor_doc_nro']))}</span></p>")
    if c["receptor_domicilio"]:
        receptor.append(f"<p>Domicilio: {e(c['receptor_domicilio'])}</p>")
    if c["concepto"] in (2, 3):
        receptor.append(f"<p>{e(_periodo(c))}</p>")

    forma_pago = f"<p>{e(_forma_pago(d))}</p>" if d["pagos"] else ""
    moneda = f"<p>{e(_moneda(d))}</p>" if c["moneda"] != "PES" else ""
    prueba = f"<p class=\"leyenda-prueba\">{LEYENDA_PRUEBA}</p>" if d["prueba"] else ""
    if d["qr"] is not None:
        pie = (f"<div class=\"qr\">{d['qr'].svg_inline(border=2, omitsize=True, title='Código QR de ARCA')}</div>"
               f"<div class=\"autorizacion\"><p class=\"cae\">C.A.E. N° <span class=\"mono\">{e(c['cae'])}</span></p>"
               f"<p class=\"cae\">Fecha Vto.: {_fecha(c['cae_vencimiento'])}</p>{prueba}</div>")
    else:
        pie = f"<div class=\"autorizacion\"><p class=\"autorizado\">{NO_VALIDO}</p>{prueba}</div>"
    fantasia = f"<h2>{e(rs['nombre_fantasia'])}</h2>" if rs["nombre_fantasia"] else ""
    datos_derecha = [f"<p>N.º <span class=\"mono\">{numero}</span></p>",
                     f"<p>Fecha de emisión: {_fecha(c['fecha'])}</p>",
                     f"<p>CUIT: <span class=\"mono\">{formatear_cuit(rs['cuit'])}</span></p>"]
    if d["ingresos_brutos"]:
        datos_derecha.append(f"<p>Ingresos Brutos: {e(d['ingresos_brutos'])}</p>")
    if d["inicio_actividades"]:
        datos_derecha.append(f"<p>INICIO DE ACTIVIDADES: {_fecha(d['inicio_actividades'])}</p>")
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
<p>{e(d['domicilio'])}</p>
<p>{e(d['condicion_emisor'])}</p>
</div>
<div class="letra"><span>{e(c['letra'] or 'X')}</span>{codigo}</div>
<div class="datos-comprobante">
<h1>{e(d['titulo'])}</h1>
{"".join(datos_derecha)}
</div>
</header>
<section class="receptor">
{"".join(receptor)}
<p>Concepto: {e(d['concepto'])}. Condiciones de venta: {e(c['condicion_venta'])}.</p>
{forma_pago}
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


def comprobante_pdf(d: dict) -> bytes:
    """El mismo comprobante que `imprimir`, en PDF (A4, Helvetica): cabecera con emisor, letra y datos; receptor;
    detalle con corte de pagina; total; QR con C.A.E. y vencimiento, o la leyenda de no valido como factura."""
    c, rs = d["c"], d["rs"]
    documento = pdf.Documento(f"{c['nombre']} {d['numero']}", rs["nombre_legal"], f"JZBill {__version__}")
    ancho_hoja, alto_hoja = pdf.A4
    margen, derecha, centro = 40, pdf.A4[0] - 40, ancho_hoja / 2
    pagina = documento.pagina()
    y = alto_hoja - margen

    # Cabecera: emisor a la izquierda, letra al centro, datos del comprobante a la derecha.
    yi = y
    if rs["nombre_fantasia"]:
        pagina.texto(margen, yi - 12, rs["nombre_fantasia"], 13, True)
        yi -= 18
    pagina.texto(margen, yi - 10, rs["nombre_legal"], 10.5, True)
    yi -= 15
    for linea in pdf.partir(d["domicilio"] or "", 200, 9) + [d["condicion_emisor"]]:
        pagina.texto(margen, yi - 9, linea, 9)
        yi -= 12
    pagina.rectangulo(centro - 22, y - 44, 44, 44, borde=0)
    pagina.texto_centrado(centro, y - 34, c["letra"] or "X", 26, True)
    if c["codigo_arca"]:
        pagina.texto_centrado(centro, y - 54, f"Código N° {c['codigo_arca']:03d}", 6.5)
    xd, yd = centro + 50, y
    pagina.texto(xd, yd - 12, d["titulo"], 14, True)
    yd -= 20
    datos = [f"N.º {d['numero']}", f"Fecha de emisión: {_fecha(c['fecha'])}", f"CUIT: {formatear_cuit(rs['cuit'])}"]
    if d["ingresos_brutos"]:
        datos.append(f"Ingresos Brutos: {d['ingresos_brutos']}")
    if d["inicio_actividades"]:
        datos.append(f"INICIO DE ACTIVIDADES: {_fecha(d['inicio_actividades'])}")
    for texto in datos:
        pagina.texto(xd, yd - 9, texto, 9.5)
        yd -= 13
    y = min(yi, yd, y - 62) - 8
    pagina.linea(margen, y, derecha, y, 0.75)
    y -= 14

    # Receptor y condiciones.
    receptor = []
    if d["consumidor_final"]:
        receptor.append(("A CONSUMIDOR FINAL", True))
        if c["receptor_nombre"]:
            receptor.append((c["receptor_nombre"], False))
    else:
        receptor.append((c["receptor_nombre"] or "Sin nombre", True))
        receptor.append((f"Condición frente al IVA: {d['condicion'].upper()}", False))
    if c["receptor_doc_nro"]:
        receptor.append((f"{d['doc']}: {c['receptor_doc_nro']}", False))
    if c["receptor_domicilio"]:
        receptor.append((f"Domicilio: {c['receptor_domicilio']}", False))
    if c["concepto"] in (2, 3):
        receptor.append((_periodo(c), False))
    receptor.append((f"Concepto: {d['concepto']}. Condiciones de venta: {c['condicion_venta']}.", False))
    if d["pagos"]:
        receptor.append((_forma_pago(d), False))
    if c["moneda"] != "PES":
        receptor.append((_moneda(d), False))
    for texto, negrita in receptor:
        for linea in pdf.partir(texto, derecha - margen, 9.5, negrita):
            pagina.texto(margen, y - 9, linea, 9.5, negrita)
            y -= 13
    y -= 4

    # Detalle, con encabezado repetido en cada pagina.
    x_cantidad, x_precio, x_importe, ancho_descripcion = 385, 470, derecha - 3, 290

    def encabezado(pag, y_):
        pag.rectangulo(margen, y_ - 15, derecha - margen, 15, relleno=0.92)
        pag.texto(margen + 3, y_ - 11, "Descripción", 9, True)
        pag.texto_derecha(x_cantidad, y_ - 11, "Cantidad", 9, True)
        pag.texto_derecha(x_precio, y_ - 11, "Precio unitario", 9, True)
        pag.texto_derecha(x_importe, y_ - 11, "Importe", 9, True)
        return y_ - 19

    y = encabezado(pagina, y)
    for l in d["lineas"]:
        descripcion = pdf.partir(l["descripcion"], ancho_descripcion, 9)
        detalle = pdf.partir(f"{l['oferta_detalle']} (precio de lista {_importe(l['precio_lista'])})", ancho_descripcion, 7.5) if l["oferta_detalle"] else []
        alto = 12 * len(descripcion) + 10 * len(detalle) + 3
        if y - alto < margen + 30:
            pagina = documento.pagina()
            y = encabezado(pagina, alto_hoja - margen)
        yl = y
        for texto in descripcion:
            pagina.texto(margen + 3, yl - 9, texto, 9)
            yl -= 12
        for texto in detalle:
            pagina.texto(margen + 3, yl - 8, texto, 7.5, gris=0.4)
            yl -= 10
        pagina.texto_derecha(x_cantidad, y - 9, _cantidad(l["cantidad"]), 9)
        pagina.texto_derecha(x_precio, y - 9, _importe(l["precio_unitario"]), 9)
        pagina.texto_derecha(x_importe, y - 9, _importe(l["importe"]), 9)
        y -= alto
        pagina.linea(margen, y, derecha, y, 0.3, 0.8)

    # Total y autorizacion (juntos en la misma pagina).
    if y - 160 < margen:
        pagina = documento.pagina()
        y = alto_hoja - margen
    y -= 10
    pagina.texto_derecha(x_importe, y - 12, f"Total: {c['moneda']} {_importe(c['importe_total'])}", 13, True)
    y -= 30
    if d["qr"] is not None:
        pagina.qr(d["qr"].matrix_iter(scale=1, border=2), margen, y, 110)
        xa = margen + 125
        pagina.texto(xa, y - 24, f"C.A.E. N° {c['cae']}", 12, True)
        pagina.texto(xa, y - 42, f"Fecha Vto.: {_fecha(c['cae_vencimiento'])}", 12, True)
        if d["prueba"]:
            pagina.texto(xa, y - 60, LEYENDA_PRUEBA, 9, gris=0.45)
    else:
        pagina.texto(margen, y - 14, NO_VALIDO, 11, True)
        if d["prueba"]:
            pagina.texto(margen, y - 30, LEYENDA_PRUEBA, 9, gris=0.45)
    total = len(documento.paginas)
    for i, pag in enumerate(documento.paginas, start=1):
        pag.texto(margen, 24, f"Generado con JZBill {__version__}", 7, gris=0.5)
        pag.texto_derecha(derecha, 24, f"Página {i} de {total}", 7, gris=0.5)
    return documento.bytes()


@router.get("/comprobantes/{comprobante_id}/pdf")
async def comprobante_en_pdf(comprobante_id: str, ctx: dict = Depends(contexto_requerido),
                             conn: asyncpg.Connection = Depends(get_conn)):
    """El comprobante en PDF (el mismo que va adjunto en el correo), para verlo o guardarlo."""
    c = await comprobante_visible(conn, ctx, comprobante_id)
    d = await datos_impresion(conn, c)
    nombre = nombre_archivo(c, d["numero"])
    ascii_ = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().replace('"', "")
    return Response(comprobante_pdf(d), media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nombre)}"})
