-- Fase 2 (ARCA): pedidos de certificado generados en el servidor, tickets de acceso del WSAA y parametros
-- fiscales leidos de WSFEv1 (FEParamGet*) como datos con version.

-- Pedidos de certificado (CSR). La clave privada la genera el servidor, queda CIFRADA (cifrado.py) y nunca se
-- devuelve. El CSR es publico: se pega en WSASS (homologacion) o en el Administrador de Certificados Digitales
-- (produccion). Cuando ARCA devuelve el certificado, se carga contra este pedido.
CREATE TABLE certificado_pedidos (
    id UUID PRIMARY KEY,
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    alias VARCHAR(50) NOT NULL,
    clave_cifrada BYTEA NOT NULL,
    csr_pem TEXT NOT NULL,
    creado_por UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    usado_en TIMESTAMPTZ,
    certificado_id UUID REFERENCES certificados (id)
);
CREATE INDEX certificado_pedidos_rs_idx ON certificado_pedidos (razon_social_id, modo, creado_en);

-- Ticket de acceso (TA) del WSAA por razon social, modo y servicio: token y sign CIFRADOS. Se reutiliza hasta que
-- vence (ARCA no da otro mientras haya uno valido). Tambien guarda el ultimo error y hasta cuando no se puede
-- volver a pedir (reglas de reintento de la especificacion tecnica del WSAA).
CREATE TABLE arca_tickets (
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    servicio VARCHAR(32) NOT NULL,
    certificado_id UUID REFERENCES certificados (id),
    token_cifrado BYTEA,
    sign_cifrado BYTEA,
    expira TIMESTAMPTZ,
    ultimo_error VARCHAR(80) NOT NULL DEFAULT '',
    ultimo_error_en TIMESTAMPTZ,
    bloqueado_hasta TIMESTAMPTZ,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (razon_social_id, modo, servicio)
);

-- Parametros fiscales de ARCA (tipos de comprobante, de documento, alicuotas de IVA, tributos, monedas,
-- conceptos, opcionales, condicion frente al IVA del receptor). La fuente de verdad son los FEParamGet* de
-- WSFEv1: el sistema los lee, no los copia a mano. Cada lectura distinta crea una version nueva (inmutable);
-- los comprobantes van a guardar con que version se emitieron. Por modo: homologacion y produccion pueden diferir.
CREATE TABLE parametros_fiscales_versiones (
    id BIGSERIAL PRIMARY KEY,
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    origen VARCHAR(30) NOT NULL DEFAULT 'arca-wsfev1',
    huella CHAR(64) NOT NULL,
    obtenido_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    obtenido_por UUID REFERENCES usuarios (id),
    razon_social_id UUID REFERENCES razones_sociales (id)
);
CREATE INDEX parametros_fiscales_versiones_modo_idx ON parametros_fiscales_versiones (modo, id DESC);

CREATE TABLE parametros_fiscales (
    version_id BIGINT NOT NULL REFERENCES parametros_fiscales_versiones (id),
    tipo VARCHAR(40) NOT NULL,
    codigo VARCHAR(20) NOT NULL,
    descripcion VARCHAR(250) NOT NULL DEFAULT '',
    vigente_desde DATE,
    vigente_hasta DATE,
    datos JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (version_id, tipo, codigo)
);

-- Versiones y parametros son historicos: no se modifican ni se borran.
CREATE FUNCTION parametros_fiscales_inmutables() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Los parametros fiscales versionados no se modifican ni se borran.';
END;
$$;
CREATE TRIGGER parametros_fiscales_sin_cambios BEFORE UPDATE OR DELETE ON parametros_fiscales
    FOR EACH ROW EXECUTE FUNCTION parametros_fiscales_inmutables();
CREATE TRIGGER parametros_fiscales_versiones_sin_cambios BEFORE UPDATE OR DELETE ON parametros_fiscales_versiones
    FOR EACH ROW EXECUTE FUNCTION parametros_fiscales_inmutables();
