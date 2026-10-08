"""Emision y consulta de comprobantes, en el contexto de la sesion (razon social, modo y punto de venta).

Numeracion (diseno, seccion 5): el contador del formulario y modo se bloquea con SELECT ... FOR UPDATE dentro de una
transaccion; si es electronico se pide el CAE a ARCA antes de confirmar. Si ARCA rechaza, se revierte y el numero
queda libre. Si se pierde la respuesta, se consulta FECompConsultar antes de decidir. Antes de pedir el CAE se
verifica que el ultimo numero de ARCA coincida con el de JZBill: si no, se frena (lo corrige un administrador
sincronizando el formulario) en vez de saltear o repetir numeros.

Fase 3 (decisiones de Jonny 2026-10-08): receptor consumidor final o cargado a mano; lineas con descripcion libre;
comprobantes C (A y B necesitan IVA discriminado y un emisor responsable inscripto para probarlos)."""

import asyncio
import json
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jzbill import config
from jzbill.arca import parametros, servicio, soap, wsfev1
from jzbill.arca_api import _error as error_arca
from jzbill.auth import client_ip, registrar
from jzbill.contexto import contexto_requerido
from jzbill.cuit import normalizar_cuit
from jzbill.db import get_conn
from jzbill.permisos import puntos_venta_visibles, uuid_o_404

router = APIRouter(prefix="/api/comprobantes", tags=["Comprobantes"])
router_facturacion = APIRouter(prefix="/api/facturacion", tags=["Comprobantes"])

EMITEN = ("administrador", "supervisor", "cajero")
CENTAVO = Decimal("0.01")
# ponytail: Argentina no tiene horario de verano desde 2009; UTC-3 fijo (sin depender de tzdata).
HORA_AR = timezone(timedelta(hours=-3))
LETRAS_SOPORTADAS = ("C",)


class Linea(BaseModel):
    descripcion: str = Field(min_length=1, max_length=250)
    cantidad: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    precio_unitario: Decimal = Field(ge=0, max_digits=15, decimal_places=2)


class Receptor(BaseModel):
    doc_tipo: int = Field(ge=0, le=999)
    doc_nro: str = Field(default="0", max_length=20)
    nombre: str = Field(default="", max_length=200)
    condicion_iva: int = Field(ge=0, le=99)   # 0: sin informar (solo no electronicos; los electronicos se validan)


class ComprobanteNuevo(BaseModel):
    formulario_id: str = Field(max_length=40)
    concepto: Literal[1, 2, 3] = 1
    receptor: Receptor
    moneda: str = Field(default="PES", min_length=3, max_length=3)
    lineas: List[Linea] = Field(min_length=1, max_length=100)
    servicio_desde: Optional[date] = None
    servicio_hasta: Optional[date] = None
    vencimiento_pago: Optional[date] = None
    asociado_id: Optional[str] = Field(default=None, max_length=40)


class Rechazo(Exception):
    def __init__(self, respuesta: dict):
        self.respuesta = respuesta


