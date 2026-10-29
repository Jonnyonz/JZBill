-- Fase 5 / adelanto de la Fase 8 (OK de Jonny 2026-10-29): conexion a Tracker360 para importar el catalogo de
-- articulos por su API de canales (GET /api/v1/channel/items) y no cargarlos dos veces. Una sola conexion por
-- instalacion (Tracker es uno por deposito; el stock y la cola de ventas llegan en la Fase 8).
-- La clave del canal (tch_...) se guarda cifrada con la clave maestra, como los certificados de ARCA.

CREATE TABLE tracker_conexion (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    url VARCHAR(300) NOT NULL,
    clave_cifrada BYTEA NOT NULL,
    canal VARCHAR(120) NOT NULL DEFAULT '',
    ultimo_ok TIMESTAMPTZ,
    ultimo_error VARCHAR(300),
    actualizado_por UUID REFERENCES usuarios (id),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
