// Articulos (SKU global, costo de referencia, precio final con vigencia). Todo con el() / textContent.
'use strict';

function puedeEditarArticulos() { return Panel.yo && ['administrador', 'supervisor'].includes(Panel.yo.rol); }

function formatoImporte(texto) {
    if (texto === null || texto === undefined) return '';
    return Number(texto).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function hoyIso() { return new Date().toISOString().slice(0, 10); }

// Formulario de alta o edicion. alGuardar(articulo) recibe el articulo guardado.
function formularioArticulo(opciones, articulo, alGuardar, alCancelar) {
    const deTracker = !!(articulo && articulo.origen === 'tracker');
    const sku = el('input', { name: 'sku', required: true, maxlength: 100, value: articulo ? articulo.sku : '', readonly: deTracker });
    const descripcion = el('input', { name: 'descripcion', required: true, maxlength: 200, value: articulo ? articulo.descripcion : '', readonly: deTracker });
    const categoria = el('input', { name: 'categoria', maxlength: 80, value: articulo ? articulo.categoria : '', readonly: deTracker });
    const al21 = opciones.alicuotas.find(a => a.descripcion.replace(/\s/g, '') === '21%');
    const selIva = el('select', { name: 'alicuota_iva', required: true }, el('option', { value: '' }, 'Elegí la alícuota'), opciones.alicuotas.map(a =>
        el('option', { value: a.codigo, selected: articulo ? String(articulo.alicuota_iva) === a.codigo : (al21 && a.codigo === al21.codigo) }, a.descripcion)));
    const costo = el('input', { name: 'costo', type: 'number', min: 0, step: '0.01', inputmode: 'decimal', value: articulo ? articulo.costo : '0' });
    const precio = el('input', { name: 'precio', type: 'number', min: 0, step: '0.01', inputmode: 'decimal' });
    const selMoneda = el('select', { name: 'moneda' }, opciones.monedas.map(m => el('option', { value: m.codigo, selected: m.codigo === 'PES' }, m.descripcion)));
    const activo = el('input', { type: 'checkbox', name: 'activo', checked: articulo ? articulo.activo : true });
    const guardar = el('button', { type: 'submit' }, articulo ? 'Guardar cambios' : 'Crear artículo');
    const cancelar = el('button', { type: 'button', class: 'secundario' }, 'Cancelar');
    cancelar.addEventListener('click', () => alCancelar && alCancelar());
    const sinParametros = !opciones.alicuotas.length;
    const campos = el('fieldset', { disabled: sinParametros },
        el('div', { class: 'grilla-form' },
            el('label', {}, 'SKU', sku), el('label', {}, 'Descripción', descripcion),
            el('label', {}, 'Categoría', categoria), el('label', {}, 'Alícuota de IVA', selIva),
            el('label', {}, 'Costo (referencia, no va al comprobante)', costo),
            articulo ? null : el('label', {}, 'Precio de venta final (con IVA)', precio),
            articulo ? null : el('label', {}, 'Moneda del precio', selMoneda)),
        articulo ? el('label', { class: 'casilla' }, activo, 'Activo') : null);
    guardar.disabled = sinParametros;
    const form = el('form', { class: 'form-cliente' },
        sinParametros ? el('p', { class: 'aviso-form error' }, 'Faltan los parámetros fiscales de ARCA. Un administrador tiene que actualizarlos en Razones sociales, Conexión con ARCA.') : null,
        deTracker ? el('p', { class: 'aviso-form' }, 'Este artículo viene de Tracker360: el SKU, la descripción y la categoría se cambian allá y se actualizan al importar. Acá se manejan el IVA, el costo y los precios.') : null,
        campos, el('div', { class: 'acciones' }, guardar, alCancelar ? cancelar : null));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const cuerpo = { sku: sku.value.trim(), descripcion: descripcion.value, categoria: categoria.value,
            alicuota_iva: Number(selIva.value), costo: costo.value || '0' };
        if (articulo) cuerpo.activo = activo.checked;
        else if (precio.value !== '') { cuerpo.precio = precio.value; cuerpo.moneda = selMoneda.value; }
        const r = await conBoton(guardar, () => api(articulo ? '/api/articulos/' + encodeURIComponent(articulo.id) : '/api/articulos',
            { method: articulo ? 'PUT' : 'POST', body: cuerpo }));
        if (r) { mostrarMensaje(articulo ? 'Artículo guardado.' : 'Artículo creado.', 'ok'); alGuardar(r); }
    });
    return form;
}

