-- Fase 6: caja. Seguimiento simple, no contabilidad (diseno, seccion 8): cobros ligados a comprobantes y
-- movimientos manuales, por razon social y por modo (lo de prueba nunca se suma a la caja real).
--
-- Medios de pago y categorias: configurables por razon social, con un juego predeterminado.
-- Caja: local, tesoreria o dueno; opcionalmente atada a una sucursal. Una caja tiene una planilla por dia y modo,
-- una sola abierta a la vez; al cierre se hace el arqueo por medio de pago y moneda contra lo que la planilla
-- indica que deberia haber. Retiro a tesoreria o al dueno: salida en la caja de origen y entrada espejo en la caja
-- de destino, mismo importe y referencia cruzada (espejo_id), las dos en una transaccion.
-- Dinero en NUMERIC, nunca float.

CREATE TABLE medios_pago (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    nombre VARCHAR(60) NOT NULL CHECK (btrim(nombre) <> ''),
    efectivo BOOLEAN NOT NULL DEFAULT false,   -- se cuenta en el arqueo y recibe el fondo inicial
    activo BOOLEAN NOT NULL DEFAULT true,
    orden SMALLINT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX medios_pago_nombre_unico ON medios_pago (razon_social_id, lower(nombre));

CREATE TABLE caja_categorias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    nombre VARCHAR(80) NOT NULL CHECK (btrim(nombre) <> ''),
    activa BOOLEAN NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX caja_categorias_nombre_unico ON caja_categorias (razon_social_id, lower(nombre));

CREATE TABLE cajas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    nombre VARCHAR(80) NOT NULL CHECK (btrim(nombre) <> ''),
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('local', 'tesoreria', 'dueno')),
    sucursal_id UUID REFERENCES sucursales (id),
    activa BOOLEAN NOT NULL DEFAULT true,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX cajas_nombre_unico ON cajas (razon_social_id, lower(nombre));

CREATE TABLE caja_planillas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caja_id UUID NOT NULL REFERENCES cajas (id),
    modo VARCHAR(10) NOT NULL CHECK (modo IN ('empresa', 'prueba')),
    fecha DATE NOT NULL,
    estado VARCHAR(10) NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'cerrada')),
    fondo_inicial NUMERIC(15, 2) NOT NULL DEFAULT 0 CHECK (fondo_inicial >= 0),
    abierta_por UUID REFERENCES usuarios (id),
    abierta_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    cerrada_por UUID REFERENCES usuarios (id),
    cerrada_en TIMESTAMPTZ,
    observaciones VARCHAR(500) NOT NULL DEFAULT '',
    UNIQUE (caja_id, modo, fecha)
);
CREATE UNIQUE INDEX caja_planillas_una_abierta ON caja_planillas (caja_id, modo) WHERE estado = 'abierta';

CREATE TABLE caja_movimientos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planilla_id UUID NOT NULL REFERENCES caja_planillas (id),
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('entrada', 'salida')),
    origen VARCHAR(12) NOT NULL CHECK (origen IN ('comprobante', 'manual', 'retiro')),
    comprobante_id UUID REFERENCES comprobantes (id),
    categoria_id UUID REFERENCES caja_categorias (id),
    medio_pago_id UUID NOT NULL REFERENCES medios_pago (id),
    moneda VARCHAR(3) NOT NULL,
    importe NUMERIC(15, 2) NOT NULL CHECK (importe > 0),
    descripcion VARCHAR(250) NOT NULL DEFAULT '',
    espejo_id UUID REFERENCES caja_movimientos (id),
    usuario_id UUID REFERENCES usuarios (id),
    -- clock_timestamp(): los movimientos de una misma transaccion (cobro repartido, retiro) conservan su orden.
    creado_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((origen = 'comprobante') = (comprobante_id IS NOT NULL)),
    CHECK (origen = 'comprobante' OR categoria_id IS NOT NULL),
    CHECK (espejo_id IS NULL OR origen = 'retiro')
);
CREATE INDEX caja_movimientos_planilla_idx ON caja_movimientos (planilla_id, creado_en);
CREATE INDEX caja_movimientos_comprobante_idx ON caja_movimientos (comprobante_id) WHERE comprobante_id IS NOT NULL;

-- Arqueo del cierre: lo esperado segun la planilla y lo contado, por medio de pago y moneda.
CREATE TABLE caja_arqueos (
    planilla_id UUID NOT NULL REFERENCES caja_planillas (id) ON DELETE CASCADE,
    medio_pago_id UUID NOT NULL REFERENCES medios_pago (id),
    moneda VARCHAR(3) NOT NULL,
    esperado NUMERIC(15, 2) NOT NULL,
    contado NUMERIC(15, 2),
    PRIMARY KEY (planilla_id, medio_pago_id, moneda)
);

-- Juego predeterminado para las razones sociales existentes (las nuevas lo reciben al darlas de alta).
INSERT INTO medios_pago (razon_social_id, nombre, efectivo, orden)
SELECT rs.id, m.nombre, m.efectivo, m.orden
FROM razones_sociales rs,
     (VALUES ('Efectivo', true, 1), ('Transferencia', false, 2), ('Tarjeta de débito', false, 3),
             ('Tarjeta de crédito', false, 4), ('Cheque', false, 5), ('Otro', false, 6)) AS m (nombre, efectivo, orden);

INSERT INTO caja_categorias (razon_social_id, nombre)
SELECT rs.id, c.nombre
FROM razones_sociales rs,
     (VALUES ('Proveedores'), ('Servicios'), ('Vales y adelantos'), ('Gastos varios'), ('Retiro a tesorería'),
             ('Retiro del dueño'), ('Ingreso de fondos')) AS c (nombre);
