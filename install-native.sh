#!/bin/bash
# ==============================================================================
# Instalador nativo (sin Docker) de JZFactura - ESQUELETO de la Fase 0
# ==============================================================================
# Adaptado de install-native.sh de JZ_Middle_ML-Tracker (mismo patron). Para Debian 12/13 y Ubuntu 24.04
# (apt, Python 3.11 o mas nuevo). Correr como root desde la raiz del repo clonado o de una version
# descargada:
#
#   sudo JZF_DOMAIN=factura.cliente.com ./install-native.sh
#
# Se instala en el MISMO servidor que el Tracker360 del cliente. Queda asi:
#   /opt/jzfactura/releases/<version>/   codigo + su propio venv (una carpeta por version)
#   /opt/jzfactura/current               enlace a la version en uso (el actualizador lo va a cambiar)
#   /etc/jzfactura/jzfactura.env         configuracion y secretos (root:jzfactura, 0640)
#   servicio systemd "jzfactura"         uvicorn en 127.0.0.1:8050, un worker
#   base "jzfactura_db" y rol "jzfactura" propios en el PostgreSQL del servidor
#   Caddy delante con HTTPS para el subdominio
#
# Pendiente para la Fase 9: actualizador jz-factura-actualizar (respaldo, migracion, chequeo, vuelta atras).
#
# Idempotente: se puede volver a correr. Los secretos ya generados (clave de la base, token de
# instalacion) no se pisan. Sin compilador: las dependencias se instalan solo con paquetes binarios
# (wheels) y verificando los hashes de requirements.txt; si hay una carpeta wheelhouse/ al lado, se usa
# esa (instalacion sin internet).
#
# Variables opcionales:
#   JZF_DOMAIN=factura.cliente.com   subdominio (obligatorio la primera vez; despues se reutiliza)
#   JZF_CADDY=0                      no instalar ni tocar Caddy (si el servidor ya usa otro proxy HTTPS)
#   JZF_TLS_INTERNAL=1               certificado de la CA local de Caddy (red interna sin dominio publico)
#   JZF_PORT=8050                    puerto local del servicio
# ==============================================================================

set -euo pipefail

APP_NAME="jzfactura"
APP_USER="jzfactura"
BASE_DIR="${JZF_DIR:-/opt/jzfactura}"
RELEASES="$BASE_DIR/releases"
ENV_DIR="/etc/$APP_NAME"
ENV_FILE="$ENV_DIR/$APP_NAME.env"
SERVICE="$APP_NAME"
DB_NAME="jzfactura_db"
DB_USER="jzfactura"
APP_PORT="${JZF_PORT:-8050}"
APP_BIND="127.0.0.1"
CADDY="${JZF_CADDY:-1}"
TLS_INTERNAL="${JZF_TLS_INTERNAL:-0}"
DOMAIN="${JZF_DOMAIN:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /   # psql como postgres no puede entrar a la carpeta desde la que se corre (por ejemplo /root)

