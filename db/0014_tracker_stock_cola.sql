-- Fase 8: integracion con Tracker360 (diseno, seccion 9). Tracker es el dueno del stock; JZBill nunca depende de
-- el para emitir.
--
-- stock_foto: ultima lectura del stock por SKU desde la API de canales (GET /api/v1/channel/stock), tal como lo
-- ve el canal de JZBill. Cada venta descuenta la foto local hasta la proxima lectura. Solo para avisar al
-- facturar: no bloquea la venta (politica "foto en cero": avisar; revisable).
-- articulos.en_tracker: NULL = sin verificar; false = el SKU no existe en Tracker (se marca en cada lectura).
-- cola_tracker: lo que hay que informar a Tracker en orden. Una venta de modo EMPRESA con articulos entra como
-- pedido del canal (POST /api/v1/channel/orders, idempotente por external_ref); una nota de credito asociada entra
-- como cancelacion parcial del pedido original. Con Tracker caido la factura se emite igual y la cola se vacia en
-- orden cuando vuelve. Lo de modo prueba nunca se informa.

CREATE TABLE stock_foto (
    sku VARCHAR(100) PRIMARY KEY,                 -- en mayusculas, como lo devuelve Tracker
    disponible NUMERIC(15, 3) NOT NULL,
    fisico NUMERIC(15, 3) NOT NULL,
    leido_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE articulos ADD COLUMN en_tracker BOOLEAN;

CREATE TABLE cola_tracker (
    id BIGSERIAL PRIMARY KEY,
    comprobante_id UUID NOT NULL REFERENCES comprobantes (id),
    accion VARCHAR(12) NOT NULL CHECK (accion IN ('venta', 'cancelacion')),
    external_ref VARCHAR(100) NOT NULL,
    cuerpo JSONB NOT NULL,
    estado VARCHAR(12) NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'sincronizado', 'error', 'descartado')),
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error VARCHAR(300),
    respuesta JSONB,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    sincronizado_en TIMESTAMPTZ,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX cola_tracker_pendientes_idx ON cola_tracker (creado_en, id) WHERE estado = 'pendiente';
CREATE INDEX cola_tracker_comprobante_idx ON cola_tracker (comprobante_id);

ALTER TABLE tracker_conexion
    ADD COLUMN stock_leido_en TIMESTAMPTZ,
    ADD COLUMN cola_procesada_en TIMESTAMPTZ;
