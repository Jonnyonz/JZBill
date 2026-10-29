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

// ===== Pantalla Configuracion =====
function vistaConfiguracion(contenedor) {
    vaciar(contenedor);
    contenedor.append(tarjetaConexionTracker(),
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Dónde está cada cosa'),
            el('p', { class: 'ayuda' }, 'Razones sociales: datos fiscales, puntos de venta, certificados y parámetros de ARCA. Sucursales y Usuarios: quién trabaja dónde. Artículos: importar desde Tracker360 y precios por CSV.')));
}
