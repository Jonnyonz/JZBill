-- El SKU sigue las reglas de Tracker360, que es su dueno (2026-10-29: 56 articulos reales con espacios adentro,
-- como "ACTUADOR FORD", quedaban afuera de la importacion): hasta 100 caracteres (VARCHAR(100) en Tracker) y
-- espacios internos permitidos; sin espacios en los extremos ni vacio. La unicidad sigue sin distinguir mayusculas.
ALTER TABLE articulos DROP CONSTRAINT IF EXISTS articulos_sku_check;
ALTER TABLE articulos ALTER COLUMN sku TYPE VARCHAR(100);
ALTER TABLE articulos ADD CONSTRAINT articulos_sku_check CHECK (sku <> '' AND btrim(sku) = sku);
ALTER TABLE comprobante_lineas ALTER COLUMN sku TYPE VARCHAR(100);
