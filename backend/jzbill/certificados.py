"""Certificados de ARCA (WSAA) por razon social y modo. Solo administrador.

El certificado y la clave privada se guardan CIFRADOS (cifrado.py) y la API nunca los devuelve: solo los
datos para reconocerlos (sujeto, emisor, vencimiento, huella). Al cargar uno nuevo para la misma razon social
y modo, el anterior queda inactivo (historial). El modo prueba y el modo empresa nunca se listan juntos.
Nada del contenido (PEM) va al log."""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jzbill import cifrado
from jzbill.auth import client_ip, registrar
from jzbill.db import get_conn
from jzbill.permisos import razon_social_visible, require_admin

router = APIRouter(prefix="/api/razones-sociales/{razon_social_id}/certificados", tags=["Certificados"])

Modo = Literal["empresa", "prueba"]
_MAX_PEM = 16000


class CertificadoNuevo(BaseModel):
    modo: Modo
    alias: str = Field(default="", max_length=120)
    certificado_pem: str = Field(max_length=_MAX_PEM)
    clave_pem: str = Field(max_length=_MAX_PEM)


def _proposito(cert_id: uuid.UUID, parte: str) -> str:
    return f"certificado:{cert_id}:{parte}"


def _validar(certificado_pem: str, clave_pem: str) -> dict:
    """Datos para mostrar del certificado si el par certificado/clave es valido; si no, 400 generico."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    try:
        cert = x509.load_pem_x509_certificate(certificado_pem.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise HTTPException(400, "El certificado no es válido (se espera formato PEM).")
    try:
        clave = serialization.load_pem_private_key(clave_pem.encode("ascii"), password=None)
    except TypeError:
        raise HTTPException(400, "La clave privada no puede tener contraseña.")
    except (ValueError, UnicodeEncodeError):
        raise HTTPException(400, "La clave privada no es válida (se espera formato PEM).")
    publica = serialization.PublicFormat.SubjectPublicKeyInfo
    der = serialization.Encoding.DER
    if cert.public_key().public_bytes(der, publica) != clave.public_key().public_bytes(der, publica):
        raise HTTPException(400, "La clave privada no corresponde al certificado.")
    if cert.not_valid_after_utc <= datetime.now(timezone.utc):
        raise HTTPException(400, "El certificado está vencido.")
    return {
        "sujeto": cert.subject.rfc4514_string()[:300],
        "emisor": cert.issuer.rfc4514_string()[:300],
        "numero_serie": format(cert.serial_number, "x")[:80],
        "huella": hashlib.sha256(cert.public_bytes(der)).hexdigest(),
        "valido_desde": cert.not_valid_before_utc,
        "valido_hasta": cert.not_valid_after_utc,
    }


def _salida(fila) -> dict:
    dias = (fila["valido_hasta"] - datetime.now(timezone.utc)).days
    return {"id": str(fila["id"]), "modo": fila["modo"], "alias": fila["alias"], "sujeto": fila["sujeto"],
            "emisor": fila["emisor"], "numero_serie": fila["numero_serie"], "huella": fila["huella"],
            "valido_desde": fila["valido_desde"].isoformat(), "valido_hasta": fila["valido_hasta"].isoformat(),
            "dias_para_vencer": dias, "activo": fila["activo"], "creado_en": fila["creado_en"].isoformat()}


@router.get("")
async def listar(razon_social_id: str, modo: Modo = Query(...), admin: dict = Depends(require_admin),
                 conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    filas = await conn.fetch("""
        SELECT id, modo, alias, sujeto, emisor, numero_serie, huella, valido_desde, valido_hasta, activo, creado_en
        FROM certificados WHERE razon_social_id = $1 AND modo = $2 ORDER BY creado_en DESC
    """, rs["id"], modo)
    return [_salida(f) for f in filas]


@router.post("", status_code=201)
async def cargar(razon_social_id: str, data: CertificadoNuevo, request: Request, admin: dict = Depends(require_admin),
                 conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    certificado_pem, clave_pem = data.certificado_pem.strip(), data.clave_pem.strip()
    datos = _validar(certificado_pem, clave_pem)
    cert_id = uuid.uuid4()
    try:
        certificado_cifrado = cifrado.cifrar(certificado_pem.encode("ascii"), _proposito(cert_id, "certificado"))
        clave_cifrada = cifrado.cifrar(clave_pem.encode("ascii"), _proposito(cert_id, "clave"))
    except cifrado.SecretosNoDisponibles:
        raise HTTPException(503, "No se puede guardar el certificado: falta la clave maestra del servidor.")
    async with conn.transaction():
        await conn.execute(
            "UPDATE certificados SET activo = false WHERE razon_social_id = $1 AND modo = $2 AND activo",
            rs["id"], data.modo)
        fila = await conn.fetchrow("""
            INSERT INTO certificados (id, razon_social_id, modo, alias, certificado_cifrado, clave_cifrada, sujeto,
                                      emisor, numero_serie, huella, valido_desde, valido_hasta, cargado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id, modo, alias, sujeto, emisor, numero_serie, huella, valido_desde, valido_hasta, activo,
                      creado_en
        """, cert_id, rs["id"], data.modo, data.alias.strip(), certificado_cifrado, clave_cifrada, datos["sujeto"],
            datos["emisor"], datos["numero_serie"], datos["huella"], datos["valido_desde"], datos["valido_hasta"],
            admin["id"])
        await registrar(conn, admin["id"], admin["usuario"], "CERTIFICADO_CARGA",
                        f"Modo {data.modo}, huella {datos['huella'][:16]}, vence {datos['valido_hasta']:%Y-%m-%d}.",
                        client_ip(request), rs["id"])
    return _salida(fila)
