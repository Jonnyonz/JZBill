-- Datos obligatorios de la representacion impresa (RG 1415 Anexo II, aplicada al comprobante electronico por la
-- RG 4291 art. 14; textos en referencias/arca/RG-1415.txt):
--   I.a.4: numero de ingresos brutos o condicion de no contribuyente, del emisor.
--   I.a.7: fecha de inicio de actividades, precedida de "INICIO DE ACTIVIDADES".
--   I.a.2 y V.3: domicilio comercial = el del local donde se emite (sucursal del punto de venta).
--   II.a, c, e: domicilio comercial del receptor responsable inscripto, monotributista o exento.
--   Anexo II B, e): condiciones de venta (contado, cuenta corriente, etc.).
-- El comprobante guarda una copia de los datos del emisor al emitir: emitido = inmutable, y lo impreso no cambia
-- aunque despues cambie el domicilio o los datos de la razon social.

ALTER TABLE razones_sociales
    ADD COLUMN ingresos_brutos VARCHAR(40) NOT NULL DEFAULT '',
    ADD COLUMN inicio_actividades DATE;

ALTER TABLE comprobantes
    ADD COLUMN emisor_domicilio VARCHAR(300),
    ADD COLUMN emisor_ingresos_brutos VARCHAR(40),
    ADD COLUMN emisor_inicio_actividades DATE,
    ADD COLUMN receptor_domicilio VARCHAR(300) NOT NULL DEFAULT '',
    ADD COLUMN condicion_venta VARCHAR(40) NOT NULL DEFAULT 'Contado';
