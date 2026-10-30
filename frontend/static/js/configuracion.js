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
    contenedor.append(tarjetaConexionTracker(), tarjetaCorreo(),
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Dónde está cada cosa'),
            el('p', { class: 'ayuda' }, 'Razones sociales: datos fiscales, puntos de venta, certificados y parámetros de ARCA. Sucursales y Usuarios: quién trabaja dónde. Artículos: importar desde Tracker360 y precios por CSV.')));
}
