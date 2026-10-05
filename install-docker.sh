#!/bin/bash
# ==============================================================================
# Instalador con Docker de JZBill (app + PostgreSQL + Caddy con HTTPS)
# ==============================================================================
# Alternativa a install-native.sh para quien ya usa Docker (por ejemplo, un facturador personal). En equipos con
# pocos recursos conviene la nativa: Docker suma consumo de memoria. Para Linux con Docker Engine y el plugin
# "docker compose" (v2). Correr como root desde la raiz del repo clonado:
#
#   sudo ./install-docker.sh                                  por IP: https://<ip del equipo>:8443
#   sudo JZB_DOMAIN=factura.casa ./install-docker.sh          nombre de la red interna: https://factura.casa:8443
#   sudo JZB_BIND=127.0.0.1 ./install-docker.sh               solo desde este mismo equipo
#
# Queda asi:
#   /etc/jzbill-docker/jzbill.env       configuracion y secretos (root, 0600)
#   /etc/jzbill-docker/clave-secretos   clave maestra de los certificados de ARCA (solo la lee la app)
#   /etc/jzbill-docker/Caddyfile        sitio HTTPS
#   /etc/jzbill-docker/ca-local.crt     certificado de la CA local de Caddy (instalarlo en cada terminal)
#   volumenes jzbill_db (la base) y jzbill_caddy_data (la CA y los certificados de Caddy)
#
# El HTTPS lo da la CA local de Caddy ("tls internal"): cada terminal tiene que confiar en ca-local.crt una vez.
# Con un dominio publico y certificado de Let's Encrypt, usar install-native.sh.
#
# Idempotente: se puede volver a correr (asi tambien se actualiza, despues de bajar la version nueva del repo).
# Los secretos ya generados no se pisan. Si la base ya existe y falta la clave maestra o la configuracion, se
# corta: una clave nueva dejaria inutilizables los certificados guardados.
#
# Ojo: Docker publica el puerto por encima del firewall del sistema (ufw no lo filtra). Si el equipo esta
# expuesto a internet, usar JZB_BIND=<ip de la red interna> o JZB_BIND=127.0.0.1.
#
# Variables opcionales (si no se pasan, se reutilizan las de la instalacion anterior):
#   JZB_DOMAIN=factura.casa      nombre para entrar (tiene que resolver a este equipo en la red interna)
#   JZB_IP=192.168.1.10          IP del equipo, si no se usa nombre (por defecto se detecta)
#   JZB_HTTPS_PORT=8443          puerto HTTPS publicado
#   JZB_BIND=0.0.0.0             IP del equipo donde se publica el puerto (0.0.0.0 = todas)
#   JZB_SUBRED=172.30.86.0/28    subred de la red "web" de Docker (cambiarla solo si choca con la red local)
#   JZB_CONF=/etc/jzbill-docker  carpeta de configuracion
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${JZB_CONF:-/etc/jzbill-docker}"
ENV_FILE="$CONF/jzbill.env"
CLAVE_SECRETOS="$CONF/clave-secretos"
APP_UID=10001   # el usuario de la app dentro de la imagen (Dockerfile)

echo "=================================================="
echo "Instalador con Docker de JZBill"
echo "=================================================="

# 1. Privilegios, Docker y ubicacion
if [ "$EUID" -ne 0 ]; then
  echo "Error: correr como root (sudo ./install-docker.sh)." >&2
  exit 1
fi
if ! command -v docker &> /dev/null || ! docker compose version &> /dev/null; then
  echo "Error: hace falta Docker Engine con el plugin \"docker compose\" (v2)." >&2
  echo "Debian/Ubuntu: apt install docker.io docker-compose (o el paquete docker-compose-plugin de Docker)." >&2
  exit 1
fi
if ! docker info &> /dev/null; then
  echo "Error: Docker no responde (systemctl start docker)." >&2
  exit 1