echo "=================================================="
echo "Instalador nativo de JZFactura"
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
if [ ! -f "$SCRIPT_DIR/backend/jzfactura/__init__.py" ] || [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
  echo "Error: correr el script desde la raiz del repo (faltan backend/jzfactura/ o requirements.txt)." >&2
  exit 1
fi
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$SCRIPT_DIR/backend/jzfactura/__init__.py")"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: no se pudo leer la version de backend/jzfactura/__init__.py." >&2
  exit 1
fi
echo "Version a instalar: $VERSION"

# Subdominio: el de JZF_DOMAIN, el de la instalacion anterior o se pregunta.
if [ -z "$DOMAIN" ] && [ -f "$ENV_FILE" ]; then
  DOMAIN="$(sed -n 's#^PUBLIC_URL=https\?://##p' "$ENV_FILE" | cut -d/ -f1)"
fi
if [ -z "$DOMAIN" ] && [ -t 0 ]; then
  read -r -p "Subdominio del facturador (ej. factura.suempresa.com): " DOMAIN || DOMAIN=""
fi
if ! [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "Error: falta el subdominio (JZF_DOMAIN=factura.suempresa.com)." >&2
  exit 1
fi

# 2. Paquetes del sistema (sin compilador ni cabeceras de Python)
echo "Instalando paquetes del sistema..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv postgresql postgresql-client openssl curl rsync ca-certificates \
  gnupg iproute2 > /dev/null
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

# 6. Configuracion (se reescribe con los mismos secretos; root:jzfactura 0640)
echo "Escribiendo $ENV_FILE..."
mkdir -p "$ENV_DIR"
ADICIONALES=""
if [ -f "$ENV_FILE" ]; then
  # Lo que el administrador agrego a mano se conserva.
  ADICIONALES="$(grep -Ev '^(#|$|POSTGRES_|SETUP_TOKEN=|PUBLIC_URL=|TRUSTED_PROXIES=|COOKIES_SECURE=|APP_PORT=|JZF_INSTALACION=|PYTHONDONTWRITEBYTECODE=)' "$ENV_FILE" || true)"
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
PUBLIC_URL=https://$DOMAIN
TRUSTED_PROXIES=127.0.0.1/32,::1/128
COOKIES_SECURE=true
APP_PORT=$APP_PORT
JZF_INSTALACION=nativa
PYTHONDONTWRITEBYTECODE=1
EOF
if [ -n "$ADICIONALES" ]; then
  printf '%s\n' "$ADICIONALES" >> "$TMP_ENV"
fi
chown root:"$APP_USER" "$TMP_ENV"
chmod 640 "$TMP_ENV"
mv -f "$TMP_ENV" "$ENV_FILE"

# 7. Version en uso y servicio systemd
ln -sfn "$DEST" "$BASE_DIR/current.tmp"
mv -Tf "$BASE_DIR/current.tmp" "$BASE_DIR/current"

echo "Escribiendo el servicio systemd..."
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=JZFactura (facturacion electronica ARCA)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$BASE_DIR/current
EnvironmentFile=$ENV_FILE
Environment=JZFACTURA_ENV_FILE=$ENV_FILE
ExecStart=$BASE_DIR/current/venv/bin/uvicorn jzfactura.main:app --app-dir $BASE_DIR/current/backend --host $APP_BIND --port $APP_PORT --workers 1 --no-proxy-headers
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
OK=0
for _ in $(seq 1 30); do
  if curl -fsS "http://$APP_BIND:$APP_PORT/api/health" 2>/dev/null | grep -q "\"version\":\"$VERSION\""; then
    OK=1
    break
  fi
  sleep 2
done
if [ "$OK" != "1" ]; then
  echo "Error: el servicio no responde en http://$APP_BIND:$APP_PORT/api/health." >&2
  echo "Ver el detalle con: journalctl -u $SERVICE -n 50 --no-pager" >&2
  exit 1
fi
echo "Servicio en marcha (version $VERSION)."

# 8. Proxy HTTPS (Caddy). Si los puertos 80/443 los usa otro programa, no se toca nada.
if [ "$TLS_INTERNAL" = "1" ]; then
  TLS_LINEA="tls internal"
else
  TLS_LINEA="# certificado automatico: el subdominio tiene que apuntar a este servidor (puertos 80 y 443 abiertos)"
fi
BLOQUE="$DOMAIN {
    $TLS_LINEA
    reverse_proxy $APP_BIND:$APP_PORT
}"
if [ "$CADDY" = "1" ]; then
  OCUPADOS="$(ss -ltnpH '( sport = :80 or sport = :443 )' 2>/dev/null | grep -v '"caddy"' || true)"
  if [ -n "$OCUPADOS" ]; then
    echo "Aviso: los puertos 80/443 los usa otro programa; no se instala Caddy." >&2
    echo "$OCUPADOS" >&2
    CADDY="0"
  fi
fi
if [ "$CADDY" = "1" ]; then
  if ! command -v caddy &> /dev/null; then
    echo "Instalando Caddy..."
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy > /dev/null
  fi
  CADDYFILE="/etc/caddy/Caddyfile"
  # Mismo criterio que los otros instaladores de JZTech: el Caddyfile de ejemplo compite por el puerto 80.
  if [ ! -f "$CADDYFILE" ] || ! grep -q "# Gestionado por los instaladores nativos de JZTech" "$CADDYFILE"; then
    printf '%s\n%s\n' "# Gestionado por los instaladores nativos de JZTech (install-native.sh)." \
      "# Cada app agrega su propio bloque de dominio abajo." > "$CADDYFILE"
  fi
  if ! grep -q "^$DOMAIN {" "$CADDYFILE"; then
    printf '\n# jzfactura\n%s\n' "$BLOQUE" >> "$CADDYFILE"
  fi
  if caddy validate --config "$CADDYFILE" --adapter caddyfile > /dev/null 2>&1; then
    systemctl enable --now caddy > /dev/null
    systemctl reload caddy 2> /dev/null || systemctl restart caddy
  else
    echo "Aviso: el Caddyfile no valida; no se recargo Caddy. Revisar $CADDYFILE." >&2
  fi
  if [ "$TLS_INTERNAL" = "1" ] && ! getent hosts "$DOMAIN" > /dev/null 2>&1; then
    echo "127.0.0.1 $DOMAIN" >> /etc/hosts   # solo para que el propio servidor lo resuelva
  fi
fi

# 9. Resumen
USUARIOS=$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT count(*) FROM usuarios" 2>/dev/null || echo 0)
echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA - JZFactura $VERSION"
echo "================================================================="
echo "Pagina: https://$DOMAIN"
if [ "$CADDY" != "1" ]; then
  echo "Caddy no se configuro. Agregar al proxy HTTPS del servidor el equivalente a:"
  echo "$BLOQUE"
elif [ "$TLS_INTERNAL" = "1" ]; then
  echo "Certificado de la CA local de Caddy: cada terminal tiene que confiar en esa CA."
fi
if [ "$USUARIOS" = "0" ]; then
  echo ""
  echo "Token de configuracion inicial: $SETUP_TOKEN"
  echo "La pagina lo pide para crear el administrador (sirve una sola vez)."
fi
echo "================================================================="
