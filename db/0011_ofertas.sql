-- Fase 5: ofertas (decision de Jonny 2026-10-30). Primera version: descuento por porcentaje o monto fijo por unidad
-- sobre todos los articulos, una categoria o una lista de articulos, con vigencia (desde / hasta) y opcional por
-- medio de pago (la condicion de venta del comprobante). Sin "unidad gratis" ni combinaciones: si varias aplican,
-- gana la de mayor descuento. Una oferta no se borra (las lineas emitidas la referencian): se desactiva.
--
-- La linea del comprobante guarda el detalle de la oferta aplicada (precio de lista, descuento y un texto con el
-- nombre y el efecto): lo emitido se reconstruye sin depender de la regla actual. precio_unitario e importe siguen
-- siendo los finales (lo que se cobro y lo que fue a ARCA).

CREATE TABLE ofertas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(80) NOT NULL CHECK (btrim(nombre) <> ''),
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('porcentaje', 'monto')),
    valor NUMERIC(15, 2) NOT NULL CHECK (valor > 0),
    alcance VARCHAR(10) NOT NULL CHECK (alcance IN ('todo', 'categoria', 'articulos')),
    categoria VARCHAR(80) NOT NULL DEFAULT '',
    condicion_venta VARCHAR(40),            -- NULL: cualquier medio de pago
    vigencia_desde DATE NOT NULL,
    vigencia_hasta DATE,                    -- NULL: sin fecha de fin
    activa BOOLEAN NOT NULL DEFAULT true,
    creado_por UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (tipo <> 'porcentaje' OR valor <= 100),
    CHECK (alcance <> 'categoria' OR categoria <> ''),
    CHECK (vigencia_hasta IS NULL OR vigencia_hasta >= vigencia_desde)
);

CREATE TABLE ofertas_articulos (
    oferta_id UUID NOT NULL REFERENCES ofertas (id) ON DELETE CASCADE,
    articulo_id UUID NOT NULL REFERENCES articulos (id),
    PRIMARY KEY (oferta_id, articulo_id)
);

ALTER TABLE comprobante_lineas
    ADD COLUMN precio_lista NUMERIC(15, 2) CHECK (precio_lista IS NULL OR precio_lista >= 0),
    ADD COLUMN descuento NUMERIC(15, 2) NOT NULL DEFAULT 0 CHECK (descuento >= 0),
    ADD COLUMN oferta_id UUID REFERENCES ofertas (id),
    ADD COLUMN oferta_detalle VARCHAR(120);
