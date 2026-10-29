"""Conexion con Tracker360 e importacion de su catalogo de articulos (adelanto de la Fase 8, OK de Jonny 2026-10-29).

Tracker es el dueno del SKU, la descripcion y la categoria; Bill agrega lo suyo (IVA, costo, precios). Una sola
conexion por instalacion, con la clave del canal (tch_...) cifrada con la clave maestra. Cliente HTTP con la
biblioteca estandar, JSON, sin dependencias. La URL la pone un administrador a proposito (puede ser de la red
interna: Tracker suele vivir en el mismo deposito), solo http/https y sin usuario ni clave en la URL."""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill import cifrado, config
from jzbill.arca import parametros
from jzbill.auth import client_ip, registrar
from jzbill.db import get_conn
from jzbill.permisos import require_admin, require_rol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integraciones/tracker", tags=["Tracker360"])
router_importacion = APIRouter(prefix="/api/articulos/importar-tracker", tags=["Tracker360"])

MAX_RESPUESTA = 4 * 1024 * 1024   # 4 MiB por pagina del catalogo
PAGINA = 500
PREFIJO_CLAVE = "tch_"
_PROPOSITO = "tracker:clave"
# Limites de las columnas de Bill (migracion 0008): lo que no entra se omite y se informa.
MAX_SKU, MAX_DESCRIPCION, MAX_CATEGORIA = 60, 200, 80


