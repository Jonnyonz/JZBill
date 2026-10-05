"""Parametros fiscales de ARCA como datos con version (regla del proyecto: la fuente de verdad son los FEParamGet*
de WSFEv1; el sistema los lee, no los copia a mano).

Cada actualizacion lee todos los FEParamGet* configurados en wsfev1.PARAMETROS. Si el contenido es identico a la
ultima version del modo, no se crea otra. Las versiones son inmutables (trigger en la base)."""

import asyncio
import hashlib
import json
from datetime import date
from typing import Optional

import asyncpg

from jzbill import config
from jzbill.arca import servicio, wsfev1


def _fecha(valor: str) -> Optional[date]:
    """Las fechas de ARCA vienen como yyyymmdd o "NULL"."""
    valor = (valor or "").strip()
    if len(valor) == 8 and valor.isdigit():
        try:
            return date(int(valor[:4]), int(valor[4:6]), int(valor[6:]))
        except ValueError:
            return None
    return None


def _agrupar(items: list) -> list:
    """Un item por codigo (Id). Si ARCA repite un Id (por ejemplo la condicion frente al IVA del receptor, una vez
    por clase de comprobante), los demas campos se juntan en listas ordenadas."""
    por_codigo = {}
    for item in items:
        codigo = (item.get("Id") or "").strip()[:20]
        if not codigo:
            continue
        actual = por_codigo.setdefault(codigo, {"codigo": codigo, "descripcion": (item.get("Desc") or "")[:250],
                                                "desde": item.get("FchDesde", ""), "hasta": item.get("FchHasta", ""),
                                                "datos": {}})
        for clave, valor in item.items():
            if clave in ("Id", "Desc", "FchDesde", "FchHasta"):
                continue
            valores = set(actual["datos"].get(clave, [])) | {valor}
            actual["datos"][clave] = sorted(valores)
    return [por_codigo[c] for c in sorted(por_codigo, key=lambda c: (len(c), c))]


async def actualizar(conn: asyncpg.Connection, rs: asyncpg.Record, modo: str, usuario: dict) -> dict:
    credenciales = await servicio.credenciales(conn, rs, modo)
    url = config.ARCA_URLS[modo]["wsfe"]
    leidos = {}
    for tipo in wsfev1.PARAMETROS:
        leidos[tipo] = _agrupar(await asyncio.to_thread(wsfev1.parametro, url, credenciales, tipo))
    huella = hashlib.sha256(json.dumps(leidos, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cantidades = {tipo: len(items) for tipo, items in leidos.items()}
    ultima = await conn.fetchrow(
        "SELECT id, huella FROM parametros_fiscales_versiones WHERE modo = $1 ORDER BY id DESC LIMIT 1", modo)
    if ultima is not None and ultima["huella"] == huella:
        return {"version": ultima["id"], "nueva": False, "cantidades": cantidades}
    async with conn.transaction():
        version = await conn.fetchval("""
            INSERT INTO parametros_fiscales_versiones (modo, huella, obtenido_por, razon_social_id)
            VALUES ($1, $2, $3, $4) RETURNING id
        """, modo, huella, usuario["id"], rs["id"])
        await conn.executemany("""
            INSERT INTO parametros_fiscales (version_id, tipo, codigo, descripcion, vigente_desde, vigente_hasta, datos)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        """, [(version, tipo, i["codigo"], i["descripcion"], _fecha(i["desde"]), _fecha(i["hasta"]),
               json.dumps(i["datos"], ensure_ascii=False)) for tipo, items in leidos.items() for i in items])
    return {"version": version, "nueva": True, "cantidades": cantidades}


async def vigentes(conn: asyncpg.Connection, modo: str) -> Optional[dict]:
    version = await conn.fetchrow(
        "SELECT id, obtenido_en FROM parametros_fiscales_versiones WHERE modo = $1 ORDER BY id DESC LIMIT 1", modo)
    if version is None:
        return None
    filas = await conn.fetch("""
        SELECT tipo, codigo, descripcion, vigente_desde, vigente_hasta, datos FROM parametros_fiscales
        WHERE version_id = $1 ORDER BY tipo, length(codigo), codigo
    """, version["id"])
    tipos = {}
    for f in filas:
        tipos.setdefault(f["tipo"], []).append({
            "codigo": f["codigo"], "descripcion": f["descripcion"],
            "desde": f["vigente_desde"].isoformat() if f["vigente_desde"] else None,
            "hasta": f["vigente_hasta"].isoformat() if f["vigente_hasta"] else None,
            "datos": json.loads(f["datos"]) if isinstance(f["datos"], str) else f["datos"]})
    return {"version": version["id"], "obtenido_en": version["obtenido_en"].isoformat(), "tipos": tipos}
