"""Clientes (compartidos entre todas las razones sociales, decision de Jonny 2026-10-08) y grupos economicos.

Ver: cualquier rol. Crear y modificar: administrador, supervisor y cajero (el cajero da de alta clientes durante la
venta). Tipo de documento y condicion frente al IVA son codigos de ARCA, validados contra los parametros vigentes;
el CUIT/CUIL con su digito verificador. Un mismo documento no se carga dos veces."""

import asyncio
import unicodedata
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jzbill import config
from jzbill.arca import padron, parametros, servicio, soap
from jzbill.arca_api import _error as error_arca
from jzbill.auth import client_ip, registrar, require_usuario
from jzbill.contexto import contexto_requerido
from jzbill.cuit import formatear_cuit, normalizar_cuit
from jzbill.db import get_conn
from jzbill.permisos import require_rol, uuid_o_404

router = APIRouter(prefix="/api/clientes", tags=["Clientes"])
router_grupos = APIRouter(prefix="/api/grupos-clientes", tags=["Clientes"])
router_padron = APIRouter(prefix="/api/padron", tags=["Clientes"])

editor = require_rol("administrador", "supervisor", "cajero")


class ClienteDatos(BaseModel):
    doc_tipo: int = Field(ge=0, le=999)
    doc_nro: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=200)
    condicion_iva: int = Field(ge=1, le=99)
    domicilio: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=200)
    grupo_id: Optional[str] = Field(default=None, max_length=40)
    origen: Literal["manual", "arca"] = "manual"


class ClienteCambios(ClienteDatos):
    activo: bool = True


