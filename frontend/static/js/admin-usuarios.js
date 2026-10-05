// Administracion de usuarios: alta, rol global, activacion, reseteo de clave y accesos por razon social,
// modo y (opcional) punto de venta. Solo administrador (la API lo exige igual).
'use strict';

function selectRol(valor) {
    const s = el('select', { name: 'rol', required: true });
    for (const [k, v] of Object.entries(ROLES)) s.append(el('option', { value: k, selected: k === valor }, v));
    return s;
}

async function vistaUsuarios(contenedor, elegidoId) {
    vaciar(contenedor);
    let lista;
    try {
        lista = await api('/api/usuarios');
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    const formNuevo = el('form', { class: 'oculto', autocomplete: 'off' },
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Usuario', el('input', { name: 'usuario', required: true, minlength: 3, maxlength: 50, autocomplete: 'off' })),
            el('label', {}, 'Nombre', el('input', { name: 'nombre', maxlength: 120 })),
            el('label', {}, 'Rol', selectRol('cajero')),
            el('label', {}, 'Contraseña inicial (mínimo 10)', el('input', { name: 'clave', type: 'password', required: true, minlength: 10, maxlength: 128, autocomplete: 'new-password' }))),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, 'Crear usuario')));
    formNuevo.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const f = formNuevo.elements;
        const nuevo = await conBoton(formNuevo.querySelector('button'), () => api('/api/usuarios', { method: 'POST', body: {
            usuario: f.usuario.value, nombre: f.nombre.value, rol: f.rol.value, clave: f.clave.value } }));
        if (nuevo) { mostrarMensaje('Usuario creado. Asignale las razones sociales.', 'ok'); vistaUsuarios(contenedor, nuevo.id); }
    });

    const cuerpo = el('tbody');
    for (const u of lista) {
        const fila = el('tr', { class: 'seleccionable' + (u.id === elegidoId ? ' elegida' : '') },
            el('td', { class: 'mono' }, u.usuario),
            el('td', {}, u.nombre),
            el('td', {}, ROLES[u.rol]),
            el('td', {}, u.activo ? el('span', { class: 'etiqueta ok' }, 'Activo') : el('span', { class: 'etiqueta neutra' }, 'Inactivo')));
        fila.addEventListener('click', () => vistaUsuarios(contenedor, u.id));
        cuerpo.append(fila);
    }
    contenedor.append(el('div', { class: 'tarjeta' },
        el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Usuarios'),
            el('button', { type: 'button', class: 'secundario', onclick: () => formNuevo.classList.toggle('oculto') }, 'Nuevo usuario')),
        formNuevo,
        el('div', { class: 'tabla-scroll' }, el('table', {},
            el('thead', {}, el('tr', {}, el('th', {}, 'Usuario'), el('th', {}, 'Nombre'), el('th', {}, 'Rol'), el('th', {}, 'Estado'))), cuerpo))));

    if (elegidoId && lista.some(u => u.id === elegidoId)) await detalleUsuario(contenedor, elegidoId);
}

async function detalleUsuario(contenedor, usuarioId) {
    let u, razones;
    try {
        [u, razones] = await Promise.all([api(`/api/usuarios/${encodeURIComponent(usuarioId)}`), api('/api/razones-sociales')]);
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    const esYo = Panel.yo && Panel.yo.usuario === u.usuario;
    const form = el('form', { autocomplete: 'off' },
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Nombre', el('input', { name: 'nombre', maxlength: 120, value: u.nombre })),
            el('label', {}, 'Rol', selectRol(u.rol)),
            esYo ? null : el('label', {}, 'Resetear contraseña (opcional)',
                el('input', { name: 'clave_nueva', type: 'password', minlength: 10, maxlength: 128, autocomplete: 'new-password' }))),
        el('label', { class: 'casilla' }, el('input', { type: 'checkbox', name: 'activo', checked: u.activo }), 'Activo'),
        el('p', { class: 'ayuda' }, 'Resetear la contraseña o desactivar al usuario cierra todas sus sesiones.'),
        el('div', { class: 'acciones' }, el('button', { type: 'submit' }, 'Guardar cambios')));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const f = form.elements;
        const cuerpo = { nombre: f.nombre.value, rol: f.rol.value, activo: f.activo.checked };
        if (f.clave_nueva && f.clave_nueva.value) cuerpo.clave_nueva = f.clave_nueva.value;
        const r = await conBoton(form.querySelector('button[type=submit]'), () => api(`/api/usuarios/${encodeURIComponent(u.id)}`, { method: 'PUT', body: cuerpo }));
        if (r) {
            mostrarMensaje('Cambios guardados.', 'ok');
            if (esYo && r.rol !== 'administrador') { window.location.reload(); return; }
            vistaUsuarios(contenedor, u.id);
        }
    });
    const tarjetaAccesos = el('div', { class: 'tarjeta' });
    const tarjetaSucursales = el('div', { class: 'tarjeta' });
    contenedor.append(el('div', { class: 'tarjeta' }, el('h2', {}, `${u.nombre || u.usuario} (${u.usuario})`), form),
        tarjetaSucursales, tarjetaAccesos);
    await editorSucursales(tarjetaSucursales, u);
    await editorAccesos(tarjetaAccesos, u, razones);
}

