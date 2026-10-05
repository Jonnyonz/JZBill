# Notas de los parches

Cambios de JZBill, del más nuevo al más viejo.

## 2026-10-05 - 0.3.0

### Agregado
- Sucursales: locales físicos donde pueden facturar varias razones sociales, cada una con su punto de venta
  predeterminado (un punto de venta está en un solo local). Pantalla de administración.
- Sucursales asignadas a cada usuario, con una predeterminada.
- Color por razón social, en orden de paleta (primero rojo, azul y amarillo; después verde, naranja y violeta),
  editable por el administrador.

### Cambiado
- Al entrar, cada usuario queda solo en su primera razón social (preferentemente una que facture en su
  sucursal predeterminada), en modo empresa si lo tiene, con su sucursal y el punto de venta de esa sucursal.
  Ya no hay que elegir a mano; se cambia desde el avatar.
- La barra superior toma el color de la razón social elegida; en modo prueba se ve a rayas. Se quitó el aviso
  de texto del modo prueba.

## 2026-10-05 - 0.2.0

### Agregado
- Razones sociales (CUIT validado con dígito verificador y fijo después del alta, condición frente al IVA,
  domicilio, régimen especial de ARBA) y sus puntos de venta.
- Roles globales (administrador, supervisor, cajero, solo lectura) y accesos por usuario a razones sociales,
  modo (empresa o prueba) y, opcionalmente, puntos de venta. Una razón social sin acceso responde igual que
  una que no existe, también pedida por ID. Siempre queda al menos un administrador activo; resetear la
  contraseña o desactivar a un usuario cierra sus sesiones.
- Selector "división empresa" bajo el avatar: razón social y modo por sesión, revalidado en cada pedido. El
  modo prueba se distingue por el color de la barra superior.
- Certificados de ARCA por razón social y modo, cifrados en reposo con AES-256-GCM (dependencia
  `cryptography`) y una clave maestra fuera de la base que genera el instalador. La API nunca los devuelve.
- Auditoría por razón social, inmutable en la base, con pantalla de consulta.
- Pantallas de administración de razones sociales, puntos de venta, certificados, usuarios y accesos.

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