// Historial de precios y alta de un precio nuevo con vigencia.
function tarjetaPrecios(opciones, articulo, alCambiar) {
    const cuerpo = el('tbody');
    const moneda = codigo => (opciones.monedas.find(m => m.codigo === codigo) || {}).descripcion || codigo;
    if (!articulo.precios.length) cuerpo.append(el('tr', {}, el('td', { colspan: 3, class: 'vacio' }, 'Sin precio cargado: no se puede vender hasta ponerle uno.')));
    for (const p of articulo.precios) {
        cuerpo.append(el('tr', {}, el('td', {}, moneda(p.moneda)), el('td', { class: 'mono' }, formatoImporte(p.importe)),
            el('td', {}, fecha(p.vigencia_desde), ' ', p.vigente ? el('span', { class: 'etiqueta ok' }, 'Vigente')
                : (p.vigencia_desde > hoyIso() ? el('span', { class: 'etiqueta' }, 'Futuro') : null))));
    }
    const importe = el('input', { type: 'number', min: 0, step: '0.01', inputmode: 'decimal', required: true, placeholder: 'Importe final', 'aria-label': 'Importe' });
    const selMoneda = el('select', { 'aria-label': 'Moneda' }, opciones.monedas.map(m => el('option', { value: m.codigo, selected: m.codigo === 'PES' }, m.descripcion)));
    const desde = el('input', { type: 'date', 'aria-label': 'Vigente desde', value: hoyIso() });
    const boton = el('button', { type: 'submit', class: 'secundario' }, 'Poner precio');
    const form = el('form', { class: 'fila-form' }, importe, selMoneda, desde, boton);
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const r = await conBoton(boton, () => api('/api/articulos/' + encodeURIComponent(articulo.id) + '/precios',
            { method: 'POST', body: { importe: importe.value, moneda: selMoneda.value, vigencia_desde: desde.value || null } }));
        if (r) { mostrarMensaje('Precio guardado.', 'ok'); alCambiar(r); }
    });
    return el('div', { class: 'tarjeta' }, el('h2', {}, 'Precios de ' + articulo.sku),
        el('p', { class: 'ayuda' }, 'El precio es el final, con IVA incluido. Rige el de fecha más reciente que ya empezó; un precio con fecha futura espera su día.'),
        el('div', { class: 'tabla-scroll' }, el('table', {}, el('thead', {}, el('tr', {}, el('th', {}, 'Moneda'), el('th', {}, 'Importe'), el('th', {}, 'Vigente desde'))), cuerpo)),
        puedeEditarArticulos() ? form : null);
}

// ===== Conexion con Tracker360 (solo administrador) =====
function tarjetaConexionTracker() {
    const estado = el('p', { class: 'ayuda' }, 'Cargando...');
    const url = el('input', { type: 'url', maxlength: 300, placeholder: 'https://wms.ejemplo.com.ar o http://192.168.1.10:8001', required: true, 'aria-label': 'URL de Tracker360' });
    const clave = el('input', { type: 'password', maxlength: 200, placeholder: 'Clave del canal (tch_...)', autocomplete: 'off', 'aria-label': 'Clave del canal' });
    const guardar = el('button', { type: 'submit' }, 'Guardar');
    const probar = el('button', { type: 'button', class: 'secundario' }, 'Probar conexión');
    const pintar = (d) => {
        url.value = d.url || '';
        clave.placeholder = d.configurada ? 'Clave guardada (dejar vacío para no cambiarla)' : 'Clave del canal (tch_...)';
        vaciar(estado).append(!d.configurada ? 'Sin configurar. Creá un canal de venta en Tracker360 (Configuración, Canales de venta) y pegá acá su clave.'
            : d.ultimo_error ? el('span', { class: 'etiqueta error' }, 'Último error: ' + d.ultimo_error)
            : d.ultimo_ok ? el('span', { class: 'etiqueta ok' }, 'Conectado' + (d.canal ? ' como ' + d.canal : '') + ' · ' + fechaHora(d.ultimo_ok))
            : 'Guardada, sin probar todavía.');
    };
    api('/api/integraciones/tracker').then(pintar).catch(e => vaciar(estado).append(e.message));
    const form = el('form', { class: 'fila-form' }, url, clave, guardar, probar);
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const d = await conBoton(guardar, () => api('/api/integraciones/tracker', { method: 'PUT', body: { url: url.value, clave: clave.value } }));
        if (d) { clave.value = ''; mostrarMensaje('Conexión guardada.', 'ok'); pintar(d); }
    });
    probar.addEventListener('click', async () => {
        const d = await conBoton(probar, () => api('/api/integraciones/tracker/probar', { method: 'POST', body: {} }));
        if (d) { mostrarMensaje('Tracker360 responde' + (d.canal ? ' (canal ' + d.canal + ')' : '') + '.', 'ok'); pintar(d); }
        else api('/api/integraciones/tracker').then(pintar).catch(() => {});
    });
    return el('div', { class: 'tarjeta' }, el('h2', {}, 'Conexión con Tracker360'),
        el('p', { class: 'ayuda' }, 'Tracker360 es el dueño del catálogo: SKU, descripción y categoría. Bill agrega el IVA, el costo y los precios. La clave se guarda cifrada.'),
        estado, form);
}

