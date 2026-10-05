-- Sucursales (locales fisicos, compartidos por varias razones sociales), punto de venta predeterminado por
-- sucursal y razon social, sucursales de cada usuario, color de cada razon social y sucursal / punto de venta
-- en el contexto de la sesion.

-- Color de la razon social (barra superior del panel). Las existentes reciben la paleta en orden de alta:
-- primero los primarios (rojo, azul, amarillo), despues los secundarios (verde, naranja, violeta).
ALTER TABLE razones_sociales ADD COLUMN color CHAR(7) NOT NULL DEFAULT '#d32f2f' CHECK (color ~ '^#[0-9a-f]{6}$');
UPDATE razones_sociales rs SET color = paleta.color
FROM (
    SELECT id, (ARRAY['#d32f2f', '#1565c0', '#f9a825', '#2e7d32', '#ef6c00', '#6a1b9a',
                      '#0288d1', '#c2185b', '#6d4c41', '#546e7a'])[((row_number() OVER (ORDER BY creado_en, id) - 1) % 10) + 1] AS color
    FROM razones_sociales
) paleta
WHERE paleta.id = rs.id;

CREATE TABLE sucursales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(120) NOT NULL UNIQUE CHECK (btrim(nombre) <> ''),
    domicilio VARCHAR(300) NOT NULL DEFAULT '',
    activa BOOLEAN NOT NULL DEFAULT true,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Que razones sociales facturan en cada sucursal y con que punto de venta por defecto. Un punto de venta esta
-- fisicamente en un solo local: no puede ser el predeterminado de dos sucursales.
CREATE TABLE sucursal_puntos_venta (
    sucursal_id UUID NOT NULL REFERENCES sucursales (id) ON DELETE CASCADE,
    razon_social_id UUID NOT NULL REFERENCES razones_sociales (id),
    punto_venta_id UUID NOT NULL UNIQUE REFERENCES puntos_venta (id),
    PRIMARY KEY (sucursal_id, razon_social_id)
);

-- Sucursales en que trabaja cada usuario; una sola predeterminada (la que se elige sola al entrar).
CREATE TABLE usuario_sucursales (
    usuario_id UUID NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    sucursal_id UUID NOT NULL REFERENCES sucursales (id) ON DELETE CASCADE,
    predeterminada BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (usuario_id, sucursal_id)
);
CREATE UNIQUE INDEX usuario_sucursales_una_predeterminada ON usuario_sucursales (usuario_id) WHERE predeterminada;

ALTER TABLE sesion_contexto
    ADD COLUMN sucursal_id UUID REFERENCES sucursales (id) ON DELETE SET NULL,
    ADD COLUMN punto_venta_id UUID REFERENCES puntos_venta (id) ON DELETE SET NULL;
