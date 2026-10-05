#!/bin/bash
# ==============================================================================
# Instalador nativo (sin Docker) de JZBill - ESQUELETO de la Fase 0
# ==============================================================================
# Adaptado de install-native.sh de JZ_Middle_ML-Tracker (mismo patron). Para Debian 12/13 y Ubuntu 24.04
# (apt, Python 3.11 o mas nuevo). Correr como root desde la raiz del repo clonado o de una version
# descargada:
#
#   sudo ./install-native.sh                                  por IP: https://<ip del servidor>:8443
#   sudo JZB_DOMAIN=factura.cliente.com ./install-native.sh   dominio: https://factura.cliente.com
#
# Se instala en el MISMO servidor que el Tracker360 del cliente. Queda asi:
#   /opt/jzbill/releases/<version>/   codigo + su propio venv (una carpeta por version)
#   /opt/jzbill/current               enlace a la version en uso (el actualizador lo va a cambiar)
#   /etc/jzbill/jzbill.env            configuracion y secretos (root:jzbill, 0640)
#   servicio systemd "jzbill"         uvicorn en 127.0.0.1:8050, un worker
#   base "jzbill_db" y rol "jzbill" propios en el PostgreSQL del servidor
#   Caddy delante con HTTPS (la sesion usa cookies Secure: sin HTTPS no se puede ingresar)
#
# Por IP, el HTTPS va por defecto al puerto 8443: el 443 de la IP lo usa Tracker360. El certificado lo da la
# CA local de Caddy (la misma de Tracker360): cada terminal tiene que confiar en esa CA una sola vez.
#
# El Caddyfile se comparte con las otras apps de JZTech: solo se le agrega el bloque de JZBill. Si existe y no
# lo armo un instalador de JZTech, NO se toca: se muestra el bloque para agregarlo a mano. Si al agregarlo
# deja de validar, se vuelve al Caddyfile anterior.
#
# Pendiente para la Fase 9: actualizador jz-bill-actualizar (respaldo, migracion, chequeo, vuelta atras).
#
# Idempotente: se puede volver a correr. Los secretos ya generados (clave de la base, token de
# instalacion) no se pisan. Sin compilador: las dependencias se instalan solo con paquetes binarios
# (wheels) y verificando los hashes de requirements.txt; si hay una carpeta wheelhouse/ al lado, se usa
# esa (instalacion sin internet).
#
# Variables opcionales (si no se pasan, se reutilizan las de la instalacion anterior):
#   JZB_DOMAIN=factura.cliente.com   dominio (Caddy saca el certificado solo; tiene que apuntar aca)
#   JZB_IP=192.168.1.10              IP del servidor, si no se usa dominio (por defecto se detecta)
#   JZB_HTTPS_PORT=8443              puerto HTTPS (por defecto 8443 con IP y 443 con dominio)
#   JZB_TLS_INTERNAL=1               con dominio, usar igual la CA local de Caddy (dominio solo de la red interna)
#   JZB_CADDY=0                      no instalar ni tocar Caddy (si el servidor ya usa otro proxy HTTPS)
#   JZB_PORT=8050                    puerto local del servicio
# ==============================================================================

set -euo pipefail

APP_NAME="jzbill"
APP_USER="jzbill"
BASE_DIR="${JZB_DIR:-/opt/jzbill}"
RELEASES="$BASE_DIR/releases"
ENV_DIR="/etc/$APP_NAME"
ENV_FILE="$ENV_DIR/$APP_NAME.env"
SERVICE="$APP_NAME"
DB_NAME="jzbill_db"
DB_USER="jzbill"
APP_BIND="127.0.0.1"
CADDY="${JZB_CADDY:-1}"
TLS_INTERNAL="${JZB_TLS_INTERNAL:-0}"
CADDYFILE="/etc/caddy/Caddyfile"
MARCA="# Gestionado por los instaladores nativos de JZTech"
CA_LOCAL="/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"

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
  echo "Error: correr el script desde la raiz del repo (faltan backend/jzbill/ o requirements.txt)." >&2
  exit 1
