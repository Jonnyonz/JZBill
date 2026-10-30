"""Tracker360, Fase 8: foto de stock y cola de ventas (diseno, seccion 9). Tracker es el dueno del stock y JZBill
nunca depende de el para emitir.

- Foto de stock: cada TRACKER_STOCK_MINUTOS (o a pedido) se lee todo el stock del canal (GET /api/v1/channel/stock,
  paginado) y se guarda en stock_foto; los articulos cuyo SKU no existe en Tracker quedan marcados
  (articulos.en_tracker = false). La foto solo sirve para AVISAR al facturar: no bloquea la venta (politica "foto en
  cero": avisar; decision tomada por Claude el 2026-10-30, revisable). Cada venta descuenta la foto local y cada nota
  de credito la devuelve, hasta la proxima lectura.
- Cola: al emitir en modo EMPRESA un comprobante con articulos (SKU), queda en cola_tracker una 'venta' = pedido del
  canal (POST /api/v1/channel/orders, idempotente por external_ref, tipo de envio MOSTRADOR); una nota de credito
  asociada queda como 'cancelacion' parcial del pedido original (POST .../orders/{ref}/cancel con lineas). Lo de modo
  prueba nunca se informa (seria crear pedidos reales en el deposito).
- Proceso: cada TRACKER_COLA_SEGUNDOS (o a pedido) se envian los pendientes EN ORDEN. Un error de red o del servidor
  detiene la cola (lo que sigue espera, se reintenta despues); un rechazo de Tracker (SKU inexistente, pedido ya
  despachado) marca ese item con error y sigue con el siguiente; un administrador lo reintenta o lo descarta.
"""

import asyncio
import json
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from jzbill import config, db
from jzbill.auth import client_ip, registrar
from jzbill.db import get_conn
from jzbill.permisos import require_admin
from jzbill import tracker
from jzbill.tracker import ErrorTracker, _clave, _conexion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integraciones/tracker", tags=["Tracker360"])

TIPO_ENVIO = "MOSTRADOR"
PAGINA_STOCK = 1000
# Codigos de ErrorTracker que no se arreglan reintentando (el item queda con error y la cola sigue).
PERMANENTES = ("rechazo.", "json", "respuesta.grande")
MILESIMO = Decimal("0.001")


def referencia(cuit: str, nombre: str, punto_venta: int, numero: int) -> str:
    """external_ref del comprobante en Tracker: legible y unica aunque varias razones sociales compartan el canal
    (nombre + punto de venta + numero es unico dentro de la razon social; solo se informa modo empresa)."""
    return f"JZB {cuit} {nombre[:50]} {punto_venta:05d}-{numero:08d}"


# --- Foto de stock ---
def stock_todo(url_base: str, clave: str) -> list:
    """Todo el stock del canal, paginado por SKU."""
    items, after = [], ""
    while True:
        d = tracker.llamar(url_base, "/api/v1/channel/stock", clave, {"after": after, "limit": PAGINA_STOCK})
        pagina = d.get("items") if isinstance(d, dict) else None
        if not isinstance(pagina, list):
            raise ErrorTracker("json", "Respuesta de Tracker360 ilegible.")
        items.extend(pagina)
        after = d.get("next_after")
        if not after or len(items) > 200000:
            return items


def _cantidad(valor) -> Decimal:
    """Tracker manda numeros de punto flotante; se guardan con 3 decimales."""
    return Decimal(str(valor)).quantize(MILESIMO)


