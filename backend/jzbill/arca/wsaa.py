"""WSAA (autenticacion y autorizacion): TRA firmado (CMS) -> Ticket de Acceso (token + sign).

Segun la especificacion tecnica 1.2.2 y el WSDL: pedido loginCms(in0 = CMS en Base64), SOAPAction vacio,
respuesta loginCmsReturn (XML loginTicketResponse). El CMS es SignedData con el TRA adentro (como
"openssl cms -sign -nodetach" del manual del desarrollador), firmado con SHA-256."""

import base64
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from jzbill.arca import soap

NS = "http://wsaa.view.sua.dvadac.desein.afip.gov"
_SERVICIO = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")
# Margen de las horas del TRA: ARCA acepta hasta 24 h; con minutos alcanza y tolera relojes algo corridos.
_MARGEN = timedelta(minutes=10)


@dataclass
class Ticket:
    token: str
    sign: str
    expira: datetime


def crear_tra(servicio: str, ahora: Optional[datetime] = None) -> bytes:
    if not _SERVICIO.match(servicio):
        raise ValueError("Servicio inválido.")
    ahora = (ahora or datetime.now(timezone.utc)).replace(microsecond=0)
    raiz = ET.Element("loginTicketRequest", {"version": "1.0"})
    cabecera = ET.SubElement(raiz, "header")
    ET.SubElement(cabecera, "uniqueId").text = str(int(ahora.timestamp()) & 0xFFFFFFFF)
    ET.SubElement(cabecera, "generationTime").text = (ahora - _MARGEN).isoformat()
    ET.SubElement(cabecera, "expirationTime").text = (ahora + _MARGEN).isoformat()
    ET.SubElement(raiz, "service").text = servicio
    return ET.tostring(raiz, encoding="utf-8", xml_declaration=True)


def firmar_tra(tra: bytes, certificado_pem: bytes, clave_pem: bytes) -> str:
    """CMS SignedData (contenido incluido) en DER y luego Base64."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7

    certificado = x509.load_pem_x509_certificate(certificado_pem)
    clave = serialization.load_pem_private_key(clave_pem, password=None)
    cms = (pkcs7.PKCS7SignatureBuilder().set_data(tra).add_signer(certificado, clave, hashes.SHA256())
           .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary]))
    return base64.b64encode(cms).decode("ascii")


def pedir_ticket(url: str, cms_base64: str) -> Ticket:
    cuerpo = ET.Element(f"{{{NS}}}loginCms")
    ET.SubElement(cuerpo, f"{{{NS}}}in0").text = cms_base64
    respuesta = soap.llamar(url, "", cuerpo)
    retorno = respuesta.findtext(f"{{{NS}}}loginCmsReturn") or respuesta.findtext("loginCmsReturn")
    if not retorno:
        raise soap.ErrorRed("wsaa.sin_ticket", "El WSAA no devolvió el ticket.")
    ticket = soap.parsear_xml(retorno.encode("utf-8"))
    token = (ticket.findtext("credentials/token") or "").strip()
    sign = (ticket.findtext("credentials/sign") or "").strip()
    vence = (ticket.findtext("header/expirationTime") or "").strip()
    try:
        expira = datetime.fromisoformat(vence)
    except ValueError:
        expira = None
    if not token or not sign or expira is None or expira.tzinfo is None:
        raise soap.ErrorRed("wsaa.ticket_invalido", "El ticket del WSAA está incompleto.")
    return Ticket(token=token, sign=sign, expira=expira)
