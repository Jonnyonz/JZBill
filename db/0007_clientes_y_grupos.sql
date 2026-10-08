-- Fase 4: clientes compartidos entre todas las razones sociales (decision de Jonny 2026-10-08) y grupos economicos
-- simples (vinculo comercial; los reportes consolidados son de la Fase 7).
-- Tipo de documento y condicion frente al IVA son codigos de ARCA (FEParamGetTiposDoc y
-- FEParamGetCondicionIvaReceptor), validados contra los parametros vigentes al guardar.
-- El comprobante sigue copiando los datos del receptor al emitir: si el cliente cambia, lo emitido no.

CREATE TABLE grupos_clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(120) NOT NULL CHECK (btrim(nombre) <> ''),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX grupos_clientes_nombre_unico ON grupos_clientes (lower(nombre));

CREATE TABLE clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_tipo INTEGER NOT NULL CHECK (doc_tipo BETWEEN 0 AND 999),
    doc_nro BIGINT NOT NULL CHECK (doc_nro BETWEEN 1 AND 99999999999),
    nombre VARCHAR(200) NOT NULL CHECK (btrim(nombre) <> ''),
    condicion_iva INTEGER NOT NULL CHECK (condicion_iva BETWEEN 1 AND 99),
    domicilio VARCHAR(300) NOT NULL DEFAULT '',
    email VARCHAR(200) NOT NULL DEFAULT '',
    grupo_id UUID REFERENCES grupos_clientes (id),
    activo BOOLEAN NOT NULL DEFAULT true,
    -- 'manual' o 'arca' (datos traidos de la constancia de inscripcion y confirmados por el usuario).
    origen VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual', 'arca')),
    datos_arca_en TIMESTAMPTZ,
    creado_por UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_tipo, doc_nro)
);
CREATE INDEX clientes_nombre_idx ON clientes (lower(nombre));

ALTER TABLE comprobantes ADD COLUMN cliente_id UUID REFERENCES clientes (id);
