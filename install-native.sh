#!/bin/bash
# ==============================================================================
# Instalador nativo (sin Docker) de JZBill
# ==============================================================================
# Para Debian 12/13 y Ubuntu 24.04 (apt, Python 3.11 o mas nuevo). Correr como root desde la raiz del repo
# clonado completo:
#
#   sudo ./install-native.sh                                  https://<ip del servidor>:9443
#   sudo JZB_DOMAIN=factura.cliente.com ./install-native.sh   https://factura.cliente.com:9443
#
# Queda asi:
#   /opt/jzbill/releases/<version>/   codigo + su propio venv (una carpeta por version)
#   /opt/jzbill/current               enlace a la version en uso
#   /etc/jzbill/jzbill.env            configuracion y secretos (root:jzbill, 0640)
#   /etc/jzbill/tls/                  certificado HTTPS (cert.pem, key.pem)
#   servicio systemd "jzbill"         la app con HTTPS propio en el puerto 9443, un worker
#   base "jzbill_db" y rol "jzbill" propios en el PostgreSQL del servidor
#
# Sin proxy: la app sirve HTTPS directamente (la sesion usa cookies Secure: sin HTTPS no se puede ingresar).
# Si no hay certificado, se genera uno autofirmado para la IP o el dominio: cada terminal tiene que confiar en
# /etc/jzbill/tls/cert.pem una vez. Para usar uno propio (por ejemplo de un dominio): copiar cert.pem (con la
# cadena) y key.pem a /etc/jzbill/tls/, borrar /etc/jzbill/tls/.autofirmado y volver a correr.
#
# Pendiente para la Fase 9: actualizador jz-bill-actualizar (respaldo, migracion, chequeo, vuelta atras).
#
# Idempotente: se puede volver a correr. Los secretos ya generados (clave de la base, token de
# instalacion, clave maestra) no se pisan. Sin compilador: las dependencias se instalan solo con paquetes
# binarios (wheels) y verificando los hashes de requirements.txt; si hay una carpeta wheelhouse/ al lado, se
# usa esa (instalacion sin internet).
#
# Variables opcionales (si no se pasan, se reutilizan las de la instalacion anterior):
#   JZB_DOMAIN=factura.cliente.com   nombre para entrar (va en el certificado autofirmado)
#   JZB_IP=192.168.1.10              IP del servidor, si no se usa dominio (por defecto se detecta)
#   JZB_HTTPS_PORT=9443              puerto HTTPS (1024 o mas)
#   JZB_BIND=0.0.0.0                 IP donde escucha (0.0.0.0 = todas; 127.0.0.1 = solo este equipo)
# ==============================================================================

set -euo pipefail

APP_NAME="jzbill"
APP_USER="jzbill"
BASE_DIR="${JZB_DIR:-/opt/jzbill}"
RELEASES="$BASE_DIR/releases"
ENV_DIR="/etc/$APP_NAME"
ENV_FILE="$ENV_DIR/$APP_NAME.env"
TLS_DIR="$ENV_DIR/tls"
SERVICE="$APP_NAME"
DB_NAME="jzbill_db"
DB_USER="jzbill"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /   # psql como postgres no puede entrar a la carpeta desde la que se corre (por ejemplo /root)

echo "=================================================="
echo "Instalador nativo de JZBill"
echo "=================================================="

# 1. Privilegios, sistema y ubicacion
if [ "$EUID" -ne 0 ]; then
  echo "Error: correr como root (sudo ./install-native.sh)." >&2
  exit 1
fi
if [ ! -f /etc/debian_version ]; then
  echo "Error: este instalador es para Debian/Ubuntu (apt)." >&2
  exit 1
