# JZFactura

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
| `backend/` | Aplicación FastAPI (`jzfactura/`), tests (`tests/`), herramientas (`tools/`) y contrato de la API (`api-snapshot.json`) |
| `db/` | Migraciones SQL versionadas (`NNNN_descripcion.sql`), se aplican solas al arrancar |
| `frontend/` | Páginas HTML, CSS y JS sin dependencias externas (CSP estricta: nada inline) |
| `install-native.sh` | Instalador nativo para Debian/Ubuntu |
| `requirements*.in` / `.txt` | Dependencias con versión exacta y lockfiles con hashes |
| `DEPENDENCIAS.md` | Justificación de cada dependencia |
| `.env.example` | Todas las variables de configuración, con valores de ejemplo |

## Instalación en el servidor

Debian 12/13 o Ubuntu 24.04, sin Docker y sin compilador:

```bash
sudo JZF_DOMAIN=factura.suempresa.com ./install-native.sh
```

Deja el servicio systemd `jzfactura` en `127.0.0.1:8050`, la base `jzfactura_db` con su rol propio,
la configuración en `/etc/jzfactura/jzfactura.env` y Caddy con HTTPS delante. Al terminar muestra el
token de configuración inicial, que la página pide una sola vez para crear el administrador.

## Desarrollo

Las dependencias se instalan solo desde wheels y con hashes, igual que en el servidor:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.txt -r requirements-dev.txt
```

Para correr la app en la máquina local, copiar `.env.example` a `.env` (nunca se versiona) y:

```bash
.venv/bin/uvicorn jzfactura.main:app --app-dir backend --port 8050
```

Tests, desde la raíz. El de deny-by-default no necesita base; los de autenticación usan un PostgreSQL
**descartable** (cada test borra el esquema; el nombre de la base tiene que terminar en `_test`):

```bash
docker run -d --name jzf-pg -p 5433:5432 -e POSTGRES_USER=jzfactura -e POSTGRES_PASSWORD=prueba -e POSTGRES_DB=jzfactura_test postgres:15-alpine
JZF_TEST_DB=1 POSTGRES_PORT=5433 POSTGRES_PASSWORD=prueba .venv/bin/python -m pytest
```

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
python tools/api_snapshot.py jzfactura.main api-snapshot.json --check
```

Si el contrato cambió a propósito, se regenera sin `--check` y el cambio se revisa en el commit.

## Versiones

[Versionado semántico](https://semver.org/lang/es/) `MAYOR.MENOR.PARCHE`. La versión vive en un solo lugar,
`backend/jzfactura/__init__.py`, y la leen el instalador, `/api/health` y el futuro actualizador.

- Mientras sea `0.x`: cada etapa del plan cerrada y aceptada sube MENOR (`0.1.0`, `0.2.0`, ...). Los arreglos
  y los cambios chicos dentro de una etapa suben PARCHE.
- `1.0.0`: la primera versión apta para facturar en producción contra ARCA.
- Cada versión publicada lleva su entrada en `CHANGELOG.md` y un tag anotado `vX.Y.Z` sobre el commit
  exacto. Nunca se mueve ni se reutiliza un tag.
- Un cambio de esquema siempre es una migración nueva en `db/`; nunca se edita una migración ya publicada.

## Licencia

AGPLv3. Ver `LICENSE`. Los aportes requieren `Signed-off-by` (DCO), ver `CONTRIBUTING.md`.