fi
if [ ! -f "$SCRIPT_DIR/compose.yaml" ] || [ ! -f "$SCRIPT_DIR/backend/jzbill/__init__.py" ]; then
  echo "Error: correr el script desde la raiz del repo (faltan compose.yaml o backend/jzbill/)." >&2
  exit 1
fi
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$SCRIPT_DIR/backend/jzbill/__init__.py")"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: no se pudo leer la version de backend/jzbill/__init__.py." >&2
  exit 1
fi
echo "Version a instalar: $VERSION"

# 2. Direccion de acceso. Lo que no se pasa se toma de la instalacion anterior.
valor_env() { if [ -f "$ENV_FILE" ]; then sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; fi; }
DOMAIN="${JZB_DOMAIN:-$(valor_env JZB_DOMAIN)}"
IP="${JZB_IP:-$(valor_env JZB_IP)}"
if [ -z "$DOMAIN" ] && [ -z "$IP" ]; then
  IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
fi
if [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "Error: nombre invalido: $DOMAIN" >&2
  exit 1
fi
ES_IP='^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'
if [ -z "$DOMAIN" ] && ! [[ "$IP" =~ $ES_IP ]]; then
  echo "Error: no se pudo saber la IP del equipo. Indicarla con JZB_IP=192.168.1.10 (o usar JZB_DOMAIN)." >&2
  exit 1
fi
if [ -n "$DOMAIN" ]; then HOST="$DOMAIN"; else HOST="$IP"; fi
HTTPS_PORT="${JZB_HTTPS_PORT:-$(valor_env JZB_HTTPS_PORT)}"; HTTPS_PORT="${HTTPS_PORT:-8443}"
BIND="${JZB_BIND:-$(valor_env JZB_BIND)}"; BIND="${BIND:-0.0.0.0}"
SUBRED="${JZB_SUBRED:-$(valor_env JZB_SUBRED)}"; SUBRED="${SUBRED:-172.30.86.0/28}"
if ! [[ "$HTTPS_PORT" =~ ^[0-9]+$ ]] || [ "$HTTPS_PORT" -lt 1 ] || [ "$HTTPS_PORT" -gt 65535 ]; then
  echo "Error: puerto invalido: $HTTPS_PORT" >&2
  exit 1
fi
if ! [[ "$BIND" =~ $ES_IP ]]; then
  echo "Error: JZB_BIND tiene que ser una IPv4 (0.0.0.0, 127.0.0.1 o la IP de la red interna)." >&2
  exit 1
fi
if ! [[ "$SUBRED" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.0/(2[4-8])$ ]]; then
  echo "Error: JZB_SUBRED tiene que ser una red /24 a /28 terminada en .0 (por ejemplo 172.30.86.0/28)." >&2
  exit 1
fi
IP_CADDY="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}.10"
if [ "$HTTPS_PORT" = "443" ]; then SITIO="https://$HOST"; else SITIO="https://$HOST:$HTTPS_PORT"; fi
echo "Direccion: $SITIO"

COMPOSE=(docker compose --project-directory "$SCRIPT_DIR" -f "$SCRIPT_DIR/compose.yaml" --env-file "$ENV_FILE")

# El puerto tiene que estar libre, salvo que lo use la propia instalacion anterior (el Caddy de JZBill).
DB_EXISTE=0
if docker volume inspect jzbill_db &> /dev/null; then DB_EXISTE=1; fi
CADDY_ACTIVO="$(docker ps -q --filter label=com.docker.compose.project=jzbill --filter label=com.docker.compose.service=caddy)"
OCUPANTE="$(ss -ltnH "( sport = :$HTTPS_PORT )" 2>/dev/null || true)"
if [ -n "$OCUPANTE" ] && [ -z "$CADDY_ACTIVO" ]; then
  echo "Error: el puerto $HTTPS_PORT ya esta en uso:" >&2
  echo "$OCUPANTE" >&2
  echo "Usar otro con JZB_HTTPS_PORT=9443." >&2
  exit 1
fi

# 3. Secretos: se generan una sola vez y nunca se pisan
mkdir -p "$CONF"
chmod 700 "$CONF"
if [ -f "$ENV_FILE" ]; then
  echo "Ya existe $ENV_FILE: se reutilizan los secretos (no se pisan)."
  DB_PASSWORD="$(valor_env POSTGRES_PASSWORD)"
  SETUP_TOKEN="$(valor_env SETUP_TOKEN)"
  if [ -z "$DB_PASSWORD" ] || [ -z "$SETUP_TOKEN" ]; then
    echo "Error: $ENV_FILE no tiene POSTGRES_PASSWORD o SETUP_TOKEN. Revisar a mano." >&2
    exit 1
  fi
else
  if [ "$DB_EXISTE" = "1" ]; then
    echo "Error: ya existe el volumen jzbill_db pero no hay $ENV_FILE con la clave de la base." >&2
    echo "No se genera una clave nueva porque romperia el acceso a la base. Restaurar $ENV_FILE del respaldo." >&2
    exit 1
  fi
  echo "Generando secretos..."
  DB_PASSWORD="$(openssl rand -hex 24)"
  SETUP_TOKEN="$(openssl rand -hex 24)"
fi
if [ ! -f "$CLAVE_SECRETOS" ]; then
  if [ "$DB_EXISTE" = "1" ]; then
    echo "Error: falta $CLAVE_SECRETOS pero la base ya existe (puede tener certificados cifrados con ella)." >&2
    echo "Restaurar la clave desde su respaldo. Una clave nueva dejaria esos certificados inutilizables." >&2
    exit 1
  fi
  echo "Generando la clave maestra de secretos..."
  (umask 077 && head -c 32 /dev/urandom | base64 -w0 > "$CLAVE_SECRETOS.tmp" && echo >> "$CLAVE_SECRETOS.tmp")
  mv -f "$CLAVE_SECRETOS.tmp" "$CLAVE_SECRETOS"
fi
# La lee solo el usuario de la app dentro del contenedor (Docker monta el archivo tal cual, con su dueno).
chown "$APP_UID:$APP_UID" "$CLAVE_SECRETOS"
chmod 400 "$CLAVE_SECRETOS"

# 4. Configuracion (se reescribe con los mismos secretos; las lineas agregadas a mano se conservan)
echo "Escribiendo $ENV_FILE..."
ADICIONALES=""
if [ -f "$ENV_FILE" ]; then
  ADICIONALES="$(grep -Ev '^(#|$|POSTGRES_|SETUP_TOKEN=|SECRETS_KEY_FILE=|PUBLIC_URL=|TRUSTED_PROXIES=|COOKIES_SECURE=|JZB_)' "$ENV_FILE" || true)"
fi
TMP_ENV="$(mktemp "$CONF/.env.XXXXXX")"
cat > "$TMP_ENV" <<EOF
# Generado por install-docker.sh (se vuelve a escribir en cada instalacion; las lineas agregadas a mano al
# final se conservan). Lo usan docker compose (--env-file) y la app. No versionar ni copiar tal cual.
POSTGRES_DB=jzbill_db
POSTGRES_USER=jzbill
POSTGRES_PASSWORD=$DB_PASSWORD
SETUP_TOKEN=$SETUP_TOKEN
PUBLIC_URL=$SITIO
COOKIES_SECURE=true
JZB_VERSION=$VERSION
JZB_CONF=$CONF
JZB_DOMAIN=$DOMAIN
JZB_IP=$IP
JZB_HTTPS_PORT=$HTTPS_PORT
JZB_BIND=$BIND
JZB_SUBRED=$SUBRED
JZB_IP_CADDY=$IP_CADDY
EOF
if [ -n "$ADICIONALES" ]; then
  printf '%s\n' "$ADICIONALES" >> "$TMP_ENV"
fi
chmod 600 "$TMP_ENV"
mv -f "$TMP_ENV" "$ENV_FILE"

# 5. Caddy: HTTPS con la CA local. default_sni: entrando por IP el navegador no manda nombre, y dentro de Docker
#    la IP de destino es la del contenedor; asi Caddy usa igual el certificado de $HOST.
cat > "$CONF/Caddyfile.tmp" <<EOF
# Generado por install-docker.sh.
{
	auto_https disable_redirects
	skip_install_trust
	default_sni $HOST
}

https://$HOST {
	tls internal
	header {
		Strict-Transport-Security "max-age=31536000"
		-Server
	}
	reverse_proxy app:8050
}
EOF
chmod 644 "$CONF/Caddyfile.tmp"
mv -f "$CONF/Caddyfile.tmp" "$CONF/Caddyfile"

