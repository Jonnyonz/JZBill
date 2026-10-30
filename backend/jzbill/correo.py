"""Correo (Fase 7): un servidor SMTP por razon social y envio de comprobantes por email.

- Configuracion: solo administrador, sobre la razon social del contexto. La clave se guarda cifrada con la clave
  maestra (cifrado.py) y nunca vuelve por la API (solo si hay una guardada). STARTTLS (587) o SSL (465), siempre con
  verificacion de certificado: no hay opcion sin cifrar.
- Envio: a pedido desde Comprobantes o Facturar (administrador, supervisor y cajero), o automatico al emitir si la
  razon social lo tiene activado y el comprobante lleva un cliente con email. El automatico nunca frena ni revierte
  la emision: si falla, queda registrado en comprobante_envios y el comprobante se puede reenviar.
- Mensaje: cuerpo HTML con los mismos datos de la representacion impresa (emisor, receptor, detalle, total, CAE,
  leyenda de prueba) y el QR oficial de ARCA como imagen PNG incrustada (segno la genera sin dependencias), mas una
  version en texto plano. Sin PDF adjunto: no hay biblioteca de PDF aprobada (decision 2026-10-08); cuando la haya,
  el adjunto entra aca.

Todo con la biblioteca estandar: smtplib, ssl, email. El envio real se hace en un hilo (asyncio.to_thread)."""

import asyncio
import logging
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from io import BytesIO
from typing import Literal, Optional

import asyncpg
import segno
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jzbill import cifrado
from jzbill.auth import client_ip, registrar
from jzbill.contexto import contexto_requerido
from jzbill.cuit import formatear_cuit
from jzbill.db import get_conn
from jzbill.impresion import CONDICIONES_EMISOR, _cantidad, _descripcion, _fecha, _importe, texto_qr
from jzbill.permisos import es_admin, uuid_o_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/correo", tags=["Correo"])
router_envios = APIRouter(prefix="/api/comprobantes", tags=["Correo"])

ENVIAN = ("administrador", "supervisor", "cajero")
TIMEOUT = 20
_EMAIL = re.compile(r"^[^@\s]{1,120}@[^@\s]{1,120}\.[^@\s.]{2,}$")


class CorreoDatos(BaseModel):
    servidor: str = Field(min_length=1, max_length=200)
    puerto: int = Field(default=587, ge=1, le=65535)
    seguridad: Literal["starttls", "ssl"] = "starttls"
    usuario: str = Field(default="", max_length=200)
    clave: str = Field(default="", max_length=200)   # vacia: se conserva la guardada
    remitente: str = Field(min_length=3, max_length=200)
    nombre_remitente: str = Field(default="", max_length=120)
    envio_automatico: bool = False


class Destinatario(BaseModel):
    destinatario: str = Field(min_length=3, max_length=200)


def _email_valido(texto: str) -> str:
    email = texto.strip()
    if not _EMAIL.match(email):
        raise HTTPException(400, "La dirección de correo no es válida.")
    return email


def _proposito(rs_id) -> str:
    return f"correo:{rs_id}"


def _salida(fila) -> dict:
    if fila is None:
        return {"configurado": False, "servidor": "", "puerto": 587, "seguridad": "starttls", "usuario": "", "clave_guardada": False,
                "remitente": "", "nombre_remitente": "", "envio_automatico": False, "ultimo_ok": None, "ultimo_error": None}
    return {"configurado": True, "servidor": fila["servidor"], "puerto": fila["puerto"], "seguridad": fila["seguridad"],
            "usuario": fila["usuario"], "clave_guardada": fila["clave_cifrada"] is not None, "remitente": fila["remitente"],
            "nombre_remitente": fila["nombre_remitente"], "envio_automatico": fila["envio_automatico"],
            "ultimo_ok": fila["ultimo_ok"].isoformat() if fila["ultimo_ok"] else None, "ultimo_error": fila["ultimo_error"]}


async def _config(conn: asyncpg.Connection, rs_id):
    return await conn.fetchrow("SELECT * FROM correo_config WHERE razon_social_id = $1", rs_id)


def _clave(fila) -> str:
    if fila["clave_cifrada"] is None:
        return ""
    try:
        return cifrado.descifrar(fila["clave_cifrada"], _proposito(fila["razon_social_id"])).decode("utf-8")
    except (cifrado.SecretosNoDisponibles, cifrado.SecretoInvalido):
        raise HTTPException(503, "No se puede leer la clave guardada: falta la clave maestra del servidor.")


