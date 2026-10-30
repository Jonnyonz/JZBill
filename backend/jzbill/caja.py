"""Caja (Fase 6): seguimiento simple, no contabilidad. Registra los cobros ligados a comprobantes y los movimientos
manuales, por razon social y por modo: lo de prueba nunca se suma a la caja real.

- Medios de pago y categorias de caja: configurables por razon social (administrador y supervisor), con un juego
  predeterminado que se carga al dar de alta la razon social.
- Cajas: local, tesoreria o dueno, opcionalmente atadas a una sucursal. Cada caja tiene una planilla por dia y
  modo, una sola abierta a la vez. La abren y operan administrador, supervisor y cajero; solo lectura la ve.
- Cobro al emitir (comprobantes.py): la terminal manda los pagos repartidos por medio de pago y la caja; el
  servidor exige una planilla abierta en el modo del contexto y que la suma sea igual al total. Una nota de
  credito genera la salida; una de debito, la entrada. Sin pagos, el comprobante se emite sin movimiento de caja
  (cuenta corriente o quien no lleva caja).
- Movimiento manual: siempre con categoria y medio de pago. Retiro a tesoreria o al dueno: salida en la caja de
  origen y entrada espejo en la caja de destino (misma razon social), referencia cruzada y una sola transaccion.
- Cierre con arqueo por medio de pago y moneda: lo esperado sale de la planilla (fondo inicial en efectivo mas
  entradas menos salidas); lo contado lo carga quien cierra. Reabrir: administrador o supervisor.

Dinero en Decimal/NUMERIC. Fechas de planilla en hora de Argentina (UTC-3 fijo)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jzbill.auth import client_ip, registrar
from jzbill.contexto import contexto_requerido
from jzbill.db import get_conn
from jzbill.permisos import uuid_o_404

router = APIRouter(prefix="/api/caja", tags=["Caja"])

CONFIGURAN = ("administrador", "supervisor")
OPERAN = ("administrador", "supervisor", "cajero")
# ponytail: Argentina no tiene horario de verano desde 2009; UTC-3 fijo (sin depender de tzdata).
HORA_AR = timezone(timedelta(hours=-3))
CERO = Decimal("0.00")
MEDIOS_PREDETERMINADOS = (("Efectivo", True), ("Transferencia", False), ("Tarjeta de débito", False),
                          ("Tarjeta de crédito", False), ("Cheque", False), ("Otro", False))
CATEGORIAS_PREDETERMINADAS = ("Proveedores", "Servicios", "Vales y adelantos", "Gastos varios", "Retiro a tesorería",
                              "Retiro del dueño", "Ingreso de fondos")


class MedioDatos(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    efectivo: bool = False
    activo: bool = True


class CategoriaDatos(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    activa: bool = True


class CajaDatos(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    tipo: Literal["local", "tesoreria", "dueno"] = "local"
    sucursal_id: Optional[str] = Field(default=None, max_length=40)
    activa: bool = True


class Apertura(BaseModel):
    fondo_inicial: Decimal = Field(default=CERO, ge=0, max_digits=15, decimal_places=2)


class MovimientoNuevo(BaseModel):
    tipo: Literal["entrada", "salida"] = "salida"
    categoria_id: str = Field(max_length=40)
    medio_pago_id: str = Field(max_length=40)
    moneda: str = Field(default="PES", min_length=3, max_length=3)
    importe: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    descripcion: str = Field(default="", max_length=250)
    # Retiro: salida de esta caja y entrada espejo en la caja de destino (tesoreria, dueno u otra).
    caja_destino_id: Optional[str] = Field(default=None, max_length=40)


class Conteo(BaseModel):
    medio_pago_id: str = Field(max_length=40)
    moneda: str = Field(default="PES", min_length=3, max_length=3)
    contado: Decimal = Field(ge=0, max_digits=15, decimal_places=2)


class Cierre(BaseModel):
    arqueo: List[Conteo] = Field(default_factory=list, max_length=100)
    observaciones: str = Field(default="", max_length=500)


class Pago(BaseModel):
    """Una parte del cobro de un comprobante (el total se reparte entre medios de pago)."""
    medio_pago_id: str = Field(max_length=40)
    importe: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


def _hoy():
    return datetime.now(HORA_AR).date()


def _exigir(ctx: dict, roles: tuple) -> None:
    if ctx["usuario"]["rol"] not in roles:
        raise HTTPException(403, "No tiene permiso para esta acción.")


def _moneda(texto: str) -> str:
    moneda = texto.strip().upper()
    if len(moneda) != 3 or not moneda.isalpha():
        raise HTTPException(400, "Moneda inválida.")
    return moneda


async def predeterminados(conn: asyncpg.Connection, rs_id) -> None:
    """Medios de pago y categorias iniciales de una razon social nueva (la migracion 0012 los dio a las existentes)."""
    await conn.executemany("INSERT INTO medios_pago (razon_social_id, nombre, efectivo, orden) VALUES ($1, $2, $3, $4)",
                           [(rs_id, nombre, efectivo, orden) for orden, (nombre, efectivo) in enumerate(MEDIOS_PREDETERMINADOS, 1)])
    await conn.executemany("INSERT INTO caja_categorias (razon_social_id, nombre) VALUES ($1, $2)",
                           [(rs_id, nombre) for nombre in CATEGORIAS_PREDETERMINADAS])


# --- Salidas ---
def _medio_salida(m) -> dict:
    return {"id": str(m["id"]), "nombre": m["nombre"], "efectivo": m["efectivo"], "activo": m["activo"]}


def _categoria_salida(c) -> dict:
    return {"id": str(c["id"]), "nombre": c["nombre"], "activa": c["activa"]}


def _caja_salida(c) -> dict:
    abierta = None
    if c["planilla_id"]:
        abierta = {"planilla_id": str(c["planilla_id"]), "fecha": c["planilla_fecha"].isoformat(),
                   "abierta_en": c["abierta_en"].isoformat()}
    return {"id": str(c["id"]), "nombre": c["nombre"], "tipo": c["tipo"], "activa": c["activa"],
            "sucursal_id": str(c["sucursal_id"]) if c["sucursal_id"] else None, "sucursal_nombre": c["sucursal_nombre"],
            "abierta": abierta}


def _planilla_resumen(p) -> dict:
    return {"id": str(p["id"]), "caja_id": str(p["caja_id"]), "caja": p["caja_nombre"], "caja_tipo": p["caja_tipo"],
            "modo": p["modo"], "fecha": p["fecha"].isoformat(), "estado": p["estado"],
            "fondo_inicial": str(p["fondo_inicial"]), "abierta_por": p["abierta_por_nombre"],
            "abierta_en": p["abierta_en"].isoformat(), "cerrada_por": p["cerrada_por_nombre"],
            "cerrada_en": p["cerrada_en"].isoformat() if p["cerrada_en"] else None, "observaciones": p["observaciones"]}


# --- Lecturas con autorizacion por razon social y modo del contexto ---
async def _cajas(conn: asyncpg.Connection, ctx: dict, incluir_inactivas: bool = False, caja_id=None) -> list:
    return await conn.fetch("""
        SELECT c.*, s.nombre AS sucursal_nombre, p.id AS planilla_id, p.fecha AS planilla_fecha, p.abierta_en
        FROM cajas c
        LEFT JOIN sucursales s ON s.id = c.sucursal_id
        LEFT JOIN caja_planillas p ON p.caja_id = c.id AND p.modo = $2 AND p.estado = 'abierta'
        WHERE c.razon_social_id = $1 AND ($3 OR c.activa) AND ($4::uuid IS NULL OR c.id = $4)
        ORDER BY c.nombre
    """, uuid_o_404(ctx["razon_social_id"]), ctx["modo"], incluir_inactivas, caja_id)


async def _caja(conn: asyncpg.Connection, ctx: dict, caja_id, incluir_inactivas: bool = False) -> asyncpg.Record:
    filas = await _cajas(conn, ctx, incluir_inactivas, uuid_o_404(caja_id))
    if not filas:
        raise HTTPException(404, "No encontrado.")
    return filas[0]


async def _medio(conn: asyncpg.Connection, rs_id, medio_id, solo_activos: bool = True) -> asyncpg.Record:
    m = await conn.fetchrow("SELECT * FROM medios_pago WHERE id = $1 AND razon_social_id = $2 AND ($3 = false OR activo)",
                            uuid_o_404(medio_id), rs_id, solo_activos)
    if m is None:
        raise HTTPException(400, "Medio de pago desconocido o inactivo.")
    return m


async def _planilla(conn: asyncpg.Connection, ctx: dict, planilla_id) -> asyncpg.Record:
    p = await conn.fetchrow("""
        SELECT p.*, c.nombre AS caja_nombre, c.tipo AS caja_tipo, c.razon_social_id,
               ua.usuario AS abierta_por_nombre, uc.usuario AS cerrada_por_nombre
        FROM caja_planillas p JOIN cajas c ON c.id = p.caja_id
        LEFT JOIN usuarios ua ON ua.id = p.abierta_por LEFT JOIN usuarios uc ON uc.id = p.cerrada_por
        WHERE p.id = $1 AND c.razon_social_id = $2 AND p.modo = $3
    """, uuid_o_404(planilla_id), uuid_o_404(ctx["razon_social_id"]), ctx["modo"])
    if p is None:
        raise HTTPException(404, "No encontrado.")
    return p


async def _movimientos(conn: asyncpg.Connection, planilla_id) -> list:
    return await conn.fetch("""
        SELECT m.*, mp.nombre AS medio, mp.efectivo, cat.nombre AS categoria, u.usuario AS usuario_nombre,
               c.nombre AS comprobante_nombre, c.punto_venta, c.numero, oc.nombre AS caja_espejo
        FROM caja_movimientos m
        JOIN medios_pago mp ON mp.id = m.medio_pago_id
        LEFT JOIN caja_categorias cat ON cat.id = m.categoria_id
        LEFT JOIN usuarios u ON u.id = m.usuario_id
        LEFT JOIN comprobantes c ON c.id = m.comprobante_id
        LEFT JOIN caja_movimientos e ON e.id = m.espejo_id
        LEFT JOIN caja_planillas ep ON ep.id = e.planilla_id
        LEFT JOIN cajas oc ON oc.id = ep.caja_id
        WHERE m.planilla_id = $1 ORDER BY m.creado_en, m.id
    """, planilla_id)


async def _totales(conn: asyncpg.Connection, p, movimientos: list) -> tuple:
    """(por medio de pago y moneda, por categoria y moneda). El saldo por medio es lo que deberia haber al cierre:
    el fondo inicial (efectivo en pesos) mas las entradas menos las salidas."""
    por_medio, por_categoria = {}, {}
    for m in movimientos:
        t = por_medio.setdefault((m["medio_pago_id"], m["moneda"]), {
            "medio_pago_id": m["medio_pago_id"], "medio": m["medio"], "efectivo": m["efectivo"], "moneda": m["moneda"],
            "entradas": CERO, "salidas": CERO, "fondo": CERO})
        t["entradas" if m["tipo"] == "entrada" else "salidas"] += m["importe"]
        if m["categoria_id"]:
            c = por_categoria.setdefault((m["categoria"], m["moneda"]), {"categoria": m["categoria"], "moneda": m["moneda"],
                                                                        "entradas": CERO, "salidas": CERO})
            c["entradas" if m["tipo"] == "entrada" else "salidas"] += m["importe"]
    if p["fondo_inicial"] > 0:
        efectivo = await conn.fetchrow("SELECT id, nombre FROM medios_pago WHERE razon_social_id = $1 AND efectivo "
                                       "ORDER BY activo DESC, orden LIMIT 1", p["razon_social_id"])
        if efectivo is not None:
            t = por_medio.setdefault((efectivo["id"], "PES"), {
                "medio_pago_id": efectivo["id"], "medio": efectivo["nombre"], "efectivo": True, "moneda": "PES",
                "entradas": CERO, "salidas": CERO, "fondo": CERO})
            t["fondo"] = p["fondo_inicial"]
    for t in por_medio.values():
        t["saldo"] = t["fondo"] + t["entradas"] - t["salidas"]
    orden = lambda t: (not t["efectivo"], t["medio"], t["moneda"])
    return sorted(por_medio.values(), key=orden), sorted(por_categoria.values(), key=lambda c: (c["categoria"], c["moneda"]))


async def _detalle(conn: asyncpg.Connection, p) -> dict:
    movimientos = await _movimientos(conn, p["id"])
    por_medio, por_categoria = await _totales(conn, p, movimientos)
    arqueo = await conn.fetch("""
        SELECT a.*, mp.nombre AS medio FROM caja_arqueos a JOIN medios_pago mp ON mp.id = a.medio_pago_id
        WHERE a.planilla_id = $1 ORDER BY mp.efectivo DESC, mp.nombre, a.moneda
    """, p["id"])
    salida = _planilla_resumen(p)
    salida["movimientos"] = [{
        "id": str(m["id"]), "tipo": m["tipo"], "origen": m["origen"], "hora": m["creado_en"].isoformat(),
        "descripcion": m["descripcion"], "categoria": m["categoria"], "medio": m["medio"], "moneda": m["moneda"],
        "importe": str(m["importe"]), "usuario": m["usuario_nombre"],
        "comprobante_id": str(m["comprobante_id"]) if m["comprobante_id"] else None,
        "comprobante": f"{m['comprobante_nombre']} {m['punto_venta']:05d}-{m['numero']:08d}" if m["comprobante_id"] else None,
        "caja_espejo": m["caja_espejo"]} for m in movimientos]
    salida["totales"] = {
        "por_medio": [{"medio_pago_id": str(t["medio_pago_id"]), "medio": t["medio"], "efectivo": t["efectivo"],
                       "moneda": t["moneda"], "fondo": str(t["fondo"]), "entradas": str(t["entradas"]),
                       "salidas": str(t["salidas"]), "saldo": str(t["saldo"])} for t in por_medio],
        "por_categoria": [{"categoria": c["categoria"], "moneda": c["moneda"], "entradas": str(c["entradas"]),
                           "salidas": str(c["salidas"])} for c in por_categoria]}
    salida["arqueo"] = [{"medio_pago_id": str(a["medio_pago_id"]), "medio": a["medio"], "moneda": a["moneda"],
                         "esperado": str(a["esperado"]), "contado": str(a["contado"]) if a["contado"] is not None else None,
                         "diferencia": str(a["contado"] - a["esperado"]) if a["contado"] is not None else None}
                        for a in arqueo]
    return salida


async def _insertar(conn: asyncpg.Connection, planilla_id, tipo: str, origen: str, medio_id, moneda: str, importe: Decimal,
                    descripcion: str, usuario_id, comprobante_id=None, categoria_id=None, espejo_id=None):
    return await conn.fetchval("""
        INSERT INTO caja_movimientos (planilla_id, tipo, origen, comprobante_id, categoria_id, medio_pago_id, moneda,
                                      importe, descripcion, espejo_id, usuario_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id
    """, planilla_id, tipo, origen, comprobante_id, categoria_id, medio_id, moneda, importe, descripcion[:250], espejo_id,
        usuario_id)


# --- Cobro de comprobantes (lo usa comprobantes.emitir) ---
async def preparar_cobro(conn: asyncpg.Connection, ctx: dict, caja_id: Optional[str], pagos: list, moneda: str,
                         total: Decimal) -> Optional[dict]:
    """Antes de pedir el CAE: caja con planilla abierta en este modo, medios activos y suma igual al total."""
    if not pagos:
        return None
    if not caja_id:
        raise HTTPException(400, "Elegí la caja donde registrar el cobro.")
    rs_id = uuid_o_404(ctx["razon_social_id"])
    p = await conn.fetchrow("""
        SELECT p.* FROM caja_planillas p JOIN cajas c ON c.id = p.caja_id
        WHERE c.id = $1 AND c.razon_social_id = $2 AND c.activa AND p.modo = $3 AND p.estado = 'abierta'
    """, uuid_o_404(caja_id), rs_id, ctx["modo"])
    if p is None:
        raise HTTPException(409, "Esa caja no tiene una planilla abierta en este modo: abrila desde Caja.")
    medios = {m["id"]: m for m in await conn.fetch("SELECT * FROM medios_pago WHERE razon_social_id = $1 AND activo", rs_id)}
    partes = []
    for pago in pagos:
        medio = medios.get(uuid_o_404(pago.medio_pago_id))
        if medio is None:
            raise HTTPException(400, "Medio de pago desconocido o inactivo.")
        partes.append((medio["id"], pago.importe))
    suma = sum((importe for _, importe in partes), CERO)
    if suma != total:
        raise HTTPException(400, f"Los pagos suman {suma} y el total del comprobante es {total}.")
    return {"planilla_id": p["id"], "partes": partes, "moneda": moneda}


async def asegurar_abierta(conn: asyncpg.Connection, cobro: dict) -> None:
    """Dentro de la transaccion de emision, antes del CAE: bloquea la planilla (FOR SHARE) para que un cierre
    simultaneo espere a que termine la emision y tome el cobro."""
    estado = await conn.fetchval("SELECT estado FROM caja_planillas WHERE id = $1 FOR SHARE", cobro["planilla_id"])
    if estado != "abierta":
        raise HTTPException(409, "La caja se cerró mientras se emitía: abrila de nuevo desde Caja.")


async def registrar_cobro(conn: asyncpg.Connection, cobro: dict, comprobante_id, tipo: str, descripcion: str,
                          usuario_id) -> None:
    for medio_id, importe in cobro["partes"]:
        await _insertar(conn, cobro["planilla_id"], tipo, "comprobante", medio_id, cobro["moneda"], importe, descripcion,
                        usuario_id, comprobante_id=comprobante_id)


async def pagos_de(conn: asyncpg.Connection, comprobante_id) -> list:
    filas = await conn.fetch("""
        SELECT m.tipo, m.importe, m.moneda, mp.nombre AS medio, c.nombre AS caja
        FROM caja_movimientos m JOIN medios_pago mp ON mp.id = m.medio_pago_id
        JOIN caja_planillas p ON p.id = m.planilla_id JOIN cajas c ON c.id = p.caja_id
        WHERE m.comprobante_id = $1 ORDER BY m.creado_en, m.id
    """, comprobante_id)
    return [{"medio": f["medio"], "importe": str(f["importe"]), "moneda": f["moneda"], "caja": f["caja"], "tipo": f["tipo"]}
            for f in filas]


# --- Opciones para las pantallas (Caja y Facturar) ---
@router.get("/opciones")
async def opciones(ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    rs_id = uuid_o_404(ctx["razon_social_id"])
    medios = await conn.fetch("SELECT * FROM medios_pago WHERE razon_social_id = $1 AND activo ORDER BY orden, nombre", rs_id)
    categorias = await conn.fetch("SELECT * FROM caja_categorias WHERE razon_social_id = $1 AND activa ORDER BY nombre", rs_id)
    sucursales = await conn.fetch("SELECT id, nombre FROM sucursales WHERE activa ORDER BY nombre")
    return {"medios": [_medio_salida(m) for m in medios], "categorias": [_categoria_salida(c) for c in categorias],
            "cajas": [_caja_salida(c) for c in await _cajas(conn, ctx)],
            "sucursales": [{"id": str(s["id"]), "nombre": s["nombre"]} for s in sucursales]}


# --- Medios de pago ---
@router.get("/medios-pago")
async def listar_medios(incluir_inactivos: bool = False, ctx: dict = Depends(contexto_requerido),
                        conn: asyncpg.Connection = Depends(get_conn)):
    filas = await conn.fetch("SELECT * FROM medios_pago WHERE razon_social_id = $1 AND ($2 OR activo) ORDER BY orden, nombre",
                             uuid_o_404(ctx["razon_social_id"]), incluir_inactivos)
    return [_medio_salida(m) for m in filas]


@router.post("/medios-pago", status_code=201)
async def crear_medio(data: MedioDatos, request: Request, ctx: dict = Depends(contexto_requerido),
                      conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, CONFIGURAN)
    rs_id, u = uuid_o_404(ctx["razon_social_id"]), ctx["usuario"]
    async with conn.transaction():
        try:
            m = await conn.fetchrow("""
                INSERT INTO medios_pago (razon_social_id, nombre, efectivo, activo, orden)
                VALUES ($1, $2, $3, $4, (SELECT COALESCE(MAX(orden), 0) + 1 FROM medios_pago WHERE razon_social_id = $1))
                RETURNING *
            """, rs_id, data.nombre.strip(), data.efectivo, data.activo)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe un medio de pago con ese nombre.")
        await registrar(conn, u["id"], u["usuario"], "CAJA_CONFIG", f"Medio de pago {m['nombre']}.", client_ip(request), rs_id)
    return _medio_salida(m)


@router.put("/medios-pago/{medio_id}")
async def modificar_medio(medio_id: str, data: MedioDatos, request: Request, ctx: dict = Depends(contexto_requerido),
                          conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, CONFIGURAN)
    rs_id, u = uuid_o_404(ctx["razon_social_id"]), ctx["usuario"]
    async with conn.transaction():
        try:
            m = await conn.fetchrow("""
                UPDATE medios_pago SET nombre = $3, efectivo = $4, activo = $5 WHERE id = $1 AND razon_social_id = $2 RETURNING *
            """, uuid_o_404(medio_id), rs_id, data.nombre.strip(), data.efectivo, data.activo)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe un medio de pago con ese nombre.")
        if m is None:
            raise HTTPException(404, "No encontrado.")
        await registrar(conn, u["id"], u["usuario"], "CAJA_CONFIG", f"Medio de pago {m['nombre']}.", client_ip(request), rs_id)
    return _medio_salida(m)


# --- Categorias ---
@router.get("/categorias")
async def listar_categorias(incluir_inactivas: bool = False, ctx: dict = Depends(contexto_requerido),
                            conn: asyncpg.Connection = Depends(get_conn)):
    filas = await conn.fetch("SELECT * FROM caja_categorias WHERE razon_social_id = $1 AND ($2 OR activa) ORDER BY nombre",
                             uuid_o_404(ctx["razon_social_id"]), incluir_inactivas)
    return [_categoria_salida(c) for c in filas]


@router.post("/categorias", status_code=201)
async def crear_categoria(data: CategoriaDatos, request: Request, ctx: dict = Depends(contexto_requerido),
                          conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, CONFIGURAN)
    rs_id, u = uuid_o_404(ctx["razon_social_id"]), ctx["usuario"]
    async with conn.transaction():
        try:
            c = await conn.fetchrow("INSERT INTO caja_categorias (razon_social_id, nombre, activa) VALUES ($1, $2, $3) RETURNING *",
                                    rs_id, data.nombre.strip(), data.activa)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe una categoría con ese nombre.")
        await registrar(conn, u["id"], u["usuario"], "CAJA_CONFIG", f"Categoría {c['nombre']}.", client_ip(request), rs_id)
    return _categoria_salida(c)


@router.put("/categorias/{categoria_id}")
async def modificar_categoria(categoria_id: str, data: CategoriaDatos, request: Request,
                              ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, CONFIGURAN)
    rs_id, u = uuid_o_404(ctx["razon_social_id"]), ctx["usuario"]
    async with conn.transaction():
        try:
            c = await conn.fetchrow("UPDATE caja_categorias SET nombre = $3, activa = $4 WHERE id = $1 AND razon_social_id = $2 "
                                    "RETURNING *", uuid_o_404(categoria_id), rs_id, data.nombre.strip(), data.activa)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe una categoría con ese nombre.")
        if c is None:
            raise HTTPException(404, "No encontrado.")
        await registrar(conn, u["id"], u["usuario"], "CAJA_CONFIG", f"Categoría {c['nombre']}.", client_ip(request), rs_id)
    return _categoria_salida(c)


# --- Cajas ---
async def _sucursal_id(conn: asyncpg.Connection, sucursal_id: Optional[str]):
    if not sucursal_id:
        return None
    s_id = await conn.fetchval("SELECT id FROM sucursales WHERE id = $1 AND activa", uuid_o_404(sucursal_id))
    if s_id is None:
        raise HTTPException(400, "Sucursal desconocida o inactiva.")
    return s_id


@router.get("/cajas")
async def listar_cajas(incluir_inactivas: bool = False, ctx: dict = Depends(contexto_requerido),
                       conn: asyncpg.Connection = Depends(get_conn)):
    return [_caja_salida(c) for c in await _cajas(conn, ctx, incluir_inactivas)]


@router.post("/cajas", status_code=201)
async def crear_caja(data: CajaDatos, request: Request, ctx: dict = Depends(contexto_requerido),
                     conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, CONFIGURAN)
    rs_id, u = uuid_o_404(ctx["razon_social_id"]), ctx["usuario"]
    sucursal_id = await _sucursal_id(conn, data.sucursal_id)
    async with conn.transaction():
        try:
            caja_id = await conn.fetchval("""
                INSERT INTO cajas (razon_social_id, nombre, tipo, sucursal_id, activa) VALUES ($1, $2, $3, $4, $5) RETURNING id
            """, rs_id, data.nombre.strip(), data.tipo, sucursal_id, data.activa)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe una caja con ese nombre.")
        await registrar(conn, u["id"], u["usuario"], "CAJA_CONFIG", f"Caja {data.nombre.strip()} ({data.tipo}).",
                        client_ip(request), rs_id)
    return _caja_salida(await _caja(conn, ctx, caja_id, incluir_inactivas=True))


@router.put("/cajas/{caja_id}")
async def modificar_caja(caja_id: str, data: CajaDatos, request: Request, ctx: dict = Depends(contexto_requerido),
                         conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, CONFIGURAN)
    caja = await _caja(conn, ctx, caja_id, incluir_inactivas=True)
    u = ctx["usuario"]
    sucursal_id = await _sucursal_id(conn, data.sucursal_id)
    if not data.activa and caja["planilla_id"]:
        raise HTTPException(409, "La caja tiene una planilla abierta: cerrala antes de desactivarla.")
    async with conn.transaction():
        try:
            await conn.execute("UPDATE cajas SET nombre = $2, tipo = $3, sucursal_id = $4, activa = $5 WHERE id = $1",
                               caja["id"], data.nombre.strip(), data.tipo, sucursal_id, data.activa)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ya existe una caja con ese nombre.")
        await registrar(conn, u["id"], u["usuario"], "CAJA_CONFIG", f"Caja {data.nombre.strip()} ({data.tipo}).",
                        client_ip(request), caja["razon_social_id"])
    return _caja_salida(await _caja(conn, ctx, caja["id"], incluir_inactivas=True))


# --- Planillas ---
@router.post("/cajas/{caja_id}/abrir", status_code=201)
async def abrir(caja_id: str, data: Apertura, request: Request, ctx: dict = Depends(contexto_requerido),
                conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, OPERAN)
    caja = await _caja(conn, ctx, caja_id)
    u = ctx["usuario"]
    try:
        async with conn.transaction():
            planilla_id = await conn.fetchval("""
                INSERT INTO caja_planillas (caja_id, modo, fecha, fondo_inicial, abierta_por) VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, caja["id"], ctx["modo"], _hoy(), data.fondo_inicial, u["id"])
            await registrar(conn, u["id"], u["usuario"], "CAJA_APERTURA",
                            f"Caja {caja['nombre']}, modo {ctx['modo']}, fondo inicial {data.fondo_inicial}.",
                            client_ip(request), caja["razon_social_id"])
    except asyncpg.UniqueViolationError as e:
        if e.constraint_name == "caja_planillas_una_abierta":
            raise HTTPException(409, "La caja ya tiene una planilla abierta.")
        raise HTTPException(409, "La planilla de hoy de esta caja ya se cerró: un supervisor puede reabrirla.")
    return await _detalle(conn, await _planilla(conn, ctx, planilla_id))


