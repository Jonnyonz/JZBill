"""Escritor de PDF minimo con la biblioteca estandar (sin fpdf2, reportlab ni Pillow: decision del cierre de la
Fase 7, sin biblioteca de PDF aprobada; lo que necesita un comprobante entra en estas lineas).

- Paginas A4 con texto en Helvetica y Helvetica-Bold (fuentes base del PDF, no se incrustan) en WinAnsiEncoding
  (cp1252: alcanza para el castellano; lo que no entra sale como "?").
- Texto alineado a izquierda, derecha o centro con las metricas AFM de Adobe (ancho por caracter), lineas,
  rectangulos y el QR como rectangulos (segno da la matriz: no hace falta codificar una imagen).
- Contenido comprimido con zlib (FlateDecode). Titulo y autor en UTF-16 para no perder acentos.

Las cadenas se escapan siempre (parentesis y barra invertida): un dato con ")" no rompe el contenido."""

import unicodedata
import zlib
from datetime import datetime, timezone
from typing import Iterable, List, Optional

A4 = (595.28, 841.89)

# Anchos (milesimas de em) de los caracteres 32..126 segun los AFM de Helvetica y Helvetica-Bold.
_ANCHOS = {
    False: [int(a) for a in (
        "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 "
        "278 278 584 584 584 556 1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 667 778 722 667 "
        "611 722 667 944 667 667 611 278 278 278 469 556 333 556 556 500 556 556 278 556 556 222 222 500 222 833 "
        "556 556 556 556 333 500 278 556 500 722 500 500 500 334 260 334 584").split()],
    True: [int(a) for a in (
        "278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 "
        "333 333 584 584 584 611 975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778 667 778 722 667 "
        "611 722 667 944 667 667 611 333 278 333 584 556 333 556 611 556 611 556 333 611 611 278 278 556 278 889 "
        "611 611 611 611 389 556 333 611 556 778 556 556 500 389 280 389 584").split()],
}
_ANCHOS_EXTRA = {"°": 400, "º": 365, "ª": 370, "€": 556, "·": 278, "–": 556, "—": 1000, "¿": 611, "¡": 333,
                 "“": 333, "”": 333, "‘": 222, "’": 222, "ß": 611, "æ": 889, "ø": 611}


def ancho(texto: str, tamano: float, negrita: bool = False) -> float:
    """Ancho del texto en puntos. Las letras acentuadas miden como su base (asi lo definen los AFM)."""
    tabla = _ANCHOS[negrita]
    total = 0
    for ch in texto:
        n = ord(ch)
        if 32 <= n <= 126:
            total += tabla[n - 32]
        elif ch in _ANCHOS_EXTRA:
            total += _ANCHOS_EXTRA[ch]
        else:
            base = unicodedata.normalize("NFD", ch)[0]
            total += tabla[ord(base) - 32] if 32 <= ord(base) <= 126 else 556
    return total * tamano / 1000


def partir(texto: str, ancho_max: float, tamano: float, negrita: bool = False) -> List[str]:
    """Corta el texto en lineas que entran en ancho_max (por palabras; una palabra mas larga se corta a la fuerza)."""
    lineas, actual = [], ""
    for palabra in texto.split():
        while ancho(palabra, tamano, negrita) > ancho_max:   # palabra mas ancha que la columna
            corte = max(1, int(len(palabra) * ancho_max / ancho(palabra, tamano, negrita)))
            if actual:
                lineas.append(actual)
                actual = ""
            lineas.append(palabra[:corte])
            palabra = palabra[corte:]
        candidata = f"{actual} {palabra}".strip()
        if actual and ancho(candidata, tamano, negrita) > ancho_max:
            lineas.append(actual)
            actual = palabra
        else:
            actual = candidata
    if actual or not lineas:
        lineas.append(actual)
    return lineas


def _cadena(texto: str) -> bytes:
    datos = texto.encode("cp1252", errors="replace")
    return b"(" + datos.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").replace(b"\r", b" ").replace(b"\n", b" ") + b")"


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))