# --- Envio SMTP (los tests lo reemplazan) ---
def _enviar(cfg, clave: str, mensaje: EmailMessage) -> None:
    contexto = ssl.create_default_context()
    if cfg["seguridad"] == "ssl":
        servidor = smtplib.SMTP_SSL(cfg["servidor"], cfg["puerto"], timeout=TIMEOUT, context=contexto)
    else:
        servidor = smtplib.SMTP(cfg["servidor"], cfg["puerto"], timeout=TIMEOUT)
    with servidor:
        if cfg["seguridad"] == "starttls":
            servidor.starttls(context=contexto)
        if cfg["usuario"]:
            servidor.login(cfg["usuario"], clave)
        servidor.send_message(mensaje)


enviar_smtp = _enviar


def _motivo(e: Exception) -> str:
    """Texto corto y sin secretos para guardar y mostrar. El detalle completo va al log."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "El servidor rechazó el usuario o la clave."
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "El servidor rechazó el destinatario."
    if isinstance(e, ssl.SSLError):
        return "No se pudo establecer la conexión segura (certificado o TLS)."
    if isinstance(e, (smtplib.SMTPException, OSError)):
        return f"No se pudo conectar o enviar ({type(e).__name__})."
    return "Error inesperado al enviar."


async def _despachar(conn: asyncpg.Connection, cfg, mensaje: EmailMessage) -> Optional[str]:
    """Envia en un hilo y anota el resultado en la configuracion. Devuelve el motivo del error o None."""
    try:
        await asyncio.to_thread(enviar_smtp, cfg, _clave(cfg), mensaje)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[CORREO] Error enviando con {cfg['servidor']}:{cfg['puerto']}: {type(e).__name__}: {str(e)[:200]}")
        motivo = _motivo(e)
        await conn.execute("UPDATE correo_config SET ultimo_error = $2 WHERE razon_social_id = $1", cfg["razon_social_id"], motivo[:300])
        return motivo
    await conn.execute("UPDATE correo_config SET ultimo_ok = now(), ultimo_error = NULL WHERE razon_social_id = $1", cfg["razon_social_id"])
    return None


def _base(cfg, destinatario: str, asunto: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = formataddr((cfg["nombre_remitente"], cfg["remitente"])) if cfg["nombre_remitente"] else cfg["remitente"]
    m["To"] = destinatario
    m["Subject"] = asunto
    m["Message-ID"] = make_msgid(domain="jzbill")
    return m


# --- Mensaje del comprobante ---
async def mensaje_comprobante(conn: asyncpg.Connection, cfg, c, destinatario: str) -> EmailMessage:
    rs = await conn.fetchrow("SELECT * FROM razones_sociales WHERE id = $1", c["razon_social_id"])
    lineas = await conn.fetch("SELECT * FROM comprobante_lineas WHERE comprobante_id = $1 ORDER BY orden", c["id"])
    version = c["parametros_version_id"]
    doc = await _descripcion(conn, version, "TiposDoc", c["receptor_doc_tipo"])
    condicion = await _descripcion(conn, version, "CondicionIvaReceptor", c["condicion_iva_receptor"])
    e = escape
    numero = f"{c['punto_venta']:05d}-{c['numero']:08d}"
    emisor = rs["nombre_fantasia"] or rs["nombre_legal"]
    titulo = f"{c['nombre']} {numero}"
    asunto = f"{titulo} de {emisor}"
    m = _base(cfg, destinatario, asunto)

    receptor = c["receptor_nombre"] or "Consumidor final"
    if c["receptor_doc_nro"]:
        receptor += f" ({doc} {c['receptor_doc_nro']})"
    prueba = c["modo"] == "prueba"
    texto = [f"{titulo}", f"Emisor: {rs['nombre_legal']}, CUIT {formatear_cuit(rs['cuit'])}", f"Fecha: {_fecha(c['fecha'])}",
             f"Receptor: {receptor}. Condición frente al IVA: {condicion}.", "", "Detalle:"]
    texto += [f"  {_cantidad(l['cantidad'])} x {l['descripcion']} a {_importe(l['precio_unitario'])} = {_importe(l['importe'])}" for l in lineas]
    texto += ["", f"Total: {c['moneda']} {_importe(c['importe_total'])}", f"Condiciones de venta: {c['condicion_venta']}."]
    if c["cae"]:
        texto += [f"CAE {c['cae']}, vencimiento {_fecha(c['cae_vencimiento'])}."]
    if prueba:
        texto += ["Homologación ARCA, sin validez fiscal."]
    m.set_content("\n".join(texto))

    filas = "".join(f"<tr><td>{e(l['descripcion'])}</td><td align=\"right\">{e(_cantidad(l['cantidad']))}</td>"
                    f"<td align=\"right\">{e(_importe(l['precio_unitario']))}</td><td align=\"right\">{e(_importe(l['importe']))}</td></tr>" for l in lineas)
    qr_cid = None
    png = None
    if c["cae"]:
        qr = segno.make(texto_qr(rs["cuit"], c["fecha"], c["punto_venta"], c["codigo_arca"], c["numero"], c["importe_total"], c["moneda"],
                                 c["cotizacion"], c["receptor_doc_tipo"], c["receptor_doc_nro"], c["cae"]), error="m")
        png = BytesIO()
        qr.save(png, kind="png", scale=4, border=2)
        qr_cid = make_msgid(domain="jzbill")
    autorizacion = (f"<p><strong>C.A.E. N° {e(c['cae'])}</strong> &middot; Fecha Vto.: {_fecha(c['cae_vencimiento'])}</p>"
                    f"<p><img src=\"cid:{qr_cid[1:-1]}\" alt=\"Código QR de ARCA\" width=\"140\" height=\"140\"></p>") if c["cae"] else \
        "<p>Documento no válido como factura.</p>"
    leyenda = "<p style=\"color:#777\">Homologación ARCA, sin validez fiscal.</p>" if prueba else ""
    html = f"""<!doctype html><html lang="es"><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:680px">
