-- Esquema base de JZFactura (Fase 0): usuarios, sesiones, limite de login y auditoria.
-- Razones sociales, puntos de venta, roles y accesos van en la Fase 1 (docs/02_PLAN_DE_TRABAJO.md).
-- Fechas en UTC (timestamptz).

CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario VARCHAR(50) UNIQUE NOT NULL,
    nombre VARCHAR(120) NOT NULL DEFAULT '',
    clave_hash TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    clave_cambiada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sesiones opacas de jztech_core.sessions (en la base solo el hash del token). El nombre y las
-- columnas los fija jztech_core (sessions.CREATE_TABLE_SQL).
CREATE TABLE IF NOT EXISTS jztech_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS jztech_sessions_user_id_idx ON jztech_sessions (user_id);

-- Intentos de login. Dos claves por intento: "u|<ip>|<usuario>" y "ip|<ip>".
CREATE TABLE IF NOT EXISTS login_limites (
    clave VARCHAR(255) PRIMARY KEY,
    intentos INT NOT NULL DEFAULT 0,
    ultimo_intento TIMESTAMPTZ NOT NULL DEFAULT now(),
    bloqueado_hasta TIMESTAMPTZ
);

-- Registro de acciones sensibles. Solo se inserta: nunca se modifica ni se borra desde la app.
CREATE TABLE IF NOT EXISTS auditoria (
    id BIGSERIAL PRIMARY KEY,
    usuario_id UUID,
    usuario VARCHAR(50) NOT NULL,
    accion VARCHAR(60) NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    ip VARCHAR(64) NOT NULL DEFAULT '',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auditoria_creado_en_idx ON auditoria (creado_en);