def _normal(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().strip().lower()


def es_nota(nombre: str) -> bool:
    return _normal(nombre).startswith(("nota de credito", "nota de debito"))


def _items(vigentes: Optional[dict], tipo: str) -> list:
    return [] if vigentes is None else vigentes["tipos"].get(tipo, [])


def _item(vigentes: Optional[dict], tipo: str, codigo) -> Optional[dict]:
    return next((i for i in _items(vigentes, tipo) if i["codigo"] == str(codigo)), None)


def clases(item: dict) -> list:
    """Clases de comprobante de una condicion frente al IVA. ARCA manda Cmp_Clase como texto de hasta 5 caracteres
    que puede juntar varias (por ejemplo "A/M/C"); se separa en cada una ("A", "M", "C", "ALEY", "49")."""
    salida = set()
    for valor in item["datos"].get("Cmp_Clase", []):
        salida.update(p for p in "".join(c if c.isalnum() else " " for c in str(valor).upper()).split() if p)
    return sorted(salida)


def _fecha_arca(valor: str) -> Optional[date]:
    try:
        return date(int(valor[:4]), int(valor[4:6]), int(valor[6:8]))
    except (TypeError, ValueError):
        return None


def _yyyymmdd(d: Optional[date]) -> Optional[str]:
    return d.strftime("%Y%m%d") if d else None


def calcular(lineas: List[Linea]) -> tuple:
    """(lineas con importe, total). Importe por linea = cantidad x precio redondeado a centavos (mitad hacia
    arriba); el total es la suma de los importes ya redondeados, asi coincide con lo impreso."""
    salida = []
    for orden, linea in enumerate(lineas, start=1):
        importe = (linea.cantidad * linea.precio_unitario).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        salida.append({"orden": orden, "descripcion": linea.descripcion.strip(), "cantidad": linea.cantidad,
                       "precio_unitario": linea.precio_unitario, "importe": importe})
    return salida, sum((l["importe"] for l in salida), Decimal("0.00"))


async def _pv_visibles(conn: asyncpg.Connection, usuario: dict, rs_id) -> list:
    return [pv["id"] for pv in await puntos_venta_visibles(conn, usuario, rs_id, solo_activos=False)]


# --- Opciones para la pantalla de facturacion ---
@router_facturacion.get("/opciones")
async def opciones(ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    rs_id = uuid_o_404(ctx["razon_social_id"])
    formularios = []
    if ctx["punto_venta_id"]:
        formularios = [{"id": str(f["id"]), "nombre": f["nombre"], "letra": f["letra"], "electronico": f["electronico"],
                        "codigo_arca": f["codigo_arca"], "es_nota": es_nota(f["nombre"]),
                        "soportado": (not f["electronico"]) or f["letra"] in LETRAS_SOPORTADAS}
                       for f in await conn.fetch("""
                           SELECT * FROM formularios WHERE razon_social_id = $1 AND punto_venta_id = $2 AND activo
                           ORDER BY electronico DESC, codigo_arca, nombre""", rs_id, uuid_o_404(ctx["punto_venta_id"]))]
    vigentes = await parametros.vigentes(conn, ctx["modo"])
    simple = lambda tipo: [{"codigo": i["codigo"], "descripcion": i["descripcion"]} for i in _items(vigentes, tipo)]
    asociables = await conn.fetch("""
        SELECT id, nombre, letra, punto_venta, numero, fecha, importe_total, moneda FROM comprobantes
        WHERE razon_social_id = $1 AND modo = $2 AND electronico ORDER BY creado_en DESC LIMIT 100
    """, rs_id, ctx["modo"])
    return {
        "punto_venta": ctx["punto_venta_numero"], "modo": ctx["modo"], "formularios": formularios,
        "parametros": vigentes is not None,
        "documentos": simple("TiposDoc"), "monedas": simple("TiposMonedas"), "conceptos": simple("TiposConcepto"),
        "condiciones": [{"codigo": i["codigo"], "descripcion": i["descripcion"],
                         "clases": clases(i)} for i in _items(vigentes, "CondicionIvaReceptor")],
        "asociables": [{"id": str(a["id"]), "nombre": a["nombre"], "letra": a["letra"], "punto_venta": a["punto_venta"],
                        "numero": a["numero"], "fecha": a["fecha"].isoformat(), "total": str(a["importe_total"]),
                        "moneda": a["moneda"]} for a in asociables if not es_nota(a["nombre"])],
    }


# --- Emision ---
async def _recuperar(url: str, cred, pv: int, tipo: int, numero: int, total: Decimal) -> dict:
    """Se perdio la respuesta del CAE: ARCA pudo haberlo autorizado igual. Se consulta ese numero."""
    try:
        c = await asyncio.to_thread(wsfev1.consultar, url, cred, pv, tipo, numero)
    except wsfev1.ErrorNegocio:
        raise HTTPException(502, "ARCA no respondió y el comprobante no quedó autorizado. Probá de nuevo.")
    except soap.ErrorArca:
        raise HTTPException(503, f"Sin respuesta de ARCA: no se sabe si el comprobante {pv}-{numero} quedó "
                                 "autorizado. Antes de volver a emitir, un administrador tiene que consultar el "
                                 "último número en ARCA desde el formulario.")
    if c.get("Resultado") == "A" and c.get("CodAutorizacion") and Decimal(c.get("ImpTotal") or "0") == total:
        return {"resultado": "A", "cae": c["CodAutorizacion"], "vencimiento_cae": c.get("FchVto", ""),
                "observaciones": c.get("observaciones", []), "errores": []}
    raise HTTPException(409, f"ARCA tiene el comprobante {pv}-{numero} con otros datos. Un administrador tiene que "
                             "revisarlo y sincronizar el formulario.")


@router.post("", status_code=201)
async def emitir(data: ComprobanteNuevo, request: Request, ctx: dict = Depends(contexto_requerido),
                 conn: asyncpg.Connection = Depends(get_conn)):
    usuario, modo = ctx["usuario"], ctx["modo"]
    if usuario["rol"] not in EMITEN:
        raise HTTPException(403, "No tiene permiso para esta acción.")
    if not ctx["punto_venta_id"]:
        raise HTTPException(409, "No tiene un punto de venta asignado en esta sucursal.")
    rs = await conn.fetchrow("SELECT * FROM razones_sociales WHERE id = $1", uuid_o_404(ctx["razon_social_id"]))
    f = await conn.fetchrow("""
        SELECT f.*, pv.numero AS pv_numero FROM formularios f JOIN puntos_venta pv ON pv.id = f.punto_venta_id
        WHERE f.id = $1 AND f.razon_social_id = $2 AND f.punto_venta_id = $3 AND f.activo AND pv.activo
    """, uuid_o_404(data.formulario_id), rs["id"], uuid_o_404(ctx["punto_venta_id"]))
    if f is None:
        raise HTTPException(404, "No encontrado.")
    lineas, total = calcular(data.lineas)
    if total <= 0:
        raise HTTPException(400, "El total tiene que ser mayor a cero.")
    if data.concepto in (2, 3) and not (data.servicio_desde and data.servicio_hasta and data.vencimiento_pago):
        raise HTTPException(400, "Para servicios hacen falta las fechas del período y el vencimiento del pago.")

    vigentes = await parametros.vigentes(conn, modo)
    doc_nro = "".join(c for c in data.receptor.doc_nro if c.isdigit()) or "0"
    if len(doc_nro) > 11:
        raise HTTPException(400, "Número de documento inválido.")
    doc = _item(vigentes, "TiposDoc", data.receptor.doc_tipo)
    if doc and _normal(doc["descripcion"]) in ("cuit", "cuil") and normalizar_cuit(doc_nro) is None:
        raise HTTPException(400, "El CUIT o CUIL del receptor no es válido (dígito verificador).")
    asociado = None
    cotizacion = "1"
    cred = None
    url = config.ARCA_URLS[modo]["wsfe"]
    if f["electronico"]:
        if f["letra"] not in LETRAS_SOPORTADAS:
            raise HTTPException(409, "Por ahora JZBill emite comprobantes C. Los A y B llegan cuando se prueben con "
                                     "un emisor responsable inscripto.")
        if vigentes is None:
            raise HTTPException(409, "Faltan los parámetros fiscales de ARCA de este modo: actualizalos desde "
                                     "Conexión con ARCA.")
        if doc is None:
            raise HTTPException(400, "Tipo de documento del receptor desconocido para ARCA.")
        condicion = _item(vigentes, "CondicionIvaReceptor", data.receptor.condicion_iva)
        if condicion is None or f["letra"] not in clases(condicion):
            raise HTTPException(400, f"Esa condición frente al IVA del receptor no corresponde a un comprobante "
                                     f"{f['letra']} según ARCA.")
        if _item(vigentes, "TiposMonedas", data.moneda) is None:
            raise HTTPException(400, "Moneda desconocida para ARCA.")
        if es_nota(f["nombre"]):
            if not data.asociado_id:
                raise HTTPException(400, "Elegí el comprobante al que corresponde la nota.")
            asociado = await conn.fetchrow("""
                SELECT * FROM comprobantes WHERE id = $1 AND razon_social_id = $2 AND modo = $3 AND electronico
            """, uuid_o_404(data.asociado_id), rs["id"], modo)
            if asociado is None or asociado["letra"] != f["letra"] or es_nota(asociado["nombre"]):
                raise HTTPException(400, "El comprobante asociado tiene que ser una factura de la misma letra.")
        try:
            # Fuera de la transaccion: si el comprobante se revierte, el ticket nuevo del WSAA no se pierde.
            cred = await servicio.credenciales(conn, rs, modo)
            if data.moneda != "PES":
                cotizacion, _ = await asyncio.to_thread(wsfev1.cotizacion, url, cred, data.moneda)
        except soap.ErrorArca as e:
            raise error_arca(e)

    hoy = datetime.now(HORA_AR).date()
    try:
        async with conn.transaction():
            await conn.execute("SET LOCAL lock_timeout = '20s'")
            ultimo = await conn.fetchval("SELECT ultimo_numero FROM contadores WHERE formulario_id = $1 AND modo = $2 "
                                         "FOR UPDATE", f["id"], modo)
            numero = ultimo + 1
            cae = vencimiento = None
            observaciones = []
            if f["electronico"]:
                try:
                    ultimo_arca = await asyncio.to_thread(wsfev1.ultimo_autorizado, url, cred, f["pv_numero"],
                                                          f["codigo_arca"])
                except soap.ErrorArca as e:
                    raise error_arca(e)
                if ultimo_arca != ultimo:
                    raise HTTPException(409, f"La numeración no coincide: en ARCA el último {f['nombre']} es el "
                                             f"{ultimo_arca} y en JZBill el {ultimo}. Un administrador tiene que tocar "
                                             "'Consultar último número en ARCA' en el formulario.")
                detalle = {
                    "Concepto": data.concepto, "DocTipo": data.receptor.doc_tipo, "DocNro": int(doc_nro),
                    "CbteDesde": numero, "CbteHasta": numero, "CbteFch": _yyyymmdd(hoy),
                    # Comprobante C: el total es el subtotal (ImpNeto); sin IVA, no gravado ni exento.
                    "ImpTotal": total, "ImpTotConc": Decimal("0"), "ImpNeto": total, "ImpOpEx": Decimal("0"),
                    "ImpTrib": Decimal("0"), "ImpIVA": Decimal("0"),
                    "FchServDesde": _yyyymmdd(data.servicio_desde) if data.concepto in (2, 3) else None,
                    "FchServHasta": _yyyymmdd(data.servicio_hasta) if data.concepto in (2, 3) else None,
                    "FchVtoPago": _yyyymmdd(data.vencimiento_pago) if data.concepto in (2, 3) else None,
                    "MonId": data.moneda, "MonCotiz": cotizacion,
                    "CanMisMonExt": "N" if data.moneda != "PES" else None,
                    "CondicionIVAReceptorId": data.receptor.condicion_iva}
                asociados = ()
                if asociado is not None:
                    asociados = ({"Tipo": asociado["codigo_arca"], "PtoVta": asociado["punto_venta"],
                                  "Nro": asociado["numero"], "Cuit": rs["cuit"],
                                  "CbteFch": _yyyymmdd(asociado["fecha"])},)
                try:
                    r = await asyncio.to_thread(wsfev1.solicitar_cae, url, cred, f["pv_numero"], f["codigo_arca"],
                                                detalle, asociados)
                except soap.ErrorRed:
                    r = await _recuperar(url, cred, f["pv_numero"], f["codigo_arca"], numero, total)
                except soap.ErrorArca as e:
                    raise error_arca(e)
                if r["resultado"] != "A" or not r["cae"]:
                    raise Rechazo(r)
                cae, vencimiento, observaciones = r["cae"], _fecha_arca(r["vencimiento_cae"]), r["observaciones"]
                if vencimiento is None:
                    raise HTTPException(502, "ARCA autorizó el comprobante pero sin fecha de vencimiento del CAE.")
            comprobante_id = await conn.fetchval("""
                INSERT INTO comprobantes (razon_social_id, formulario_id, modo, electronico, codigo_arca, nombre, letra,
                    punto_venta, numero, fecha, concepto, servicio_desde, servicio_hasta, vencimiento_pago,
                    receptor_doc_tipo, receptor_doc_nro, receptor_nombre, condicion_iva_receptor, moneda, cotizacion,
                    importe_neto, importe_total, cae, cae_vencimiento, observaciones_arca, parametros_version_id,
                    comprobante_ref, usuario_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                        $21, $21, $22, $23, $24, $25, $26, $27)
                RETURNING id
            """, rs["id"], f["id"], modo, f["electronico"], f["codigo_arca"], f["nombre"], f["letra"], f["pv_numero"],
                numero, hoy, data.concepto, data.servicio_desde if data.concepto in (2, 3) else None,
                data.servicio_hasta if data.concepto in (2, 3) else None,
                data.vencimiento_pago if data.concepto in (2, 3) else None,
                data.receptor.doc_tipo, int(doc_nro), data.receptor.nombre.strip(), data.receptor.condicion_iva,
                data.moneda, Decimal(cotizacion), total, cae, vencimiento, json.dumps(observaciones),
                vigentes["version"] if vigentes else None, asociado["id"] if asociado else None, usuario["id"])
            await conn.executemany("""
                INSERT INTO comprobante_lineas (comprobante_id, orden, descripcion, cantidad, precio_unitario, importe)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, [(comprobante_id, l["orden"], l["descripcion"], l["cantidad"], l["precio_unitario"], l["importe"])
                  for l in lineas])
            await conn.execute("UPDATE contadores SET ultimo_numero = $3, actualizado_en = now() "
                               "WHERE formulario_id = $1 AND modo = $2", f["id"], modo, numero)
            await registrar(conn, usuario["id"], usuario["usuario"], "COMPROBANTE_EMITIDO",
                            f"{f['nombre']} {f['pv_numero']:05d}-{numero:08d}, {total} {data.moneda}, modo {modo}"
                            + (f", CAE {cae}." if cae else "."), client_ip(request), rs["id"])
    except Rechazo as e:
        motivos = "; ".join(f"{o['codigo']}: {o['mensaje']}" for o in (e.respuesta["observaciones"]
                                                                        + e.respuesta["errores"])) or "sin detalle"
        await registrar(conn, usuario["id"], usuario["usuario"], "COMPROBANTE_RECHAZADO",
                        f"{f['nombre']} PV {f['pv_numero']}, modo {modo}: {motivos}"[:2000], client_ip(request), rs["id"])
        raise HTTPException(422, f"ARCA rechazó el comprobante (el número queda libre): {motivos}"[:1000])
    except asyncpg.LockNotAvailableError:
        raise HTTPException(503, "Otra caja está emitiendo en este punto de venta. Probá de nuevo en unos segundos.")
    return await detalle_comprobante(conn, comprobante_id)


# --- Consulta ---
def _salida(c, lineas=None) -> dict:
    salida = {"id": str(c["id"]), "nombre": c["nombre"], "letra": c["letra"], "electronico": c["electronico"],
              "modo": c["modo"], "codigo_arca": c["codigo_arca"], "punto_venta": c["punto_venta"], "numero": c["numero"],
              "fecha": c["fecha"].isoformat(), "concepto": c["concepto"],
              "receptor": {"doc_tipo": c["receptor_doc_tipo"], "doc_nro": str(c["receptor_doc_nro"]),
                           "nombre": c["receptor_nombre"], "condicion_iva": c["condicion_iva_receptor"]},
              "moneda": c["moneda"], "cotizacion": str(c["cotizacion"]), "total": str(c["importe_total"]),
              "cae": c["cae"], "cae_vencimiento": c["cae_vencimiento"].isoformat() if c["cae_vencimiento"] else None,
              "comprobante_ref": str(c["comprobante_ref"]) if c["comprobante_ref"] else None,
              "creado_en": c["creado_en"].isoformat()}
    if lineas is not None:
        salida["lineas"] = [{"descripcion": l["descripcion"], "cantidad": str(l["cantidad"]),
                             "precio_unitario": str(l["precio_unitario"]), "importe": str(l["importe"])} for l in lineas]
        salida["servicio_desde"] = c["servicio_desde"].isoformat() if c["servicio_desde"] else None
        salida["servicio_hasta"] = c["servicio_hasta"].isoformat() if c["servicio_hasta"] else None
        salida["vencimiento_pago"] = c["vencimiento_pago"].isoformat() if c["vencimiento_pago"] else None
        obs = c["observaciones_arca"]
        salida["observaciones_arca"] = json.loads(obs) if isinstance(obs, str) else obs
    return salida


async def detalle_comprobante(conn: asyncpg.Connection, comprobante_id) -> dict:
    c = await conn.fetchrow("SELECT * FROM comprobantes WHERE id = $1", comprobante_id)
    lineas = await conn.fetch("SELECT * FROM comprobante_lineas WHERE comprobante_id = $1 ORDER BY orden", c["id"])
    return _salida(c, lineas)


async def comprobante_visible(conn: asyncpg.Connection, ctx: dict, comprobante_id: str) -> asyncpg.Record:
    """Comprobante de la razon social y modo del contexto, de un punto de venta que el usuario puede ver; si no, 404."""
    c = await conn.fetchrow("""
        SELECT c.*, f.punto_venta_id FROM comprobantes c JOIN formularios f ON f.id = c.formulario_id
        WHERE c.id = $1 AND c.razon_social_id = $2 AND c.modo = $3
    """, uuid_o_404(comprobante_id), uuid_o_404(ctx["razon_social_id"]), ctx["modo"])
    if c is None or c["punto_venta_id"] not in await _pv_visibles(conn, ctx["usuario"], c["razon_social_id"]):
        raise HTTPException(404, "No encontrado.")
    return c


@router.get("")
async def listar(limite: int = Query(50, ge=1, le=200), antes_de: Optional[str] = Query(None, max_length=40),
                 ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    """Comprobantes de la razon social y modo del contexto, de los puntos de venta visibles, del mas nuevo al mas
    viejo. Paginado por fecha de creacion (antes_de = creado_en del ultimo recibido)."""
    rs_id = uuid_o_404(ctx["razon_social_id"])
    limite_fecha = None
    if antes_de:
        try:
            limite_fecha = datetime.fromisoformat(antes_de)
        except ValueError:
            raise HTTPException(400, "Fecha inválida.")
    filas = await conn.fetch("""
        SELECT c.* FROM comprobantes c JOIN formularios f ON f.id = c.formulario_id
        WHERE c.razon_social_id = $1 AND c.modo = $2 AND f.punto_venta_id = ANY($3::uuid[])
          AND ($4::timestamptz IS NULL OR c.creado_en < $4)
        ORDER BY c.creado_en DESC LIMIT $5
    """, rs_id, ctx["modo"], await _pv_visibles(conn, ctx["usuario"], rs_id), limite_fecha, limite)
    return [_salida(c) for c in filas]


@router.get("/{comprobante_id}")
async def ver(comprobante_id: str, ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    c = await comprobante_visible(conn, ctx, comprobante_id)
    return await detalle_comprobante(conn, c["id"])