class GrupoNuevo(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


def _normal(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().strip().lower()


async def _vigentes(conn: asyncpg.Connection) -> Optional[dict]:
    for modo in ("empresa", "prueba"):
        v = await parametros.vigentes(conn, modo)
        if v is not None:
            return v
    return None


async def _validar(conn: asyncpg.Connection, data: ClienteDatos) -> tuple:
    """(doc_nro como entero, grupo_id). 400 si algo no corresponde."""
    vigentes = await _vigentes(conn)
    if vigentes is None:
        raise HTTPException(409, "Faltan los parámetros fiscales de ARCA: un administrador tiene que actualizarlos.")
    doc = next((i for i in vigentes["tipos"].get("TiposDoc", []) if i["codigo"] == str(data.doc_tipo)), None)
    if doc is None:
        raise HTTPException(400, "Tipo de documento desconocido para ARCA.")
    if not any(i["codigo"] == str(data.condicion_iva) for i in vigentes["tipos"].get("CondicionIvaReceptor", [])):
        raise HTTPException(400, "Condición frente al IVA desconocida para ARCA.")
    numero = "".join(c for c in data.doc_nro if c.isdigit())
    if not numero or len(numero) > 11 or int(numero) == 0:
        raise HTTPException(400, "Número de documento inválido.")
    if _normal(doc["descripcion"]) in ("cuit", "cuil") and normalizar_cuit(numero) is None:
        raise HTTPException(400, "El CUIT o CUIL no es válido (dígito verificador).")
    email = data.email.strip()
    if email and ("@" not in email or " " in email):
        raise HTTPException(400, "Email inválido.")
    grupo = None
    if data.grupo_id:
        grupo = await conn.fetchval("SELECT id FROM grupos_clientes WHERE id = $1", uuid_o_404(data.grupo_id))
        if grupo is None:
            raise HTTPException(404, "No encontrado.")
    return int(numero), grupo


def _salida(fila) -> dict:
    numero = str(fila["doc_nro"])
    return {"id": str(fila["id"]), "doc_tipo": fila["doc_tipo"], "doc_nro": numero,
            "doc_formateado": formatear_cuit(numero) if len(numero) == 11 else numero,
            "nombre": fila["nombre"], "condicion_iva": fila["condicion_iva"], "domicilio": fila["domicilio"],
            "email": fila["email"], "grupo_id": str(fila["grupo_id"]) if fila["grupo_id"] else None,
            "grupo": fila["grupo"], "activo": fila["activo"], "origen": fila["origen"]}


_SELECT = "SELECT c.*, g.nombre AS grupo FROM clientes c LEFT JOIN grupos_clientes g ON g.id = c.grupo_id"


@router.get("")
async def buscar(q: str = Query("", max_length=100), limite: int = Query(20, ge=1, le=100),
                 incluir_inactivos: bool = False, usuario: dict = Depends(require_usuario),
                 conn: asyncpg.Connection = Depends(get_conn)):
    """Por nombre (contiene) o numero de documento (empieza con, desde 3 digitos). Sin texto: los ultimos
    modificados."""
    texto = q.strip().replace("%", "").replace("_", "")
    digitos = "".join(c for c in texto if c.isdigit())
    filas = await conn.fetch(_SELECT + """
        WHERE ($1 OR c.activo)
          AND ($2 = '' OR lower(c.nombre) LIKE '%' || lower($2) || '%' OR ($3 <> '' AND c.doc_nro::text LIKE $3 || '%'))
        ORDER BY (CASE WHEN $3 <> '' AND c.doc_nro::text = $3 THEN 0 ELSE 1 END), c.actualizado_en DESC
        LIMIT $4
    """, incluir_inactivos, texto, digitos if len(digitos) >= 3 else "", limite)
    return [_salida(f) for f in filas]


async def _cliente_o_404(conn: asyncpg.Connection, cliente_id: str) -> asyncpg.Record:
    fila = await conn.fetchrow(_SELECT + " WHERE c.id = $1", uuid_o_404(cliente_id))
    if fila is None:
        raise HTTPException(404, "No encontrado.")
    return fila


@router.get("/{cliente_id}")
async def ver(cliente_id: str, usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    return _salida(await _cliente_o_404(conn, cliente_id))


@router.post("", status_code=201)
async def crear(data: ClienteDatos, request: Request, usuario: dict = Depends(editor),
                conn: asyncpg.Connection = Depends(get_conn)):
    numero, grupo = await _validar(conn, data)
    try:
        async with conn.transaction():
            nuevo = await conn.fetchval("""
                INSERT INTO clientes (doc_tipo, doc_nro, nombre, condicion_iva, domicilio, email, grupo_id, origen,
                                      datos_arca_en, creado_por)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::varchar, CASE WHEN $8::varchar = 'arca' THEN now() END, $9) RETURNING id
            """, data.doc_tipo, numero, data.nombre.strip(), data.condicion_iva, data.domicilio.strip(),
                data.email.strip(), grupo, data.origen, usuario["id"])
            await registrar(conn, usuario["id"], usuario["usuario"], "CLIENTE_ALTA",
                            f"{data.nombre.strip()[:80]} (doc {numero})"
                            + (", datos de ARCA." if data.origen == "arca" else "."), client_ip(request))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un cliente con ese documento.")
    return _salida(await _cliente_o_404(conn, str(nuevo)))


@router.put("/{cliente_id}")
async def modificar(cliente_id: str, data: ClienteCambios, request: Request, usuario: dict = Depends(editor),
                    conn: asyncpg.Connection = Depends(get_conn)):
    actual = await _cliente_o_404(conn, cliente_id)
    numero, grupo = await _validar(conn, data)
    try:
        async with conn.transaction():
            await conn.execute("""
                UPDATE clientes SET doc_tipo = $2, doc_nro = $3, nombre = $4, condicion_iva = $5, domicilio = $6,
                       email = $7, grupo_id = $8, activo = $9, actualizado_en = now(),
                       origen = CASE WHEN $10 = 'arca' THEN 'arca' ELSE origen END,
                       datos_arca_en = CASE WHEN $10 = 'arca' THEN now() ELSE datos_arca_en END
                WHERE id = $1
            """, actual["id"], data.doc_tipo, numero, data.nombre.strip(), data.condicion_iva, data.domicilio.strip(),
                data.email.strip(), grupo, data.activo, data.origen)
            await registrar(conn, usuario["id"], usuario["usuario"], "CLIENTE_CAMBIO",
                            f"{data.nombre.strip()[:80]} (doc {numero}).", client_ip(request))
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un cliente con ese documento.")
    return _salida(await _cliente_o_404(conn, cliente_id))


@router_grupos.get("")
async def grupos(usuario: dict = Depends(require_usuario), conn: asyncpg.Connection = Depends(get_conn)):
    filas = await conn.fetch("""
        SELECT g.id, g.nombre, count(c.id) AS clientes FROM grupos_clientes g
        LEFT JOIN clientes c ON c.grupo_id = g.id GROUP BY g.id ORDER BY lower(g.nombre)
    """)
    return [{"id": str(f["id"]), "nombre": f["nombre"], "clientes": f["clientes"]} for f in filas]


@router_grupos.post("", status_code=201)
async def crear_grupo(data: GrupoNuevo, request: Request, usuario: dict = Depends(editor),
                      conn: asyncpg.Connection = Depends(get_conn)):
    nombre = data.nombre.strip()
    if not nombre:
        raise HTTPException(400, "Poné un nombre al grupo.")
    try:
        fila = await conn.fetchrow("INSERT INTO grupos_clientes (nombre) VALUES ($1) RETURNING id, nombre", nombre)
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Ya existe un grupo con ese nombre.")
    await registrar(conn, usuario["id"], usuario["usuario"], "GRUPO_CLIENTES_ALTA", nombre[:120], client_ip(request))
    return {"id": str(fila["id"]), "nombre": fila["nombre"], "clientes": 0}


# Descripciones de ARCA (FEParamGetCondicionIvaReceptor) para la sugerencia de condicion frente al IVA.
_SUGERENCIAS = {"responsable_inscripto": "iva responsable inscripto", "monotributo": "responsable monotributo"}


@router_padron.get("/{cuit}")
async def consultar_padron(cuit: str, request: Request, ctx: dict = Depends(contexto_requerido),
                           conn: asyncpg.Connection = Depends(get_conn)):
    """Alta rapida: datos del contribuyente segun la constancia de inscripcion de ARCA, con el certificado de la
    razon social y el modo de la sesion (el certificado tiene que estar autorizado para ws_sr_constancia_inscripcion).
    No guarda nada: el usuario revisa, completa y confirma con POST /api/clientes."""
    usuario = ctx["usuario"]
    if usuario["rol"] not in ("administrador", "supervisor", "cajero"):
        raise HTTPException(403, "No tiene permiso para esta acción.")
    numero = normalizar_cuit(cuit)
    if numero is None:
        raise HTTPException(400, "El CUIT no es válido (dígito verificador).")
    rs = await conn.fetchrow("SELECT * FROM razones_sociales WHERE id = $1", uuid_o_404(ctx["razon_social_id"]))
    try:
        cred = await servicio.credenciales(conn, rs, ctx["modo"], padron.SERVICIO)
        datos = await asyncio.to_thread(padron.consultar, config.ARCA_URLS[ctx["modo"]]["padron"], cred, numero)
    except soap.ErrorArca as e:
        raise error_arca(e)
    vigentes = await _vigentes(conn)
    condiciones = vigentes["tipos"].get("CondicionIvaReceptor", []) if vigentes else []
    sugerida = _SUGERENCIAS.get(datos["sugerencia"] or "")
    datos["condicion_sugerida"] = next((int(c["codigo"]) for c in condiciones if _normal(c["descripcion"]) == sugerida), None)
    cuit_doc = next((int(d["codigo"]) for d in (vigentes["tipos"].get("TiposDoc", []) if vigentes else [])
                     if _normal(d["descripcion"]) == "cuit"), None)
    datos["doc_tipo"] = cuit_doc
    existente = await conn.fetchval("SELECT id FROM clientes WHERE doc_nro = $1", int(numero))
    datos["cliente_existente"] = str(existente) if existente else None
    await registrar(conn, usuario["id"], usuario["usuario"], "PADRON_CONSULTA", f"CUIT {numero}, modo {ctx['modo']}.",
                    client_ip(request), rs["id"])
    return datos