class Pagina:
    def __init__(self):
        self.ops: List[bytes] = []

    def texto(self, x: float, y: float, texto: str, tamano: float = 10, negrita: bool = False, gris: float = 0) -> None:
        fuente = b"/F2" if negrita else b"/F1"
        self.ops.append(b"BT " + fuente + f" {_num(tamano)} Tf {_num(gris)} g 1 0 0 1 {_num(x)} {_num(y)} Tm ".encode()
                        + _cadena(texto) + b" Tj ET 0 g")

    def texto_derecha(self, x_derecha: float, y: float, texto: str, tamano: float = 10, negrita: bool = False, gris: float = 0) -> None:
        self.texto(x_derecha - ancho(texto, tamano, negrita), y, texto, tamano, negrita, gris)

    def texto_centrado(self, x_centro: float, y: float, texto: str, tamano: float = 10, negrita: bool = False, gris: float = 0) -> None:
        self.texto(x_centro - ancho(texto, tamano, negrita) / 2, y, texto, tamano, negrita, gris)

    def linea(self, x1: float, y1: float, x2: float, y2: float, grosor: float = 0.5, gris: float = 0) -> None:
        self.ops.append(f"{_num(grosor)} w {_num(gris)} G {_num(x1)} {_num(y1)} m {_num(x2)} {_num(y2)} l S 0 G".encode())

    def rectangulo(self, x: float, y: float, ancho_: float, alto: float, relleno: Optional[float] = None, borde: Optional[float] = None) -> None:
        """relleno y borde son niveles de gris (0 negro, 1 blanco); None omite esa parte."""
        if relleno is not None:
            self.ops.append(f"{_num(relleno)} g {_num(x)} {_num(y)} {_num(ancho_)} {_num(alto)} re f 0 g".encode())
        if borde is not None:
            self.ops.append(f"0.75 w {_num(borde)} G {_num(x)} {_num(y)} {_num(ancho_)} {_num(alto)} re S 0 G".encode())

    def qr(self, filas: Iterable[Iterable[int]], x: float, y_superior: float, lado: float) -> None:
        """Dibuja la matriz (filas de 0/1, de arriba hacia abajo, con el borde ya incluido) en un cuadrado de `lado`."""
        matriz = [list(f) for f in filas]
        if not matriz:
            return
        modulo = lado / len(matriz)
        partes = [b"0 g"]
        for i, fila in enumerate(matriz):
            y = y_superior - (i + 1) * modulo
            j = 0
            while j < len(fila):           # modulos oscuros consecutivos en un solo rectangulo
                if fila[j]:
                    inicio = j
                    while j < len(fila) and fila[j]:
                        j += 1
                    partes.append(f"{_num(x + inicio * modulo)} {_num(y)} {_num((j - inicio) * modulo)} {_num(modulo)} re".encode())
                else:
                    j += 1
        partes.append(b"f")
        self.ops.append(b" ".join(partes))


class Documento:
    def __init__(self, titulo: str, autor: str = "", productor: str = "JZBill"):
        self.titulo, self.autor, self.productor = titulo, autor, productor
        self.paginas: List[Pagina] = []

    def pagina(self) -> Pagina:
        p = Pagina()
        self.paginas.append(p)
        return p

    def bytes(self) -> bytes:
        def utf16(texto: str) -> bytes:
            return b"<" + (b"\xfe\xff" + texto.encode("utf-16-be")).hex().encode() + b">"

        fecha = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%S+00'00'")
        objetos: List[bytes] = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"",   # 2: Pages, se completa con los hijos
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            b"<< /Title " + utf16(self.titulo) + b" /Author " + utf16(self.autor) + b" /Producer " + utf16(self.productor)
            + b" /CreationDate " + _cadena(fecha) + b" >>",
        ]
        hijos = []
        for p in self.paginas or [Pagina()]:
            contenido = zlib.compress(b"\n".join(p.ops), 6)
            n_pagina = len(objetos) + 1
            objetos.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_num(A4[0])} {_num(A4[1])}] "
                           f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {n_pagina + 1} 0 R >>".encode())
            objetos.append(f"<< /Length {len(contenido)} /Filter /FlateDecode >>\nstream\n".encode() + contenido + b"\nendstream")
            hijos.append(f"{n_pagina} 0 R")
        objetos[1] = f"<< /Type /Pages /Kids [{' '.join(hijos)}] /Count {len(hijos)} >>".encode()

        salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        posiciones = []
        for i, cuerpo in enumerate(objetos, start=1):
            posiciones.append(len(salida))
            salida += f"{i} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
        xref = len(salida)
        salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
        for pos in posiciones:
            salida += f"{pos:010d} 00000 n \n".encode()
        salida += (f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
        return bytes(salida)
