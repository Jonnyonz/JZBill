# Notas de los parches

Cambios de JZBill, del más nuevo al más viejo.

## 0.7.0 - 2026-10-30

Fase 6: caja.

### Agregado
- Caja: pantalla Caja en la barra lateral (ven todos; abren, operan y cierran administrador, supervisor y cajero;
  configuran administrador y supervisor). Cada razón social tiene sus cajas (local, tesorería o dueño, opcionalmente
  atadas a una sucursal), sus medios de pago (efectivo, transferencia, tarjetas, cheque y otro, configurables) y
  sus categorías de caja (configurables; se cargan predeterminadas). Cada caja lleva una planilla por día y modo, una
  sola abierta a la vez: apertura con fondo inicial, movimientos manuales siempre con categoría y medio de pago,
  retiro a otra caja (salida acá y entrada espejo en la caja de destino, las dos en una misma transacción y
  enlazadas) y cierre con arqueo por medio de pago y moneda (esperado según la planilla, contado y diferencia).
  Reabrir una planilla cerrada: administrador o supervisor. Totales por medio de pago y por categoría. Lo del modo
  prueba nunca se suma a la caja real.
- Cobro al facturar: en Facturar, bloque Cobro con la caja abierta y el total repartido por medio de pago (el
  primer renglón toma el resto). El servidor exige una planilla abierta en el modo del contexto y que la suma sea
  igual al total; cada parte queda como movimiento ligado al comprobante, una nota de crédito genera la salida.
  Sin caja abierta, o en cuenta corriente, el comprobante se emite sin movimiento de caja. El impreso y el detalle
  del comprobante muestran la forma de pago.

### Cambiado
- Contrato de la API: 97 operaciones (17 nuevas bajo `/api/caja`); `POST /api/comprobantes` acepta `pagos` y
  `caja_id` opcionales y el detalle devuelve `pagos`.
- Migración 0012 (medios_pago, caja_categorias, cajas, caja_planillas, caja_movimientos, caja_arqueos).

## 0.6.0 - 2026-10-30

Fase 5: artículos, precios, acciones masivas, Tracker360 y ofertas.

### Agregado
- Ofertas (Fase 5, cierre): pantalla Ofertas en la barra lateral (ven todos; crean y modifican administrador y
  supervisor). Una oferta descuenta un porcentaje o un monto fijo por unidad sobre el precio de lista, a todos los
  artículos, a una categoría o a una lista de artículos; con vigencia desde y hasta (opcional) y opcional por medio de
  pago (la condición de venta del comprobante). Al facturar, el sistema propone la mejor oferta vigente en cada
  línea con artículo; el cajero la ve bajo la descripción y puede quitarla. Al emitir, el servidor vuelve a validar y
  calcular la oferta, y la línea guarda el precio de lista, el descuento y el detalle (también en el impreso): lo
  emitido no cambia aunque la oferta cambie o se desactive. Sin "unidad gratis" ni combinaciones; si aplican varias,
  gana la de mayor descuento. Un monto fijo está en pesos: en otra moneda solo aplican los porcentajes.
- Artículos (Fase 5, primera parte): pantalla Artículos con SKU único en todo el sistema, descripción, categoría,
  alícuota de IVA de ARCA, costo de referencia (no participa del comprobante) y precios de venta finales (con IVA)
  con vigencia e historial; buscador por SKU o descripción. Cargan y modifican administrador y supervisor.
- Conexión con Tracker360 (tarjeta en Artículos, solo administrador): URL y clave del canal (`tch_...`, guardada
  cifrada), prueba de conexión y estado. Importar desde Tracker360: trae el catálogo (Tracker 1.5.0 o posterior),
  muestra la vista previa (nuevos, cambios y omitidos) y al confirmar crea los artículos nuevos sin precio con la
  alícuota elegida y actualiza descripción, categoría y activo de los existentes. Un artículo manual con el mismo
  SKU pasa a ser de Tracker360. En los de Tracker360, SKU, descripción y categoría no se editan en Bill; costo, IVA
  y precios sí.
- El SKU sigue las reglas de Tracker360: hasta 100 caracteres y con espacios adentro (se normalizan a uno). Antes
  los artículos con espacios en el SKU quedaban afuera de la importación.
- Precios y costos por CSV (Artículos, administrador y supervisor): archivo con columnas sku y precio o costo
  (opcionales vigencia_desde y moneda), vista previa con el valor actual y el nuevo por SKU, SKU no encontrados
  aparte (nunca crea artículos) y filas con error señaladas; con errores no se aplica nada. Hasta 2 MB y 20.000
  filas; separador ; o , y decimales con coma o punto.
- Facturar con artículos: buscador por SKU o descripción en el detalle; al elegir uno se agrega la línea con su
  descripción y el precio vigente en la moneda del comprobante (editables). La línea guarda el artículo y el SKU.
  Las líneas libres siguen igual. Enter en el buscador agrega el artículo cuyo SKU coincide (sirve con lector de
  código de barras); con un solo resultado, agrega ese.
- Pantalla Configuración (solo administrador): la conexión con Tracker360 se mudó ahí desde Artículos.
- Modificaciones masivas (Artículos, administrador y supervisor): subir o bajar precios y/o costos por porcentaje o
  monto fijo, a todos los artículos activos o a una categoría, con vista previa y confirmación. Los artículos sin
  precio se informan y no se tocan; si alguno quedara por debajo de cero no se aplica nada.
- Artículos: el alta y la edición se abren en una ventana flotante sobre la lista (Esc, Cancelar o la X la cierran),
  en vez de al final de la página.
- Clientes compartidos entre razones sociales y grupos económicos; alta rápida con los datos de la constancia de
  inscripción de ARCA (lupa en Clientes y "Crear cliente nuevo" al facturar); el comprobante guarda el cliente.
- Pie "Powered By JZTech Solutions" con logo en el ingreso y en el panel.

### Corregido
- Consumidor final (documento tipo 99) siempre va a ARCA con número 0, aunque se haya tipeado un número: antes
  ARCA rechazaba el comprobante con el error 10015.
- Conexión con ARCA en producción: se evitan las suites DHE (clave de 1024 bits) que OpenSSL 3 rechaza.
- La tarjeta de Conexión con ARCA arranca en el modo del avatar.

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
