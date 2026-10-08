"""Configuracion de la instalacion (variables de entorno, archivo .env). Lo que cambia por cliente y se
carga desde la pagina (razones sociales, certificados, SMTP) vive en la base, no aca."""

import logging
import os
from pathlib import Path

from jztech_core.net import parse_networks

logger = logging.getLogger(__name__)


def _cargar_env(ruta: Path) -> None:
    """Carga KEY=VALOR de un .env sin pisar variables ya definidas (systemd manda)."""
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


_cargar_env(Path(os.getenv("JZBILL_ENV_FILE", Path(__file__).resolve().parents[2] / ".env")))


def _entero(nombre: str, defecto: int, minimo: int = 1) -> int:
    """Entero de una variable de entorno. Un valor invalido corta el arranque: mejor no arrancar que
    arrancar con una configuracion distinta de la que se escribio."""
    crudo = os.getenv(nombre, str(defecto)).strip()
    try:
        valor = int(crudo)
    except ValueError:
        raise RuntimeError(f"{nombre}: se esperaba un numero entero y vino {crudo!r}.")
    if valor < minimo:
        raise RuntimeError(f"{nombre}: el minimo es {minimo}.")
    return valor


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = _entero("POSTGRES_PORT", 5432)
POSTGRES_DB = os.getenv("POSTGRES_DB", "jzbill_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "jzbill")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
DB_POOL_MAX = _entero("DB_POOL_MAX", 5)

# Token de la configuracion inicial (alta del primer administrador). Lo genera el instalador.
SETUP_TOKEN = os.getenv("SETUP_TOKEN", "")

# Direccion publica con HTTPS del facturador.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

# Proxies de confianza para la IP real (X-Forwarded-For). Un valor invalido corta el arranque.
try:
    TRUSTED_PROXIES = parse_networks(os.getenv("TRUSTED_PROXIES", "127.0.0.1/32,::1/128"))
except ValueError as e:
    raise RuntimeError(f"TRUSTED_PROXIES invalido: {e}")

# Cookies Secure: en produccion (HTTPS) siempre. Solo para pruebas locales por HTTP se puede apagar.
COOKIES_SECURE = os.getenv("COOKIES_SECURE", "true").strip().lower() != "false"

# Login: intentos fallidos antes de bloquear (por IP + usuario y por IP sola) y minutos de bloqueo.
MAX_LOGIN_ATTEMPTS = _entero("MAX_LOGIN_ATTEMPTS", 5)
MAX_LOGIN_ATTEMPTS_IP = _entero("MAX_LOGIN_ATTEMPTS_IP", 20)
LOCKOUT_MINUTES = _entero("LOCKOUT_MINUTES", 15)
SESSION_HOURS = _entero("SESSION_HOURS", 8)

# Largo minimo de las claves de los usuarios. El maximo es fijo (128) para que Argon2 no se use para
# agotar CPU y memoria con claves enormes.
PASSWORD_MIN_LENGTH = _entero("PASSWORD_MIN_LENGTH", 10, minimo=8)
PASSWORD_MAX_LENGTH = 128

# Clave maestra para cifrar secretos en reposo (32 bytes en base64, una linea). La genera el instalador en
# /etc/jzbill/clave-secretos (root:jzbill 0640). Sin ella la app arranca, pero no puede guardar ni leer
# certificados ni claves. Se respalda APARTE de la base: con las dos juntas, el respaldo expone los secretos.
SECRETS_KEY_FILE = os.getenv("SECRETS_KEY_FILE", "").strip()

# Servicios de ARCA. Valores oficiales (manual WSFEv1 v4.7 del 2026-09-01 y pagina del WSAA): modo "prueba" =
# homologacion, modo "empresa" = produccion. Se pueden cambiar por .env SOLO para apuntar a una ARCA simulada en
# pruebas; en una instalacion real no se tocan.
ARCA_URLS = {
    "prueba": {
        "wsaa": os.getenv("ARCA_WSAA_URL_PRUEBA", "https://wsaahomo.afip.gov.ar/ws/services/LoginCms"),
        "wsfe": os.getenv("ARCA_WSFE_URL_PRUEBA", "https://wswhomo.afip.gov.ar/wsfev1/service.asmx"),
        # Constancia de inscripcion (ex padron A5). El manual v4.1 cita awshomo.arca.gob.ar, que todavia no resuelve.
        "padron": os.getenv("ARCA_PADRON_URL_PRUEBA", "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5"),
    },
    "empresa": {
        "wsaa": os.getenv("ARCA_WSAA_URL_EMPRESA", "https://wsaa.afip.gov.ar/ws/services/LoginCms"),
        "wsfe": os.getenv("ARCA_WSFE_URL_EMPRESA", "https://servicios1.afip.gov.ar/wsfev1/service.asmx"),
        "padron": os.getenv("ARCA_PADRON_URL_EMPRESA", "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5"),
    },
}
# Segundos maximos de espera por cada llamada a ARCA (conexion + respuesta).
ARCA_TIMEOUT = _entero("ARCA_TIMEOUT", 30)

# Instalacion: "nativa" (install-native.sh), "docker" (install-docker.sh) o "desarrollo". La pagina muestra como actualizar segun el caso.
JZB_INSTALACION = os.getenv("JZB_INSTALACION", "desarrollo").strip().lower()