// ===== Importar el catalogo desde Tracker360 (administrador y supervisor) =====
function tarjetaImportarTracker(opciones, alImportar) {
    const zona = el('div', {});
    const previa = el('button', { type: 'button' }, 'Importar desde Tracker360');
    previa.addEventListener('click', async () => {
        vaciar(zona);
        const r = await conBoton(previa, () => api('/api/articulos/importar-tracker/previa', { method: 'POST', body: {} }));
        if (!r) return;
        const lista = (titulo, filas, pinta) => filas.length ? el('details', { open: filas.length <= 20 },
            el('summary', {}, titulo + ' (' + filas.length + (filas.length === 200 ? ' o más' : '') + ')'),
            el('ul', { class: 'lista-simple' }, filas.map(f => el('li', {}, pinta(f))))) : null;
        const al21 = opciones.alicuotas.find(a => a.descripcion.replace(/\s/g, '') === '21%');
        const selIva = el('select', { 'aria-label': 'Alícuota de IVA para los artículos nuevos' }, opciones.alicuotas.map(a =>
            el('option', { value: a.codigo, selected: al21 ? a.codigo === al21.codigo : false }, a.descripcion)));
        const confirmar = el('button', { type: 'button' }, 'Confirmar importación');
        confirmar.addEventListener('click', async () => {
            const d = await conBoton(confirmar, () => api('/api/articulos/importar-tracker', { method: 'POST', body: { alicuota_iva: Number(selIva.value) } }));
            if (!d) return;
            vaciar(zona).append(el('p', { class: 'aviso-form' }, 'Importado: ' + d.altas + ' artículos nuevos y ' + d.cambios + ' actualizados' + (d.omitidos ? '; ' + d.omitidos + ' omitidos.' : '.')));
            mostrarMensaje('Catálogo importado.', 'ok');
            alImportar();
        });
        const nada = !r.altas && !r.cambios;
        const flecha = ' \u2192 ';
        zona.append(el('div', { class: 'aviso-form' },
            el('strong', {}, 'Tracker360 tiene ' + r.total_tracker + ' artículos: ' + r.altas + ' nuevos para Bill, ' + r.cambios + ' con cambios' + (r.omitidos ? ', ' + r.omitidos + ' que no entran (SKU vacío o de más de 100 caracteres)' : '') + '.'),
            nada ? el('p', { class: 'sub' }, 'No hay nada que importar: Bill ya está igual que Tracker360.') : null,
            lista('Nuevos', r.detalle.altas, a => a.sku + ' · ' + a.descripcion + (a.categoria ? ' · ' + a.categoria : '') + (a.activo ? '' : ' · inactivo')),
            lista('Con cambios', r.detalle.cambios, c => c.sku + ': ' + (c.antes.origen !== 'tracker' ? 'pasa a ser de Tracker360' : '') +
                (c.antes.descripcion !== c.descripcion ? ' · descripción "' + c.antes.descripcion + '"' + flecha + '"' + c.descripcion + '"' : '') +
                (c.antes.categoria !== c.categoria ? ' · categoría "' + c.antes.categoria + '"' + flecha + '"' + c.categoria + '"' : '') +
                (c.antes.activo !== c.activo ? (c.activo ? ' · se activa' : ' · se desactiva') : '')),
            lista('Omitidos', r.detalle.omitidos, s => s),
            nada ? null : el('div', { class: 'fila-form' }, r.altas ? el('label', {}, 'IVA de los nuevos ', selIva) : null, confirmar)));
    });
    return el('div', { class: 'tarjeta' }, el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Importar desde Tracker360'), previa),
        el('p', { class: 'ayuda' }, 'Trae el catálogo de Tracker360 y muestra qué cambiaría antes de aplicar. Los artículos nuevos quedan sin precio: se cargan acá. Costo, IVA y precios de los existentes no se tocan.'),
        zona);
}

