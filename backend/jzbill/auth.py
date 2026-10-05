"""Usuarios de la pagina: alta inicial con SETUP_TOKEN, login con limite de intentos, sesiones opacas y
CSRF de jztech_core (mismos criterios que Tracker360 y el middleware), cambio de clave y cierre de sesiones.

Toda ruta que no sea publica depende de require_usuario: el test de deny-by-default (fuera del repo publico)
lo verifica para todas las rutas de la app."""

from datetime import datetime, timedelta, timezone
import logging
import secrets
import uuid
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jztech_core import sessions as core_sessions
from jztech_core.csrf import enforce_csrf, generate_csrf_token
from jztech_core.net import real_ip
from jztech_core.passwords import hash_password, needs_rehash, verify_password
from jztech_core.setup_flow import verify_setup_token
from pydantic import BaseModel, Field

from jzbill import config
from jzbill.db import ConexionComoPool, get_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

CSRF_COOKIE = "csrf_token"
_CSRF_SUJETO = "jzbill-csrf"

# Hash de una clave al azar: si el usuario no existe se verifica contra este, para que la respuesta tarde
# lo mismo y no delate que usuarios existen.
_hash_ficticio: Optional[str] = None


def _verificar_o_simular(clave: str, hash_guardado: Optional[str]) -> bool:
    global _hash_ficticio
    if hash_guardado:
        return verify_password(clave, hash_guardado)
    if _hash_ficticio is None:
        _hash_ficticio = hash_password(secrets.token_hex(16))
    verify_password(clave, _hash_ficticio)
    return False


def client_ip(request: Request) -> str:
    return real_ip(request, config.TRUSTED_PROXIES) if request.client else "desconocida"


