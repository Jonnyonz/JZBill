// Administracion de razones sociales: alta, datos de encabezado, puntos de venta y certificados de ARCA.
// Solo administrador (la API lo exige igual). Todo se arma con el() / textContent: nunca HTML con datos.
'use strict';

const CONDICIONES_IVA = { responsable_inscripto: 'Responsable inscripto', monotributo: 'Monotributo', exento: 'Exento' };
const MAX_PEM = 16000;

function selectCondicion(valor) {
    const s = el('select', { name: 'condicion_iva', required: true });
    for (const [k, v] of Object.entries(CONDICIONES_IVA)) s.append(el('option', { value: k, selected: k === valor }, v));
    return s;
}

async function vistaRazones(contenedor, elegidaId) {
    vaciar(contenedor);
    let lista;
    try {
        lista = await api('/api/razones-sociales');
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    const formNueva = el('form', { class: 'oculto' },
        el('div', { class: 'grilla-form' },
            el('label', {}, 'CUIT', el('input', { name: 'cuit', required: true, maxlength: 20, placeholder: '30-12345678-9', autocomplete: 'off' })),
            el('label', {}, 'Nombre legal', el('input', { name: 'nombre_legal', required: true, maxlength: 200 })),
            el('label', {}, 'Nombre de fantasía', el('input', { name: 'nombre_fantasia', maxlength: 200 })),
            el('label', {}, 'Condición frente al IVA', selectCondicion('responsable_inscripto')),
            el('label', {}, 'Domicilio', el('input', { name: 'domicilio', maxlength: 300 }))),
        el('label', { class: 'casilla' }, el('input', { type: 'checkbox', name: 'regimen_arba_bsas' }),
            'Percibe o retiene ingresos brutos de Buenos Aires (régimen especial ARBA)'),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, 'Crear razón social')));
    formNueva.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const f = formNueva.elements;
        const nueva = await conBoton(formNueva.querySelector('button'), () => api('/api/razones-sociales', { method: 'POST', body: {
            cuit: f.cuit.value, nombre_legal: f.nombre_legal.value, nombre_fantasia: f.nombre_fantasia.value,
            condicion_iva: f.condicion_iva.value, domicilio: f.domicilio.value, regimen_arba_bsas: f.regimen_arba_bsas.checked } }));
        if (nueva) {
            mostrarMensaje('Razón social creada.', 'ok');
            await cargarContexto();
            vistaRazones(contenedor, nueva.id);
        }
    });

    const cuerpo = el('tbody');
    for (const rs of lista) {
        const fila = el('tr', { class: 'seleccionable' + (rs.id === elegidaId ? ' elegida' : '') },
            el('td', {}, el('div', { class: 'contexto-chip' }, puntoColor(rs.color), rs.nombre_legal),
                rs.nombre_fantasia ? el('div', { class: 'sub' }, rs.nombre_fantasia) : null),
            el('td', { class: 'mono' }, rs.cuit_formateado),
            el('td', {}, CONDICIONES_IVA[rs.condicion_iva]),
            el('td', {}, rs.activa ? el('span', { class: 'etiqueta ok' }, 'Activa') : el('span', { class: 'etiqueta neutra' }, 'Inactiva')));
        fila.addEventListener('click', () => vistaRazones(contenedor, rs.id));
        cuerpo.append(fila);
    }
    contenedor.append(el('div', { class: 'tarjeta' },
        el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Razones sociales'),
            el('button', { type: 'button', class: 'secundario', onclick: () => formNueva.classList.toggle('oculto') }, 'Nueva razón social')),
        formNueva,
        lista.length
            ? el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'Nombre'), el('th', {}, 'CUIT'), el('th', {}, 'IVA'), el('th', {}, 'Estado'))), cuerpo))
            : el('p', { class: 'ayuda' }, 'Todavía no hay razones sociales. Creá la primera con el botón de arriba.')));

    const elegida = lista.find(r => r.id === elegidaId);
    if (elegida) contenedor.append(...detalleRazon(contenedor, elegida));
}