<h2 style="margin-bottom:0">{e(titulo)}</h2>
<p style="margin-top:4px">{e(rs['nombre_legal'])} &middot; CUIT {e(formatear_cuit(rs['cuit']))} &middot; {e(CONDICIONES_EMISOR.get(rs['condicion_iva'], rs['condicion_iva']))}<br>
{e(c['emisor_domicilio'] or rs['domicilio'])}</p>
<p>Fecha de emisión: {_fecha(c['fecha'])}<br>Receptor: {e(receptor)}<br>Condición frente al IVA: {e(condicion)}<br>Condiciones de venta: {e(c['condicion_venta'])}</p>
<table cellpadding="6" cellspacing="0" border="0" style="border-collapse:collapse;width:100%">
<thead><tr style="background:#eee"><th align="left">Descripción</th><th align="right">Cantidad</th><th align="right">Precio unitario</th><th align="right">Importe</th></tr></thead>
<tbody>{filas}</tbody></table>
<p style="font-size:1.2em"><strong>Total: {e(c['moneda'])} {e(_importe(c['importe_total']))}</strong></p>
{autorizacion}{leyenda}
<p style="color:#777;font-size:0.9em">Enviado por {e(emisor)} con JZBill.</p>
</body></html>"""
    m.add_alternative(html, subtype="html")
    if qr_cid:
        m.get_payload()[1].add_related(png.getvalue(), maintype="image", subtype="png", cid=qr_cid)
    return m


async def _registrar_envio(conn: asyncpg.Connection, comprobante_id, destinatario: str, error: Optional[str], automatico: bool, usuario_id) -> dict:
    fila = await conn.fetchrow("""
        INSERT INTO comprobante_envios (comprobante_id, destinatario, estado, detalle, automatico, usuario_id)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING *
    """, comprobante_id, destinatario, "error" if error else "enviado", error or "", automatico, usuario_id)
    return envio_salida(fila)


def envio_salida(f) -> dict:
    return {"destinatario": f["destinatario"], "estado": f["estado"], "detalle": f["detalle"], "automatico": f["automatico"],
            "creado_en": f["creado_en"].isoformat()}


async def enviar_automatico(conn: asyncpg.Connection, c, usuario_id) -> None:
    """Despues de emitir: si la razon social tiene envio automatico y el comprobante lleva un cliente con email.
    Nunca levanta: el comprobante ya esta emitido."""
    try:
        cfg = await _config(conn, c["razon_social_id"])
        if cfg is None or not cfg["envio_automatico"] or not c["cliente_id"]:
            return
        email = await conn.fetchval("SELECT email FROM clientes WHERE id = $1", c["cliente_id"])
        if not email or not _EMAIL.match(email):
            return
        mensaje = await mensaje_comprobante(conn, cfg, c, email)
        error = await _despachar(conn, cfg, mensaje)
        await _registrar_envio(conn, c["id"], email, error, True, usuario_id)
    except Exception as e:   # noqa: BLE001  (la emision ya esta hecha; el error queda en el log)
        logger.warning(f"[CORREO] Envío automático del comprobante {c['id']} no realizado: {type(e).__name__}")


# --- Configuracion ---
def _exigir_admin(ctx: dict) -> None:
    if not es_admin(ctx["usuario"]):
        raise HTTPException(403, "No tiene permiso para esta acción.")


@router.get("")
async def ver(ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    _exigir_admin(ctx)
    return _salida(await _config(conn, uuid_o_404(ctx["razon_social_id"])))


@router.put("")
async def guardar(data: CorreoDatos, request: Request, ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    _exigir_admin(ctx)
    rs_id, u = uuid_o_404(ctx["razon_social_id"]), ctx["usuario"]
    servidor = data.servidor.strip().lower()
    if not re.match(r"^[a-z0-9.-]+$", servidor):
        raise HTTPException(400, "El servidor tiene que ser un nombre de host o una IP, sin http:// ni puerto.")
    remitente = _email_valido(data.remitente)
    actual = await _config(conn, rs_id)
    if data.clave:
        try:
            clave_cifrada = cifrado.cifrar(data.clave.encode("utf-8"), _proposito(rs_id))
        except cifrado.SecretosNoDisponibles:
            raise HTTPException(503, "No se puede guardar la clave: falta la clave maestra del servidor.")
    else:
        clave_cifrada = actual["clave_cifrada"] if actual is not None else None
    if data.usuario.strip() and clave_cifrada is None:
        raise HTTPException(400, "Falta la clave del usuario SMTP.")
    async with conn.transaction():
        fila = await conn.fetchrow("""
            INSERT INTO correo_config (razon_social_id, servidor, puerto, seguridad, usuario, clave_cifrada, remitente, nombre_remitente,
                                       envio_automatico, actualizado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (razon_social_id) DO UPDATE SET servidor = $2, puerto = $3, seguridad = $4, usuario = $5, clave_cifrada = $6,
                remitente = $7, nombre_remitente = $8, envio_automatico = $9, actualizado_por = $10, actualizado_en = now(),
                ultimo_ok = NULL, ultimo_error = NULL
            RETURNING *
        """, rs_id, servidor, data.puerto, data.seguridad, data.usuario.strip(), clave_cifrada, remitente, data.nombre_remitente.strip(),
            data.envio_automatico, u["id"])
        await registrar(conn, u["id"], u["usuario"], "CORREO_CONFIG",
                        f"SMTP {servidor}:{data.puerto} ({data.seguridad}), remitente {remitente}, automático {'sí' if data.envio_automatico else 'no'}.",
                        client_ip(request), rs_id)
    return _salida(fila)


@router.post("/prueba")
async def prueba(data: Destinatario, request: Request, ctx: dict = Depends(contexto_requerido), conn: asyncpg.Connection = Depends(get_conn)):
    _exigir_admin(ctx)
    rs_id, u = uuid_o_404(ctx["razon_social_id"]), ctx["usuario"]
    cfg = await _config(conn, rs_id)
    if cfg is None:
        raise HTTPException(409, "Primero guardá la configuración del correo.")
    destinatario = _email_valido(data.destinatario)
    m = _base(cfg, destinatario, "Prueba de correo de JZBill")
    m.set_content(f"Prueba de envío de {ctx['nombre_fantasia'] or ctx['nombre_legal']} desde JZBill, "
                  f"{datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}. Si llegó, el correo está bien configurado.")
    error = await _despachar(conn, cfg, m)
    await registrar(conn, u["id"], u["usuario"], "CORREO_PRUEBA", f"A {destinatario}: {error or 'enviado'}.", client_ip(request), rs_id)
    if error:
        raise HTTPException(502, f"No se pudo enviar: {error}")
    return _salida(await _config(conn, rs_id))


# --- Envio de un comprobante a pedido ---
@router_envios.post("/{comprobante_id}/enviar")
async def enviar_comprobante(comprobante_id: str, data: Destinatario, request: Request, ctx: dict = Depends(contexto_requerido),
                             conn: asyncpg.Connection = Depends(get_conn)):
    from jzbill.comprobantes import comprobante_visible   # import tardio: comprobantes importa este modulo

    if ctx["usuario"]["rol"] not in ENVIAN:
        raise HTTPException(403, "No tiene permiso para esta acción.")
    c = await comprobante_visible(conn, ctx, comprobante_id)
    cfg = await _config(conn, c["razon_social_id"])
    if cfg is None:
        raise HTTPException(409, "Esta razón social no tiene el correo configurado (Configuración, Correo).")
    destinatario = _email_valido(data.destinatario)
    u = ctx["usuario"]
    mensaje = await mensaje_comprobante(conn, cfg, c, destinatario)
    error = await _despachar(conn, cfg, mensaje)
    envio = await _registrar_envio(conn, c["id"], destinatario, error, False, u["id"])
    await registrar(conn, u["id"], u["usuario"], "COMPROBANTE_ENVIADO",
                    f"{c['nombre']} {c['punto_venta']:05d}-{c['numero']:08d} a {destinatario}: {error or 'enviado'}.", client_ip(request),
                    c["razon_social_id"])
    if error:
        raise HTTPException(502, f"No se pudo enviar: {error}")
    return envio