fi
if [ ! -f "$SCRIPT_DIR/backend/jzbill/__init__.py" ] || [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
  echo "Error: falta el resto del repo al lado del script (backend/jzbill/, requirements.txt)." >&2
  echo "Clonarlo completo: git clone https://github.com/Jonnyonz/JZBill.git" >&2
  exit 1
fi
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$SCRIPT_DIR/backend/jzbill/__init__.py")"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: no se pudo leer la version de backend/jzbill/__init__.py." >&2
  exit 1
fi
echo "Version a instalar: $VERSION"

# Direccion de acceso: dominio o IP, y puerto. Lo que no se pasa se toma de la instalacion anterior.
valor_env() { if [ -f "$ENV_FILE" ]; then sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; fi; }
DOMAIN="${JZB_DOMAIN:-$(valor_env JZB_DOMAIN)}"
IP="${JZB_IP:-$(valor_env JZB_IP)}"
if [ -z "$DOMAIN" ] && [ -z "$IP" ]; then
  IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
fi
ES_IP='^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'
if [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "Error: dominio invalido: $DOMAIN" >&2
  exit 1
fi
if [ -z "$DOMAIN" ] && ! [[ "$IP" =~ $ES_IP ]]; then
  echo "Error: no se pudo saber la IP del servidor. Indicarla con JZB_IP=192.168.1.10 (o usar JZB_DOMAIN)." >&2
  exit 1
fi
if [ -n "$DOMAIN" ]; then HOST="$DOMAIN"; else HOST="$IP"; fi
HTTPS_PORT="${JZB_HTTPS_PORT:-$(valor_env JZB_HTTPS_PORT)}"; HTTPS_PORT="${HTTPS_PORT:-9443}"
BIND="${JZB_BIND:-$(valor_env JZB_BIND)}"; BIND="${BIND:-0.0.0.0}"
if ! [[ "$HTTPS_PORT" =~ ^[0-9]+$ ]] || [ "$HTTPS_PORT" -lt 1024 ] || [ "$HTTPS_PORT" -gt 65535 ]; then
  echo "Error: puerto invalido: $HTTPS_PORT (de 1024 a 65535)." >&2
  exit 1
fi
if ! [[ "$BIND" =~ $ES_IP ]]; then
  echo "Error: JZB_BIND tiene que ser una IPv4 (0.0.0.0, 127.0.0.1 o la IP del servidor)." >&2
  exit 1
fi
SITIO="https://$HOST:$HTTPS_PORT"
echo "Direccion: $SITIO"

# El puerto tiene que estar libre, salvo que lo use la propia instalacion anterior.
OCUPANTE="$(ss -ltnpH "( sport = :$HTTPS_PORT )" 2>/dev/null || true)"
if [ -n "$OCUPANTE" ] && ! systemctl is-active --quiet "$SERVICE"; then
  echo "Error: el puerto $HTTPS_PORT ya esta en uso:" >&2
  echo "$OCUPANTE" >&2
  echo "Usar otro con JZB_HTTPS_PORT=9444." >&2
  exit 1
fi

# 2. Paquetes del sistema (sin compilador ni cabeceras de Python)
echo "Instalando paquetes del sistema..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv postgresql postgresql-client openssl curl rsync ca-certificates \
  iproute2 > /dev/null
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Error: hace falta Python 3.11 o mas nuevo (este sistema tiene $(python3 --version 2>&1))." >&2
  echo "Sistemas soportados: Debian 12, Debian 13, Ubuntu 24.04." >&2
  exit 1
fi

# 3. Usuario de sistema sin login (no es dueno del codigo: solo lo lee)
if ! id "$APP_USER" &> /dev/null; then
  echo "Creando usuario de sistema $APP_USER..."
  useradd --system --no-create-home --home-dir "$BASE_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

# 4. Codigo y entorno virtual de esta version
DEST="$RELEASES/$VERSION"
echo "Instalando la version $VERSION en $DEST..."
mkdir -p "$RELEASES"
rsync -a --delete --exclude '.git' --exclude 'venv' --exclude '.venv' --exclude 'wheelhouse' --exclude 'dist' \
  --exclude '__pycache__' --exclude '.env' --exclude 'tests' --exclude 'requirements-dev.*' --exclude 'docs' --exclude 'CLAUDE.md' \
  "$SCRIPT_DIR"/ "$DEST"/
if [ ! -x "$DEST/venv/bin/python" ]; then
  python3 -m venv "$DEST/venv"
fi
PIP_ORIGEN=()
if [ -d "$SCRIPT_DIR/wheelhouse" ]; then
  echo "Usando wheelhouse/ (sin internet)."
  PIP_ORIGEN=(--no-index --find-links "$SCRIPT_DIR/wheelhouse")
fi
"$DEST/venv/bin/pip" install --quiet --disable-pip-version-check --require-hashes --only-binary=:all: \
  "${PIP_ORIGEN[@]}" -r "$DEST/requirements.txt"
chown -R root:root "$DEST"
chmod -R a+rX,go-w "$DEST"

# 5. PostgreSQL: rol y base propios en el cluster del servidor
echo "Verificando PostgreSQL..."
systemctl enable --now postgresql > /dev/null
ROL_EXISTE=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")
BASE_EXISTE=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")
if [ -f "$ENV_FILE" ]; then
  echo "Ya existe $ENV_FILE: se reutilizan los secretos (no se pisan)."
  DB_PASSWORD="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$ENV_FILE")"
  SETUP_TOKEN="$(sed -n 's/^SETUP_TOKEN=//p' "$ENV_FILE")"
  if [ "$ROL_EXISTE" != "1" ]; then
    echo "Error: $ENV_FILE existe pero el rol $DB_USER no existe en PostgreSQL. Revisar a mano." >&2
    exit 1
  fi
else
  if [ "$ROL_EXISTE" = "1" ]; then
    echo "Error: el rol $DB_USER ya existe en PostgreSQL pero no hay $ENV_FILE con su clave." >&2
    echo "No se genera una clave nueva porque romperia el acceso existente. Revisar a mano." >&2
    exit 1
  fi
  echo "Generando secretos..."
  DB_PASSWORD="$(openssl rand -hex 24)"
  SETUP_TOKEN="$(openssl rand -hex 24)"
fi
if [ "$ROL_EXISTE" != "1" ]; then
  echo "Creando rol $DB_USER..."
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';"
fi
if [ "$BASE_EXISTE" != "1" ]; then
  echo "Creando base $DB_NAME..."
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
fi
# Por defecto PostgreSQL deja que cualquier rol se conecte a cualquier base: solo jzbill entra a la suya
# (las otras apps del servidor, como Tracker360, no).
sudo -u postgres psql -q -v ON_ERROR_STOP=1 \
  -c "REVOKE CONNECT, TEMPORARY ON DATABASE $DB_NAME FROM PUBLIC;" \
  -c "GRANT CONNECT, TEMPORARY ON DATABASE $DB_NAME TO $DB_USER;"

# 6. Clave maestra de los secretos cifrados (certificados de ARCA, claves). Se genera UNA vez y nunca se pisa:
#    si se pierde, los secretos guardados no se pueden recuperar (hay que volver a cargarlos).
mkdir -p "$ENV_DIR"
CLAVE_SECRETOS="$ENV_DIR/clave-secretos"
if [ ! -f "$CLAVE_SECRETOS" ]; then
  HAY_SECRETOS=0
  if [ "$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT to_regclass('public.certificados') IS NOT NULL")" = "t" ] \
      && [ "$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT EXISTS (SELECT 1 FROM certificados)")" = "t" ]; then
    HAY_SECRETOS=1
  fi
  if [ "$HAY_SECRETOS" = "1" ]; then
    echo "Error: falta $CLAVE_SECRETOS pero la base tiene certificados cifrados con ella." >&2
    echo "Restaurar la clave desde su respaldo. Una clave nueva dejaria esos certificados inutilizables." >&2
    exit 1
  fi
  echo "Generando la clave maestra de secretos..."
  (umask 077 && head -c 32 /dev/urandom | base64 -w0 > "$CLAVE_SECRETOS.tmp" && echo >> "$CLAVE_SECRETOS.tmp")
  mv -f "$CLAVE_SECRETOS.tmp" "$CLAVE_SECRETOS"
