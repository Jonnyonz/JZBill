"""Certificados de ARCA (WSAA) por razon social y modo. Solo administrador.

El certificado y la clave privada se guardan CIFRADOS (cifrado.py) y la API nunca los devuelve: solo los
datos para reconocerlos (sujeto, emisor, vencimiento, huella). Al cargar uno nuevo para la misma razon social
y modo, el anterior queda inactivo (historial). El modo prueba y el modo empresa nunca se listan juntos.
Nada del contenido (PEM) va al log."""

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jzbill import cifrado
from jzbill.auth import client_ip, registrar
from jzbill.db import get_conn
from jzbill.permisos import razon_social_visible, require_admin, uuid_o_404

router = APIRouter(prefix="/api/razones-sociales/{razon_social_id}/certificados", tags=["Certificados"])

Modo = Literal["empresa", "prueba"]
_MAX_PEM = 16000


class CertificadoNuevo(BaseModel):
    modo: Modo
    alias: str = Field(default="", max_length=120)
    certificado_pem: str = Field(max_length=_MAX_PEM)
    clave_pem: str = Field(max_length=_MAX_PEM)


def _sin_acentos(texto: str) -> str:
    """Solo ASCII para el campo O del CSR (ARCA no lo usa, pero asi ningun formulario se traba con tildes o enies)."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").strip()


def _proposito(cert_id: uuid.UUID, parte: str) -> str:
    return f"certificado:{cert_id}:{parte}"


def _validar(certificado_pem: str, clave_pem: str,
            no_corresponde: str = "La clave privada no corresponde al certificado.") -> dict:
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
        raise HTTPException(400, no_corresponde)
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


async def _guardar(conn: asyncpg.Connection, rs, modo: str, alias: str, certificado_pem: str, clave_pem: str,
                  admin: dict, ip: str, pedido_id=None) -> asyncpg.Record:
    """Valida el par, lo guarda cifrado como certificado activo del modo (el anterior queda inactivo)."""
    datos = _validar(certificado_pem, clave_pem, "Ese certificado no corresponde a este pedido: cargá el que ARCA "
                     "devolvió para este CSR.") if pedido_id else _validar(certificado_pem, clave_pem)
    cert_id = uuid.uuid4()
    try:
        certificado_cifrado = cifrado.cifrar(certificado_pem.encode("ascii"), _proposito(cert_id, "certificado"))
        clave_cifrada = cifrado.cifrar(clave_pem.encode("ascii"), _proposito(cert_id, "clave"))
    except cifrado.SecretosNoDisponibles:
        raise HTTPException(503, "No se puede guardar el certificado: falta la clave maestra del servidor.")
    async with conn.transaction():
        await conn.execute(
            "UPDATE certificados SET activo = false WHERE razon_social_id = $1 AND modo = $2 AND activo",
            rs["id"], modo)
        fila = await conn.fetchrow("""
            INSERT INTO certificados (id, razon_social_id, modo, alias, certificado_cifrado, clave_cifrada, sujeto,
                                      emisor, numero_serie, huella, valido_desde, valido_hasta, cargado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id, modo, alias, sujeto, emisor, numero_serie, huella, valido_desde, valido_hasta, activo,
                      creado_en
        """, cert_id, rs["id"], modo, alias, certificado_cifrado, clave_cifrada, datos["sujeto"],
            datos["emisor"], datos["numero_serie"], datos["huella"], datos["valido_desde"], datos["valido_hasta"],
            admin["id"])
        if pedido_id is not None:
            await conn.execute("UPDATE certificado_pedidos SET usado_en = now(), certificado_id = $2 WHERE id = $1",
                               pedido_id, cert_id)
        await registrar(conn, admin["id"], admin["usuario"], "CERTIFICADO_CARGA",
                        f"Modo {modo}, huella {datos['huella'][:16]}, vence {datos['valido_hasta']:%Y-%m-%d}"
                        + (", desde un pedido generado en el servidor." if pedido_id else "."), ip, rs["id"])
    return fila


@router.post("", status_code=201)
async def cargar(razon_social_id: str, data: CertificadoNuevo, request: Request, admin: dict = Depends(require_admin),
                 conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    fila = await _guardar(conn, rs, data.modo, data.alias.strip(), data.certificado_pem.strip(),
                          data.clave_pem.strip(), admin, client_ip(request))
    return _salida(fila)


# --- Pedidos de certificado (CSR) generados en el servidor ---
# La clave privada se crea aca, queda cifrada y nunca se devuelve. El CSR es publico: se pega en WSASS
# (homologacion) o en el Administrador de Certificados Digitales de ARCA (produccion). Formato del sujeto segun la
# especificacion tecnica del WSAA: C=AR, O=<organizacion>, CN=<alias>, serialNumber=CUIT <cuit>.

_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")


class PedidoNuevo(BaseModel):
    modo: Modo
    alias: str = Field(max_length=50)


class CertificadoDelPedido(BaseModel):
    certificado_pem: str = Field(max_length=_MAX_PEM)


def _pedido_salida(fila, con_csr: bool = False) -> dict:
    salida = {"id": str(fila["id"]), "modo": fila["modo"], "alias": fila["alias"],
              "creado_en": fila["creado_en"].isoformat(),
              "usado_en": fila["usado_en"].isoformat() if fila["usado_en"] else None}
    if con_csr:
        salida["csr_pem"] = fila["csr_pem"]
    return salida


async def _pedido_o_404(conn: asyncpg.Connection, rs, pedido_id: str) -> asyncpg.Record:
    fila = await conn.fetchrow("SELECT * FROM certificado_pedidos WHERE id = $1 AND razon_social_id = $2",
                               uuid_o_404(pedido_id), rs["id"])
    if fila is None:
        raise HTTPException(404, "No encontrado.")
    return fila


@router.post("/pedidos", status_code=201)
async def crear_pedido(razon_social_id: str, data: PedidoNuevo, request: Request, admin: dict = Depends(require_admin),
                       conn: asyncpg.Connection = Depends(get_conn)):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    rs = await razon_social_visible(conn, admin, razon_social_id)
    alias = data.alias.strip()
    if not _ALIAS.match(alias):
        raise HTTPException(400, "Alias inválido: letras, números, guion o guion bajo (hasta 50).")
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, _sin_acentos(rs["nombre_legal"])[:64] or "JZBill"),
        x509.NameAttribute(NameOID.COMMON_NAME, alias),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CUIT {rs['cuit']}"),
    ])
    csr = x509.CertificateSigningRequestBuilder().subject_name(sujeto).sign(clave, hashes.SHA256())
    pedido_id = uuid.uuid4()
    clave_pem = clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    try:
        clave_cifrada = cifrado.cifrar(clave_pem, f"pedido:{pedido_id}:clave")
    except cifrado.SecretosNoDisponibles:
        raise HTTPException(503, "No se puede generar el pedido: falta la clave maestra del servidor.")
    async with conn.transaction():
        fila = await conn.fetchrow("""
            INSERT INTO certificado_pedidos (id, razon_social_id, modo, alias, clave_cifrada, csr_pem, creado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *
        """, pedido_id, rs["id"], data.modo, alias, clave_cifrada,
            csr.public_bytes(serialization.Encoding.PEM).decode("ascii"), admin["id"])
        await registrar(conn, admin["id"], admin["usuario"], "CERTIFICADO_PEDIDO",
                        f"Pedido de certificado (CSR) {alias}, modo {data.modo}.", client_ip(request), rs["id"])
    return _pedido_salida(fila, con_csr=True)


@router.get("/pedidos")
async def listar_pedidos(razon_social_id: str, modo: Modo = Query(...), admin: dict = Depends(require_admin),
                         conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    filas = await conn.fetch("""
        SELECT * FROM certificado_pedidos WHERE razon_social_id = $1 AND modo = $2 ORDER BY creado_en DESC
    """, rs["id"], modo)
    return [_pedido_salida(f) for f in filas]


@router.get("/pedidos/{pedido_id}")
async def ver_pedido(razon_social_id: str, pedido_id: str, admin: dict = Depends(require_admin),
                     conn: asyncpg.Connection = Depends(get_conn)):
    rs = await razon_social_visible(conn, admin, razon_social_id)
    return _pedido_salida(await _pedido_o_404(conn, rs, pedido_id), con_csr=True)


@router.post("/pedidos/{pedido_id}/certificado", status_code=201)
async def cargar_certificado_del_pedido(razon_social_id: str, pedido_id: str, data: CertificadoDelPedido,
                                        request: Request, admin: dict = Depends(require_admin),
                                        conn: asyncpg.Connection = Depends(get_conn)):
    """Certificado que devolvio ARCA para un pedido: tiene que corresponder a la clave generada en el servidor."""
    rs = await razon_social_visible(conn, admin, razon_social_id)
    pedido = await _pedido_o_404(conn, rs, pedido_id)
    if pedido["usado_en"] is not None:
        raise HTTPException(409, "Ese pedido ya se usó.")
    try:
        clave_pem = cifrado.descifrar(pedido["clave_cifrada"], f"pedido:{pedido['id']}:clave").decode("ascii")
    except cifrado.SecretosNoDisponibles:
        raise HTTPException(503, "No se puede cargar el certificado: falta la clave maestra del servidor.")
    except cifrado.SecretoInvalido:
        raise HTTPException(409, "No se pudo leer la clave del pedido (¿cambió la clave maestra?). Generá otro pedido.")
    fila = await _guardar(conn, rs, pedido["modo"], pedido["alias"], data.certificado_pem.strip(), clave_pem, admin,
                          client_ip(request), pedido["id"])
    return _salida(fila)