async function editorAccesos(tarjeta, u, razones) {
    vaciar(tarjeta).append(el('h2', {}, 'Razones sociales a las que accede'));
    if (u.rol === 'administrador') {
        tarjeta.append(el('p', { class: 'ayuda' }, 'Los administradores entran a todas las razones sociales, en los dos modos.'));
        return;
    }
    if (!razones.length) {
        tarjeta.append(el('p', { class: 'ayuda' }, 'Todavía no hay razones sociales.'));
        return;
    }
    const actuales = new Map(u.accesos.map(a => [a.razon_social_id, a]));
    const bloques = [];
    for (const rs of razones) {
        const actual = actuales.get(rs.id);
        const casillaModo = (modo) => el('input', { type: 'checkbox', 'data-modo': modo, checked: !!(actual && actual.modos.includes(modo)) });
        const empresa = casillaModo('empresa');
        const prueba = casillaModo('prueba');
        const pvs = el('div', { class: 'accesos-pv' });
        const bloque = el('div', { class: 'accesos-rs' },
            el('div', {}, el('strong', {}, rs.nombre_legal), ' ', el('span', { class: 'sub mono' }, rs.cuit_formateado), ' ',
                rs.activa ? null : el('span', { class: 'etiqueta neutra' }, 'Inactiva')),
            el('div', { class: 'acciones' }, el('label', { class: 'casilla' }, empresa, 'Empresa'), el('label', { class: 'casilla' }, prueba, 'Prueba')),
            pvs);
        bloques.push({ rs, empresa, prueba, pvs });
        try {
            const lista = await api(`/api/razones-sociales/${encodeURIComponent(rs.id)}/puntos-venta`);
            if (lista.length) {
                const elegidos = new Set(actual ? actual.puntos_venta : []);
                pvs.append(el('span', { class: 'sub' }, 'Puntos de venta (sin marcar ninguno: todos):'));
                for (const pv of lista) {
                    pvs.append(el('label', { class: 'casilla' },
                        el('input', { type: 'checkbox', 'data-pv': pv.id, checked: elegidos.has(pv.id) }),
                        String(pv.numero).padStart(5, '0') + (pv.descripcion ? ' ' + pv.descripcion : '')));
                }
            }
        } catch (e) {
            mostrarMensaje(e.message, 'error');
        }
        tarjeta.append(bloque);
    }
    const guardar = el('button', { type: 'button' }, 'Guardar accesos');
    guardar.addEventListener('click', async () => {
        const accesos = [];
        for (const b of bloques) {
            const modos = [b.empresa, b.prueba].filter(c => c.checked).map(c => c.dataset.modo);
            if (!modos.length) continue;
            const puntos = [...b.pvs.querySelectorAll('input[data-pv]')].filter(c => c.checked).map(c => c.dataset.pv);
            accesos.push({ razon_social_id: b.rs.id, modos, puntos_venta: puntos });
        }
        const r = await conBoton(guardar, () => api(`/api/usuarios/${encodeURIComponent(u.id)}/accesos`, { method: 'PUT', body: { accesos } }));
        if (r) mostrarMensaje('Accesos guardados.', 'ok');
    });
    tarjeta.append(el('div', { class: 'acciones' }, guardar));
}

async function editorSucursales(tarjeta, u) {
    vaciar(tarjeta).append(el('h2', {}, 'Sucursales'),
        el('p', { class: 'ayuda' }, 'Donde trabaja. Al entrar se elige sola la predeterminada, con su punto de venta.'));
    let sucursales;
    try {
        sucursales = await api('/api/sucursales');
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return;
    }
    if (!sucursales.length) {
        tarjeta.append(el('p', { class: 'ayuda' }, 'Todavía no hay sucursales. Crealas en Sucursales.'));
        return;
    }
    const asignadas = new Map(u.sucursales.map(s => [s.sucursal_id, s.predeterminada]));
    const filas = [];
    const cuerpo = el('tbody');
    for (const s of sucursales) {
        const casilla = el('input', { type: 'checkbox', checked: asignadas.has(s.id), 'aria-label': 'Asignada: ' + s.nombre });
        const radio = el('input', { type: 'radio', name: 'sucursal-predeterminada-' + u.id, value: s.id,
            checked: asignadas.get(s.id) === true, 'aria-label': 'Predeterminada: ' + s.nombre });
        radio.addEventListener('change', () => { if (radio.checked) casilla.checked = true; });
        casilla.addEventListener('change', () => { if (!casilla.checked) radio.checked = false; });
        filas.push({ s, casilla, radio });
        cuerpo.append(el('tr', {}, el('td', {}, casilla), el('td', {}, s.nombre, s.activa ? null : ' (inactiva)'), el('td', {}, radio)));
    }
    const guardar = el('button', { type: 'button' }, 'Guardar sucursales');
    guardar.addEventListener('click', async () => {
        const elegidas = filas.filter(f => f.casilla.checked);
        const predeterminada = elegidas.find(f => f.radio.checked);
        const cuerpoPut = { sucursales: elegidas.map(f => f.s.id) };
        if (predeterminada) cuerpoPut.predeterminada = predeterminada.s.id;
        const r = await conBoton(guardar, () => api(`/api/usuarios/${encodeURIComponent(u.id)}/sucursales`, { method: 'PUT', body: cuerpoPut }));
        if (r) {
            u.sucursales = r.sucursales;
            mostrarMensaje('Sucursales guardadas.', 'ok');
            editorSucursales(tarjeta, u);
        }
    });
    tarjeta.append(el('div', { class: 'tabla-scroll' }, el('table', {},
        el('thead', {}, el('tr', {}, el('th', {}, 'Asignada'), el('th', {}, 'Sucursal'), el('th', {}, 'Predeterminada'))), cuerpo)),
        el('div', { class: 'acciones' }, guardar));
}