async def actualizar_stock(conn: asyncpg.Connection) -> dict:
    fila = await _conexion(conn)
    if fila is None:
        raise HTTPException(409, "Primero configurá la conexión con Tracker360.")
    try:
        items = await asyncio.to_thread(stock_todo, fila["url"], _clave(fila))
    except ErrorTracker as e:
        await conn.execute("UPDATE tracker_conexion SET ultimo_error = $1 WHERE id = 1", e.mensaje[:300])
        raise HTTPException(502, e.mensaje)
    filas = {}
    for i in items:
        if not isinstance(i, dict) or not i.get("sku"):
            continue
        try:
            filas[str(i["sku"]).strip().upper()[:100]] = (_cantidad(i.get("available", 0)), _cantidad(i.get("physical", 0)))
        except (InvalidOperation, ValueError, TypeError):
            continue
    async with conn.transaction():
        await conn.execute("DELETE FROM stock_foto")
        await conn.executemany("INSERT INTO stock_foto (sku, disponible, fisico, leido_en) VALUES ($1, $2, $3, now())",
                               [(sku, d, f) for sku, (d, f) in filas.items()])
        await conn.execute("UPDATE articulos SET en_tracker = (upper(sku) IN (SELECT sku FROM stock_foto))")
        await conn.execute("UPDATE tracker_conexion SET stock_leido_en = now(), ultimo_ok = now(), ultimo_error = NULL WHERE id = 1")
    sin_tracker = await conn.fetchval("SELECT count(*) FROM articulos WHERE activo AND en_tracker = false")
    return {"articulos_tracker": len(filas), "sin_tracker": sin_tracker,
            "stock_leido_en": datetime.now(timezone.utc).isoformat()}


# --- Encolar al emitir ---
async def encolar(conn: asyncpg.Connection, comprobante_id) -> None:
    """Despues de confirmar la emision. Nunca levanta: el comprobante ya esta emitido y la cola es de mejor esfuerzo."""
    try:
        await _encolar(conn, comprobante_id)
    except Exception as e:   # noqa: BLE001
        logger.warning(f"[TRACKER] No se pudo encolar el comprobante {comprobante_id}: {type(e).__name__}: {str(e)[:200]}")


async def _encolar(conn: asyncpg.Connection, comprobante_id) -> None:
    from jzbill.comprobantes import es_credito   # import tardio: comprobantes importa este modulo

    c = await conn.fetchrow("""
        SELECT c.*, rs.cuit FROM comprobantes c JOIN razones_sociales rs ON rs.id = c.razon_social_id WHERE c.id = $1
    """, comprobante_id)
    if c is None or c["modo"] != "empresa" or await _conexion(conn) is None:
        return
    lineas = await conn.fetch("SELECT sku, cantidad FROM comprobante_lineas WHERE comprobante_id = $1 AND sku IS NOT NULL ORDER BY orden",
                              comprobante_id)
    if not lineas:
        return
    cantidades = {}
    for l in lineas:
        sku = l["sku"].strip().upper()
        cantidades[sku] = cantidades.get(sku, Decimal("0")) + l["cantidad"]
    # La API de Tracker recibe numeros de punto flotante (son cantidades, no dinero).
    lines = [{"sku": sku, "quantity": float(q)} for sku, q in cantidades.items()]
    if es_credito(c["nombre"]):
        if c["comprobante_ref"] is None:
            return
        f = await conn.fetchrow("""
            SELECT c.nombre, c.punto_venta, c.numero, rs.cuit FROM comprobantes c JOIN razones_sociales rs ON rs.id = c.razon_social_id
            WHERE c.id = $1
        """, c["comprobante_ref"])
        ref, accion, cuerpo, signo = referencia(f["cuit"], f["nombre"], f["punto_venta"], f["numero"]), "cancelacion", {"lines": lines}, 1
    else:
        ref = referencia(c["cuit"], c["nombre"], c["punto_venta"], c["numero"])
        doc = str(c["receptor_doc_nro"])
        cuerpo = {"external_ref": ref, "account": c["cuit"],
                  "buyer": {"name": c["receptor_nombre"] or None, "tax_id": doc if len(doc) == 11 else None,
                            "address": c["receptor_domicilio"] or None},
                  "shipping": {"type": TIPO_ENVIO}, "lines": lines}
        accion, signo = "venta", -1
    async with conn.transaction():
        await conn.execute("INSERT INTO cola_tracker (comprobante_id, accion, external_ref, cuerpo) VALUES ($1, $2, $3, $4::jsonb)",
                           c["id"], accion, ref, json.dumps(cuerpo))
        # Foto local: la venta descuenta y la nota devuelve, hasta la proxima lectura de Tracker.
        for sku, q in cantidades.items():
            await conn.execute("UPDATE stock_foto SET disponible = GREATEST(0, disponible + $2) WHERE sku = $1", sku, q * signo)