function detalleRazon(contenedor, rs) {
    const form = el('form', {},
        el('div', { class: 'grilla-form' },
            el('label', {}, 'CUIT (no se modifica)', el('input', { value: rs.cuit_formateado, disabled: true })),
            el('label', {}, 'Nombre legal', el('input', { name: 'nombre_legal', required: true, maxlength: 200, value: rs.nombre_legal })),
            el('label', {}, 'Nombre de fantasía', el('input', { name: 'nombre_fantasia', maxlength: 200, value: rs.nombre_fantasia })),
            el('label', {}, 'Condición frente al IVA', selectCondicion(rs.condicion_iva)),
            el('label', {}, 'Domicilio', el('input', { name: 'domicilio', maxlength: 300, value: rs.domicilio })),
            el('label', {}, 'Color (barra superior)', el('input', { type: 'color', name: 'color', value: rs.color }))),
        el('label', { class: 'casilla' }, el('input', { type: 'checkbox', name: 'regimen_arba_bsas', checked: rs.regimen_arba_bsas }),
            'Percibe o retiene ingresos brutos de Buenos Aires (régimen especial ARBA)'),
        el('label', { class: 'casilla' }, el('input', { type: 'checkbox', name: 'activa', checked: rs.activa }), 'Activa'),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, 'Guardar cambios')));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const f = form.elements;
        const r = await conBoton(form.querySelector('button[type=submit]'), () => api(`/api/razones-sociales/${encodeURIComponent(rs.id)}`, { method: 'PUT', body: {
            nombre_legal: f.nombre_legal.value, nombre_fantasia: f.nombre_fantasia.value, condicion_iva: f.condicion_iva.value,
            domicilio: f.domicilio.value, regimen_arba_bsas: f.regimen_arba_bsas.checked, activa: f.activa.checked,
            color: f.color.value } }));
        if (r) {
            mostrarMensaje('Cambios guardados.', 'ok');
            await cargarContexto();
            vistaRazones(contenedor, rs.id);
        }
    });

    const tarjetaPv = el('div', { class: 'tarjeta' });
    const tarjetaCert = el('div', { class: 'tarjeta' });
    puntosVenta(tarjetaPv, rs);
    certificados(tarjetaCert, rs, 'empresa');
    return [el('div', { class: 'tarjeta' }, el('h2', { class: 'contexto-chip' }, puntoColor(rs.color), rs.nombre_legal), form),
            el('div', { class: 'dos-columnas' }, tarjetaPv, tarjetaCert)];
}

async function puntosVenta(tarjeta, rs) {
    vaciar(tarjeta).append(el('h2', {}, 'Puntos de venta'));
    let lista;
    try {
        lista = await api(`/api/razones-sociales/${encodeURIComponent(rs.id)}/puntos-venta`);
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    const cuerpo = el('tbody');
    for (const pv of lista) {
        const boton = el('button', { type: 'button', class: 'secundario' }, pv.activo ? 'Desactivar' : 'Activar');
        boton.addEventListener('click', async () => {
            const r = await conBoton(boton, () => api(`/api/razones-sociales/${encodeURIComponent(rs.id)}/puntos-venta/${encodeURIComponent(pv.id)}`,
                { method: 'PUT', body: { activo: !pv.activo } }));
            if (r) puntosVenta(tarjeta, rs);
        });
        cuerpo.append(el('tr', {},
            el('td', { class: 'mono' }, String(pv.numero).padStart(5, '0')),
            el('td', {}, pv.descripcion),
            el('td', {}, pv.activo ? el('span', { class: 'etiqueta ok' }, 'Activo') : el('span', { class: 'etiqueta neutra' }, 'Inactivo')),
            el('td', {}, boton)));
    }
    const form = el('form', {},
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Número', el('input', { name: 'numero', type: 'number', min: 1, max: 99999, required: true })),
            el('label', {}, 'Descripción', el('input', { name: 'descripcion', maxlength: 120 }))),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, 'Agregar punto de venta')));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const r = await conBoton(form.querySelector('button'), () => api(`/api/razones-sociales/${encodeURIComponent(rs.id)}/puntos-venta`,
            { method: 'POST', body: { numero: Number(form.elements.numero.value), descripcion: form.elements.descripcion.value } }));
        if (r) { mostrarMensaje('Punto de venta agregado.', 'ok'); puntosVenta(tarjeta, rs); }
    });
    tarjeta.append(
        lista.length ? el('div', { class: 'tabla-scroll' }, el('table', {}, el('thead', {}, el('tr', {},
            el('th', {}, 'Número'), el('th', {}, 'Descripción'), el('th', {}, 'Estado'), el('th', {}, ''))), cuerpo))
            : el('p', { class: 'ayuda' }, 'Sin puntos de venta.'),
        form);
}

