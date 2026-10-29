"""Articulos (Fase 5): SKU global unico, costo de referencia y precios de venta con vigencia.

Ver: cualquier rol. Crear, modificar y poner precios: administrador y supervisor (el diseno asigna precios y ofertas
al supervisor). El precio es el final, con IVA incluido; la alicuota es un codigo de ARCA (FEParamGetTiposIva)
validado contra los parametros vigentes y guardado como dato. El costo nunca participa del comprobante."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jzbill.arca import parametros
from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.db import get_conn
from jzbill.permisos import require_rol, uuid_o_404

router = APIRouter(prefix="/api/articulos", tags=["Articulos"])

editor = require_rol("administrador", "supervisor")

# Monedas que se ofrecen para los precios (pedido de Jonny 2026-10-29): la lista completa de ARCA tiene mas de
# cincuenta. Los codigos son los de FEParamGetTiposMonedas; la descripcion se toma de ahi.
MONEDAS_OFRECIDAS = ("PES", "DOL", "060", "012")   # pesos, dolar estadounidense, euro, real


class ArticuloDatos(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    descripcion: str = Field(min_length=1, max_length=200)
    categoria: str = Field(default="", max_length=80)
    alicuota_iva: int = Field(ge=1, le=99)
    costo: Decimal = Field(default=Decimal("0"), ge=0, max_digits=15, decimal_places=2)


class ArticuloNuevo(ArticuloDatos):
    # Precio inicial opcional, vigente desde hoy.
    precio: Optional[Decimal] = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    moneda: str = Field(default="PES", min_length=3, max_length=3)


class ArticuloCambios(ArticuloDatos):
    activo: bool = True


class ArchivoCsv(BaseModel):
    # El navegador lee el archivo y lo manda como texto (sin dependencias de multipart). Tope: 2 MB.
    csv: str = Field(min_length=1, max_length=2 * 1024 * 1024)


class PrecioNuevo(BaseModel):
    importe: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    moneda: str = Field(default="PES", min_length=3, max_length=3)
    vigencia_desde: Optional[date] = None   # sin fecha: desde hoy


async def _vigentes(conn: asyncpg.Connection) -> Optional[dict]:
    for modo in ("empresa", "prueba"):
        v = await parametros.vigentes(conn, modo)
        if v is not None:
            return v
    return None


def _codigos(vigentes: Optional[dict], tipo: str) -> list:
    return [] if vigentes is None else vigentes["tipos"].get(tipo, [])


async def _validar(conn: asyncpg.Connection, data: ArticuloDatos, moneda: Optional[str] = None) -> str:
    """Devuelve el SKU normalizado. 400 si algo no corresponde a los parametros de ARCA."""
    vigentes = await _vigentes(conn)
    if vigentes is None:
        raise HTTPException(409, "Faltan los parámetros fiscales de ARCA: un administrador tiene que actualizarlos.")
    if not any(i["codigo"] == str(data.alicuota_iva) for i in _codigos(vigentes, "TiposIva")):
        raise HTTPException(400, "Alícuota de IVA desconocida para ARCA.")
    if moneda is not None and not any(i["codigo"] == moneda for i in _codigos(vigentes, "TiposMonedas")):
        raise HTTPException(400, "Moneda desconocida para ARCA.")
    # Mismas reglas que Tracker360, el dueno del SKU: hasta 100 caracteres, espacios internos permitidos.
    sku = " ".join(data.sku.split())
    if not sku:
        raise HTTPException(400, "Poné un SKU.")
    if not data.descripcion.strip():
        raise HTTPException(400, "Poné una descripción.")
    return sku


_SELECT = """
    SELECT a.*, p.importe AS precio, p.moneda AS precio_moneda, p.vigencia_desde AS precio_desde
    FROM articulos a
    LEFT JOIN LATERAL (
        SELECT importe, moneda, vigencia_desde FROM articulos_precios
        WHERE articulo_id = a.id AND moneda = 'PES' AND vigencia_desde <= CURRENT_DATE
        ORDER BY vigencia_desde DESC LIMIT 1
    ) p ON true
