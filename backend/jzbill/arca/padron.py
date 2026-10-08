"""Constancia de inscripcion de ARCA (ws_sr_constancia_inscripcion, ex padron A5): datos de un contribuyente por
CUIT para el alta rapida de clientes. Fuentes: manual v4.1 (marzo 2026) y WSDL real de homologacion y produccion
(referencias/arca/WSCI-constancia-inscripcion-manual-v4.1.txt, padron-A5-personaServiceA5-*.wsdl.xml).

SOAP 1.1, document/literal, soapAction vacio. elementFormDefault="unqualified": solo el elemento de la operacion
lleva el namespace; sus hijos y los de la respuesta van sin namespace.

El manual no publica una regla oficial para deducir la condicion frente al IVA a partir de los impuestos: aca solo se
devuelven los datos (impuestos inscriptos, monotributo) y una SUGERENCIA para los dos casos claros; el usuario
confirma la condicion antes de guardar."""

import xml.etree.ElementTree as ET
from typing import Optional

from jzbill.arca import soap
from jzbill.arca.wsfev1 import Credenciales

NS = "http://a5.soap.ws.server.puc.sr/"
SERVICIO = "ws_sr_constancia_inscripcion"
# Del propio manual v4.1 (ejemplos y anexo 5.3): 20 = Monotributo, 30 = IVA. Los demas codigos no estan publicados.
IMPUESTO_MONOTRIBUTO = "20"
IMPUESTO_IVA = "30"


def _t(elemento: Optional[ET.Element], nombre: str) -> str:
    return ((elemento.findtext(nombre) if elemento is not None else None) or "").strip()


def dummy(url: str) -> dict:
    cuerpo = ET.Element(f"{{{NS}}}dummy")
    r = soap.llamar(url, "", cuerpo).find("return")
    return {"aplicacion": _t(r, "appserver"), "base": _t(r, "dbserver"), "autenticacion": _t(r, "authserver")}


def _errores(bloque: Optional[ET.Element]) -> list:
    if bloque is None:
        return []
    return [e.text.strip()[:300] for e in bloque.findall("error") if e.text and e.text.strip()]


def consultar(url: str, credenciales: Credenciales, cuit: str) -> dict:
    """getPersona_v2(token, sign, cuitRepresentada, idPersona). Devuelve los datos para el alta del cliente; los
    errores de la constancia (por ejemplo, CUIT inexistente o constancia no emitible) vienen en 'errores'."""
    cuerpo = ET.Element(f"{{{NS}}}getPersona_v2")
    for nombre, valor in (("token", credenciales.token), ("sign", credenciales.sign),
                          ("cuitRepresentada", credenciales.cuit), ("idPersona", cuit)):
        ET.SubElement(cuerpo, nombre).text = str(valor)
    respuesta = soap.llamar(url, "", cuerpo)
    persona = respuesta.find("personaReturn")
    if persona is None:
        raise soap.ErrorRed("padron.sin_resultado", "La constancia de ARCA vino vacía.")
    generales = persona.find("datosGenerales")
    general = persona.find("datosRegimenGeneral")
    mono = persona.find("datosMonotributo")
    errores = (_errores(persona.find("errorConstancia")) + _errores(persona.find("errorRegimenGeneral"))
               + _errores(persona.find("errorMonotributo")))

    nombre = _t(generales, "razonSocial") or " ".join(p for p in (_t(generales, "apellido"), _t(generales, "nombre")) if p)
    dom = generales.find("domicilioFiscal") if generales is not None else None
    partes = [_t(dom, "direccion"), _t(dom, "localidad")]
    if _t(dom, "codPostal"):
        partes.append("CP " + _t(dom, "codPostal"))
    partes.append(_t(dom, "descripcionProvincia"))
    domicilio = ", ".join(p for p in partes if p)

    impuestos = [{"id": _t(i, "idImpuesto"), "descripcion": _t(i, "descripcionImpuesto"), "estado": _t(i, "estadoImpuesto")}
                 for i in (general.findall("impuesto") if general is not None else [])]
    categoria = _t(mono.find("categoriaMonotributo"), "descripcionCategoria") if mono is not None else ""
    es_mono = mono is not None and (bool(categoria) or any(_t(i, "idImpuesto") == IMPUESTO_MONOTRIBUTO
                                                           for i in mono.findall("impuesto")))
    sugerencia = None
    if es_mono:
        sugerencia = "monotributo"
    elif any(i["id"] == IMPUESTO_IVA and i["estado"] == "AC" for i in impuestos):
        sugerencia = "responsable_inscripto"
    actividad = ""
    for a in (general.findall("actividad") if general is not None else []):
        if _t(a, "orden") == "1":
            actividad = _t(a, "descripcionActividad")
    return {"cuit": cuit, "nombre": nombre[:200], "domicilio": domicilio[:300],
            "tipo_persona": _t(generales, "tipoPersona"), "estado_clave": _t(generales, "estadoClave"),
            "impuestos": impuestos, "monotributo": categoria or ("Sí" if es_mono else ""),
            "actividad": actividad[:250], "sugerencia": sugerencia, "errores": errores}
