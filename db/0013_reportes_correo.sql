-- Fase 7: reportes y correo.
--
-- Reportes: no necesitan tablas (leen comprobantes, lineas, articulos y caja); solo un indice por fecha para los
-- rangos de periodo por razon social y modo.
-- Correo: un servidor SMTP por razon social, con la clave cifrada con la clave maestra (como los certificados de
-- ARCA y la clave de Tracker) y nunca devuelta por la API. Cada envio de un comprobante queda registrado.

CREATE INDEX comprobantes_rs_modo_fecha_idx ON comprobantes (razon_social_id, modo, fecha);

CREATE TABLE correo_config (
    razon_social_id UUID PRIMARY KEY REFERENCES razones_sociales (id),
    servidor VARCHAR(200) NOT NULL CHECK (btrim(servidor) <> ''),
    puerto INTEGER NOT NULL CHECK (puerto BETWEEN 1 AND 65535),
    seguridad VARCHAR(10) NOT NULL CHECK (seguridad IN ('starttls', 'ssl')),
    usuario VARCHAR(200) NOT NULL DEFAULT '',
    clave_cifrada BYTEA,
    remitente VARCHAR(200) NOT NULL,
    nombre_remitente VARCHAR(120) NOT NULL DEFAULT '',
    envio_automatico BOOLEAN NOT NULL DEFAULT false,
    ultimo_ok TIMESTAMPTZ,
    ultimo_error VARCHAR(300),
    actualizado_por UUID REFERENCES usuarios (id),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE comprobante_envios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comprobante_id UUID NOT NULL REFERENCES comprobantes (id),
    destinatario VARCHAR(200) NOT NULL,
    estado VARCHAR(10) NOT NULL CHECK (estado IN ('enviado', 'error')),
    detalle VARCHAR(300) NOT NULL DEFAULT '',
    automatico BOOLEAN NOT NULL DEFAULT false,
    usuario_id UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX comprobante_envios_comprobante_idx ON comprobante_envios (comprobante_id, creado_en);
