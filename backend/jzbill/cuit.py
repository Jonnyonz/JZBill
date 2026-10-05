"""CUIT/CUIL: normalizacion y digito verificador (modulo 11). Se valida ANTES de cualquier consulta o
guardado. No se valida el prefijo (20, 23, 27, 30, ...): ARCA puede asignar otros, y la fuente de verdad
sobre si un CUIT existe es ARCA, no este modulo."""

import re
from typing import Optional

_PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_SEPARADORES = re.compile(r"[\s.\-]")


def digito_verificador(primeros_diez: str) -> Optional[int]:
    """Digito verificador para los 10 primeros digitos. None si el calculo da 10 (ese numero no puede ser
    un CUIT: ARCA cambia el prefijo en esos casos)."""
    suma = sum(int(d) * p for d, p in zip(primeros_diez, _PESOS))
    dv = 11 - (suma % 11)
    if dv == 11:
        return 0
    if dv == 10:
        return None
    return dv


def normalizar_cuit(valor: str) -> Optional[str]:
    """Los 11 digitos del CUIT si es valido (acepta guiones, puntos y espacios); None si no lo es."""
    if not isinstance(valor, str):
        return None
    numero = _SEPARADORES.sub("", valor)
    if len(numero) != 11 or not numero.isascii() or not numero.isdigit() or numero == "0" * 11:
        return None
    if digito_verificador(numero[:10]) != int(numero[10]):
        return None
    return numero


def formatear_cuit(numero: str) -> str:
    """11 digitos -> XX-XXXXXXXX-X (para mostrar)."""
    return f"{numero[:2]}-{numero[2:10]}-{numero[10]}"
