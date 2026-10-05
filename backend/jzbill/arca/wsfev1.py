"""WSFEv1 (factura electronica, RG 4291). Nombres de operaciones y campos segun el WSDL real de homologacion y el
manual v4.7 (2026-09-01). Namespace http://ar.gov.afip.dif.FEV1/, SOAPAction = namespace + operacion.

Los errores de negocio llegan en <Errors><Err><Code/><Msg/></Err></Errors>; los eventos en <Events>."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from jzbill.arca import soap

NS = "http://ar.gov.afip.dif.FEV1/"

# Parametros que se guardan como datos fiscales con version: operacion FEParamGet* -> etiqueta de cada item.
# (FEParamGetPtosVenta y FEParamGetCotizacion no: dependen del CUIT o del dia.)
PARAMETROS = {
    "TiposCbte": "CbteTipo",
    "TiposConcepto": "ConceptoTipo",
    "TiposDoc": "DocTipo",
    "TiposIva": "IvaTipo",
    "TiposMonedas": "Moneda",
    "TiposOpcional": "OpcionalTipo",
    "TiposTributos": "TributoTipo",
    "CondicionIvaReceptor": "CondicionIvaReceptor",
}


class ErrorNegocio(soap.ErrorArca):
    """ARCA respondio con <Errors> (por ejemplo 600: token y firma no corresponden)."""

    def __init__(self, errores: list):
        self.errores = errores
        primero = errores[0] if errores else {"codigo": "?", "mensaje": ""}
        super().__init__(f"wsfe.{primero['codigo']}", primero["mensaje"])


@dataclass
class Credenciales:
    token: str
    sign: str
    cuit: str


def _q(nombre: str) -> str:
    return f"{{{NS}}}{nombre}"


def _operacion(nombre: str, credenciales: Optional[Credenciales]) -> ET.Element:
    cuerpo = ET.Element(_q(nombre))
    if credenciales is not None:
        auth = ET.SubElement(cuerpo, _q("Auth"))
        ET.SubElement(auth, _q("Token")).text = credenciales.token
        ET.SubElement(auth, _q("Sign")).text = credenciales.sign
        ET.SubElement(auth, _q("Cuit")).text = credenciales.cuit
    return cuerpo


def _texto(elemento: ET.Element, nombre: str) -> str:
    return (elemento.findtext(_q(nombre)) or "").strip()


def _lista(elemento: Optional[ET.Element], contenedor: str, item: str) -> list:
    if elemento is None:
        return []
    bloque = elemento.find(_q(contenedor))
    if bloque is None:
        return []
    return [{"codigo": _texto(x, "Code"), "mensaje": _texto(x, "Msg")[:500]} for x in bloque.findall(_q(item))]


def _llamar(url: str, nombre: str, cuerpo: ET.Element) -> ET.Element:
    respuesta = soap.llamar(url, NS + nombre, cuerpo)
    resultado = respuesta.find(_q(nombre + "Result"))
    if resultado is None:
        raise soap.ErrorRed("wsfe.sin_resultado", f"{nombre} sin resultado.")
    return resultado


def errores_y_eventos(resultado: ET.Element) -> tuple:
    return _lista(resultado, "Errors", "Err"), _lista(resultado, "Events", "Evt")


def dummy(url: str) -> dict:
    """Estado de los servidores de ARCA (no pide autenticacion)."""
    resultado = _llamar(url, "FEDummy", _operacion("FEDummy", None))
    return {"aplicacion": _texto(resultado, "AppServer"), "base": _texto(resultado, "DbServer"),
            "autenticacion": _texto(resultado, "AuthServer")}


def parametro(url: str, credenciales: Credenciales, tipo: str) -> list:
    """Items de un FEParamGet*: lista de dicts con los campos simples de cada item (Id, Desc, FchDesde, ...)."""
    if tipo not in PARAMETROS:
        raise ValueError("Parámetro desconocido.")
    nombre = "FEParamGet" + tipo
    resultado = _llamar(url, nombre, _operacion(nombre, credenciales))
    errores, _ = errores_y_eventos(resultado)
    if errores:
        raise ErrorNegocio(errores)
    bloque = resultado.find(_q("ResultGet"))
    items = []
    for item in ([] if bloque is None else bloque.findall(_q(PARAMETROS[tipo]))):
        items.append({hijo.tag.rsplit("}", 1)[-1]: (hijo.text or "").strip() for hijo in item if len(hijo) == 0})
    return items


def ultimo_autorizado(url: str, credenciales: Credenciales, punto_venta: int, tipo_comprobante: int) -> int:
    cuerpo = _operacion("FECompUltimoAutorizado", credenciales)
    ET.SubElement(cuerpo, _q("PtoVta")).text = str(int(punto_venta))
    ET.SubElement(cuerpo, _q("CbteTipo")).text = str(int(tipo_comprobante))
    resultado = _llamar(url, "FECompUltimoAutorizado", cuerpo)
    errores, _ = errores_y_eventos(resultado)
    if errores:
        raise ErrorNegocio(errores)
    try:
        return int(_texto(resultado, "CbteNro"))
    except ValueError:
        raise soap.ErrorRed("wsfe.respuesta_invalida", "Número de comprobante inválido en la respuesta.")
