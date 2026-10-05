-- Fase 1: roles, razones sociales, puntos de venta, accesos por usuario, contexto de la sesion (selector
-- "division empresa"), certificados de ARCA cifrados y auditoria inmutable.
-- IDs UUID: no se pueden recorrer adivinando numeros. Igual, cada endpoint autoriza por rol y por acceso.

-- Rol global de cada usuario. En la Fase 0 solo podia existir el administrador inicial.
ALTER TABLE usuarios ADD COLUMN rol VARCHAR(20) NOT NULL DEFAULT 'solo_lectura'
    CHECK (rol IN ('administrador', 'supervisor', 'cajero', 'solo_lectura'));
UPDATE usuarios SET rol = 'administrador';

-- Emisores. La condicion frente al IVA es un tipo propio; el codigo de ARCA se vincula en la Fase 2 con los
-- parametros que devuelve WSFEv1 (no se copian codigos a mano).
CREATE TABLE razones_sociales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit CHAR(11) NOT NULL UNIQUE CHECK (cuit ~ '^[0-9]{11}$'),
    nombre_legal VARCHAR(200) NOT NULL CHECK (btrim(nombre_legal) <> ''),
    nombre_fantasia VARCHAR(200) NOT NULL DEFAULT '',
    condicion_iva VARCHAR(30) NOT NULL
        CHECK (condicion_iva IN ('responsable_inscripto', 'monotributo', 'exento')),
    domicilio VARCHAR(300) NOT NULL DEFAULT '',
    regimen_arba_bsas BOOLEAN NOT NULL DEFAULT false,
    activa BOOLEAN NOT NULL DEFAULT true,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE puntos_venta (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    numero INTEGER NOT NULL CHECK (numero BETWEEN 1 AND 99999),
    descripcion VARCHAR(120) NOT NULL DEFAULT '',
    activo BOOLEAN NOT NULL DEFAULT true,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (razon_social_id, numero)
);

-- A que razones sociales entra cada usuario y en que modo. Los administradores entran a todas.
CREATE TABLE usuario_accesos (
    usuario_id UUID NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id) ON DELETE CASCADE,
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    PRIMARY KEY (usuario_id, razon_social_id, modo)
);

-- Restriccion opcional por punto de venta: si un usuario no tiene filas para los puntos de venta de una
-- razon social, ve todos los de esa razon social.
CREATE TABLE usuario_puntos_venta (
    usuario_id UUID NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    punto_venta_id UUID NOT NULL REFERENCES puntos_venta (id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, punto_venta_id)
);

-- Razon social y modo elegidos en el selector, por sesion (cada terminal el suyo). Se borra con la sesion.
CREATE TABLE sesion_contexto (
    token_hash TEXT PRIMARY KEY REFERENCES jztech_sessions (token_hash) ON DELETE CASCADE,
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id) ON DELETE CASCADE,
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    elegido_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Certificados de ARCA (WSAA): certificado y clave privada CIFRADOS (cifrado.py, AES-256-GCM con la clave
-- maestra de fuera de la base). En claro solo los datos para mostrar. Uno activo por razon social y modo.
CREATE TABLE certificados (
    id UUID PRIMARY KEY,
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    alias VARCHAR(120) NOT NULL DEFAULT '',
    certificado_cifrado BYTEA NOT NULL,
    clave_cifrada BYTEA NOT NULL,
    sujeto VARCHAR(300) NOT NULL DEFAULT '',
    emisor VARCHAR(300) NOT NULL DEFAULT '',
    numero_serie VARCHAR(80) NOT NULL DEFAULT '',
    huella CHAR(64) NOT NULL,
    valido_desde TIMESTAMPTZ NOT NULL,
    valido_hasta TIMESTAMPTZ NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    cargado_por UUID REFERENCES usuarios (id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX certificados_uno_activo ON certificados (razon_social_id, modo) WHERE activo;

-- Auditoria: ahora tambien por razon social, e inmutable (ni la app puede modificar ni borrar registros).
ALTER TABLE auditoria ADD COLUMN razon_social_id UUID REFERENCES razones_sociales (id);
CREATE INDEX auditoria_razon_social_idx ON auditoria (razon_social_id, creado_en);

CREATE FUNCTION auditoria_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La auditoria no se modifica ni se borra.';
END;
$$;
CREATE TRIGGER auditoria_sin_cambios BEFORE UPDATE OR DELETE ON auditoria
    FOR EACH ROW EXECUTE FUNCTION auditoria_inmutable();
CREATE TRIGGER auditoria_sin_truncate BEFORE TRUNCATE ON auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION auditoria_inmutable();