// ===== Precios y costos por CSV (administrador y supervisor) =====
function tarjetaPreciosCsv(alAplicar) {
    const archivo = el('input', { type: 'file', accept: '.csv,text/csv', 'aria-label': 'Archivo CSV' });
    const previa = el('button', { type: 'button' }, 'Vista previa');
    const zona = el('div', {});
    let texto = null;
    const leer = () => new Promise((ok, falla) => {
        const f = archivo.files && archivo.files[0];
        if (!f) return falla(new Error('Elegí un archivo CSV.'));
        if (f.size > 2 * 1024 * 1024) return falla(new Error('El archivo supera los 2 MB.'));
        const r = new FileReader();
        r.onload = () => ok(String(r.result));
        r.onerror = () => falla(new Error('No se pudo leer el archivo.'));
        r.readAsText(f, 'utf-8');
    });
    const flecha = ' \u2192 ';
    previa.addEventListener('click', async () => {
        vaciar(zona);
        try { texto = await leer(); } catch (e) { mostrarMensaje(e.message, 'error'); return; }
        const r = await conBoton(previa, () => api('/api/articulos/precios-csv/previa', { method: 'POST', body: { csv: texto } }));
        if (!r) return;
        const cuerpo = el('tbody', {}, r.detalle.cambios.map(c => el('tr', {},
            el('td', { class: 'mono sin-corte' }, c.sku), el('td', {}, c.descripcion),
            el('td', { class: 'mono' }, c.precio_nuevo === null ? '' : (c.precio_actual === null ? 'sin precio' : formatoImporte(c.precio_actual)) + flecha + formatoImporte(c.precio_nuevo) + (c.moneda !== 'PES' ? ' ' + c.moneda : '') + ' desde ' + fecha(c.vigencia_desde)),
            el('td', { class: 'mono' }, c.costo_nuevo === null ? '' : formatoImporte(c.costo_actual) + flecha + formatoImporte(c.costo_nuevo)))));
        const confirmar = el('button', { type: 'button' }, 'Confirmar cambios');
        confirmar.addEventListener('click', async () => {
            const d = await conBoton(confirmar, () => api('/api/articulos/precios-csv', { method: 'POST', body: { csv: texto } }));
            if (!d) return;
            vaciar(zona).append(el('p', { class: 'aviso-form' }, 'Aplicado: ' + d.cambios + ' artículos actualizados.' + (d.no_encontrados ? ' ' + d.no_encontrados + ' SKU no encontrados.' : '')));
            archivo.value = '';
            mostrarMensaje('Precios y costos actualizados.', 'ok');
            alAplicar();
        });
        const lista = (titulo, filas, pinta) => filas.length ? el('details', { open: filas.length <= 20 },
            el('summary', {}, titulo + ' (' + filas.length + (filas.length === 500 ? ' o más' : '') + ')'),
            el('ul', { class: 'lista-simple' }, filas.map(f => el('li', {}, pinta(f))))) : null;
        zona.append(el('div', { class: 'aviso-form' },
            el('strong', {}, r.filas + ' filas: ' + r.cambios + ' artículos cambian, ' + r.sin_cambios + ' sin cambios, ' + r.no_encontrados + ' SKU no encontrados, ' + r.errores + ' filas con error.'),
            r.errores ? el('p', { class: 'sub' }, 'Con filas con error no se aplica nada: corregí el archivo y volvé a subirlo.') : null,
            lista('Errores', r.detalle.errores, e => 'Fila ' + e.fila + (e.sku ? ' (' + e.sku + ')' : '') + ': ' + e.motivo),
            lista('SKU no encontrados (no se crean)', r.detalle.no_encontrados, s => s),
            r.cambios ? el('div', { class: 'tabla-scroll' }, el('table', {}, el('thead', {}, el('tr', {}, el('th', {}, 'SKU'), el('th', {}, 'Descripción'), el('th', {}, 'Precio'), el('th', {}, 'Costo'))), cuerpo)) : null,
            r.cambios && !r.errores ? el('div', { class: 'acciones' }, confirmar) : null));
    });
    return el('div', { class: 'tarjeta' }, el('h2', {}, 'Precios y costos por CSV'),
        el('p', { class: 'ayuda' }, 'Primera fila con los nombres de columna: sku y precio o costo; opcionales vigencia_desde (AAAA-MM-DD, sin fecha es hoy) y moneda (PES si falta). Separador ; o , y decimales con coma o punto. Solo cambia artículos que ya existen; un SKU que no está se lista aparte y no se crea. Ejemplo:'),
        el('pre', { class: 'mono' }, 'sku;precio;costo\nABC-001;1250,00;800\nXYZ-9;990;'),
        el('div', { class: 'fila-form' }, archivo, previa), zona);
}

