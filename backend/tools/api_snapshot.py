#!/usr/bin/env python3
"""Snapshot del contrato de API (metodo + ruta + parametros + si lleva cuerpo).

Sirve como red de seguridad al cambiar dependencias: el contrato HTTP no debe
cambiar. Ejecutar desde la carpeta que contiene el modulo del backend y con las
variables de entorno minimas definidas (no necesita base de datos).

  python tools/api_snapshot.py MODULO api-snapshot.json           # genera
  python tools/api_snapshot.py MODULO api-snapshot.json --check   # compara

En JZFactura se corre desde la carpeta backend/.

Ejemplos de MODULO: jzfactura.main (este repo), jzmiddle.main (middleware), backend.main (Tracker360).
Sale con codigo 1 si hay diferencias.
"""
import importlib
import json
import sys

METODOS = ("get", "post", "put", "patch", "delete")


def tomar_snapshot(nombre_modulo):
    sys.path.insert(0, ".")
    app = importlib.import_module(nombre_modulo).app
    spec = app.openapi()
    ops = {}
    for ruta, item in spec["paths"].items():
        for metodo, op in item.items():
            if metodo not in METODOS:
                continue
            params = sorted(f'{p["in"]}:{p["name"]}' for p in op.get("parameters", []))
            ops[f"{metodo.upper()} {ruta}"] = {"params": params, "cuerpo": "requestBody" in op}
    return dict(sorted(ops.items()))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    modulo, archivo = sys.argv[1], sys.argv[2]
    actual = tomar_snapshot(modulo)
    if "--check" not in sys.argv:
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(actual, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        print(f"Snapshot escrito: {len(actual)} operaciones -> {archivo}")
        return
    with open(archivo, encoding="utf-8") as f:
        previo = json.load(f)
    faltan = sorted(set(previo) - set(actual))
    nuevas = sorted(set(actual) - set(previo))
    cambian = sorted(k for k in set(previo) & set(actual) if previo[k] != actual[k])
    if not (faltan or nuevas or cambian):
        print(f"OK: contrato identico ({len(actual)} operaciones).")
        return
    for etiqueta, lista in (("FALTAN", faltan), ("NUEVAS", nuevas), ("CAMBIAN", cambian)):
        for k in lista:
            print(f"{etiqueta}: {k}")
    sys.exit(1)


if __name__ == "__main__":
    main()