async function certificados(tarjeta, rs, modo) {
    vaciar(tarjeta);
    const selector = el('select', { 'aria-label': 'Modo' },
        el('option', { value: 'empresa', selected: modo === 'empresa' }, 'Empresa (producción de ARCA)'),
        el('option', { value: 'prueba', selected: modo === 'prueba' }, 'Prueba (homologación)'));
    selector.addEventListener('change', () => certificados(tarjeta, rs, selector.value));
    tarjeta.append(el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Certificados de ARCA'), selector));
    let lista;
    try {
        lista = await api(`/api/razones-sociales/${encodeURIComponent(rs.id)}/certificados?modo=${encodeURIComponent(modo)}`);
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    const cuerpo = el('tbody');
    for (const c of lista) {
        const vence = c.dias_para_vencer < 30 ? 'aviso' : 'ok';
        cuerpo.append(el('tr', {},
            el('td', {}, c.alias || c.sujeto, el('div', { class: 'sub mono' }, c.huella.slice(0, 16))),
            el('td', {}, fecha(c.valido_hasta), el('div', {}, el('span', { class: 'etiqueta ' + vence }, `${c.dias_para_vencer} días`))),
            el('td', {}, c.activo ? el('span', { class: 'etiqueta ok' }, 'En uso') : el('span', { class: 'etiqueta neutra' }, 'Reemplazado'))));
    }
    const form = el('form', {},
        el('p', { class: 'ayuda' }, 'El certificado y la clave privada se guardan cifrados y no se pueden volver a descargar. La clave no puede tener contraseña.'),
        el('label', {}, 'Alias (opcional)', el('input', { name: 'alias', maxlength: 120 })),
        el('label', {}, 'Certificado (.crt / .pem)', el('input', { name: 'certificado', type: 'file', accept: '.crt,.pem,.cer', required: true })),
        el('label', {}, 'Clave privada (.key / .pem)', el('input', { name: 'clave', type: 'file', accept: '.key,.pem', required: true })),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, `Cargar certificado (${modo === 'prueba' ? 'prueba' : 'empresa'})`)));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const archivoCert = form.elements.certificado.files[0];
        const archivoClave = form.elements.clave.files[0];
        if (!archivoCert || !archivoClave || archivoCert.size > MAX_PEM || archivoClave.size > MAX_PEM) {
            mostrarMensaje('Elegí el certificado y la clave (cada uno de hasta 16 KB).', 'error');
            return;
        }
        const r = await conBoton(form.querySelector('button'), async () => api(`/api/razones-sociales/${encodeURIComponent(rs.id)}/certificados`, {
            method: 'POST', body: { modo, alias: form.elements.alias.value,
                certificado_pem: await archivoCert.text(), clave_pem: await archivoClave.text() } }));
        form.reset();
        if (r) { mostrarMensaje('Certificado cargado.', 'ok'); certificados(tarjeta, rs, modo); }
    });
    tarjeta.append(
        lista.length ? el('div', { class: 'tabla-scroll' }, el('table', {}, el('thead', {}, el('tr', {},
            el('th', {}, 'Certificado'), el('th', {}, 'Vence'), el('th', {}, 'Estado'))), cuerpo))
            : el('p', { class: 'ayuda' }, `Sin certificado para el modo ${modo}.`),
        form);
}
