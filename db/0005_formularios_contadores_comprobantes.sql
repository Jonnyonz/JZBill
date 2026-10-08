-- Fase 3: formularios, contadores y comprobantes.
--
-- Formulario: un tipo de comprobante en un punto de venta de una razon social. Si es electronico lleva el codigo
-- de ARCA (FEParamGetTiposCbte) y pide CAE; si no, solo numera y guarda (presupuestos, remitos internos).
-- Contador: uno por formulario y MODO (decision de Jonny 2026-10-08): ARCA lleva numeraciones separadas en
-- homologacion y produccion, y una prueba no debe consumir ni desordenar numeros reales.
-- Comprobante: se guarda solo si ARCA lo autorizo (o si no es electronico). Emitido = inmutable: se corrige con
-- una nota de credito o debito enlazada (comprobante_ref). Dinero en NUMERIC, nunca float.

CREATE TABLE formularios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    punto_venta_id UUID NOT NULL REFERENCES puntos_venta (id),
    electronico BOOLEAN NOT NULL,
    codigo_arca INTEGER CHECK (codigo_arca BETWEEN 1 AND 999),
    nombre VARCHAR(80) NOT NULL,
    letra CHAR(1) CHECK (letra IN ('A', 'B', 'C', 'M', 'E')),
    activo BOOLEAN NOT NULL DEFAULT true,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (NOT electronico OR codigo_arca IS NOT NULL)
);
-- Un mismo tipo electronico una sola vez por punto de venta; los no electronicos, por nombre.
CREATE UNIQUE INDEX formularios_electronico_unico ON formularios (punto_venta_id, codigo_arca) WHERE electronico;
CREATE UNIQUE INDEX formularios_interno_unico ON formularios (punto_venta_id, lower(nombre)) WHERE NOT electronico;

CREATE TABLE contadores (
    formulario_id UUID NOT NULL REFERENCES formularios (id),
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    ultimo_numero BIGINT NOT NULL DEFAULT 0 CHECK (ultimo_numero BETWEEN 0 AND 99999999),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (formulario_id, modo)
);

CREATE TABLE comprobantes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    formulario_id UUID NOT NULL REFERENCES formularios (id),
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    electronico BOOLEAN NOT NULL,
    codigo_arca INTEGER,
    nombre VARCHAR(80) NOT NULL,
    letra CHAR(1),
    punto_venta INTEGER NOT NULL,
    numero BIGINT NOT NULL CHECK (numero BETWEEN 1 AND 99999999),
    fecha DATE NOT NULL,
    concepto SMALLINT NOT NULL CHECK (concepto IN (1, 2, 3)),
    servicio_desde DATE,
    servicio_hasta DATE,
    vencimiento_pago DATE,
    receptor_doc_tipo INTEGER NOT NULL,
    receptor_doc_nro BIGINT NOT NULL CHECK (receptor_doc_nro >= 0),
    receptor_nombre VARCHAR(200) NOT NULL DEFAULT '',
    condicion_iva_receptor INTEGER NOT NULL,
    moneda VARCHAR(3) NOT NULL,
    cotizacion NUMERIC(16, 6) NOT NULL CHECK (cotizacion > 0),
    importe_neto NUMERIC(15, 2) NOT NULL,
    importe_no_gravado NUMERIC(15, 2) NOT NULL DEFAULT 0,
    importe_exento NUMERIC(15, 2) NOT NULL DEFAULT 0,
    importe_iva NUMERIC(15, 2) NOT NULL DEFAULT 0,
    importe_tributos NUMERIC(15, 2) NOT NULL DEFAULT 0,
    importe_total NUMERIC(15, 2) NOT NULL CHECK (importe_total > 0),
    cae VARCHAR(14),
    cae_vencimiento DATE,
    observaciones_arca JSONB NOT NULL DEFAULT '[]',
    parametros_version_id INTEGER REFERENCES parametros_fiscales_versiones (id),
    comprobante_ref UUID REFERENCES comprobantes (id),
    usuario_id UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (formulario_id, modo, numero),
    CHECK (NOT electronico OR (cae IS NOT NULL AND cae_vencimiento IS NOT NULL))
);
CREATE INDEX comprobantes_rs_modo_idx ON comprobantes (razon_social_id, modo, creado_en DESC);

CREATE TABLE comprobante_lineas (
    comprobante_id UUID NOT NULL REFERENCES comprobantes (id),
    orden SMALLINT NOT NULL CHECK (orden BETWEEN 1 AND 500),
    descripcion VARCHAR(250) NOT NULL,
    cantidad NUMERIC(15, 3) NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC(15, 2) NOT NULL CHECK (precio_unitario >= 0),
    importe NUMERIC(15, 2) NOT NULL,
    PRIMARY KEY (comprobante_id, orden)
);

CREATE FUNCTION comprobantes_inmutables() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Un comprobante emitido no se modifica ni se borra: se corrige con una nota enlazada.';
END;
$$;
CREATE TRIGGER comprobantes_sin_cambios BEFORE UPDATE OR DELETE ON comprobantes
    FOR EACH ROW EXECUTE FUNCTION comprobantes_inmutables();
CREATE TRIGGER comprobantes_sin_truncate BEFORE TRUNCATE ON comprobantes
    FOR EACH STATEMENT EXECUTE FUNCTION comprobantes_inmutables();
CREATE TRIGGER comprobante_lineas_sin_cambios BEFORE UPDATE OR DELETE ON comprobante_lineas
    FOR EACH ROW EXECUTE FUNCTION comprobantes_inmutables();
CREATE TRIGGER comprobante_lineas_sin_truncate BEFORE TRUNCATE ON comprobante_lineas
    FOR EACH STATEMENT EXECUTE FUNCTION comprobantes_inmutables();
