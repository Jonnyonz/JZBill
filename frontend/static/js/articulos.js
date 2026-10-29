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
    const sku = el('input', { name: 'sku', required: true, maxlength: 60, title: 'Sin espacios', value: articulo ? articulo.sku : '' });
    const descripcion = el('input', { name: 'descripcion', required: true, maxlength: 200, value: articulo ? articulo.descripcion : '' });
    const categoria = el('input', { name: 'categoria', maxlength: 80, value: articulo ? articulo.categoria : '' });
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
        if (!lista.length) cuerpo.append(el('tr', {}, el('td', { colspan: 6, class: 'vacio' }, 'No hay artículos que coincidan.')));
        for (const a of lista) {
            const fila = el('tr', { class: 'seleccionable' },
                el('td', { class: 'mono sin-corte' }, a.sku),
                el('td', {}, a.descripcion, a.categoria ? el('div', { class: 'sub' }, a.categoria) : null),
                el('td', {}, alicuota(a.alicuota_iva)),
                el('td', { class: 'mono' }, formatoImporte(a.costo)),
                el('td', { class: 'mono' }, a.precio === null ? el('span', { class: 'etiqueta' }, 'Sin precio') : formatoImporte(a.precio)),
                el('td', {}, a.activo ? el('span', { class: 'etiqueta ok' }, 'Activo') : el('span', { class: 'etiqueta' }, 'Inactivo')));
            fila.addEventListener('click', () => abrirForm(a));
            cuerpo.append(fila);
        }
    }
    buscador.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(buscar, 250); });
    inactivos.addEventListener('change', buscar);

    contenedor.append(
        el('div', { class: 'tarjeta' },
            el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Artículos'), puedeEditar ? nuevo : null),
            el('p', { class: 'ayuda' }, 'El SKU es único en todo el sistema y es la clave para vincular con Tracker360. El costo es solo de referencia para la rentabilidad; el precio de venta es el final, con IVA incluido.'),
            el('div', { class: 'fila-form' }, buscador, el('label', { class: 'casilla' }, inactivos, 'Incluir inactivos')),
            el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'SKU'), el('th', {}, 'Descripción'), el('th', {}, 'IVA'),
                    el('th', {}, 'Costo'), el('th', {}, 'Precio'), el('th', {}, 'Estado'))), cuerpo))),
        zonaForm);
    await buscar();
}
