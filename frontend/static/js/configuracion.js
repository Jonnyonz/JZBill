// Configuracion (solo administrador): lo general de la instalacion. Por ahora, la conexion con Tracker360;
// lo fiscal (razones sociales, certificados, parametros de ARCA) sigue en Razones sociales.
'use strict';

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

// ===== Tracker360: stock y cola de ventas (Fase 8, solo administrador) =====
function tarjetaColaTracker() {
    const estado = el('p', { class: 'ayuda' }, 'Cargando...');
    const cuerpo = el('tbody');
    const leer = el('button', { type: 'button', class: 'secundario' }, 'Leer stock ahora');
    const procesar = el('button', { type: 'button', class: 'secundario' }, 'Procesar cola ahora');
    const ETIQUETA = { sincronizado: 'ok', pendiente: 'aviso', error: 'error', descartado: '' };
    function botonCola(texto, id, accion, clase) {
        const b = el('button', { type: 'button', class: clase || 'secundario' }, texto);
        b.addEventListener('click', async () => {
            const r = await conBoton(b, () => api('/api/integraciones/tracker/cola/' + encodeURIComponent(id) + '/' + accion, { method: 'POST' }));
            if (r) cargar();
        });
        return b;
    }
    async function cargar() {
        let d;
        try { d = await api('/api/integraciones/tracker/cola'); } catch (e) { vaciar(estado).append(e.message); return; }
        vaciar(estado).append(...(!d.configurada ? ['Sin conexión con Tracker360: no hay stock ni cola.'] : [
            el('span', { class: 'etiqueta ' + (d.con_error ? 'error' : d.pendientes ? 'aviso' : 'ok') }, d.pendientes + ' pendientes, ' + d.con_error + ' con error, ' + d.sincronizados + ' sincronizados'), ' ',
            'Stock leído: ' + (d.stock_leido_en ? fechaHora(d.stock_leido_en) : 'nunca') + ' · Cola procesada: ' + (d.cola_procesada_en ? fechaHora(d.cola_procesada_en) : 'nunca')
            + (d.sin_tracker ? ' · Artículos activos que no están en Tracker: ' + d.sin_tracker : '')]));
        vaciar(cuerpo);
        if (!d.items.length) cuerpo.append(el('tr', {}, el('td', { colspan: 6, class: 'vacio' }, 'Todavía no hay ventas informadas a Tracker360 (solo las de modo empresa con artículos).')));
        for (const i of d.items) {
            const acciones = [];
            if (i.estado === 'error' || i.estado === 'descartado') acciones.push(botonCola('Reintentar', i.id, 'reintentar'));
            if (i.estado === 'error' || i.estado === 'pendiente') acciones.push(botonCola('Descartar', i.id, 'descartar', 'peligro'));
            cuerpo.append(el('tr', {},
                el('td', { class: 'sin-corte' }, fechaHora(i.creado_en)),
                el('td', {}, i.comprobante, el('div', { class: 'sub mono' }, i.external_ref)),
                el('td', {}, i.accion === 'venta' ? 'Venta' : 'Cancelación'),
                el('td', {}, el('span', { class: 'etiqueta ' + (ETIQUETA[i.estado] || '') }, i.estado),
                    i.respuesta && i.respuesta.document_number ? el('div', { class: 'sub mono' }, 'Pedido ' + i.respuesta.document_number) : null),
                el('td', {}, i.ultimo_error ? el('span', { class: 'sub' }, i.ultimo_error) : ''),
                el('td', { class: 'sin-corte' }, acciones)));
        }
    }
    leer.addEventListener('click', async () => {
        const r = await conBoton(leer, () => api('/api/integraciones/tracker/stock', { method: 'POST' }));
        if (r) { mostrarMensaje('Stock leído: ' + r.articulos_tracker + ' SKU en Tracker360.', 'ok'); cargar(); }
    });
    procesar.addEventListener('click', async () => {
        const r = await conBoton(procesar, () => api('/api/integraciones/tracker/cola/procesar', { method: 'POST' }));
        if (r) { mostrarMensaje(r.sincronizados + ' sincronizados, ' + r.con_error + ' con error' + (r.detenida ? '. Detenida: ' + r.detenida : '.'), r.detenida ? 'error' : 'ok'); cargar(); }
    });
    cargar();
    return el('div', { class: 'tarjeta' }, el('h2', {}, 'Tracker360: stock y cola de ventas'),
        el('p', { class: 'ayuda' }, 'Cada venta de modo empresa con artículos entra en Tracker360 como pedido del canal (entrega en mostrador); una nota de crédito la cancela. Si Tracker no responde, la factura se emite igual y la cola se envía en orden cuando vuelve. El stock leído solo avisa al facturar: no frena la venta.'),
        estado, el('div', { class: 'acciones' }, leer, procesar),
        el('div', { class: 'tabla-scroll' }, el('table', {},
            el('thead', {}, el('tr', {}, el('th', {}, 'Fecha'), el('th', {}, 'Comprobante'), el('th', {}, 'Acción'), el('th', {}, 'Estado'), el('th', {}, 'Error'), el('th', {}, ''))),
            cuerpo)));
}

