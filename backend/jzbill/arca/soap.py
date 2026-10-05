"""Transporte SOAP 1.1 minimo hacia ARCA.

- TLS con el contexto por defecto de Python (verifica certificado y nombre; no se debilita nada).
- Tiempo maximo por llamada (ARCA_TIMEOUT) y tamaño maximo de respuesta.
- XML: se rechaza cualquier respuesta con DTD o entidades (XXE / expansion de entidades). Los pedidos se arman
  con ElementTree, que escapa los textos: nunca se concatenan strings con datos.
- Al log va la operacion, el estado y la duracion; nunca el contenido (token, sign, CMS, certificados).

Las funciones son bloqueantes: desde la app se llaman con asyncio.to_thread."""

import logging
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

from jzbill import config

logger = logging.getLogger(__name__)

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
MAX_RESPUESTA = 5 * 1024 * 1024
_TLS = ssl.create_default_context()


class ErrorArca(Exception):
    """Error al hablar con ARCA. codigo y mensaje sirven para el log y para el administrador; no contienen secretos."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"{codigo}: {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


class ErrorRed(ErrorArca):
    """No se pudo conectar, se agoto el tiempo o la respuesta no es un SOAP valido."""


class ErrorSoap(ErrorArca):
    """ARCA respondio un SOAP Fault (por ejemplo los errores del WSAA: coe.*, cms.*, xml.*, wsaa.*)."""


def parsear_xml(datos: bytes) -> ET.Element:
    if b"<!DOCTYPE" in datos or b"<!ENTITY" in datos:
        raise ErrorRed("xml.dtd", "Respuesta con DTD rechazada.")
    try:
        return ET.fromstring(datos)
    except ET.ParseError:
        raise ErrorRed("xml.invalido", "Respuesta XML inválida.")


def sobre(cuerpo: ET.Element) -> bytes:
    envelope = ET.Element(f"{{{SOAP_ENV}}}Envelope")
    ET.SubElement(envelope, f"{{{SOAP_ENV}}}Body").append(cuerpo)
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def llamar(url: str, accion: str, cuerpo: ET.Element, timeout: Optional[int] = None) -> ET.Element:
    """POST SOAP 1.1 a url con SOAPAction = accion. Devuelve el primer elemento del Body."""
    pedido = urllib.request.Request(url, data=sobre(cuerpo), method="POST", headers={
        "Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{accion}"'})
    operacion = cuerpo.tag.rsplit("}", 1)[-1]
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(pedido, timeout=timeout or config.ARCA_TIMEOUT, context=_TLS) as r:
            datos, estado = r.read(MAX_RESPUESTA + 1), r.status
    except urllib.error.HTTPError as e:
        # Los SOAP Fault llegan con HTTP 500: se leen igual.
        datos, estado = e.read(MAX_RESPUESTA + 1), e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning(f"[ARCA] {operacion}: sin conexion ({type(e).__name__}) tras {time.monotonic() - inicio:.1f}s")
        raise ErrorRed("red", "No se pudo conectar con ARCA.")
    logger.info(f"[ARCA] {operacion}: HTTP {estado} en {time.monotonic() - inicio:.1f}s")
    if len(datos) > MAX_RESPUESTA:
        raise ErrorRed("respuesta.grande", "Respuesta de ARCA demasiado grande.")
    body = parsear_xml(datos).find(f"{{{SOAP_ENV}}}Body")
    if body is None or len(body) == 0:
        raise ErrorRed("soap.sin_body", "Respuesta de ARCA sin cuerpo SOAP.")
    primero = body[0]
    if primero.tag == f"{{{SOAP_ENV}}}Fault":
        codigo = (primero.findtext("faultcode") or "").strip().rsplit(":", 1)[-1] or "soap.fault"
        mensaje = (primero.findtext("faultstring") or "").strip()[:500]
        logger.warning(f"[ARCA] {operacion}: SOAP Fault {codigo}")
        raise ErrorSoap(codigo, mensaje)
    if estado != 200:
        raise ErrorRed(f"http.{estado}", "Respuesta inesperada de ARCA.")
    return primero
