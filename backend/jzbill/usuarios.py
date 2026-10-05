"""Usuarios, rol global y accesos por razon social / modo / punto de venta. Solo administrador.

- Nunca queda el sistema sin un administrador activo (se controla con bloqueo, sin carreras).
- Resetear la clave o desactivar a un usuario cierra todas sus sesiones.
- El administrador cambia su propia clave desde /api/auth/clave (que pide la actual), no desde aca.
- Los accesos se reemplazan completos, en una transaccion."""

import re
from typing import List, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from jztech_core import sessions as core_sessions
from jztech_core.passwords import hash_password
from pydantic import BaseModel, Field

from jzbill import config
from jzbill.auth import client_ip, registrar
from jzbill.db import ConexionComoPool, get_conn
from jzbill.permisos import require_admin, uuid_o_404

router = APIRouter(prefix="/api/usuarios", tags=["Usuarios"])

Rol = Literal["administrador", "supervisor", "cajero", "solo_lectura"]
Modo = Literal["empresa", "prueba"]
_USUARIO_VALIDO = re.compile(r"^[a-z0-9._-]{3,50}$")


class UsuarioNuevo(BaseModel):
    usuario: str = Field(max_length=50)
    nombre: str = Field(default="", max_length=120)
    rol: Rol
    clave: str = Field(max_length=config.PASSWORD_MAX_LENGTH)


class UsuarioCambios(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=120)
    rol: Optional[Rol] = None
    activo: Optional[bool] = None
    clave_nueva: Optional[str] = Field(default=None, max_length=config.PASSWORD_MAX_LENGTH)


class Acceso(BaseModel):
    razon_social_id: str = Field(max_length=40)
    modos: List[Modo] = Field(min_length=1, max_length=2)
    puntos_venta: List[str] = Field(default_factory=list, max_length=500)


class Accesos(BaseModel):
    accesos: List[Acceso] = Field(max_length=500)


def _validar_clave(clave: str) -> None:
    if len(clave) < config.PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"La contraseña debe tener al menos {config.PASSWORD_MIN_LENGTH} caracteres.")


def _usuario_salida(fila) -> dict:
    return {"id": str(fila["id"]), "usuario": fila["usuario"], "nombre": fila["nombre"], "rol": fila["rol"],
            "activo": fila["activo"]}


async def _accesos_de(conn: asyncpg.Connection, usuario_id) -> list:
    modos = await conn.fetch("""
        SELECT a.razon_social_id, rs.nombre_legal, array_agg(a.modo ORDER BY a.modo) AS modos
        FROM usuario_accesos a JOIN razones_sociales rs ON rs.id = a.razon_social_id
        WHERE a.usuario_id = $1 GROUP BY a.razon_social_id, rs.nombre_legal ORDER BY rs.nombre_legal
    """, usuario_id)
    pvs = await conn.fetch("""
        SELECT pv.razon_social_id, pv.id FROM usuario_puntos_venta upv
        JOIN puntos_venta pv ON pv.id = upv.punto_venta_id
        WHERE upv.usuario_id = $1
    """, usuario_id)
    por_rs = {}
    for pv in pvs:
        por_rs.setdefault(pv["razon_social_id"], []).append(str(pv["id"]))
    return [{"razon_social_id": str(f["razon_social_id"]), "nombre_legal": f["nombre_legal"],
             "modos": list(f["modos"]), "puntos_venta": sorted(por_rs.get(f["razon_social_id"], []))}
            for f in modos]


async def _usuario_o_404(conn: asyncpg.Connection, usuario_id: str) -> asyncpg.Record:
    fila = await conn.fetchrow("SELECT * FROM usuarios WHERE id = $1", uuid_o_404(usuario_id))
    if fila is None:
        raise HTTPException(404, "No encontrado.")
    return fila


@router.get("")
async def listar(admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    filas = await conn.fetch("SELECT * FROM usuarios ORDER BY usuario")
    return [_usuario_salida(f) for f in filas]


@router.post("", status_code=201)
async def crear(data: UsuarioNuevo, request: Request, admin: dict = Depends(require_admin),
                conn: asyncpg.Connection = Depends(get_conn)):
    usuario = data.usuario.strip().lower()
    if not _USUARIO_VALIDO.match(usuario):
        raise HTTPException(400, "Usuario inválido: de 3 a 50 caracteres, letras minúsculas, números, punto o guion.")
    _validar_clave(data.clave)
    hashed = hash_password(data.clave)
    async with conn.transaction():
        try:
            fila = await conn.fetchrow(
                "INSERT INTO usuarios (usuario, nombre, clave_hash, rol) VALUES ($1, $2, $3, $4) RETURNING *",
                usuario, data.nombre.strip(), hashed, data.rol)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "Ese usuario ya existe.")
        await registrar(conn, admin["id"], admin["usuario"], "USUARIO_ALTA",
                        f"Alta de {usuario} con rol {data.rol}.", client_ip(request))
    return _usuario_salida(fila)


