"""Prueba de emision en HOMOLOGACION (modo prueba): pide el CAE de comprobantes C a ARCA sin pantalla, para validar
el cliente WSFEv1 antes de la Fase 3. Nunca habla con produccion. No guarda comprobantes (eso es de la Fase 3).

Los codigos (tipo de comprobante, condicion frente al IVA del receptor) se toman de los parametros fiscales leidos
de ARCA (Actualizar parametros fiscales), no de constantes. Consumidor final sin identificar (DocTipo 99, Nro 0).

Uso, dentro del servidor (con la configuracion y la clave maestra de la instalacion):
  python -m jzbill.arca.prueba_cae --cuit 20123456786 --pv 1 factura --importe 100
  python -m jzbill.arca.prueba_cae --cuit 20123456786 --pv 1 nc --importe 100 --asociado 1
  python -m jzbill.arca.prueba_cae --cuit 20123456786 --pv 1 nd --importe 10 --asociado 1
  python -m jzbill.arca.prueba_cae --cuit 20123456786 --pv 1 factura --importe 10 --moneda DOL
  python -m jzbill.arca.prueba_cae --cuit 20123456786 --pv 1 consultar --tipo factura --numero 1
"""

import argparse
import asyncio
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from jzbill import config, db
from jzbill.arca import parametros, servicio, soap, wsfev1

MODO = "prueba"
# ponytail: Argentina no tiene horario de verano desde 2009; con UTC-3 fijo no hace falta tzdata en la imagen.
HORA_AR = timezone(timedelta(hours=-3))
TIPOS = {"factura": "factura c", "nc": "nota de credito c", "nd": "nota de debito c"}


def _normal(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().strip().lower()


def _codigo(vigentes: dict, tipo: str, descripcion: str) -> int:
    for item in vigentes["tipos"].get(tipo, []):
        if _normal(item["descripcion"]) == descripcion:
            return int(item["codigo"])
    raise SystemExit(f"No está '{descripcion}' en los parámetros {tipo} de ARCA. Actualizá los parámetros fiscales.")


def _importe(texto: str) -> Decimal:
    try:
        valor = Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise SystemExit(f"Importe inválido: {texto}")
    if valor <= 0:
        raise SystemExit("El importe tiene que ser mayor a cero.")
    return valor


def _mostrar(titulo: str, datos: dict) -> None:
    print(titulo)
    for clave, valor in datos.items():
        if valor not in (None, "", []):
            print(f"  {clave}: {valor}")


async def principal(args) -> int:
    url = config.ARCA_URLS[MODO]["wsfe"]
    await db.iniciar()
    try:
        async with db.DB.pool.acquire() as conn:
            cuit = "".join(c for c in args.cuit if c.isdigit())
            rs = await conn.fetchrow("SELECT * FROM razones_sociales WHERE cuit = $1", cuit)
            if rs is None:
                raise SystemExit(f"No hay una razón social con CUIT {cuit}.")
            if not await conn.fetchval("SELECT 1 FROM puntos_venta WHERE razon_social_id = $1 AND numero = $2 AND activo",
                                       rs["id"], args.pv):
                raise SystemExit(f"El punto de venta {args.pv} no existe o no está activo en esa razón social.")
            vigentes = await parametros.vigentes(conn, MODO)
            if vigentes is None:
                raise SystemExit("Faltan los parámetros fiscales de homologación: Actualizar parámetros fiscales.")
            cred = await servicio.credenciales(conn, rs, MODO)
    finally:
        await db.cerrar()

    codigo_factura = _codigo(vigentes, "TiposCbte", TIPOS["factura"])
    if args.accion == "consultar":
        tipo = _codigo(vigentes, "TiposCbte", TIPOS[args.tipo])
        _mostrar(f"Comprobante {args.tipo} {args.pv}-{args.numero}:", wsfev1.consultar(url, cred, args.pv, tipo, args.numero))
        return 0

    tipo = _codigo(vigentes, "TiposCbte", TIPOS[args.accion])
    importe = _importe(args.importe)
    hoy = datetime.now(HORA_AR).strftime("%Y%m%d")
    detalle = {"Concepto": 1, "DocTipo": 99, "DocNro": 0, "CbteFch": hoy,
               # Comprobante C: el total es el subtotal (ImpNeto); sin IVA discriminado, no gravado ni exento.
               "ImpTotal": importe, "ImpTotConc": Decimal("0"), "ImpNeto": importe, "ImpOpEx": Decimal("0"),
               "ImpTrib": Decimal("0"), "ImpIVA": Decimal("0"), "MonId": "PES", "MonCotiz": "1",
               "CondicionIVAReceptorId": _codigo(vigentes, "CondicionIvaReceptor", "consumidor final")}
    if args.moneda != "PES":
        valor, fecha = wsfev1.cotizacion(url, cred, args.moneda)
        print(f"Cotización de ARCA para {args.moneda}: {valor} (del {fecha}).")
        detalle.update({"MonId": args.moneda, "MonCotiz": valor, "CanMisMonExt": "N"})
    asociados = ()
    if args.accion in ("nc", "nd"):
        if not args.asociado:
            raise SystemExit("Las notas de crédito y débito necesitan --asociado (número de la factura C).")
        original = wsfev1.consultar(url, cred, args.pv, codigo_factura, args.asociado)
        asociados = ({"Tipo": codigo_factura, "PtoVta": args.pv, "Nro": args.asociado, "Cuit": cuit,
                      "CbteFch": original.get("CbteFch")},)

    numero = wsfev1.ultimo_autorizado(url, cred, args.pv, tipo) + 1
    detalle.update({"CbteDesde": numero, "CbteHasta": numero})
    print(f"Pidiendo CAE (homologación): {args.accion} {args.pv}-{numero}, {importe} {detalle['MonId']}...")
    try:
        r = wsfev1.solicitar_cae(url, cred, args.pv, tipo, detalle, asociados)
    except soap.ErrorRed as e:
        # Se corto la conexion: puede que ARCA lo haya autorizado igual. Se consulta antes de reintentar.
        print(f"Sin respuesta de ARCA ({e.codigo}). Consultando si el {args.pv}-{numero} quedó autorizado...")
        _mostrar("Resultado de la consulta:", wsfev1.consultar(url, cred, args.pv, tipo, numero))
        return 1
    _mostrar("Respuesta de ARCA:", r)
    return 0 if r["resultado"] == "A" else 2


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m jzbill.arca.prueba_cae",
                                description="Pedido de CAE de prueba en HOMOLOGACION de ARCA (comprobantes C).")
    p.add_argument("--cuit", required=True, help="CUIT de la razón social emisora")
    p.add_argument("--pv", type=int, required=True, help="número de punto de venta")
    sub = p.add_subparsers(dest="accion", required=True)
    for accion in ("factura", "nc", "nd"):
        s = sub.add_parser(accion)
        s.add_argument("--importe", required=True, help="total, con punto decimal (ej. 100.50)")
        s.add_argument("--moneda", default="PES", help="código de moneda de ARCA (PES, DOL, 060...)")
        s.add_argument("--asociado", type=int, help="número de la factura C asociada (nc y nd)")
    c = sub.add_parser("consultar")
    c.add_argument("--tipo", choices=sorted(TIPOS), required=True)
    c.add_argument("--numero", type=int, required=True)
    args = p.parse_args()
    try:
        sys.exit(asyncio.run(principal(args)))
    except soap.ErrorArca as e:
        sys.exit(f"ARCA: {e.mensaje} ({e.codigo})")


if __name__ == "__main__":
    main()
