"""Acceso a ARCA con estado: certificado activo de la razon social y modo, ticket de acceso del WSAA (cifrado y
reutilizado) y reglas de reintento de la especificacion tecnica del WSAA:

- No se pide un ticket nuevo mientras haya uno valido (se renueva 10 minutos antes de que venza).
- Errores wsaa.* y wsn.unavailable (y fallas de red): no se reintenta por 60 segundos.
- coe.alreadyAuthenticated (ARCA cree que ya hay un ticket valido): se espera 10 minutos.
- Cualquier otro error (coe.notAuthorized, cms.*, xml.*): no se reintenta hasta cargar otro certificado o hasta que
  un administrador lo desbloquee despues de corregir la causa en ARCA.

Un bloqueo de PostgreSQL por razon social, modo y servicio evita que dos terminales pidan ticket a la vez."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from jzbill import cifrado, config
from jzbill.arca import soap, wsaa, wsfev1

logger = logging.getLogger(__name__)

WSFE = "wsfe"
_RENOVAR_ANTES = timedelta(minutes=10)
_ESPERA_CORTA = timedelta(seconds=60)
_ESPERA_YA_AUTENTICADO = timedelta(minutes=10)
_SIN_FIN = datetime(9999, 12, 31, tzinfo=timezone.utc)


class SinCertificado(soap.ErrorArca):
    pass


class Bloqueado(soap.ErrorArca):
    pass


def _proposito(rs_id, modo: str, servicio: str, parte: str) -> str:
    return f"ticket:{rs_id}:{modo}:{servicio}:{parte}"


async def _certificado_activo(conn: asyncpg.Connection, rs_id, modo: str):
    fila = await conn.fetchrow("""
        SELECT id, certificado_cifrado, clave_cifrada, valido_hasta FROM certificados
        WHERE razon_social_id = $1 AND modo = $2 AND activo
    """, rs_id, modo)
    if fila is None:
        raise SinCertificado("certificado.falta", "No hay certificado de ARCA cargado para este modo.")
    if fila["valido_hasta"] <= datetime.now(timezone.utc):
        raise SinCertificado("certificado.vencido", "El certificado de ARCA está vencido.")
    try:
        certificado = cifrado.descifrar(fila["certificado_cifrado"], f"certificado:{fila['id']}:certificado")
        clave = cifrado.descifrar(fila["clave_cifrada"], f"certificado:{fila['id']}:clave")
    except cifrado.SecretosNoDisponibles:
        raise soap.ErrorArca("secretos.falta", "Falta la clave maestra del servidor.")
    except cifrado.SecretoInvalido:
        raise soap.ErrorArca("secretos.invalido", "No se pudo descifrar el certificado (¿cambió la clave maestra?).")
    return fila["id"], certificado, clave


def _espera(codigo: str) -> datetime:
    ahora = datetime.now(timezone.utc)
    if codigo.startswith("wsaa.") or codigo in ("wsn.unavailable", "red") or codigo.startswith("http."):
        return ahora + _ESPERA_CORTA
    if codigo == "coe.alreadyAuthenticated":
        return ahora + _ESPERA_YA_AUTENTICADO
    return _SIN_FIN


async def credenciales(conn: asyncpg.Connection, rs: asyncpg.Record, modo: str,
                       servicio: str = WSFE) -> wsfev1.Credenciales:
    """Token y sign vigentes para la razon social y modo (pide uno nuevo al WSAA solo si hace falta)."""
    error: Optional[soap.ErrorArca] = None
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"arca:{rs['id']}:{modo}:{servicio}")
        cert_id, certificado, clave = await _certificado_activo(conn, rs["id"], modo)
        fila = await conn.fetchrow(
            "SELECT * FROM arca_tickets WHERE razon_social_id = $1 AND modo = $2 AND servicio = $3",
            rs["id"], modo, servicio)
        ahora = datetime.now(timezone.utc)
        if fila is not None and fila["certificado_id"] == cert_id:
            if fila["token_cifrado"] and fila["expira"] and fila["expira"] > ahora + _RENOVAR_ANTES:
                return wsfev1.Credenciales(
                    token=cifrado.descifrar(fila["token_cifrado"], _proposito(rs["id"], modo, servicio, "token")).decode(),
                    sign=cifrado.descifrar(fila["sign_cifrado"], _proposito(rs["id"], modo, servicio, "sign")).decode(),
                    cuit=rs["cuit"])
            if fila["bloqueado_hasta"] and fila["bloqueado_hasta"] > ahora:
                raise Bloqueado(fila["ultimo_error"] or "bloqueado",
                                "ARCA rechazó el último pedido de acceso; se reintenta más tarde o después de corregirlo.")
        try:
            cms = wsaa.firmar_tra(wsaa.crear_tra(servicio), certificado, clave)
            ticket = await asyncio.to_thread(wsaa.pedir_ticket, config.ARCA_URLS[modo]["wsaa"], cms)
        except soap.ErrorArca as e:
            error = e
            await conn.execute("""
                INSERT INTO arca_tickets (razon_social_id, modo, servicio, certificado_id, ultimo_error, ultimo_error_en,
                                          bloqueado_hasta, actualizado_en)
                VALUES ($1, $2, $3, $4, $5, now(), $6, now())
                ON CONFLICT (razon_social_id, modo, servicio) DO UPDATE SET certificado_id = $4, ultimo_error = $5,
                    ultimo_error_en = now(), bloqueado_hasta = $6, actualizado_en = now(),
                    token_cifrado = NULL, sign_cifrado = NULL, expira = NULL
            """, rs["id"], modo, servicio, cert_id, e.codigo[:80], _espera(e.codigo))
        else:
            await conn.execute("""
                INSERT INTO arca_tickets (razon_social_id, modo, servicio, certificado_id, token_cifrado, sign_cifrado,
                                          expira, ultimo_error, ultimo_error_en, bloqueado_hasta, actualizado_en)
                VALUES ($1, $2, $3, $4, $5, $6, $7, '', NULL, NULL, now())
                ON CONFLICT (razon_social_id, modo, servicio) DO UPDATE SET certificado_id = $4, token_cifrado = $5,
                    sign_cifrado = $6, expira = $7, ultimo_error = '', ultimo_error_en = NULL, bloqueado_hasta = NULL,
                    actualizado_en = now()
            """, rs["id"], modo, servicio, cert_id,
                cifrado.cifrar(ticket.token.encode(), _proposito(rs["id"], modo, servicio, "token")),
                cifrado.cifrar(ticket.sign.encode(), _proposito(rs["id"], modo, servicio, "sign")), ticket.expira)
            logger.info(f"[ARCA] Ticket nuevo para {servicio} ({modo}), vence {ticket.expira.isoformat()}")
            return wsfev1.Credenciales(token=ticket.token, sign=ticket.sign, cuit=rs["cuit"])
    raise error


async def desbloquear(conn: asyncpg.Connection, rs_id, modo: str, servicio: str = WSFE) -> None:
    await conn.execute("""
        UPDATE arca_tickets SET bloqueado_hasta = NULL, actualizado_en = now()
        WHERE razon_social_id = $1 AND modo = $2 AND servicio = $3
    """, rs_id, modo, servicio)


async def estado(conn: asyncpg.Connection, rs_id, modo: str, servicio: str = WSFE) -> dict:
    """Estado para mostrar (sin secretos): certificado activo, vencimiento del ticket, ultimo error y bloqueo."""
    cert = await conn.fetchrow("""
        SELECT alias, sujeto, valido_hasta FROM certificados WHERE razon_social_id = $1 AND modo = $2 AND activo
    """, rs_id, modo)
    ticket = await conn.fetchrow("""
        SELECT expira, ultimo_error, ultimo_error_en, bloqueado_hasta FROM arca_tickets
        WHERE razon_social_id = $1 AND modo = $2 AND servicio = $3
    """, rs_id, modo, servicio)
    ahora = datetime.now(timezone.utc)

    def iso(valor):
        return valor.isoformat() if valor else None

    return {
        "certificado": {"alias": cert["alias"] or cert["sujeto"], "vence": iso(cert["valido_hasta"])} if cert else None,
        "ticket_vence": iso(ticket["expira"]) if ticket and ticket["expira"] and ticket["expira"] > ahora else None,
        "ultimo_error": (ticket["ultimo_error"] or None) if ticket else None,
        "ultimo_error_en": iso(ticket["ultimo_error_en"]) if ticket else None,
        "bloqueado_hasta": (iso(ticket["bloqueado_hasta"]) if ticket and ticket["bloqueado_hasta"]
                            and ticket["bloqueado_hasta"] > ahora else None),
    }