fi
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$SCRIPT_DIR/backend/jzbill/__init__.py")"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: no se pudo leer la version de backend/jzbill/__init__.py." >&2
  exit 1
fi
echo "Version a instalar: $VERSION"

# Direccion de acceso: dominio o IP, y puertos. Lo que no se pasa se toma de la instalacion anterior.
valor_env() { if [ -f "$ENV_FILE" ]; then sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; fi; }
DOMAIN="${JZB_DOMAIN:-$(valor_env JZB_DOMAIN)}"
IP="${JZB_IP:-$(valor_env JZB_IP)}"
if [ -z "$DOMAIN" ] && [ -z "$IP" ]; then
  IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
fi
if [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "Error: dominio invalido: $DOMAIN" >&2
  exit 1
fi
if [ -z "$DOMAIN" ] && ! [[ "$IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
  echo "Error: no se pudo saber la IP del servidor. Indicarla con JZB_IP=192.168.1.10 (o usar JZB_DOMAIN)." >&2
  exit 1
fi
if [ -n "$DOMAIN" ]; then HOST="$DOMAIN"; PUERTO_DEF=443; else HOST="$IP"; PUERTO_DEF=8443; fi
HTTPS_PORT="${JZB_HTTPS_PORT:-$(valor_env JZB_HTTPS_PORT)}"; HTTPS_PORT="${HTTPS_PORT:-$PUERTO_DEF}"
APP_PORT="${JZB_PORT:-$(valor_env APP_PORT)}"; APP_PORT="${APP_PORT:-8050}"
for PUERTO in "$HTTPS_PORT" "$APP_PORT"; do
  if ! [[ "$PUERTO" =~ ^[0-9]+$ ]] || [ "$PUERTO" -lt 1 ] || [ "$PUERTO" -gt 65535 ]; then
    echo "Error: puerto invalido: $PUERTO" >&2
    exit 1
  fi
done
if [ "$HTTPS_PORT" = "443" ]; then SITIO="https://$HOST"; else SITIO="https://$HOST:$HTTPS_PORT"; fi
echo "Direccion: $SITIO"

# El puerto local tiene que estar libre, salvo que lo use la propia instalacion anterior.
OCUPANTE="$(ss -ltnpH "( sport = :$APP_PORT )" 2>/dev/null || true)"
if [ -n "$OCUPANTE" ] && ! systemctl is-active --quiet "$SERVICE"; then
  echo "Error: el puerto local $APP_PORT ya esta en uso:" >&2
  echo "$OCUPANTE" >&2
  echo "Usar otro puerto con JZB_PORT=8051." >&2
  exit 1
fi

# La direccion HTTPS no puede ser la de otra app del Caddyfile compartido. Se revisa ANTES de cambiar nada.
PRIMERA="$SITIO {"
if [ "$CADDY" = "1" ] && [ -f "$CADDYFILE" ] && grep -qxF "$PRIMERA" "$CADDYFILE" \
    && [ "$(grep -xF -B1 "$PRIMERA" "$CADDYFILE" | head -n1)" != "# jzbill" ]; then
  echo "Error: la direccion $SITIO ya la usa otra app en $CADDYFILE. Elegir otro puerto con JZB_HTTPS_PORT." >&2
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
# Por defecto PostgreSQL deja que cualquier rol se conecte a cualquier base: solo jzbill entra a la suya
# (las otras apps del servidor, como Tracker360, no).
sudo -u postgres psql -q -v ON_ERROR_STOP=1 \
  -c "REVOKE CONNECT, TEMPORARY ON DATABASE $DB_NAME FROM PUBLIC;" \
  -c "GRANT CONNECT, TEMPORARY ON DATABASE $DB_NAME TO $DB_USER;"

# 6. Configuracion (se reescribe con los mismos secretos; root:jzbill 0640)
echo "Escribiendo $ENV_FILE..."
mkdir -p "$ENV_DIR"
ADICIONALES=""
if [ -f "$ENV_FILE" ]; then
  # Lo que el administrador agrego a mano se conserva.
  ADICIONALES="$(grep -Ev '^(#|$|POSTGRES_|SETUP_TOKEN=|PUBLIC_URL=|TRUSTED_PROXIES=|COOKIES_SECURE=|APP_PORT=|JZB_(INSTALACION|DOMAIN|IP|HTTPS_PORT)=|PYTHONDONTWRITEBYTECODE=)' "$ENV_FILE" || true)"
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
TRUSTED_PROXIES=127.0.0.1/32,::1/128
COOKIES_SECURE=true
APP_PORT=$APP_PORT
JZB_INSTALACION=nativa
JZB_DOMAIN=$DOMAIN
JZB_IP=$IP
JZB_HTTPS_PORT=$HTTPS_PORT
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
Description=JZBill (facturacion electronica ARCA)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$BASE_DIR/current
EnvironmentFile=$ENV_FILE
Environment=JZBILL_ENV_FILE=$ENV_FILE
ExecStart=$BASE_DIR/current/venv/bin/uvicorn jzbill.main:app --app-dir $BASE_DIR/current/backend --host $APP_BIND --port $APP_PORT --workers 1 --no-proxy-headers --no-server-header
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

# 8. Proxy HTTPS (Caddy), compartido con las otras apps de JZTech del servidor.
if [ -z "$DOMAIN" ] || [ "$TLS_INTERNAL" = "1" ]; then
  TLS_LINEA="tls internal"
else
  TLS_LINEA="# certificado automatico: el dominio tiene que apuntar a este servidor"
fi
BLOQUE="$PRIMERA
    $TLS_LINEA
    header {
        Strict-Transport-Security \"max-age=31536000\"
        -Server
    }
    reverse_proxy $APP_BIND:$APP_PORT
}"
if [ "$CADDY" = "1" ]; then
  EN_HTTPS="$(ss -ltnpH "( sport = :$HTTPS_PORT )" 2>/dev/null | grep -v '"caddy"' || true)"
  EN_80="$(ss -ltnpH '( sport = :80 )' 2>/dev/null | grep -v '"caddy"' || true)"
  if [ -n "$EN_HTTPS" ]; then
    echo "Aviso: el puerto $HTTPS_PORT lo usa otro programa; no se configura Caddy (elegir otro con JZB_HTTPS_PORT)." >&2
    echo "$EN_HTTPS" >&2
    CADDY="0"
  elif [ -f "$CADDYFILE" ] && ! grep -qF "$MARCA" "$CADDYFILE"; then
    echo "Aviso: $CADDYFILE no lo armo un instalador de JZTech; no se modifica." >&2
    CADDY="0"
  elif [ -n "$EN_80" ]; then
    echo "Aviso: el puerto 80 lo usa otro programa; Caddy atiende solo HTTPS, sin redireccion desde http." >&2
  fi
fi
if [ "$CADDY" = "1" ]; then
  mkdir -p /etc/caddy
  RESPALDO_CADDY=""
  if [ -f "$CADDYFILE" ]; then
    RESPALDO_CADDY="$(mktemp /etc/caddy/.Caddyfile.jzbill.XXXXXX)"
    cp -p "$CADDYFILE" "$RESPALDO_CADDY"
  else
    # Caddyfile nuevo. Se escribe antes de instalar Caddy para que no arranque con el de ejemplo (puerto 80).
    GLOBAL=""
    if [ -n "$EN_80" ]; then GLOBAL=$'{\n\tauto_https disable_redirects\n}\n'; fi
    printf '%s%s\n%s\n' "$GLOBAL" "$MARCA (install-native.sh)." "# Cada app agrega su propio bloque de sitio abajo." > "$CADDYFILE"
  fi
  # Bloque propio siempre al dia: se quita el de una instalacion anterior (desde "# jzbill" hasta su "}",
  # con las lineas en blanco de antes) y se agrega el actual. El resto del Caddyfile no se toca.
  awk '/^# jzbill$/ { propio = 1; blancos = ""; next }
       propio { if ($0 == "}") propio = 0; next }
       /^$/ { blancos = blancos "\n"; next }
       { printf "%s", blancos; blancos = ""; print }' "$CADDYFILE" > "$CADDYFILE.jzbill.tmp"
  printf '\n# jzbill\n%s\n' "$BLOQUE" >> "$CADDYFILE.jzbill.tmp"
  chmod --reference="$CADDYFILE" "$CADDYFILE.jzbill.tmp" 2>/dev/null || true
  mv -f "$CADDYFILE.jzbill.tmp" "$CADDYFILE"
  if ! command -v caddy &> /dev/null; then
    echo "Instalando Caddy..."
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -o Dpkg::Options::=--force-confold caddy > /dev/null 2>&1; then
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
      apt-get update -qq
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -o Dpkg::Options::=--force-confold caddy > /dev/null
    fi
  fi
  if caddy validate --config "$CADDYFILE" --adapter caddyfile > /dev/null 2>&1; then
    systemctl enable --now caddy > /dev/null
    systemctl reload caddy 2> /dev/null || systemctl restart caddy
    # Se espera a que el HTTPS responda (Caddy emite el certificado unos segundos despues de recargar).
    CURL_CA=()
    if [ "$TLS_LINEA" = "tls internal" ] && [ -f "$CA_LOCAL" ]; then CURL_CA=(--cacert "$CA_LOCAL"); fi
    # Con dominio se fuerza la conexion local (--resolve); con IP se usa la IP real: sin nombre (SNI), Caddy
    # elige el certificado por la IP de la conexion, y por 127.0.0.1 no tiene ninguno.
    if [ -n "$DOMAIN" ]; then CURL_CA+=(--resolve "$HOST:$HTTPS_PORT:127.0.0.1"); fi
    HTTPS_OK=0
    for _ in $(seq 1 15); do
      if curl -fsS --max-time 5 "${CURL_CA[@]}" "$SITIO/api/health" 2>/dev/null \
          | grep -q "\"version\":\"$VERSION\""; then
        HTTPS_OK=1
        break
      fi
      sleep 2
    done
    if [ "$HTTPS_OK" = "1" ]; then
      echo "HTTPS en marcha: $SITIO"
    else
      echo "Aviso: el HTTPS todavia no responde en $SITIO. Detalle: journalctl -u caddy -n 50 --no-pager" >&2
    fi
  else
    # No se deja un Caddyfile roto: las otras apps del servidor dependen de el.
    if [ -n "$RESPALDO_CADDY" ]; then
      mv -f "$RESPALDO_CADDY" "$CADDYFILE"
      RESPALDO_CADDY=""
      echo "Aviso: con el bloque de JZBill el Caddyfile no validaba; se dejo como estaba." >&2
    else
      echo "Aviso: el Caddyfile no valida; no se recargo Caddy. Revisar $CADDYFILE." >&2
    fi
    CADDY="0"
  fi
  if [ -n "$RESPALDO_CADDY" ]; then rm -f "$RESPALDO_CADDY"; fi
fi

# 9. Resumen
USUARIOS=$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT count(*) FROM usuarios" 2>/dev/null || echo 0)
echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA - JZBill $VERSION"
echo "================================================================="
echo "Pagina: $SITIO"
if [ "$CADDY" != "1" ]; then
  echo "Caddy no se configuro. Agregar al proxy HTTPS del servidor el equivalente a:"
  echo "$BLOQUE"
elif [ "$TLS_LINEA" = "tls internal" ]; then
  echo "Certificado de la CA local de Caddy: cada terminal tiene que confiar en esa CA ($CA_LOCAL)."
fi
if [ "$USUARIOS" = "0" ]; then
  echo ""
  echo "Token de configuracion inicial: $SETUP_TOKEN"
  echo "La pagina lo pide para crear el administrador (sirve una sola vez)."
fi
echo "================================================================="