@router.get("/planillas")
async def listar_planillas(caja_id: str = Query(max_length=40), limite: int = Query(30, ge=1, le=200),
                           ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    """Planillas de una caja en el modo del contexto, de la mas nueva a la mas vieja."""
    caja = await _caja(conn, ctx, caja_id, incluir_inactivas=True)
    filas = await conn.fetch("""
        SELECT p.*, c.nombre AS caja_nombre, c.tipo AS caja_tipo, ua.usuario AS abierta_por_nombre, uc.usuario AS cerrada_por_nombre
        FROM caja_planillas p JOIN cajas c ON c.id = p.caja_id
        LEFT JOIN usuarios ua ON ua.id = p.abierta_por LEFT JOIN usuarios uc ON uc.id = p.cerrada_por
        WHERE p.caja_id = $1 AND p.modo = $2 ORDER BY p.fecha DESC, p.abierta_en DESC LIMIT $3
    """, caja["id"], ctx["modo"], limite)
    return [_planilla_resumen(p) for p in filas]


@router.get("/planillas/{planilla_id}")
async def ver_planilla(planilla_id: str, ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    return await _detalle(conn, await _planilla(conn, ctx, planilla_id))


@router.post("/planillas/{planilla_id}/movimientos", status_code=201)
async def agregar_movimiento(planilla_id: str, data: MovimientoNuevo, request: Request,
                             ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, OPERAN)
    p = await _planilla(conn, ctx, planilla_id)
    if p["estado"] != "abierta":
        raise HTTPException(409, "La planilla está cerrada.")
    rs_id, u = p["razon_social_id"], ctx["usuario"]
    categoria = await conn.fetchrow("SELECT * FROM caja_categorias WHERE id = $1 AND razon_social_id = $2 AND activa",
                                    uuid_o_404(data.categoria_id), rs_id)
    if categoria is None:
        raise HTTPException(400, "Categoría desconocida o inactiva.")
    medio = await _medio(conn, rs_id, data.medio_pago_id)
    moneda = _moneda(data.moneda)
    texto = data.descripcion.strip()
    async with conn.transaction():
        if data.caja_destino_id:
            # Retiro: las dos patas o ninguna (la transaccion se revierte con cualquier error).
            destino = await conn.fetchrow("SELECT * FROM cajas WHERE id = $1 AND razon_social_id = $2 AND activa",
                                          uuid_o_404(data.caja_destino_id), rs_id)
            if destino is None or destino["id"] == p["caja_id"]:
                raise HTTPException(400, "La caja de destino no existe, está inactiva o es la misma caja.")
            destino_planilla = await conn.fetchval(
                "SELECT id FROM caja_planillas WHERE caja_id = $1 AND modo = $2 AND estado = 'abierta'", destino["id"], p["modo"])
            if destino_planilla is None:
                try:
                    destino_planilla = await conn.fetchval("""
                        INSERT INTO caja_planillas (caja_id, modo, fecha, abierta_por) VALUES ($1, $2, $3, $4) RETURNING id
                    """, destino["id"], p["modo"], _hoy(), u["id"])
                except asyncpg.UniqueViolationError:
                    raise HTTPException(409, "La planilla de hoy de la caja de destino ya se cerró: hay que reabrirla.")
            salida_id = await _insertar(conn, p["id"], "salida", "retiro", medio["id"], moneda, data.importe,
                                        f"Retiro a {destino['nombre']}" + (f": {texto}" if texto else ""), u["id"],
                                        categoria_id=categoria["id"])
            entrada_id = await _insertar(conn, destino_planilla, "entrada", "retiro", medio["id"], moneda, data.importe,
                                         f"Retiro desde {p['caja_nombre']}" + (f": {texto}" if texto else ""), u["id"],
                                         categoria_id=categoria["id"], espejo_id=salida_id)
            await conn.execute("UPDATE caja_movimientos SET espejo_id = $2 WHERE id = $1", salida_id, entrada_id)
            await registrar(conn, u["id"], u["usuario"], "CAJA_RETIRO",
                            f"{p['caja_nombre']} -> {destino['nombre']}: {data.importe} {moneda} ({categoria['nombre']}).",
                            client_ip(request), rs_id)
        else:
            await _insertar(conn, p["id"], data.tipo, "manual", medio["id"], moneda, data.importe, texto, u["id"],
                            categoria_id=categoria["id"])
            await registrar(conn, u["id"], u["usuario"], "CAJA_MOVIMIENTO",
                            f"{p['caja_nombre']}: {data.tipo} {data.importe} {moneda} ({categoria['nombre']}).",
                            client_ip(request), rs_id)
    return await _detalle(conn, p)


@router.delete("/planillas/{planilla_id}/movimientos/{movimiento_id}")
async def quitar_movimiento(planilla_id: str, movimiento_id: str, request: Request, ctx: dict = Depends(contexto_requerido),
                            conn: asyncpg.Connection = Depends(get_conn)):
    """Solo movimientos manuales y retiros de una planilla abierta (un retiro se quita con su espejo). El cobro de
    un comprobante no se borra: se corrige con una nota de credito."""
    _exigir(ctx, OPERAN)
    p = await _planilla(conn, ctx, planilla_id)
    m = await conn.fetchrow("SELECT * FROM caja_movimientos WHERE id = $1 AND planilla_id = $2", uuid_o_404(movimiento_id), p["id"])
    if m is None:
        raise HTTPException(404, "No encontrado.")
    if m["origen"] == "comprobante":
        raise HTTPException(409, "El cobro de un comprobante no se borra: se corrige con una nota de crédito.")
    if p["estado"] != "abierta":
        raise HTTPException(409, "La planilla está cerrada.")
    u = ctx["usuario"]
    async with conn.transaction():
        ids = [m["id"]]
        if m["espejo_id"]:
            abierta = await conn.fetchval("""
                SELECT p.estado = 'abierta' FROM caja_movimientos e JOIN caja_planillas p ON p.id = e.planilla_id WHERE e.id = $1
            """, m["espejo_id"])
            if not abierta:
                raise HTTPException(409, "La planilla de la otra caja ya está cerrada.")
            ids.append(m["espejo_id"])
            await conn.execute("UPDATE caja_movimientos SET espejo_id = NULL WHERE id = ANY($1::uuid[])", ids)
        await conn.execute("DELETE FROM caja_movimientos WHERE id = ANY($1::uuid[])", ids)
        await registrar(conn, u["id"], u["usuario"], "CAJA_MOVIMIENTO_BAJA",
                        f"{p['caja_nombre']}: {m['tipo']} {m['importe']} {m['moneda']} ({m['origen']}).",
                        client_ip(request), p["razon_social_id"])
    return await _detalle(conn, p)


@router.post("/planillas/{planilla_id}/cerrar")
async def cerrar(planilla_id: str, data: Cierre, request: Request, ctx: dict = Depends(contexto_requerido),
                 conn: asyncpg.Connection = Depends(get_conn)):
    """Cierra y guarda el arqueo. Primero marca la planilla cerrada (espera a las emisiones en curso, que la tienen
    bloqueada) y recien despues calcula lo esperado, asi ningun cobro queda afuera."""
    _exigir(ctx, OPERAN)
    p = await _planilla(conn, ctx, planilla_id)
    u = ctx["usuario"]
    async with conn.transaction():
        cerrada = await conn.fetchval("""
            UPDATE caja_planillas SET estado = 'cerrada', cerrada_por = $2, cerrada_en = now(), observaciones = $3
            WHERE id = $1 AND estado = 'abierta' RETURNING id
        """, p["id"], u["id"], data.observaciones.strip())
        if cerrada is None:
            raise HTTPException(409, "La planilla ya está cerrada.")
        por_medio, _ = await _totales(conn, p, await _movimientos(conn, p["id"]))
        esperados = {(t["medio_pago_id"], t["moneda"]): t["saldo"] for t in por_medio}
        contados = {}
        for conteo in data.arqueo:
            clave = ((await _medio(conn, p["razon_social_id"], conteo.medio_pago_id, solo_activos=False))["id"], _moneda(conteo.moneda))
            contados[clave] = conteo.contado
            esperados.setdefault(clave, CERO)
        await conn.executemany("""
            INSERT INTO caja_arqueos (planilla_id, medio_pago_id, moneda, esperado, contado) VALUES ($1, $2, $3, $4, $5)
        """, [(p["id"], medio_id, moneda, esperado, contados.get((medio_id, moneda)))
              for (medio_id, moneda), esperado in esperados.items()])
        diferencias = [f"{t['medio']} {t['moneda']}: {contados[(t['medio_pago_id'], t['moneda'])] - t['saldo']}"
                       for t in por_medio if (t["medio_pago_id"], t["moneda"]) in contados
                       and contados[(t["medio_pago_id"], t["moneda"])] != t["saldo"]]
        await registrar(conn, u["id"], u["usuario"], "CAJA_CIERRE",
                        f"Caja {p['caja_nombre']}, planilla del {p['fecha'].isoformat()}. "
                        + ("Diferencias: " + "; ".join(diferencias) + "." if diferencias else "Sin diferencias."),
                        client_ip(request), p["razon_social_id"])
    return await _detalle(conn, await _planilla(conn, ctx, p["id"]))


@router.post("/planillas/{planilla_id}/reabrir")
async def reabrir(planilla_id: str, request: Request, ctx: dict = Depends(contexto_requerido),
                  conn: asyncpg.Connection = Depends(get_conn)):
    _exigir(ctx, CONFIGURAN)
    p = await _planilla(conn, ctx, planilla_id)
    if p["estado"] != "cerrada":
        raise HTTPException(409, "La planilla está abierta.")
    u = ctx["usuario"]
    try:
        async with conn.transaction():
            await conn.execute("UPDATE caja_planillas SET estado = 'abierta', cerrada_por = NULL, cerrada_en = NULL WHERE id = $1",
                               p["id"])
            await conn.execute("DELETE FROM caja_arqueos WHERE planilla_id = $1", p["id"])
            await registrar(conn, u["id"], u["usuario"], "CAJA_REAPERTURA",
                            f"Caja {p['caja_nombre']}, planilla del {p['fecha'].isoformat()}.", client_ip(request),
                            p["razon_social_id"])
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "La caja ya tiene otra planilla abierta: cerrala antes.")
    return await _detalle(conn, await _planilla(conn, ctx, p["id"]))