class ErrorTracker(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def llamar(url_base: str, ruta: str, clave: str, params: Optional[dict] = None, timeout: Optional[int] = None) -> dict:
    """GET JSON a Tracker. Lo reemplazan los tests."""
    url = url_base.rstrip("/") + ruta + ("?" + urllib.parse.urlencode(params) if params else "")
    pedido = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {clave}", "Accept": "application/json"})
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(pedido, timeout=timeout or config.ARCA_TIMEOUT) as r:
            datos, estado = r.read(MAX_RESPUESTA + 1), r.status
    except urllib.error.HTTPError as e:
        datos, estado = e.read(MAX_RESPUESTA + 1), e.code
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.warning(f"[TRACKER] {ruta}: sin conexion ({type(e).__name__}) tras {time.monotonic() - inicio:.1f}s")
        raise ErrorTracker("red", "No se pudo conectar con Tracker360.")
    logger.info(f"[TRACKER] {ruta}: HTTP {estado} en {time.monotonic() - inicio:.1f}s")
    if estado == 401:
        raise ErrorTracker("clave", "Tracker360 rechazó la clave del canal.")
    if estado == 404:
        raise ErrorTracker("version", "Tracker360 no tiene esa función: hace falta la versión 1.5.0 o posterior.")
    if estado != 200:
        raise ErrorTracker(f"http.{estado}", "Respuesta inesperada de Tracker360.")
    if len(datos) > MAX_RESPUESTA:
        raise ErrorTracker("respuesta.grande", "Respuesta de Tracker360 demasiado grande.")
    try:
        return json.loads(datos)
    except ValueError:
        raise ErrorTracker("json", "Respuesta de Tracker360 ilegible.")


def catalogo(url_base: str, clave: str) -> list:
    """Todo el catalogo, paginado por SKU."""
    items, after = [], ""
    while True:
        d = llamar(url_base, "/api/v1/channel/items", clave, {"after": after, "limit": PAGINA})
        pagina = d.get("items") if isinstance(d, dict) else None
        if not isinstance(pagina, list):
            raise ErrorTracker("json", "Respuesta de Tracker360 ilegible.")
        items.extend(pagina)
        after = d.get("next_after")
        if not after or len(items) > 200000:
            return items


class ConexionNueva(BaseModel):
    url: str = Field(min_length=1, max_length=300)
    clave: str = Field(default="", max_length=200)   # vacia: se conserva la guardada


def _url_valida(url: str) -> str:
    url = url.strip().rstrip("/")
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise HTTPException(400, "La URL tiene que ser http(s)://servidor[:puerto], sin usuario, clave ni parámetros.")
    return url


async def _conexion(conn: asyncpg.Connection):
    return await conn.fetchrow("SELECT * FROM tracker_conexion WHERE id = 1")


def _salida(fila) -> dict:
    if fila is None:
        return {"configurada": False, "url": "", "canal": "", "ultimo_ok": None, "ultimo_error": None}
    return {"configurada": True, "url": fila["url"], "canal": fila["canal"],
            "ultimo_ok": fila["ultimo_ok"].isoformat() if fila["ultimo_ok"] else None, "ultimo_error": fila["ultimo_error"]}


def _clave(fila) -> str:
    try:
        return cifrado.descifrar(fila["clave_cifrada"], _PROPOSITO).decode("ascii")
    except (cifrado.SecretosNoDisponibles, cifrado.SecretoInvalido):
        raise HTTPException(503, "No se puede leer la clave guardada: falta la clave maestra del servidor.")


async def _probar(conn: asyncpg.Connection, url: str, clave: str) -> str:
    """Llama a /api/v1/channel/me y guarda el resultado. Devuelve el nombre del canal."""
    try:
        d = await asyncio.to_thread(llamar, url, "/api/v1/channel/me", clave)
        canal = str(d.get("name") or d.get("code") or "")[:120] if isinstance(d, dict) else ""
        await conn.execute("UPDATE tracker_conexion SET canal = $1, ultimo_ok = now(), ultimo_error = NULL WHERE id = 1", canal)
        return canal
    except ErrorTracker as e:
        await conn.execute("UPDATE tracker_conexion SET ultimo_error = $1 WHERE id = 1", e.mensaje[:300])
        raise HTTPException(502, e.mensaje)


@router.get("")
async def ver(admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    return _salida(await _conexion(conn))


@router.put("")
async def guardar(data: ConexionNueva, request: Request, admin: dict = Depends(require_admin),
                  conn: asyncpg.Connection = Depends(get_conn)):
    url = _url_valida(data.url)
    actual = await _conexion(conn)
    clave = data.clave.strip()
    if clave:
        if not clave.startswith(PREFIJO_CLAVE):
            raise HTTPException(400, "La clave del canal de Tracker360 empieza con tch_.")
        try:
            cifrada = cifrado.cifrar(clave.encode("ascii"), _PROPOSITO)
        except cifrado.SecretosNoDisponibles:
            raise HTTPException(503, "No se puede guardar la clave: falta la clave maestra del servidor.")
    elif actual is None:
        raise HTTPException(400, "Falta la clave del canal.")
    else:
        cifrada = actual["clave_cifrada"]
    async with conn.transaction():
        await conn.execute("""
            INSERT INTO tracker_conexion (id, url, clave_cifrada, actualizado_por, actualizado_en)
            VALUES (1, $1, $2, $3, now())
            ON CONFLICT (id) DO UPDATE SET url = EXCLUDED.url, clave_cifrada = EXCLUDED.clave_cifrada,
                actualizado_por = EXCLUDED.actualizado_por, actualizado_en = now(), ultimo_error = NULL
        """, url, cifrada, admin["id"])
        await registrar(conn, admin["id"], admin["usuario"], "TRACKER_CONEXION",
                        f"{url}" + (", clave nueva." if clave else "."), client_ip(request))
    return _salida(await _conexion(conn))


@router.post("/probar")
async def probar(admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    fila = await _conexion(conn)
    if fila is None:
        raise HTTPException(409, "Primero guardá la URL y la clave del canal.")
    canal = await _probar(conn, fila["url"], _clave(fila))
    return {"ok": True, "canal": canal, **_salida(await _conexion(conn))}


# ===== Importacion del catalogo =====

importador = require_rol("administrador", "supervisor")


class Importacion(BaseModel):
    alicuota_iva: int = Field(ge=1, le=99)   # para los articulos nuevos (Tracker no sabe de IVA)


def _normalizar(item) -> Optional[dict]:
    """Item de Tracker a datos de Bill. None si no sirve (sin SKU o SKU que no entra en Bill)."""
    if not isinstance(item, dict):
        return None
    sku = str(item.get("sku") or "").strip()
    if not sku or len(sku) > MAX_SKU or any(c.isspace() for c in sku):
        return None
    return {"sku": sku, "descripcion": (str(item.get("description") or "").strip() or sku)[:MAX_DESCRIPCION],
            "categoria": str(item.get("category") or "").strip()[:MAX_CATEGORIA], "activo": bool(item.get("is_active", True))}


async def _comparar(conn: asyncpg.Connection) -> dict:
    """Trae el catalogo y lo cruza con los articulos de Bill por SKU (sin distinguir mayusculas)."""
    fila = await _conexion(conn)
    if fila is None:
        raise HTTPException(409, "Primero configurá la conexión con Tracker360.")
    url, clave = fila["url"], _clave(fila)
    try:
        items = await asyncio.to_thread(catalogo, url, clave)
    except ErrorTracker as e:
        await conn.execute("UPDATE tracker_conexion SET ultimo_error = $1 WHERE id = 1", e.mensaje[:300])
        raise HTTPException(502, e.mensaje)
    await conn.execute("UPDATE tracker_conexion SET ultimo_ok = now(), ultimo_error = NULL WHERE id = 1")
    existentes = {f["sku"].upper(): f for f in await conn.fetch(
        "SELECT id, sku, descripcion, categoria, activo, origen FROM articulos")}
    altas, cambios, omitidos, vistos = [], [], [], set()
    for item in items:
        d = _normalizar(item)
        if d is None:
            omitidos.append(str(item.get("sku") if isinstance(item, dict) else item)[:MAX_SKU + 20])
            continue
        if d["sku"].upper() in vistos:
            continue
        vistos.add(d["sku"].upper())
        e = existentes.get(d["sku"].upper())
        if e is None:
            altas.append(d)
        elif (e["descripcion"], e["categoria"], e["activo"], e["origen"]) != (d["descripcion"], d["categoria"], d["activo"], "tracker"):
            cambios.append({**d, "id": e["id"], "sku": e["sku"],
                            "antes": {"descripcion": e["descripcion"], "categoria": e["categoria"], "activo": e["activo"], "origen": e["origen"]}})
    return {"total_tracker": len(items), "altas": altas, "cambios": cambios, "omitidos": omitidos}


def _resumen(c: dict, maximo: int = 200) -> dict:
    return {"total_tracker": c["total_tracker"], "altas": len(c["altas"]), "cambios": len(c["cambios"]),
            "omitidos": len(c["omitidos"]),
            "detalle": {"altas": [{"sku": a["sku"], "descripcion": a["descripcion"], "categoria": a["categoria"], "activo": a["activo"]}
                                  for a in c["altas"][:maximo]],
                        "cambios": [{"sku": x["sku"], "descripcion": x["descripcion"], "categoria": x["categoria"], "activo": x["activo"],
                                     "antes": x["antes"]} for x in c["cambios"][:maximo]],
                        "omitidos": c["omitidos"][:maximo]}}


@router_importacion.post("/previa")
async def previa(usuario: dict = Depends(importador), conn: asyncpg.Connection = Depends(get_conn)):
    """Que pasaria: altas (SKU que Bill no tiene), cambios (descripcion, categoria o activo distintos, o articulo
    manual que pasa a ser de Tracker) y omitidos (SKU que no entra en Bill). No guarda nada."""
    return _resumen(await _comparar(conn))


@router_importacion.post("")
async def importar(data: Importacion, request: Request, usuario: dict = Depends(importador),
                   conn: asyncpg.Connection = Depends(get_conn)):
    """Aplica la importacion. Los nuevos quedan sin precio (se cargan en Bill) y con la alicuota indicada; los
    existentes toman descripcion, categoria y activo de Tracker y pasan a origen tracker. Costo, IVA y precios de
    los existentes no se tocan."""
    vigentes = None
    for modo in ("empresa", "prueba"):
        vigentes = vigentes or await parametros.vigentes(conn, modo)
    if not any(i["codigo"] == str(data.alicuota_iva) for i in (vigentes or {"tipos": {}})["tipos"].get("TiposIva", [])):
        raise HTTPException(400, "Alícuota de IVA desconocida para ARCA.")
    c = await _comparar(conn)
    async with conn.transaction():
        for a in c["altas"]:
            await conn.execute("""
                INSERT INTO articulos (sku, descripcion, categoria, alicuota_iva, activo, origen, creado_por)
                VALUES ($1, $2, $3, $4, $5, 'tracker', $6)
            """, a["sku"], a["descripcion"], a["categoria"], data.alicuota_iva, a["activo"], usuario["id"])
        for x in c["cambios"]:
            await conn.execute("""
                UPDATE articulos SET descripcion = $2, categoria = $3, activo = $4, origen = 'tracker', actualizado_en = now()
                WHERE id = $1
            """, x["id"], x["descripcion"], x["categoria"], x["activo"])
        await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULOS_IMPORTADOS",
                        f"Desde Tracker360: {len(c['altas'])} altas, {len(c['cambios'])} cambios, "
                        f"{len(c['omitidos'])} omitidos de {c['total_tracker']}.", client_ip(request))
    return _resumen(c)
