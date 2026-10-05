// Llamadas a la API de JZFactura. Las escrituras llevan el token CSRF de la cookie csrf_token.
'use strict';

function csrfToken() {
    const c = document.cookie.split('; ').find(r => r.startsWith('csrf_token='));
    return c ? decodeURIComponent(c.slice('csrf_token='.length)) : '';
}

async function api(url, opciones = {}) {
    const metodo = (opciones.method || 'GET').toUpperCase();
    const headers = { ...(opciones.headers || {}) };
    let body = opciones.body;
    if (body !== undefined && typeof body !== 'string') {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(body);
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(metodo)) headers['X-CSRF-Token'] = csrfToken();
    const r = await fetch(url, { method: metodo, headers, body, credentials: 'same-origin' });
    let datos = null;
    try { datos = await r.json(); } catch (e) { datos = null; }
    if (r.status === 401 && !url.startsWith('/api/auth/login') && !url.startsWith('/api/auth/setup')) {
        window.location.href = '/';
        throw new Error('Sesión expirada.');
    }
    if (!r.ok) throw new Error((datos && typeof datos.detail === 'string') ? datos.detail : 'Error al procesar la solicitud.');
    return datos;
}

function mostrarMensaje(texto, tipo = 'ok') {
    const el = document.getElementById('mensaje');
    if (!el) return;
    el.textContent = texto;
    el.className = el.className.replace(/\b(ok|error)\b/g, '').trim() + ' ' + tipo;
    if (el.classList.contains('mensaje-flotante')) {
        clearTimeout(mostrarMensaje._t);
        mostrarMensaje._t = setTimeout(() => { el.textContent = ''; }, 6000);
    }
}