# --- Procesar la cola ---
def _enviar_item(url: str, clave: str, item) -> dict:
    cuerpo = json.loads(item["cuerpo"]) if isinstance(item["cuerpo"], str) else item["cuerpo"]
    if item["accion"] == "venta":
        return tracker.llamar(url, "/api/v1/channel/orders", clave, metodo="POST", cuerpo=cuerpo)
    return tracker.llamar(url, "/api/v1/channel/orders/" + urllib.parse.quote(item["external_ref"], safe="") + "/cancel", clave,
                  metodo="POST", cuerpo=cuerpo)


def _resumen_respuesta(r) -> dict:
    if not isinstance(r, dict):
        return {}
    return {k: r.get(k) for k in ("document_number", "status", "created", "devuelto") if k in r}


async def procesar_cola(conn: asyncpg.Connection) -> dict:
    """Envia los pendientes en orden. Devuelve cuantos se sincronizaron, cuantos quedaron con error y, si la cola se
    detuvo por un problema de conexion, el motivo."""
    fila = await _conexion(conn)
    if fila is None:
        return {"sincronizados": 0, "con_error": 0, "pendientes": 0, "detenida": None}
    url, clave = fila["url"], _clave(fila)
    hechos = errores = 0
    detenida = None
    pendientes = await conn.fetch("SELECT * FROM cola_tracker WHERE estado = 'pendiente' ORDER BY creado_en, id LIMIT 200")
    for item in pendientes:
        try:
            respuesta = await asyncio.to_thread(_enviar_item, url, clave, item)
        except ErrorTracker as e:
            if e.codigo.startswith(PERMANENTES):
                await conn.execute("UPDATE cola_tracker SET estado = 'error', intentos = intentos + 1, ultimo_error = $2, actualizado_en = now() "
                                   "WHERE id = $1", item["id"], e.mensaje[:300])
                errores += 1
                continue
            await conn.execute("UPDATE cola_tracker SET intentos = intentos + 1, ultimo_error = $2, actualizado_en = now() WHERE id = $1",
                               item["id"], e.mensaje[:300])
            await conn.execute("UPDATE tracker_conexion SET ultimo_error = $1 WHERE id = 1", e.mensaje[:300])
            detenida = e.mensaje
            break
        await conn.execute("""
            UPDATE cola_tracker SET estado = 'sincronizado', intentos = intentos + 1, ultimo_error = NULL, respuesta = $2::jsonb,
                                    sincronizado_en = now(), actualizado_en = now() WHERE id = $1
        """, item["id"], json.dumps(_resumen_respuesta(respuesta)))
        hechos += 1
    if detenida is None:
        await conn.execute("UPDATE tracker_conexion SET cola_procesada_en = now(), ultimo_ok = now(), ultimo_error = NULL WHERE id = 1")
    restantes = await conn.fetchval("SELECT count(*) FROM cola_tracker WHERE estado = 'pendiente'")
    return {"sincronizados": hechos, "con_error": errores, "pendientes": restantes, "detenida": detenida}


async def bucle() -> None:
    """Tarea de fondo (main.py): cada TRACKER_COLA_SEGUNDOS procesa la cola y, cuando la foto vencio
    (TRACKER_STOCK_MINUTOS), relee el stock. Espera el intervalo antes de la primera vuelta."""
    while True:
        await asyncio.sleep(config.TRACKER_COLA_SEGUNDOS)
        try:
            if db.DB.pool is None:
                continue
            async with db.DB.pool.acquire() as conn:
                fila = await _conexion(conn)
                if fila is None:
                    continue
                await procesar_cola(conn)
                leido = fila["stock_leido_en"]
                if leido is None or datetime.now(timezone.utc) - leido > timedelta(minutes=config.TRACKER_STOCK_MINUTOS):
                    await actualizar_stock(conn)
        except asyncio.CancelledError:
            raise
        except Exception as e:   # noqa: BLE001  (la tarea no se cae por un error de Tracker o de la base)
            logger.warning(f"[TRACKER] Tarea de fondo: {type(e).__name__}: {str(e)[:200]}")


