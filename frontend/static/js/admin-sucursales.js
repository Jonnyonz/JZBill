// Administracion de sucursales (locales fisicos): alta, datos y, por cada razon social, si factura en la
// sucursal y con que punto de venta predeterminado. Solo administrador (la API lo exige igual).
'use strict';

async function vistaSucursales(contenedor, elegidaId) {
    vaciar(contenedor);
    let lista;
    try {
        lista = await api('/api/sucursales');
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    const formNueva = el('form', { class: 'oculto' },
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Nombre', el('input', { name: 'nombre', required: true, maxlength: 120 })),
            el('label', {}, 'Domicilio', el('input', { name: 'domicilio', maxlength: 300 }))),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, 'Crear sucursal')));
    formNueva.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const nueva = await conBoton(formNueva.querySelector('button'), () => api('/api/sucursales', { method: 'POST', body: {
            nombre: formNueva.elements.nombre.value, domicilio: formNueva.elements.domicilio.value } }));
        if (nueva) { mostrarMensaje('Sucursal creada.', 'ok'); vistaSucursales(contenedor, nueva.id); }
    });

    const cuerpo = el('tbody');
    for (const s of lista) {
        const fila = el('tr', { class: 'seleccionable' + (s.id === elegidaId ? ' elegida' : '') },
            el('td', {}, s.nombre),
            el('td', {}, s.domicilio),
            el('td', {}, el('div', { class: 'contexto-chip' }, s.puntos_venta.map(p => puntoColor(p.color)))),
            el('td', {}, s.activa ? el('span', { class: 'etiqueta ok' }, 'Activa') : el('span', { class: 'etiqueta neutra' }, 'Inactiva')));
        fila.addEventListener('click', () => vistaSucursales(contenedor, s.id));
        cuerpo.append(fila);
    }
    contenedor.append(el('div', { class: 'tarjeta' },
        el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Sucursales'),
            el('button', { type: 'button', class: 'secundario', onclick: () => formNueva.classList.toggle('oculto') }, 'Nueva sucursal')),
        el('p', { class: 'ayuda' }, 'Locales físicos. En un mismo local pueden facturar varias razones sociales, cada una con su punto de venta.'),
        formNueva,
        lista.length
            ? el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'Nombre'), el('th', {}, 'Domicilio'), el('th', {}, 'Razones sociales'), el('th', {}, 'Estado'))), cuerpo))
            : el('p', { class: 'ayuda' }, 'Todavía no hay sucursales.')));

    const elegida = lista.find(s => s.id === elegidaId);
    if (elegida) await detalleSucursal(contenedor, elegida);
}

async function detalleSucursal(contenedor, sucursal) {
    const form = el('form', {},
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Nombre', el('input', { name: 'nombre', required: true, maxlength: 120, value: sucursal.nombre })),
            el('label', {}, 'Domicilio', el('input', { name: 'domicilio', maxlength: 300, value: sucursal.domicilio }))),
        el('label', { class: 'casilla' }, el('input', { type: 'checkbox', name: 'activa', checked: sucursal.activa }), 'Activa'),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, 'Guardar cambios')));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const f = form.elements;
        const r = await conBoton(form.querySelector('button'), () => api(`/api/sucursales/${encodeURIComponent(sucursal.id)}`, {
            method: 'PUT', body: { nombre: f.nombre.value, domicilio: f.domicilio.value, activa: f.activa.checked } }));
        if (r) { mostrarMensaje('Cambios guardados.', 'ok'); await cargarContexto(); vistaSucursales(contenedor, sucursal.id); }
    });

    const tarjetaPv = el('div', { class: 'tarjeta' }, el('h2', {}, 'Razones sociales que facturan acá'),
        el('p', { class: 'ayuda' }, 'El punto de venta elegido es el que se usa solo cuando un usuario de esta sucursal entra a cobrar. Cada punto de venta puede estar en un solo local.'));
    contenedor.append(el('div', { class: 'tarjeta' }, el('h2', {}, sucursal.nombre), form), tarjetaPv);

    let razones;
    try {
        razones = (await api('/api/razones-sociales')).filter(r => r.activa);
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    if (!razones.length) {
        tarjetaPv.append(el('p', { class: 'ayuda' }, 'Todavía no hay razones sociales activas.'));
        return;
    }
    const actuales = new Map(sucursal.puntos_venta.map(p => [p.razon_social_id, p.punto_venta_id]));
    const selectores = [];
    const cuerpo = el('tbody');
    for (const rs of razones) {
        const selector = el('select', { 'aria-label': 'Punto de venta de ' + rs.nombre_legal },
            el('option', { value: '' }, 'No factura en esta sucursal'));
        try {
            for (const pv of await api(`/api/razones-sociales/${encodeURIComponent(rs.id)}/puntos-venta`)) {
                if (!pv.activo && actuales.get(rs.id) !== pv.id) continue;
                selector.append(el('option', { value: pv.id, selected: actuales.get(rs.id) === pv.id },
                    numeroPv(pv.numero) + (pv.descripcion ? ' ' + pv.descripcion : '')));
            }
        } catch (e) {
            mostrarMensaje(e.message, 'error');
        }
        selectores.push({ rs, selector });
        cuerpo.append(el('tr', {},
            el('td', {}, el('div', { class: 'contexto-chip' }, puntoColor(rs.color), rs.nombre_legal)),
            el('td', {}, selector)));
    }
    const guardar = el('button', { type: 'button' }, 'Guardar');
    guardar.addEventListener('click', async () => {
        const puntos = selectores.filter(x => x.selector.value).map(x => ({ razon_social_id: x.rs.id, punto_venta_id: x.selector.value }));
        const r = await conBoton(guardar, () => api(`/api/sucursales/${encodeURIComponent(sucursal.id)}/puntos-venta`, {
            method: 'PUT', body: { puntos_venta: puntos } }));
        if (r) { mostrarMensaje('Puntos de venta guardados.', 'ok'); await cargarContexto(); }
    });
    tarjetaPv.append(el('div', { class: 'tabla-scroll' }, el('table', {},
        el('thead', {}, el('tr', {}, el('th', {}, 'Razón social'), el('th', {}, 'Punto de venta predeterminado'))), cuerpo)),
        el('div', { class: 'acciones' }, guardar));
}
