"""Consulta de la auditoria (solo administrador). Solo lectura: la tabla es inmutable (trigger en la base)."""

from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Query

from jzbill.db import get_conn
from jzbill.permisos import require_admin, uuid_o_404

router = APIRouter(prefix="/api/auditoria", tags=["Auditoria"])


@router.get("")
async def listar(limite: int = Query(50, ge=1, le=200), antes_de: Optional[int] = Query(None, ge=1),
                 razon_social_id: Optional[str] = Query(None, max_length=40),
                 admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    """Mas nuevo primero. Para la pagina siguiente, antes_de = el id mas chico recibido."""
    rs_id = uuid_o_404(razon_social_id) if razon_social_id else None
    filas = await conn.fetch("""
        SELECT id, creado_en, usuario, accion, detalle, ip, razon_social_id FROM auditoria
        WHERE ($1::bigint IS NULL OR id < $1) AND ($2::uuid IS NULL OR razon_social_id = $2)
        ORDER BY id DESC LIMIT $3
    """, antes_de, rs_id, limite)
    return [{"id": f["id"], "fecha": f["creado_en"].isoformat(), "usuario": f["usuario"], "accion": f["accion"],
             "detalle": f["detalle"], "ip": f["ip"],
             "razon_social_id": str(f["razon_social_id"]) if f["razon_social_id"] else None} for f in filas]
