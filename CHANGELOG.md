# Notas de los parches

Cambios de JZBill, del más nuevo al más viejo.

## 2026-10-08 - 0.5.0

### Agregado
- Facturación (Fase 3): pantalla Facturar con tipo de comprobante, concepto, moneda, condiciones de venta,
  receptor (consumidor final o cargado a mano) y líneas con descripción libre; listado de Comprobantes.
- Formularios por punto de venta (electrónicos con tipo, nombre y letra tomados de ARCA, o no electrónicos con
  numeración propia) y contadores separados por modo, sincronizables con el último número autorizado en ARCA.
- Emisión de comprobantes C con CAE: numeración con bloqueo (varias cajas a la vez sin repetir ni saltear), el
  rechazo de ARCA libera el número, se frena si la numeración de ARCA no coincide, y si se pierde la respuesta se
  consulta a ARCA antes de decidir. Notas de crédito y débito enlazadas a su factura. Moneda extranjera con la
  cotización de ARCA. Condición del receptor validada contra la letra con los datos de ARCA.
- Comprobante impreso en una hoja A4 (imprimir o guardar como PDF) según la RG 1415 Anexo II: emisor con leyenda
  de su condición, ingresos brutos e inicio de actividades, letra con su código, receptor ("A CONSUMIDOR FINAL"),
  condiciones de venta, C.A.E. y vencimiento, y QR de ARCA de 50 x 50 mm. En modo prueba, leyenda discreta de
  homologación sin validez fiscal.
- Razón social: ingresos brutos e inicio de actividades. El comprobante guarda una copia de los datos del emisor al
  emitir (lo impreso no cambia si cambian después).
- Dependencia nueva: segno (QR), aprobada.

### Cambiado
- Interfaz con el sistema visual de JZTech Suite (Tracker360 y JZPass): barra lateral de íconos, tarjetas,
  tablas, etiquetas, tema claro u oscuro con botón, Salir en la barra lateral y menú tipo cajón en celular.
- Los comprobantes emitidos no se modifican ni se borran: lo impide la base de datos.

### Corregido
- Las fechas de calendario (por ejemplo la de un comprobante) ya no se muestran un día antes.
- Un contexto elegido antes de que existiera el punto de venta se completa solo cuando aparece uno.
- La condición frente al IVA del receptor admite las clases juntas que manda ARCA (por ejemplo "B/C").

### Pendiente
- Comprobantes A y B (IVA discriminado, Transparencia Fiscal, leyenda de la Ley 27.618): necesitan un emisor
  responsable inscripto para probarlos.

## 2026-10-08 - 0.4.0

### Agregado
- Conexión con ARCA (WSAA y WSFEv1) con cliente propio, sin dependencias nuevas: firma CMS del pedido de acceso,
  ticket guardado cifrado y reutilizado, reintentos según las reglas de ARCA (espera ante errores temporales,
  detenido ante rechazos hasta corregirlos).
- Pedido de certificado (CSR) generado en el servidor: la clave privada queda cifrada y nunca sale. Carga del
  certificado que devuelve ARCA contra el pedido, y descarte de pedidos sin usar.
- Tarjeta "Conexión con ARCA" por razón social y modo: estado de los servidores, prueba de conexión, desbloqueo y
  actualización de los parámetros fiscales.
- Parámetros fiscales leídos de ARCA (tipos de comprobante, IVA, monedas, documentos, tributos, opcionales,
  condición frente al IVA del receptor) y guardados como datos con versión, que no se modifican.
- Pedido de CAE (`FECAESolicitar`), consulta de comprobantes (`FECompConsultar`) y cotización de moneda.
  Herramienta de prueba solo para homologación: `python -m jzbill.arca.prueba_cae`. Probado contra ARCA
  homologación con CAE aprobado para factura C, nota de crédito C, nota de débito C y factura C en dólares.
- Instalación alternativa con Docker (`install-docker.sh`, `compose.yml`, `Dockerfile`): app y PostgreSQL. La
  app corre sin privilegios y con sistema de archivos de solo lectura, la base en una red sin salida a internet,
  y la imagen lleva solo el código (lista blanca en `.dockerignore`).

### Cambiado
- Sin Caddy: la app sirve HTTPS directamente en el puerto 9443 (nativa y Docker). Si no hay certificado, el
  instalador genera uno autofirmado para la IP o el nombre; se puede reemplazar por uno propio. Las
  instalaciones anteriores quedan con su bloque de Caddy sin uso: borrarlo a mano del Caddyfile.
- Las páginas y archivos de la interfaz se revalidan siempre en el navegador: después de una actualización ya no
  queda el JavaScript viejo en caché.

### Corregido
- Las tarjetas de la ficha de la razón social ya no se duplican al tocar dos botones seguidos.

### Pendiente
- Comprobantes A y B: necesitan un emisor responsable inscripto para probarlos en homologación.
- Instalación nativa sin Caddy: falta probarla en un servidor (la de Docker está probada).

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
