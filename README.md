# JZBill

Facturador electrónico web para Argentina (ARCA), módulo de **JZTech Suite**. Nombre provisorio.
Se instala en el servidor del cliente junto a Tracker360, sobre `jztech-core` (FastAPI + PostgreSQL).

**Estado: 0.0.x, base segura (usuarios y sesiones).** Todavía no emite comprobantes.

- [Estructura](#estructura)
- [Instalación en el servidor](#instalación-en-el-servidor)
- [Desarrollo](#desarrollo)
- [Contrato de la API](#contrato-de-la-api)
- [Versiones](#versiones)
- [Licencia](#licencia)

## Estructura

| Carpeta / archivo | Contenido |
|---|---|
| `backend/` | Aplicación FastAPI (`jzbill/`), herramientas (`tools/`) y contrato de la API (`api-snapshot.json`) |
| `db/` | Migraciones SQL versionadas (`NNNN_descripcion.sql`), se aplican solas al arrancar |
| `frontend/` | Páginas HTML, CSS y JS sin dependencias externas (CSP estricta: nada inline) |
| `install-native.sh` | Instalador nativo para Debian/Ubuntu |
| `requirements*.in` / `.txt` | Dependencias con versión exacta y lockfiles con hashes |
| `DEPENDENCIAS.md` | Justificación de cada dependencia |
| `.env.example` | Todas las variables de configuración, con valores de ejemplo |

## Instalación en el servidor

Debian 12/13 o Ubuntu 24.04, sin Docker y sin compilador. Por IP (red del local), queda en
`https://<ip del servidor>:8443`, porque el 443 de la IP lo usa Tracker360:

```bash
sudo ./install-native.sh
```

Con dominio propio, queda en `https://factura.suempresa.com`:

```bash
sudo JZB_DOMAIN=factura.suempresa.com ./install-native.sh
```

Deja el servicio systemd `jzbill` en `127.0.0.1:8050`, la base `jzbill_db` con su rol propio (solo ese
rol puede conectarse), la configuración en `/etc/jzbill/jzbill.env` y Caddy con HTTPS delante. Al terminar
muestra el token de configuración inicial, que la página pide una sola vez para crear el administrador.

El Caddyfile se comparte con las otras apps de JZTech: el instalador solo agrega o actualiza el bloque
`# jzbill`, no modifica un Caddyfile que no haya armado un instalador de JZTech y, si el resultado no valida,
lo deja como estaba. Por IP el certificado lo emite la CA local de Caddy (la misma de Tracker360): cada
terminal tiene que confiar en esa CA una sola vez. Se puede volver a correr para actualizar la
instalación: las claves generadas no se pisan.

Probado en Debian 13 con Tracker360 nativo en el mismo servidor.

## Desarrollo

Las dependencias se instalan solo desde wheels y con hashes, igual que en el servidor:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.txt -r requirements-dev.txt
```

Para correr la app en la máquina local, copiar `.env.example` a `.env` (nunca se versiona) y:

```bash
.venv/bin/uvicorn jzbill.main:app --app-dir backend --port 8050
```

Los tests (`backend/tests/`, `pytest.ini`) se mantienen fuera del repositorio público, en la máquina de
desarrollo. `requirements-dev.txt` trae las herramientas para correrlos y para auditar.

Auditoría de dependencias:

```bash
.venv/bin/pip-audit -r requirements.txt --require-hashes --disable-pip
```

Regenerar los lockfiles: ver el encabezado de `requirements.in` y `requirements-dev.in` (siempre en Linux
con Python 3.11).

## Contrato de la API

`backend/api-snapshot.json` congela método, ruta y parámetros de cada operación. Antes de cerrar un
cambio, desde `backend/`:

```bash
python tools/api_snapshot.py jzbill.main api-snapshot.json --check
```

Si el contrato cambió a propósito, se regenera sin `--check` y el cambio se revisa en el commit.

## Versiones

[Versionado semántico](https://semver.org/lang/es/) `MAYOR.MENOR.PARCHE`. La versión vive en un solo lugar,
`backend/jzbill/__init__.py`, y la leen el instalador, `/api/health` y el futuro actualizador.

- Mientras sea `0.x`: cada etapa del plan cerrada y aceptada sube MENOR (`0.1.0`, `0.2.0`, ...). Los arreglos
  y los cambios chicos dentro de una etapa suben PARCHE.
- `1.0.0`: la primera versión apta para facturar en producción contra ARCA.
- Cada versión publicada lleva su entrada en `CHANGELOG.md` y un tag anotado `vX.Y.Z` sobre el commit
  exacto. Nunca se mueve ni se reutiliza un tag.
- Un cambio de esquema siempre es una migración nueva en `db/`; nunca se edita una migración ya publicada.

## Licencia

AGPLv3. Ver `LICENSE`. Los aportes requieren `Signed-off-by` (DCO), ver `CONTRIBUTING.md`.