@router.get("/{usuario_id}")
async def ver(usuario_id: str, admin: dict = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    fila = await _usuario_o_404(conn, usuario_id)
    return {**_usuario_salida(fila), "accesos": await _accesos_de(conn, fila["id"])}


@router.put("/{usuario_id}")
async def modificar(usuario_id: str, data: UsuarioCambios, request: Request, admin: dict = Depends(require_admin),
                    conn: asyncpg.Connection = Depends(get_conn)):
    objetivo = await _usuario_o_404(conn, usuario_id)
    if data.clave_nueva is not None:
        if objetivo["id"] == admin["id"]:
            raise HTTPException(400, "Para cambiar su propia contraseña use Cambiar contraseña.")
        _validar_clave(data.clave_nueva)
    rol = objetivo["rol"] if data.rol is None else data.rol
    activo = objetivo["activo"] if data.activo is None else data.activo
    nombre = objetivo["nombre"] if data.nombre is None else data.nombre.strip()
    hashed = hash_password(data.clave_nueva) if data.clave_nueva is not None else None
    cierra_sesiones = hashed is not None or (objetivo["activo"] and not activo)
    async with conn.transaction():
        # Bloqueo de los administradores activos: dos cambios simultaneos no pueden dejar el sistema sin ninguno.
        admins = await conn.fetch(
            "SELECT id FROM usuarios WHERE rol = 'administrador' AND activo ORDER BY id FOR UPDATE")
        deja_de_ser_admin = objetivo["rol"] == "administrador" and objetivo["activo"] and (
            rol != "administrador" or not activo)
        if deja_de_ser_admin and len(admins) <= 1:
            raise HTTPException(409, "Tiene que quedar al menos un administrador activo.")
        fila = await conn.fetchrow("""
            UPDATE usuarios SET nombre = $2, rol = $3, activo = $4,
                   clave_hash = COALESCE($5, clave_hash),
                   clave_cambiada_en = CASE WHEN $5::text IS NULL THEN clave_cambiada_en ELSE now() END
            WHERE id = $1 RETURNING *
        """, objetivo["id"], nombre, rol, activo, hashed)
        if cierra_sesiones:
            await core_sessions.revoke_all_sessions_for_user(ConexionComoPool(conn), str(objetivo["id"]))
        cambios = [campo for campo, antes, ahora in (("nombre", objetivo["nombre"], nombre),
                                                     ("rol", objetivo["rol"], rol),
                                                     ("activo", objetivo["activo"], activo)) if antes != ahora]
        if hashed is not None:
            cambios.append("contraseña")
        if cambios:
            detalle = f"{objetivo['usuario']}: " + ", ".join(cambios) + "."
            if cierra_sesiones:
                detalle += " Se cerraron sus sesiones."
            await registrar(conn, admin["id"], admin["usuario"], "USUARIO_CAMBIO", detalle, client_ip(request))
    return _usuario_salida(fila)


@router.put("/{usuario_id}/accesos")
async def asignar_accesos(usuario_id: str, data: Accesos, request: Request, admin: dict = Depends(require_admin),
                          conn: asyncpg.Connection = Depends(get_conn)):
    objetivo = await _usuario_o_404(conn, usuario_id)
    filas_modos, filas_pv = [], []
    vistos = set()
    for acceso in data.accesos:
        rs_id = uuid_o_404(acceso.razon_social_id)
        if rs_id in vistos:
            raise HTTPException(400, "Una razón social aparece dos veces.")
        vistos.add(rs_id)
        if not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM razones_sociales WHERE id = $1)", rs_id):
            raise HTTPException(400, "Razón social inexistente.")
        for modo in sorted(set(acceso.modos)):
            filas_modos.append((objetivo["id"], rs_id, modo))
        for pv in sorted(set(acceso.puntos_venta)):
            pv_id = uuid_o_404(pv)
            if not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM puntos_venta WHERE id = $1 AND razon_social_id = $2)", pv_id, rs_id):
                raise HTTPException(400, "Un punto de venta no pertenece a su razón social.")
            filas_pv.append((objetivo["id"], pv_id))
    async with conn.transaction():
        await conn.execute("DELETE FROM usuario_accesos WHERE usuario_id = $1", objetivo["id"])
        await conn.execute("DELETE FROM usuario_puntos_venta WHERE usuario_id = $1", objetivo["id"])
        if filas_modos:
            await conn.executemany(
                "INSERT INTO usuario_accesos (usuario_id, razon_social_id, modo) VALUES ($1, $2, $3)", filas_modos)
        if filas_pv:
            await conn.executemany(
                "INSERT INTO usuario_puntos_venta (usuario_id, punto_venta_id) VALUES ($1, $2)", filas_pv)
        if objetivo["rol"] != "administrador":
            # Contextos elegidos en sesiones abiertas que ya no estan permitidos: se descartan.
            await conn.execute("""
                DELETE FROM sesion_contexto c USING jztech_sessions s
                WHERE c.token_hash = s.token_hash AND s.user_id = $1
                  AND NOT EXISTS (SELECT 1 FROM usuario_accesos a WHERE a.usuario_id = $2
                                  AND a.razon_social_id = c.razon_social_id AND a.modo = c.modo)
            """, str(objetivo["id"]), objetivo["id"])
        await registrar(conn, admin["id"], admin["usuario"], "USUARIO_ACCESOS",
                        f"{objetivo['usuario']}: {len(vistos)} razones sociales, "
                        f"{len(filas_pv)} puntos de venta restringidos.", client_ip(request))
    return {"accesos": await _accesos_de(conn, objetivo["id"])}
