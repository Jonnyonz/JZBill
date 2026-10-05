# Notas de los parches

Cambios de JZBill, del más nuevo al más viejo.

## 2026-10-05 - 0.1.0

### Agregado
- Esqueleto del repo: licencia AGPLv3, DCO, `.env.example`, dependencias con versión exacta y lockfile
  con hashes (solo wheels).
- Base segura sobre jztech-core 0.1.5: sesiones opacas en base, Argon2id, CSRF atado a la sesión,
  cabeceras de seguridad con CSP estricta, IP real solo desde proxies de confianza, migraciones
  versionadas, logs JSON y errores genéricos hacia el cliente.
- Alta del primer administrador con token de instalación, login con límite de intentos (por IP + usuario
  y por IP), cierre de sesión, cambio de contraseña (cierra las sesiones de los demás dispositivos) y
  cierre de todas las sesiones. Auditoría de cada acción.
- Test que recorre todas las rutas y verifica que exigen sesión salvo las públicas marcadas.
- Instalador nativo (esqueleto) para Debian 12/13 y Ubuntu 24.04 con systemd y Caddy.
- `backend/tools/api_snapshot.py` y `backend/api-snapshot.json`.

### Cambiado
- Instalador nativo probado en Debian 13 junto a Tracker360 nativo: acceso por IP (HTTPS en el 8443 con la
  CA local de Caddy) o por dominio, puerto HTTPS configurable, el Caddyfile compartido nunca se pisa ni queda
  roto, HSTS y sin cabecera `Server`, y solo el rol `jzbill` puede conectarse a `jzbill_db`.
- El proyecto se llama JZBill (antes JZFactura): paquete `jzbill`, servicio `jzbill`, base `jzbill_db`,
  carpetas `/opt/jzbill` y `/etc/jzbill`, variables `JZB_*` y `JZBILL_ENV_FILE`.
