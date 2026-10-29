-- Fase 5: articulos con SKU global (decision de Jonny 2026-10-29: unico en todo el sistema, como en Tracker360),
-- costo de referencia (alimenta la rentabilidad, nunca el comprobante) y precios de venta con vigencia.
-- El precio es el FINAL (IVA incluido); la alicuota es un codigo de ARCA (FEParamGetTiposIva) que se guarda como
-- dato para que las facturas A y B puedan discriminar el IVA mas adelante sin migrar. El precio vigente de una
-- moneda es el de mayor vigencia_desde que no sea futura; el siguiente lo reemplaza, no hace falta vigencia_hasta.

CREATE TABLE articulos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku VARCHAR(60) NOT NULL CHECK (sku <> '' AND sku !~ '\s'),
    descripcion VARCHAR(200) NOT NULL CHECK (btrim(descripcion) <> ''),
    categoria VARCHAR(80) NOT NULL DEFAULT '',
    alicuota_iva INTEGER NOT NULL CHECK (alicuota_iva BETWEEN 1 AND 99),
    costo NUMERIC(15, 2) NOT NULL DEFAULT 0 CHECK (costo >= 0),
    activo BOOLEAN NOT NULL DEFAULT true,
    -- 'manual', 'csv' (importacion) o 'tracker' (catalogo de Tracker360, Fase 8).
    origen VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual', 'csv', 'tracker')),
    creado_por UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX articulos_sku_unico ON articulos (upper(sku));
CREATE INDEX articulos_descripcion_idx ON articulos (lower(descripcion));

CREATE TABLE articulos_precios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    articulo_id UUID NOT NULL REFERENCES articulos (id),
    moneda CHAR(3) NOT NULL DEFAULT 'PES',
    importe NUMERIC(15, 2) NOT NULL CHECK (importe >= 0),
    vigencia_desde DATE NOT NULL,
    creado_por UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (articulo_id, moneda, vigencia_desde)
);

-- La linea del comprobante recuerda de que articulo salio (la descripcion y el precio siguen copiados: lo emitido
-- no cambia si el articulo cambia). Las lineas con descripcion libre quedan con NULL.
ALTER TABLE comprobante_lineas ADD COLUMN articulo_id UUID REFERENCES articulos (id);
ALTER TABLE comprobante_lineas ADD COLUMN sku VARCHAR(60);