fi
chown root:"$APP_USER" "$CLAVE_SECRETOS"
chmod 640 "$CLAVE_SECRETOS"

# 7. Certificado HTTPS. Uno propio (sin .autofirmado) no se toca. El autofirmado se rehace si cambio el nombre
#    o la IP, o si vence en menos de 30 dias.
mkdir -p "$TLS_DIR"
if [[ "$HOST" =~ $ES_IP ]]; then SAN="IP:$HOST"; else SAN="DNS:$HOST"; fi
REHACER=0
if [ ! -f "$TLS_DIR/cert.pem" ] || [ ! -f "$TLS_DIR/key.pem" ]; then
  REHACER=1
elif [ -f "$TLS_DIR/.autofirmado" ] && { [ "$(cat "$TLS_DIR/.autofirmado")" != "$SAN" ] \
    || ! openssl x509 -checkend 2592000 -noout -in "$TLS_DIR/cert.pem" > /dev/null; }; then
  REHACER=1
fi
if [ "$REHACER" = "1" ]; then
  echo "Generando certificado HTTPS autofirmado para $HOST..."
  (umask 077 && openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 825 -subj "/CN=$HOST" \
    -addext "subjectAltName=$SAN" -addext "extendedKeyUsage=serverAuth" \
    -keyout "$TLS_DIR/key.pem.tmp" -out "$TLS_DIR/cert.pem.tmp" 2> /dev/null)
  mv -f "$TLS_DIR/key.pem.tmp" "$TLS_DIR/key.pem"
  mv -f "$TLS_DIR/cert.pem.tmp" "$TLS_DIR/cert.pem"
  echo "$SAN" > "$TLS_DIR/.autofirmado"
fi
chown root:"$APP_USER" "$TLS_DIR/key.pem"
chmod 640 "$TLS_DIR/key.pem"
chmod 644 "$TLS_DIR/cert.pem"