// ===== Correo (SMTP) de la razon social del contexto (solo administrador) =====
function tarjetaCorreo() {
    const estado = el('p', { class: 'ayuda' }, 'Cargando...');
    const servidor = el('input', { maxlength: 200, required: true, placeholder: 'smtp.ejemplo.com' });
    const puerto = el('input', { type: 'number', min: 1, max: 65535, value: '587', required: true });
    const seguridad = el('select', {}, el('option', { value: 'starttls' }, 'STARTTLS (587)'), el('option', { value: 'ssl' }, 'SSL (465)'));
    const usuario = el('input', { maxlength: 200, autocomplete: 'off', placeholder: 'Usuario SMTP (opcional)' });
    const clave = el('input', { type: 'password', maxlength: 200, autocomplete: 'new-password', placeholder: 'Clave SMTP' });
    const remitente = el('input', { type: 'email', maxlength: 200, required: true, placeholder: 'facturacion@ejemplo.com' });
    const nombre = el('input', { maxlength: 120, placeholder: 'Nombre que ve el cliente (opcional)' });
    const automatico = el('input', { type: 'checkbox' });
    const destino = el('input', { type: 'email', maxlength: 200, placeholder: 'Enviar una prueba a...' });
    const guardar = el('button', { type: 'submit' }, 'Guardar');
    const probar = el('button', { type: 'button', class: 'secundario' }, 'Enviar prueba');
    const pintar = (d) => {
        servidor.value = d.servidor; puerto.value = d.puerto; seguridad.value = d.seguridad; usuario.value = d.usuario;
        remitente.value = d.remitente; nombre.value = d.nombre_remitente; automatico.checked = d.envio_automatico;
        clave.placeholder = d.clave_guardada ? 'Clave guardada (dejar vacío para no cambiarla)' : 'Clave SMTP';
        vaciar(estado).append(!d.configurado ? 'Sin configurar: los comprobantes no se pueden enviar por correo.'
            : d.ultimo_error ? el('span', { class: 'etiqueta error' }, 'Último error: ' + d.ultimo_error)
            : d.ultimo_ok ? el('span', { class: 'etiqueta ok' }, 'Último envío correcto: ' + fechaHora(d.ultimo_ok))
            : 'Guardado, sin probar todavía.');
    };
    api('/api/correo').then(pintar).catch(e => vaciar(estado).append(e.message));
    const form = el('form', {},
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Servidor SMTP', servidor), el('label', {}, 'Puerto', puerto), el('label', {}, 'Seguridad', seguridad),
            el('label', {}, 'Usuario', usuario), el('label', {}, 'Clave', clave),
            el('label', {}, 'Remitente', remitente), el('label', {}, 'Nombre del remitente', nombre)),
        el('label', { class: 'casilla' }, automatico, 'Enviar cada comprobante automáticamente al cliente que tenga correo'),
        el('div', { class: 'fila-form' }, guardar, destino, probar));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const d = await conBoton(guardar, () => api('/api/correo', { method: 'PUT', body: {
            servidor: servidor.value, puerto: Number(puerto.value), seguridad: seguridad.value, usuario: usuario.value, clave: clave.value,
            remitente: remitente.value, nombre_remitente: nombre.value, envio_automatico: automatico.checked } }));
        if (d) { clave.value = ''; mostrarMensaje('Correo guardado.', 'ok'); pintar(d); }
    });
    probar.addEventListener('click', async () => {
        if (!destino.value.trim()) { mostrarMensaje('Escribí la dirección a la que mandar la prueba.', 'error'); return; }
        const d = await conBoton(probar, () => api('/api/correo/prueba', { method: 'POST', body: { destinatario: destino.value } }));
        if (d) { mostrarMensaje('Prueba enviada a ' + destino.value.trim() + '.', 'ok'); pintar(d); }
        else api('/api/correo').then(pintar).catch(() => {});
    });
    const c = Panel.contexto;
    return el('div', { class: 'tarjeta' }, el('h2', {}, 'Correo de ' + (c ? (c.nombre_fantasia || c.nombre_legal) : 'la razón social')),
        el('p', { class: 'ayuda' }, 'Servidor SMTP de esta razón social (la elegida en el avatar) para mandar los comprobantes por correo. La clave se guarda cifrada y nunca se muestra. Siempre con TLS.'),
        estado, form);
}

// ===== Pantalla Configuracion =====
function vistaConfiguracion(contenedor) {
    vaciar(contenedor);
    contenedor.append(tarjetaConexionTracker(), tarjetaColaTracker(), tarjetaCorreo(),
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Dónde está cada cosa'),
            el('p', { class: 'ayuda' }, 'Razones sociales: datos fiscales, puntos de venta, certificados y parámetros de ARCA. Sucursales y Usuarios: quién trabaja dónde. Artículos: importar desde Tracker360 y precios por CSV.')));
}