# 6. Imagen y contenedores
echo "Construyendo la imagen jzbill:$VERSION..."
"${COMPOSE[@]}" build --pull app
echo "Levantando los contenedores..."
"${COMPOSE[@]}" up -d --remove-orphans
# Caddy no relee el Caddyfile solo: se recarga por si cambio la direccion.
"${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null 2>&1 || true

echo "Esperando que la app responda..."
OK=0
for _ in $(seq 1 45); do
  if "${COMPOSE[@]}" exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8050/api/health', timeout=4).read().decode())" 2>/dev/null \
      | grep -q "\"version\":\"$VERSION\""; then
    OK=1
    break
  fi
  sleep 2
done
if [ "$OK" != "1" ]; then
  echo "Error: la app no responde. Ver el detalle con:" >&2
  echo "  docker compose --env-file $ENV_FILE logs --tail 50 app" >&2
  exit 1
fi
echo "App en marcha (version $VERSION)."

# 7. HTTPS y CA local de Caddy (se exporta para instalarla en las terminales; es publica, no es un secreto)
CA_LOCAL="$CONF/ca-local.crt"
if [ "$BIND" = "0.0.0.0" ]; then LOCAL="127.0.0.1"; else LOCAL="$BIND"; fi
HTTPS_OK=0
for _ in $(seq 1 15); do
  if "${COMPOSE[@]}" cp caddy:/data/caddy/pki/authorities/local/root.crt "$CA_LOCAL" > /dev/null 2>&1 \
      && curl -fsS --max-time 5 --cacert "$CA_LOCAL" --connect-to "$HOST:$HTTPS_PORT:$LOCAL:$HTTPS_PORT" \
         "$SITIO/api/health" 2>/dev/null | grep -q "\"version\":\"$VERSION\""; then
    HTTPS_OK=1
    break
  fi
  sleep 2