# 8. Configuracion (se reescribe con los mismos secretos; root:jzbill 0640)
echo "Escribiendo $ENV_FILE..."
ADICIONALES=""
if [ -f "$ENV_FILE" ]; then
  # Lo que el administrador agrego a mano se conserva.
  ADICIONALES="$(grep -Ev '^(#|$|POSTGRES_|SETUP_TOKEN=|SECRETS_KEY_FILE=|PUBLIC_URL=|TRUSTED_PROXIES=|COOKIES_SECURE=|APP_PORT=|JZB_|PYTHONDONTWRITEBYTECODE=)' "$ENV_FILE" || true)"
fi
TMP_ENV="$(mktemp "$ENV_DIR/.env.XXXXXX")"
cat > "$TMP_ENV" <<EOF
# Generado por install-native.sh (se vuelve a escribir en cada instalacion; las lineas agregadas a mano
# al final se conservan). No versionar ni copiar a otro servidor tal cual.
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=$DB_NAME
POSTGRES_USER=$DB_USER
POSTGRES_PASSWORD=$DB_PASSWORD
SETUP_TOKEN=$SETUP_TOKEN
PUBLIC_URL=$SITIO
TRUSTED_PROXIES=
COOKIES_SECURE=true
JZB_INSTALACION=nativa
JZB_DOMAIN=$DOMAIN
JZB_IP=$IP
JZB_HTTPS_PORT=$HTTPS_PORT
JZB_BIND=$BIND
SECRETS_KEY_FILE=$CLAVE_SECRETOS
PYTHONDONTWRITEBYTECODE=1
EOF
if [ -n "$ADICIONALES" ]; then
  printf '%s\n' "$ADICIONALES" >> "$TMP_ENV"
fi
chown root:"$APP_USER" "$TMP_ENV"
chmod 640 "$TMP_ENV"
mv -f "$TMP_ENV" "$ENV_FILE"

# 9. Version en uso y servicio systemd
ln -sfn "$DEST" "$BASE_DIR/current.tmp"
mv -Tf "$BASE_DIR/current.tmp" "$BASE_DIR/current"

echo "Escribiendo el servicio systemd..."
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=JZBill (facturacion electronica ARCA)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$BASE_DIR/current
EnvironmentFile=$ENV_FILE
Environment=JZBILL_ENV_FILE=$ENV_FILE
ExecStart=$BASE_DIR/current/venv/bin/uvicorn jzbill.main:app --app-dir $BASE_DIR/current/backend --host $BIND --port $HTTPS_PORT --ssl-certfile $TLS_DIR/cert.pem --ssl-keyfile $TLS_DIR/key.pem --workers 1 --no-proxy-headers --no-server-header
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
RestrictNamespaces=yes
LockPersonality=yes
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0077
MemoryMax=192M

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE" > /dev/null
systemctl restart "$SERVICE"

echo "Esperando que el servicio responda..."
if [ "$BIND" = "0.0.0.0" ]; then LOCAL="127.0.0.1"; else LOCAL="$BIND"; fi
OK=0
for _ in $(seq 1 30); do
  # -k: es solo el chequeo local de que responde; el certificado lo valida cada navegador.
  if curl -fsSk --max-time 5 "https://$LOCAL:$HTTPS_PORT/api/health" 2>/dev/null | grep -q "\"version\":\"$VERSION\""; then
    OK=1
    break
  fi
  sleep 2
done
if [ "$OK" != "1" ]; then
  echo "Error: el servicio no responde en https://$LOCAL:$HTTPS_PORT/api/health." >&2
  echo "Ver el detalle con: journalctl -u $SERVICE -n 50 --no-pager" >&2
  exit 1
fi

# 10. Resumen
USUARIOS=$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT count(*) FROM usuarios" 2>/dev/null || echo 0)
echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA - JZBill $VERSION"
echo "================================================================="
echo "Pagina: $SITIO"
if [ -f "$TLS_DIR/.autofirmado" ]; then
  echo "Certificado autofirmado: cada terminal tiene que confiar una vez en $TLS_DIR/cert.pem."
fi
if [ "$USUARIOS" = "0" ]; then
  echo ""
  echo "Token de configuracion inicial: $SETUP_TOKEN"
  echo "La pagina lo pide para crear el administrador (sirve una sola vez)."
fi
echo ""
echo "IMPORTANTE: respaldar $CLAVE_SECRETOS APARTE del respaldo de la base."
echo "Sin esa clave los certificados guardados no se pueden recuperar; con las dos juntas, quedan expuestos."
echo "================================================================="