"""


def _salida(fila, precios=None) -> dict:
    d = {"id": str(fila["id"]), "sku": fila["sku"], "descripcion": fila["descripcion"], "categoria": fila["categoria"],
         "alicuota_iva": fila["alicuota_iva"], "costo": str(fila["costo"]), "activo": fila["activo"],
         "origen": fila["origen"],
         "precio": str(fila["precio"]) if fila["precio"] is not None else None,
         "precio_desde": fila["precio_desde"].isoformat() if fila["precio_desde"] else None}
    if precios is not None:
        d["precios"] = [{"id": str(p["id"]), "moneda": p["moneda"], "importe": str(p["importe"]),
                         "vigencia_desde": p["vigencia_desde"].isoformat(),
                         "vigente": p["moneda"] == "PES" and p["vigencia_desde"] == fila["precio_desde"]}
                        for p in precios]
    return d


async def _articulo_o_404(conn: asyncpg.Connection, articulo_id: str, con_precios: bool = False) -> dict:
    fila = await conn.fetchrow(_SELECT + " WHERE a.id = $1", uuid_o_404(articulo_id))
    if fila is None:
        raise HTTPException(404, "No encontrado.")
    precios = None
    if con_precios:
        precios = await conn.fetch("""
            SELECT id, moneda, importe, vigencia_desde FROM articulos_precios WHERE articulo_id = $1
            ORDER BY moneda, vigencia_desde DESC LIMIT 100
        """, fila["id"])
    return _salida(fila, precios)


@router.get("/opciones")
async def opciones(usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    """Alicuotas de IVA y monedas de ARCA para los formularios."""
    vigentes = await _vigentes(conn)
    simple = lambda tipo: [{"codigo": i["codigo"], "descripcion": i["descripcion"]} for i in _codigos(vigentes, tipo)]
    monedas = {m["codigo"]: m for m in simple("TiposMonedas")}
    return {"alicuotas": simple("TiposIva"), "monedas": [monedas[c] for c in MONEDAS_OFRECIDAS if c in monedas]}


@router.get("")
async def buscar(q: str = Query("", max_length=100), limite: int = Query(20, ge=1, le=200),
                 incluir_inactivos: bool = False, usuario: dict = Depends(require_usuario),
                 conn: asyncpg.Connection = Depends(get_conn)):
    """Por SKU (empieza con) o descripcion (contiene). Sin texto: los ultimos modificados."""
    texto = q.strip().replace("%", "").replace("_", "")
    filas = await conn.fetch(_SELECT + """
        WHERE ($1 OR a.activo)
          AND ($2 = '' OR upper(a.sku) LIKE upper($2) || '%' OR lower(a.descripcion) LIKE '%' || lower($2) || '%')
        ORDER BY (CASE WHEN upper(a.sku) = upper($2) THEN 0 ELSE 1 END), a.actualizado_en DESC
        LIMIT $3
    """, incluir_inactivos, texto, limite)
    return [_salida(f) for f in filas]


@router.get("/{articulo_id}")
async def ver(articulo_id: str, usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    return await _articulo_o_404(conn, articulo_id, con_precios=True)


@router.post("", status_code=201)
async def crear(data: ArticuloNuevo, request: Request, usuario: dict = Depends(editor),
                conn: asyncpg.Connection = Depends(get_conn)):
    sku = await _validar(conn, data, data.moneda if data.precio is not None else None)
    try:
        async with conn.transaction():
            nuevo = await conn.fetchval("""
                INSERT INTO articulos (sku, descripcion, categoria, alicuota_iva, costo, creado_por)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """, sku, data.descripcion.strip(), data.categoria.strip(), data.alicuota_iva, data.costo, usuario["id"])
            if data.precio is not None:
                await conn.execute("""
                    INSERT INTO articulos_precios (articulo_id, moneda, importe, vigencia_desde, creado_por)
                    VALUES ($1, $2, $3, CURRENT_DATE, $4)
                """, nuevo, data.moneda, data.precio, usuario["id"])
            await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULO_ALTA",
                            f"{sku}: {data.descripcion.strip()[:80]}"
                            + (f", precio {data.moneda} {data.precio}." if data.precio is not None else "."),
                            client_ip(request))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un artículo con ese SKU.")
    return await _articulo_o_404(conn, str(nuevo), con_precios=True)


@router.put("/{articulo_id}")
async def modificar(articulo_id: str, data: ArticuloCambios, request: Request, usuario: dict = Depends(editor),
                    conn: asyncpg.Connection = Depends(get_conn)):
    actual = await _articulo_o_404(conn, articulo_id)
    sku = await _validar(conn, data)
    # Lo que viene de Tracker360 se cambia en Tracker360 (al importar vuelve a sincronizarse).
    if actual["origen"] == "tracker" and (sku, data.descripcion.strip(), data.categoria.strip()) != (actual["sku"], actual["descripcion"], actual["categoria"]):
        raise HTTPException(409, "Este artículo viene de Tracker360: el SKU, la descripción y la categoría se cambian allá.")
    try:
        async with conn.transaction():
            await conn.execute("""
                UPDATE articulos SET sku = $2, descripcion = $3, categoria = $4, alicuota_iva = $5, costo = $6,
                       activo = $7, actualizado_en = now()
                WHERE id = $1
            """, uuid_o_404(actual["id"]), sku, data.descripcion.strip(), data.categoria.strip(), data.alicuota_iva,
                data.costo, data.activo)
            await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULO_CAMBIO",
                            f"{sku}: {data.descripcion.strip()[:80]}" + ("" if data.activo else " (inactivo)") + ".",
                            client_ip(request))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un artículo con ese SKU.")
    return await _articulo_o_404(conn, articulo_id, con_precios=True)


@router.post("/{articulo_id}/precios", status_code=201)
async def poner_precio(articulo_id: str, data: PrecioNuevo, request: Request, usuario: dict = Depends(editor),
                       conn: asyncpg.Connection = Depends(get_conn)):
    """Precio nuevo con vigencia. Uno por (moneda, fecha): repetir la fecha lo reemplaza, asi un error de tipeo se
    corrige sin dejar basura en el historial."""
    actual = await _articulo_o_404(conn, articulo_id)
    vigentes = await _vigentes(conn)
    if not any(i["codigo"] == data.moneda for i in _codigos(vigentes, "TiposMonedas")):
        raise HTTPException(400, "Moneda desconocida para ARCA.")
    desde = data.vigencia_desde or date.today()
    async with conn.transaction():
        await conn.execute("""
            INSERT INTO articulos_precios (articulo_id, moneda, importe, vigencia_desde, creado_por)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (articulo_id, moneda, vigencia_desde) DO UPDATE SET importe = EXCLUDED.importe,
                creado_por = EXCLUDED.creado_por, creado_en = now()
        """, uuid_o_404(actual["id"]), data.moneda, data.importe, desde, usuario["id"])
        await conn.execute("UPDATE articulos SET actualizado_en = now() WHERE id = $1", uuid_o_404(actual["id"]))
        await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULO_PRECIO",
                        f"{actual['sku']}: {data.moneda} {data.importe} desde {desde.isoformat()}.", client_ip(request))
    return await _articulo_o_404(conn, articulo_id, con_precios=True)


# ===== Precios y costos por CSV (accion masiva por SKU: nunca crea articulos) =====

MAX_FILAS_CSV = 20000
COLUMNAS_CSV = {"sku", "precio", "costo", "vigencia_desde", "moneda"}


def _decimal_csv(texto: str) -> Optional[Decimal]:
    """'1.234,50', '1234.50', '1234' -> Decimal con 2 decimales. Vacio -> None. Invalido o negativo -> ValueError."""
    t = (texto or "").strip().replace("$", "").replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ValueError("número inválido")
    if not d.is_finite() or d < 0:
        raise ValueError("número inválido")
    if d.as_tuple().exponent < -2:
        raise ValueError("más de dos decimales")
    if d >= Decimal("10000000000000"):
        raise ValueError("número demasiado grande")
    return d.quantize(Decimal("0.01"))


def _fecha_csv(texto: str) -> Optional[date]:
    t = (texto or "").strip()
    if not t:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, formato).date()
        except ValueError:
            pass
    raise ValueError("fecha inválida (usar AAAA-MM-DD o DD/MM/AAAA)")


def _leer_csv(texto: str) -> tuple:
    """Filas normalizadas y errores por fila. Cabecera obligatoria con 'sku' y al menos 'precio' o 'costo'."""
    texto = texto.lstrip("\ufeff")
    primera = texto.splitlines()[0] if texto.strip() else ""
    separador = ";" if primera.count(";") >= primera.count(",") else ","
    lector = csv.reader(io.StringIO(texto), delimiter=separador)
    try:
        cabecera = [c.strip().lower().lstrip("\ufeff") for c in next(lector)]
    except StopIteration:
        raise HTTPException(400, "El archivo está vacío.")
    if "sku" not in cabecera or not ({"precio", "costo"} & set(cabecera)):
        raise HTTPException(400, "La primera fila tiene que tener las columnas: sku y precio o costo (opcionales: vigencia_desde, moneda).")
    desconocidas = sorted(set(cabecera) - COLUMNAS_CSV - {""})
    if desconocidas:
        raise HTTPException(400, f"Columnas desconocidas: {', '.join(desconocidas[:5])}. Válidas: sku, precio, costo, vigencia_desde, moneda.")
    indice = {c: i for i, c in enumerate(cabecera) if c}
    filas, errores, vistos = [], [], set()
    for n, campos in enumerate(lector, start=2):
        if not any(c.strip() for c in campos):
            continue
        if len(filas) + len(errores) >= MAX_FILAS_CSV:
            raise HTTPException(400, f"Hasta {MAX_FILAS_CSV} filas por archivo.")
        celda = lambda col: campos[indice[col]] if col in indice and indice[col] < len(campos) else ""
        sku = " ".join(celda("sku").split())
        try:
            if not sku:
                raise ValueError("sin SKU")
            if sku.upper() in vistos:
                raise ValueError("SKU repetido en el archivo")
            vistos.add(sku.upper())
            precio, costo = _decimal_csv(celda("precio")), _decimal_csv(celda("costo"))
            if precio is None and costo is None:
                raise ValueError("sin precio ni costo")
            filas.append({"fila": n, "sku": sku, "precio": precio, "costo": costo, "vigencia_desde": _fecha_csv(celda("vigencia_desde")),
                          "moneda": (celda("moneda").strip().upper() or "PES")})
        except ValueError as e:
            errores.append({"fila": n, "sku": sku, "motivo": str(e)})
    return filas, errores


async def _comparar_csv(conn: asyncpg.Connection, data: ArchivoCsv) -> dict:
    filas, errores = _leer_csv(data.csv)
    vigentes = await _vigentes(conn)
    monedas = {i["codigo"] for i in _codigos(vigentes, "TiposMonedas")}
    existentes = {f["sku"].upper(): f for f in await conn.fetch(_SELECT + " WHERE upper(a.sku) = ANY($1::text[])",
                                                                  [f["sku"].upper() for f in filas])}
    cambios, sin_cambios, no_encontrados = [], 0, []
    for f in filas:
        a = existentes.get(f["sku"].upper())
        if a is None:
            no_encontrados.append(f["sku"])
            continue
        if f["moneda"] not in monedas:
            errores.append({"fila": f["fila"], "sku": f["sku"], "motivo": f"moneda desconocida para ARCA: {f['moneda']}"})
            continue
        precio_actual = a["precio"] if f["moneda"] == "PES" else None
        toca_precio = f["precio"] is not None and (f["moneda"] != "PES" or precio_actual != f["precio"] or f["vigencia_desde"] is not None)
        toca_costo = f["costo"] is not None and a["costo"] != f["costo"]
        if not toca_precio and not toca_costo:
            sin_cambios += 1
            continue
        cambios.append({"id": a["id"], "sku": a["sku"], "descripcion": a["descripcion"],
                        "precio_actual": str(precio_actual) if precio_actual is not None else None,
                        "precio_nuevo": str(f["precio"]) if toca_precio else None, "moneda": f["moneda"],
                        "vigencia_desde": (f["vigencia_desde"] or date.today()).isoformat() if toca_precio else None,
                        "costo_actual": str(a["costo"]), "costo_nuevo": str(f["costo"]) if toca_costo else None})
    errores.sort(key=lambda e: e["fila"])
    return {"filas": len(filas) + len(errores), "cambios": cambios, "sin_cambios": sin_cambios,
            "no_encontrados": no_encontrados, "errores": errores}


def _resumen_csv(c: dict, maximo: int = 500) -> dict:
    return {"filas": c["filas"], "cambios": len(c["cambios"]), "sin_cambios": c["sin_cambios"],
            "no_encontrados": len(c["no_encontrados"]), "errores": len(c["errores"]),
            "detalle": {"cambios": [{k: v for k, v in x.items() if k != "id"} for x in c["cambios"][:maximo]],
                        "no_encontrados": c["no_encontrados"][:maximo], "errores": c["errores"][:maximo]}}


@router.post("/precios-csv/previa")
async def precios_csv_previa(data: ArchivoCsv, usuario: dict = Depends(editor), conn: asyncpg.Connection = Depends(get_conn)):
    """Que cambiaria: precio (PES vigente actual contra el nuevo) y costo por SKU. SKU que no existe: aparte, no se
    crea. Fila invalida: error con su numero. No guarda nada."""
    return _resumen_csv(await _comparar_csv(conn, data))


@router.post("/precios-csv")
async def precios_csv_aplicar(data: ArchivoCsv, request: Request, usuario: dict = Depends(editor),
                              conn: asyncpg.Connection = Depends(get_conn)):
    """Aplica los cambios de la vista previa. Con filas con error no se aplica nada: corregir el archivo primero."""
    c = await _comparar_csv(conn, data)
    if c["errores"]:
        raise HTTPException(400, f"El archivo tiene {len(c['errores'])} filas con error (la primera: fila "
                                 f"{c['errores'][0]['fila']}, {c['errores'][0]['motivo']}). No se aplicó nada.")
    async with conn.transaction():
        for x in c["cambios"]:
            if x["precio_nuevo"] is not None:
                await conn.execute("""
                    INSERT INTO articulos_precios (articulo_id, moneda, importe, vigencia_desde, creado_por) VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (articulo_id, moneda, vigencia_desde) DO UPDATE SET importe = EXCLUDED.importe,
                        creado_por = EXCLUDED.creado_por, creado_en = now()
                """, uuid_o_404(x["id"]), x["moneda"], Decimal(x["precio_nuevo"]), date.fromisoformat(x["vigencia_desde"]), usuario["id"])
            if x["costo_nuevo"] is not None:
                await conn.execute("UPDATE articulos SET costo = $2 WHERE id = $1", uuid_o_404(x["id"]), Decimal(x["costo_nuevo"]))
            await conn.execute("UPDATE articulos SET actualizado_en = now() WHERE id = $1", uuid_o_404(x["id"]))
        await registrar(conn, usuario["id"], usuario["usuario"], "ARTICULOS_PRECIOS_CSV",
                        f"{len(c['cambios'])} artículos actualizados por CSV ({c['filas']} filas, "
                        f"{len(c['no_encontrados'])} SKU no encontrados).", client_ip(request))
    return _resumen_csv(c)