done
if [ -f "$CA_LOCAL" ]; then chmod 644 "$CA_LOCAL"; fi
if [ "$HTTPS_OK" = "1" ]; then
  echo "HTTPS en marcha: $SITIO"
else
  echo "Aviso: el HTTPS todavia no responde en $SITIO." >&2
  echo "Detalle: docker compose --env-file $ENV_FILE logs --tail 50 caddy" >&2
fi

# 8. Resumen
USUARIOS="$("${COMPOSE[@]}" exec -T db psql -U jzbill -d jzbill_db -tAc "SELECT count(*) FROM usuarios" 2>/dev/null || echo 0)"
echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA - JZBill $VERSION (Docker)"
echo "================================================================="
echo "Pagina: $SITIO"
echo "Certificado de la CA local de Caddy: $CA_LOCAL (cada terminal tiene que confiar en el una vez)."
if [ "$USUARIOS" = "0" ]; then
  echo ""
  echo "Token de configuracion inicial: $SETUP_TOKEN"
  echo "La pagina lo pide para crear el administrador (sirve una sola vez)."
fi
echo ""
echo "Manejo (desde $SCRIPT_DIR):"
echo "  docker compose --env-file $ENV_FILE ps | logs app | restart app"
echo "Respaldo de la base:"
echo "  docker compose --env-file $ENV_FILE exec -T db pg_dump -U jzbill -Fc jzbill_db > jzbill.dump"
echo ""
echo "IMPORTANTE: respaldar $CLAVE_SECRETOS APARTE del respaldo de la base."
echo "Sin esa clave los certificados guardados no se pueden recuperar; con las dos juntas, quedan expuestos."
echo "================================================================="
