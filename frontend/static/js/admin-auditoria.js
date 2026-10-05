// Auditoria (solo lectura, solo administrador): mas nuevo primero, filtro por razon social y "Ver mas".
'use strict';

async function vistaAuditoria(contenedor) {
    vaciar(contenedor);
    const filtro = el('select', { 'aria-label': 'Razón social' }, el('option', { value: '' }, 'Todas las razones sociales'));
    try {
        for (const rs of await api('/api/razones-sociales')) filtro.append(el('option', { value: rs.id }, rs.nombre_legal));
    } catch (e) {
        mostrarMensaje(e.message, 'error');
    }
    const cuerpo = el('tbody');
    const masBtn = el('button', { type: 'button', class: 'secundario' }, 'Ver más');
    let menorId = null;

    async function cargar(desdeCero) {
        if (desdeCero) { vaciar(cuerpo); menorId = null; }
        const params = new URLSearchParams({ limite: '50' });
        if (menorId) params.set('antes_de', String(menorId));
        if (filtro.value) params.set('razon_social_id', filtro.value);
        const filas = await conBoton(masBtn, () => api('/api/auditoria?' + params.toString()));
        if (!filas) return;
        for (const f of filas) {
            cuerpo.append(el('tr', {},
                el('td', { class: 'mono sin-corte' }, fechaHora(f.fecha)),
                el('td', {}, f.usuario),
                el('td', {}, el('span', { class: 'etiqueta neutra' }, f.accion)),
                el('td', {}, f.detalle),
                el('td', { class: 'mono' }, f.ip)));
            menorId = f.id;
        }
        masBtn.classList.toggle('oculto', filas.length < 50);
    }

    filtro.addEventListener('change', () => cargar(true));
    masBtn.addEventListener('click', () => cargar(false));
    contenedor.append(el('div', { class: 'tarjeta' },
        el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Registro de acciones'), filtro),
        el('p', { class: 'ayuda' }, 'Inmutable: nadie puede modificar ni borrar estos registros. Horario de Argentina.'),
        el('div', { class: 'tabla-scroll' }, el('table', {},
            el('thead', {}, el('tr', {}, el('th', {}, 'Fecha'), el('th', {}, 'Usuario'), el('th', {}, 'Acción'), el('th', {}, 'Detalle'), el('th', {}, 'IP'))),
            cuerpo)),
        el('div', { class: 'acciones' }, masBtn)));
    await cargar(true);
}