async def registrar(conn: asyncpg.Connection, usuario_id, usuario: str, accion: str, detalle: str = "",
                    ip: str = "", razon_social_id=None) -> None:
    """Auditoria de acciones sensibles. Nunca recibe claves, tokens ni secretos."""
    await conn.execute(
        "INSERT INTO auditoria (usuario_id, usuario, accion, detalle, ip, razon_social_id) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        usuario_id, usuario[:50], accion[:60], detalle, ip[:64], razon_social_id)


def _ttl() -> timedelta:
    return timedelta(hours=config.SESSION_HOURS)


async def _iniciar_sesion(conn: asyncpg.Connection, response: Response, usuario_id) -> None:
    await conn.execute("DELETE FROM jztech_sessions WHERE expires_at <= now()")
    token = await core_sessions.create_session(ConexionComoPool(conn), str(usuario_id), _ttl())
    core_sessions.set_session_cookie(response, token, _ttl(), secure=config.COOKIES_SECURE)
    response.set_cookie(key=CSRF_COOKIE, value=generate_csrf_token(token, _CSRF_SUJETO), httponly=False,
                        secure=config.COOKIES_SECURE, samesite="strict", max_age=int(_ttl().total_seconds()))


def _borrar_cookies(response: Response) -> None:
    core_sessions.clear_session_cookie(response, secure=config.COOKIES_SECURE)
    response.delete_cookie(CSRF_COOKIE, secure=config.COOKIES_SECURE, samesite="strict")


async def require_usuario(request: Request, conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    """Sesion valida de un usuario activo; en POST/PUT/PATCH/DELETE exige ademas X-CSRF-Token."""
    token = request.cookies.get(core_sessions.SESSION_COOKIE_NAME)
    usuario_id = await core_sessions.verify_session(ConexionComoPool(conn), token) if token else None
    if not usuario_id:
        raise HTTPException(401, "Sesión expirada.")
    try:
        uid = uuid.UUID(usuario_id)
    except ValueError:
        raise HTTPException(401, "Sesión expirada.")
    # El rol se lee en cada pedido: un cambio de rol vale desde el pedido siguiente, sin esperar otro login.
    usuario = await conn.fetchrow("SELECT id, usuario, nombre, rol, activo FROM usuarios WHERE id = $1", uid)
    if not usuario or not usuario["activo"]:
        raise HTTPException(401, "Sesión expirada.")
    await enforce_csrf(request, token, _CSRF_SUJETO)
    return {"id": usuario["id"], "usuario": usuario["usuario"], "nombre": usuario["nombre"], "rol": usuario["rol"],
            "token": token}


# --- Limite de intentos (se cuenta ANTES de verificar la clave) ---
async def _reservar_intento(conn: asyncpg.Connection, clave: str, maximo: int) -> None:
    """Suma un intento a la clave y corta con 429 si esta bloqueada. Los intentos viejos (sin actividad
    por LOCKOUT_MINUTES) se olvidan, y al vencer un bloqueo se arranca de cero."""
    ventana = timedelta(minutes=config.LOCKOUT_MINUTES)
    fila = await conn.fetchrow("""
        INSERT INTO login_limites (clave, intentos, ultimo_intento) VALUES ($1, 1, now())
        ON CONFLICT (clave) DO UPDATE SET
            intentos = CASE
                WHEN login_limites.bloqueado_hasta IS NOT NULL AND login_limites.bloqueado_hasta <= now() THEN 1
                WHEN login_limites.bloqueado_hasta IS NULL AND login_limites.ultimo_intento <= now() - $2::interval THEN 1
                ELSE login_limites.intentos + 1 END,
            bloqueado_hasta = CASE
                WHEN login_limites.bloqueado_hasta <= now() THEN NULL ELSE login_limites.bloqueado_hasta END,
            ultimo_intento = now()
        RETURNING intentos, bloqueado_hasta
    """, clave, ventana)
    ahora = datetime.now(timezone.utc)
    bloqueo = fila["bloqueado_hasta"]
    if not bloqueo and fila["intentos"] > maximo:
        bloqueo = ahora + ventana
        await conn.execute("UPDATE login_limites SET bloqueado_hasta = $2 WHERE clave = $1 AND bloqueado_hasta IS NULL",
                           clave, bloqueo)
    if bloqueo and ahora < bloqueo:
        minutos = int((bloqueo - ahora).total_seconds() / 60) + 1
        raise HTTPException(429, f"Demasiados intentos fallidos. Bloqueado por {minutos} min.")


async def _intento_correcto(conn: asyncpg.Connection, clave_usuario: str, clave_ip: Optional[str]) -> None:
    """Un intento correcto borra el contador de ese usuario y descuenta su intento del de la IP (no lo
    borra: en una oficina varios usuarios salen por la misma IP)."""
    await conn.execute("DELETE FROM login_limites WHERE clave = $1", clave_usuario)
    if clave_ip:
        await conn.execute("UPDATE login_limites SET intentos = GREATEST(intentos - 1, 0) "
                           "WHERE clave = $1 AND bloqueado_hasta IS NULL", clave_ip)


def _validar_clave_nueva(clave: str) -> None:
    if len(clave) < config.PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"La contraseña debe tener al menos {config.PASSWORD_MIN_LENGTH} caracteres.")


def _normalizar_usuario(usuario: str) -> str:
    return usuario.strip().lower()


_CLAVE = Field(max_length=config.PASSWORD_MAX_LENGTH)


class SetupInput(BaseModel):
    token: str = Field(max_length=200)
    usuario: str = Field(max_length=50)
    nombre: str = Field(default="", max_length=120)
    clave: str = _CLAVE


class LoginInput(BaseModel):
    usuario: str = Field(max_length=50)
    clave: str = _CLAVE


class CambioClaveInput(BaseModel):
    clave_actual: str = _CLAVE
    clave_nueva: str = _CLAVE


@router.get("/setup/status")
async def setup_status(conn: asyncpg.Connection = Depends(get_conn)):
    return {"needs_setup": (await conn.fetchval("SELECT COUNT(*) FROM usuarios")) == 0}


@router.post("/setup/admin")
async def setup_admin(data: SetupInput, request: Request, response: Response,
                      conn: asyncpg.Connection = Depends(get_conn)):
    ip = client_ip(request)
    # El token de instalacion tambien tiene limite de intentos (por IP).
    await _reservar_intento(conn, f"setup|{ip}"[:255], config.MAX_LOGIN_ATTEMPTS)
    if not verify_setup_token(config.SETUP_TOKEN, data.token):
        raise HTTPException(403, "Token de instalación inválido.")
    if await conn.fetchval("SELECT COUNT(*) FROM usuarios"):
        raise HTTPException(403, "La configuración inicial ya fue completada.")
    usuario = _normalizar_usuario(data.usuario)
    if not usuario:
        raise HTTPException(400, "Usuario inválido.")
    _validar_clave_nueva(data.clave)
    hashed = hash_password(data.clave)
    async with conn.transaction():
        # Dos altas simultaneas: la segunda espera y ve la primera.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('jzbill_setup_admin'))")
        if await conn.fetchval("SELECT COUNT(*) FROM usuarios"):
            raise HTTPException(403, "La configuración inicial ya fue completada.")
        uid = await conn.fetchval("INSERT INTO usuarios (usuario, nombre, clave_hash, rol) "
                                  "VALUES ($1, $2, $3, 'administrador') RETURNING id",
                                  usuario, data.nombre.strip(), hashed)
        await registrar(conn, uid, usuario, "SETUP_ADMIN", "Administrador inicial creado.", ip)
    await conn.execute("DELETE FROM login_limites WHERE clave = $1", f"setup|{ip}"[:255])
    await _iniciar_sesion(conn, response, uid)
    return {"usuario": usuario}


@router.post("/login")
async def login(data: LoginInput, request: Request, response: Response, conn: asyncpg.Connection = Depends(get_conn)):
    usuario = _normalizar_usuario(data.usuario)
    ip = client_ip(request)
    clave_ip = f"ip|{ip}"[:255]
    clave_usuario = f"u|{ip}|{usuario}"[:255]
    await _reservar_intento(conn, clave_ip, config.MAX_LOGIN_ATTEMPTS_IP)
    await _reservar_intento(conn, clave_usuario, config.MAX_LOGIN_ATTEMPTS)
    fila = await conn.fetchrow("SELECT id, usuario, clave_hash, activo FROM usuarios WHERE usuario = $1", usuario)
    if not _verificar_o_simular(data.clave, fila["clave_hash"] if fila else None) or not fila["activo"]:
        await registrar(conn, fila["id"] if fila else None, usuario or "?", "LOGIN_FALLIDO", "Intento de acceso fallido.", ip)
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    await _intento_correcto(conn, clave_usuario, clave_ip)
    if needs_rehash(fila["clave_hash"]):
        await conn.execute("UPDATE usuarios SET clave_hash = $1 WHERE id = $2", hash_password(data.clave), fila["id"])
    await _iniciar_sesion(conn, response, fila["id"])
    await registrar(conn, fila["id"], fila["usuario"], "LOGIN", "Inicio de sesión.", ip)
    return {"usuario": fila["usuario"]}


@router.post("/logout")
async def logout(request: Request, response: Response, usuario: dict = Depends(require_usuario),
                 conn: asyncpg.Connection = Depends(get_conn)):
    """Cierra solo la sesion de este dispositivo."""
    await core_sessions.revoke_session(ConexionComoPool(conn), usuario["token"])
    _borrar_cookies(response)
    await registrar(conn, usuario["id"], usuario["usuario"], "LOGOUT", "Cierre de sesión.", client_ip(request))
    return {"mensaje": "Sesión cerrada."}


@router.post("/sesiones/cerrar")
async def cerrar_todas(request: Request, response: Response, usuario: dict = Depends(require_usuario),
                       conn: asyncpg.Connection = Depends(get_conn)):
    """Cierra todas las sesiones del usuario, en todos los dispositivos (tambien esta)."""
    await core_sessions.revoke_all_sessions_for_user(ConexionComoPool(conn), str(usuario["id"]))
    _borrar_cookies(response)
    await registrar(conn, usuario["id"], usuario["usuario"], "SESIONES_CERRADAS",
                    "Cierre de todas las sesiones.", client_ip(request))
    return {"mensaje": "Se cerraron todas las sesiones."}


@router.post("/clave")
async def cambiar_clave(data: CambioClaveInput, request: Request, response: Response,
                        usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    """Cambio de la clave propia: pide la actual, cierra todas las sesiones del usuario (las de otros
    dispositivos quedan invalidas) y abre una nueva en este."""
    ip = client_ip(request)
    clave_limite = f"clave|{usuario['id']}"
    await _reservar_intento(conn, clave_limite, config.MAX_LOGIN_ATTEMPTS)
    hash_actual = await conn.fetchval("SELECT clave_hash FROM usuarios WHERE id = $1", usuario["id"])
    if not _verificar_o_simular(data.clave_actual, hash_actual):
        await registrar(conn, usuario["id"], usuario["usuario"], "CLAVE_FALLIDA",
                        "Cambio de contraseña rechazado: la actual no coincide.", ip)
        raise HTTPException(400, "La contraseña actual no es correcta.")
    _validar_clave_nueva(data.clave_nueva)
    if data.clave_nueva == data.clave_actual:
        raise HTTPException(400, "La contraseña nueva tiene que ser distinta de la actual.")
    async with conn.transaction():
        await conn.execute("UPDATE usuarios SET clave_hash = $1, clave_cambiada_en = now() WHERE id = $2",
                           hash_password(data.clave_nueva), usuario["id"])
        await core_sessions.revoke_all_sessions_for_user(ConexionComoPool(conn), str(usuario["id"]))
        await registrar(conn, usuario["id"], usuario["usuario"], "CLAVE_CAMBIADA",
                        "Contraseña cambiada; se cerraron todas las sesiones.", ip)
    await conn.execute("DELETE FROM login_limites WHERE clave = $1", clave_limite)
    await _iniciar_sesion(conn, response, usuario["id"])
    return {"mensaje": "Contraseña cambiada. Se cerraron las sesiones de los demás dispositivos."}


@router.get("/me")
async def me(usuario: dict = Depends(require_usuario)):
    return {"usuario": usuario["usuario"], "nombre": usuario["nombre"], "rol": usuario["rol"]}
