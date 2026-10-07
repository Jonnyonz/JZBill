# JZBill

Facturador electrónico web para Argentina (ARCA), módulo de **JZTech Suite**. Nombre provisorio.
Se instala en el servidor del cliente junto a Tracker360, sobre `jztech-core` (FastAPI + PostgreSQL).

**Estado: 0.3.x, razones sociales, sucursales, roles y accesos.** Todavía no emite comprobantes.

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
| `install-docker.sh`, `compose.yml`, `Dockerfile` | Instalación alternativa con Docker (app y PostgreSQL) |
| `requirements*.in` / `.txt` | Dependencias con versión exacta y lockfiles con hashes |
| `DEPENDENCIAS.md` | Justificación de cada dependencia |
| `.env.example` | Todas las variables de configuración, con valores de ejemplo |

## Instalación en el servidor

Hay que clonar el repo **completo** (los instaladores usan el código que está al lado):

```bash
git clone https://github.com/Jonnyonz/JZBill.git && cd JZBill
```

Debian 12/13 o Ubuntu 24.04, sin Docker y sin compilador. Queda en `https://<ip del servidor>:9443`:

```bash
sudo ./install-native.sh
```

Con un nombre propio, queda en `https://factura.suempresa.com:9443`:

```bash
sudo JZB_DOMAIN=factura.suempresa.com ./install-native.sh
```

Deja el servicio systemd `jzbill` escuchando con HTTPS en el puerto 9443 (sin proxy delante), la base
`jzbill_db` con su rol propio (solo ese rol puede conectarse) y la configuración en `/etc/jzbill/jzbill.env`. Al
terminar muestra el token de configuración inicial, que la página pide una sola vez para crear el administrador.
Variables opcionales: `JZB_HTTPS_PORT` (otro puerto) y `JZB_BIND=127.0.0.1` (solo desde ese equipo). Se puede
volver a correr para actualizar la instalación: las claves generadas no se pisan.

**Certificado HTTPS.** Si no hay uno, el instalador genera un certificado autofirmado para la IP o el nombre,
en `/etc/jzbill/tls/cert.pem`: cada terminal tiene que confiar en él una vez. Para usar uno propio, copiar
`cert.pem` (con la cadena) y `key.pem` a `/etc/jzbill/tls/`, borrar `/etc/jzbill/tls/.autofirmado` y volver a
correr el instalador.

**Clave maestra de los secretos.** El instalador genera `/etc/jzbill/clave-secretos` (root:jzbill 0640), con
la que se cifran los certificados y claves de ARCA. Se respalda **aparte** del respaldo de la base: sin ella
los certificados guardados no se recuperan; con las dos juntas, quedan expuestos. Nunca se pisa al reinstalar.

Probado en Debian 13 con Tracker360 nativo en el mismo servidor.

### Alternativa con Docker

Para quien ya usa Docker (por ejemplo, un facturador personal). En equipos con pocos recursos conviene la
nativa: Docker suma consumo de memoria. Hace falta Linux con Docker Engine y `docker compose` v2. Desde la
carpeta del repo clonado:

```bash
sudo ./install-docker.sh
```

Arma la imagen en el servidor y levanta dos contenedores: la app (usuario sin privilegios, sistema de archivos
de solo lectura, HTTPS propio en `https://<ip del equipo>:9443`) y PostgreSQL en una red interna sin salida a
internet. Solo la app publica un puerto. La configuración, la clave maestra y el certificado HTTPS quedan en
`/etc/jzbill-docker/` (mismas reglas que la nativa); la base, en el volumen `jzbill_db`. Mismas variables
opcionales que la nativa. Docker publica el puerto por encima del firewall del sistema: si el equipo está
expuesto a internet, usar `JZB_BIND`. Para actualizar: `git pull` y volver a correrlo.

## Desarrollo

Las dependencias se instalan solo desde wheels y con hashes, igual que en el servidor:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.txt -r requirements-dev.txt
```

Para correr la app en la máquina local, copiar `.env.example` a `.env` (nunca se versiona) y:

```bash
.venv/bin/uvicorn jzbill.main:app --app-dir backend --port 9443
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
