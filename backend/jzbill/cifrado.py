"""Cifrado en reposo de secretos que hay que poder recuperar (certificados y claves privadas de ARCA, clave
SMTP): AES-256-GCM con la clave maestra de SECRETS_KEY_FILE, que vive FUERA de la base (un volcado de la base
solo no expone nada). Los tokens que solo se comparan no van aca: se guardan hasheados.

Formato guardado: version (1 byte) + nonce (12 bytes) + texto cifrado con su etiqueta. El "proposito" (por
ejemplo "certificado:<id>:clave") va como dato autenticado: un valor cifrado copiado a otra fila o a otro
campo no se puede descifrar ahi.

cryptography se importa recien al usar un secreto, para no sumar memoria al arranque."""

import base64
import hashlib
import logging
import os
import secrets
import stat
from pathlib import Path
from typing import Optional

from jzbill import config

logger = logging.getLogger(__name__)

VERSION = b"\x01"
_LARGO_NONCE = 12
_clave: Optional[bytes] = None


class SecretosNoDisponibles(Exception):
    """No se puede usar la clave maestra (falta, no se puede leer o es invalida). El detalle va al log."""


class SecretoInvalido(Exception):
    """El valor guardado no se pudo descifrar: alterado, de otro proposito o de otra clave."""


def _cargar_clave() -> bytes:
    global _clave
    if _clave is not None:
        return _clave
    ruta = config.SECRETS_KEY_FILE
    if not ruta:
        logger.error("[CIFRADO] SECRETS_KEY_FILE no esta configurado.")
        raise SecretosNoDisponibles()
    try:
        archivo = Path(ruta)
        if os.name == "posix" and archivo.stat().st_mode & stat.S_IROTH:
            logger.error(f"[CIFRADO] {ruta} es legible por cualquier usuario: se rechaza (permisos 0640 o menos).")
            raise SecretosNoDisponibles()
        clave = base64.b64decode(archivo.read_text(encoding="ascii").strip(), validate=True)
    except SecretosNoDisponibles:
        raise
    except (OSError, ValueError) as e:
        logger.error(f"[CIFRADO] No se pudo leer la clave maestra {ruta}: {type(e).__name__}")
        raise SecretosNoDisponibles()
    if len(clave) != 32:
        logger.error(f"[CIFRADO] La clave maestra {ruta} no tiene 32 bytes.")
        raise SecretosNoDisponibles()
    _clave = clave
    return clave


def _aesgcm():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(_cargar_clave())


def cifrar(dato: bytes, proposito: str) -> bytes:
    nonce = secrets.token_bytes(_LARGO_NONCE)
    return VERSION + nonce + _aesgcm().encrypt(nonce, dato, proposito.encode("utf-8"))


def descifrar(guardado: bytes, proposito: str) -> bytes:
    from cryptography.exceptions import InvalidTag

    guardado = bytes(guardado)
    if len(guardado) < 1 + _LARGO_NONCE + 16 or guardado[:1] != VERSION:
        raise SecretoInvalido()
    nonce, cifrado = guardado[1:1 + _LARGO_NONCE], guardado[1 + _LARGO_NONCE:]
    try:
        return _aesgcm().decrypt(nonce, cifrado, proposito.encode("utf-8"))
    except InvalidTag:
        raise SecretoInvalido()


def huella(dato: bytes) -> str:
    """Identificador publico de un secreto (para mostrar o comparar sin exponerlo): SHA-256 abreviado."""
    return hashlib.sha256(dato).hexdigest()[:16]


def olvidar_clave() -> None:
    """Solo para tests: fuerza a releer SECRETS_KEY_FILE."""
    global _clave
    _clave = None