// ===== Pantalla Articulos =====
async function vistaArticulos(contenedor) {
    const vigente = redibujar(contenedor);
    let opciones;
    try {
        opciones = await api('/api/articulos/opciones');
    } catch (e) {
        if (vigente()) contenedor.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' }, e.message)));
        return;
    }
    if (!vigente()) return;
    const alicuota = codigo => (opciones.alicuotas.find(a => a.codigo === String(codigo)) || {}).descripcion || codigo;
    const puedeEditar = puedeEditarArticulos();

    const zonaForm = el('div', {});
    const buscador = el('input', { type: 'search', placeholder: 'Buscar por SKU o descripción', 'aria-label': 'Buscar artículo', maxlength: 100 });
    const inactivos = el('input', { type: 'checkbox' });
    const cuerpo = el('tbody');
    const nuevo = el('button', { type: 'button' }, 'Nuevo artículo');
    nuevo.addEventListener('click', () => abrirForm(null));

    async function abrirForm(resumen) {
        let articulo = null;
        if (resumen) {
            try { articulo = await api('/api/articulos/' + encodeURIComponent(resumen.id)); }
            catch (e) { mostrarMensaje(e.message, 'error'); return; }
        }
        vaciar(zonaForm).append(
            el('div', { class: 'tarjeta' }, el('h2', {}, articulo ? 'Editar artículo' : 'Nuevo artículo'),
                formularioArticulo(opciones, articulo, (guardado) => { if (articulo) abrirForm(guardado); else vaciar(zonaForm); buscar(); }, () => vaciar(zonaForm))),
            articulo ? tarjetaPrecios(opciones, articulo, (actualizado) => { abrirForm(actualizado); buscar(); }) : null);
        zonaForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    let espera = null;
    async function buscar() {
        let lista;
        try {
            lista = await api('/api/articulos?limite=200&q=' + encodeURIComponent(buscador.value) + (inactivos.checked ? '&incluir_inactivos=true' : ''));
        } catch (e) { mostrarMensaje(e.message, 'error'); return; }
        vaciar(cuerpo);
        if (!lista.length) cuerpo.append(el('tr', {}, el('td', { colspan: 7, class: 'vacio' }, 'No hay artículos que coincidan.')));
        for (const a of lista) {
            const editar = el('button', { type: 'button', class: 'secundario' }, 'Editar');
            editar.addEventListener('click', () => abrirForm(a));
            const fila = el('tr', {},
                el('td', { class: 'mono sin-corte' }, a.sku),
                el('td', {}, a.descripcion, a.categoria ? el('div', { class: 'sub' }, a.categoria) : null),
                el('td', {}, alicuota(a.alicuota_iva)),
                el('td', { class: 'mono' }, formatoImporte(a.costo)),
                el('td', { class: 'mono' }, a.precio === null ? el('span', { class: 'etiqueta' }, 'Sin precio') : formatoImporte(a.precio)),
                el('td', {}, a.activo ? el('span', { class: 'etiqueta ok' }, 'Activo') : el('span', { class: 'etiqueta' }, 'Inactivo'),
                    a.origen === 'tracker' ? el('span', { class: 'etiqueta acento' }, 'Tracker360') : null),
                el('td', {}, puedeEditar ? editar : null));
            cuerpo.append(fila);
        }
    }
    buscador.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(buscar, 250); });
    inactivos.addEventListener('change', buscar);

    contenedor.append(
        esAdmin() ? tarjetaConexionTracker() : null,
        puedeEditar ? tarjetaImportarTracker(opciones, buscar) : null,
        puedeEditar ? tarjetaPreciosCsv(buscar) : null,
        el('div', { class: 'tarjeta' },
            el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Artículos'), puedeEditar ? nuevo : null),
            el('p', { class: 'ayuda' }, 'El SKU es único en todo el sistema y es la clave para vincular con Tracker360. El costo es solo de referencia para la rentabilidad; el precio de venta es el final, con IVA incluido.'),
            el('div', { class: 'fila-form' }, buscador, el('label', { class: 'casilla' }, inactivos, 'Incluir inactivos')),
            el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'SKU'), el('th', {}, 'Descripción'), el('th', {}, 'IVA'),
                    el('th', {}, 'Costo'), el('th', {}, 'Precio'), el('th', {}, 'Estado'), el('th', {}, ''))), cuerpo))),
        zonaForm);
    await buscar();
}