# --- Endpoints (solo administrador) ---
def _item_salida(i) -> dict:
    return {"id": i["id"], "accion": i["accion"], "external_ref": i["external_ref"], "estado": i["estado"], "intentos": i["intentos"],
            "ultimo_error": i["ultimo_error"], "creado_en": i["creado_en"].isoformat(),
            "sincronizado_en": i["sincronizado_en"].isoformat() if i["sincronizado_en"] else None,
            "comprobante_id": str(i["comprobante_id"]), "comprobante": f"{i['nombre']} {i['punto_venta']:05d}-{i['numero']:08d}",
            "respuesta": (json.loads(i["respuesta"]) if isinstance(i["respuesta"], str) else i["respuesta"]) if i["respuesta"] else None}


@router.get("/cola")
async def ver_cola(admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    fila = await _conexion(conn)
    conteo = {r["estado"]: r["n"] for r in await conn.fetch("SELECT estado, count(*) AS n FROM cola_tracker GROUP BY estado")}
    items = await conn.fetch("""
        SELECT q.*, c.nombre, c.punto_venta, c.numero FROM cola_tracker q JOIN comprobantes c ON c.id = q.comprobante_id
        ORDER BY (q.estado = 'error') DESC, (q.estado = 'pendiente') DESC, q.creado_en DESC LIMIT 50
    """)
    return {"configurada": fila is not None,
            "stock_leido_en": fila["stock_leido_en"].isoformat() if fila and fila["stock_leido_en"] else None,
            "cola_procesada_en": fila["cola_procesada_en"].isoformat() if fila and fila["cola_procesada_en"] else None,
            "pendientes": conteo.get("pendiente", 0), "con_error": conteo.get("error", 0), "sincronizados": conteo.get("sincronizado", 0),
            "sin_tracker": await conn.fetchval("SELECT count(*) FROM articulos WHERE activo AND en_tracker = false"),
            "items": [_item_salida(i) for i in items]}


@router.post("/cola/procesar")
async def procesar(request: Request, admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    if await _conexion(conn) is None:
        raise HTTPException(409, "Primero configurá la conexión con Tracker360.")
    r = await procesar_cola(conn)
    await registrar(conn, admin["id"], admin["usuario"], "TRACKER_COLA",
                    f"Procesada a pedido: {r['sincronizados']} sincronizados, {r['con_error']} con error, {r['pendientes']} pendientes"
                    + (f"; detenida: {r['detenida']}" if r["detenida"] else "") + ".", client_ip(request))
    return r


async def _item(conn: asyncpg.Connection, item_id: int):
    i = await conn.fetchrow("SELECT * FROM cola_tracker WHERE id = $1", item_id)
    if i is None:
        raise HTTPException(404, "No encontrado.")
    return i


@router.post("/cola/{item_id}/reintentar")
async def reintentar(item_id: int, request: Request, admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    i = await _item(conn, item_id)
    if i["estado"] not in ("error", "descartado"):
        raise HTTPException(409, "Solo se reintenta lo que quedó con error o descartado.")
    async with conn.transaction():
        await conn.execute("UPDATE cola_tracker SET estado = 'pendiente', ultimo_error = NULL, actualizado_en = now() WHERE id = $1", item_id)
        await registrar(conn, admin["id"], admin["usuario"], "TRACKER_COLA", f"Reintento de {i['accion']} {i['external_ref']}.", client_ip(request))
    return {"ok": True}


@router.post("/cola/{item_id}/descartar")
async def descartar(item_id: int, request: Request, admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    """El item no se informa a Tracker (por ejemplo, un pedido que ya se cargo a mano en el deposito)."""
    i = await _item(conn, item_id)
    if i["estado"] not in ("error", "pendiente"):
        raise HTTPException(409, "Solo se descarta lo pendiente o con error.")
    async with conn.transaction():
        await conn.execute("UPDATE cola_tracker SET estado = 'descartado', actualizado_en = now() WHERE id = $1", item_id)
        await registrar(conn, admin["id"], admin["usuario"], "TRACKER_COLA", f"Descartado {i['accion']} {i['external_ref']}.", client_ip(request))
    return {"ok": True}


@router.post("/stock")
async def leer_stock(request: Request, admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    r = await actualizar_stock(conn)
    await registrar(conn, admin["id"], admin["usuario"], "TRACKER_STOCK",
                    f"Stock leído a pedido: {r['articulos_tracker']} SKU en Tracker, {r['sin_tracker']} artículos activos sin Tracker.",
                    client_ip(request))
    return r
