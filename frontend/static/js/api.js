// Llamadas a la API de JZBill. Las escrituras llevan el token CSRF de la cookie csrf_token.
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

// Construye un elemento sin HTML: los textos van siempre como texto (nunca innerHTML con datos).
// Los atributos "on..." solo aceptan funciones (addEventListener): nunca un manejador inline.
// el('td', { class: 'mono' }, 'texto', otroNodo)
function el(etiqueta, atributos = {}, ...hijos) {
    const nodo = document.createElement(etiqueta);
    for (const [clave, valor] of Object.entries(atributos || {})) {
        if (valor === null || valor === undefined || valor === false) continue;
        if (clave.startsWith('on')) {
            if (typeof valor === 'function') nodo.addEventListener(clave.slice(2), valor);
        } else if (clave === 'class') {
            nodo.className = valor;
        } else {
            nodo.setAttribute(clave, valor === true ? '' : String(valor));
        }
    }
    for (const hijo of hijos.flat()) {
        if (hijo === null || hijo === undefined || hijo === false) continue;
        nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
    }
    return nodo;
}

function vaciar(nodo) {
    while (nodo.firstChild) nodo.removeChild(nodo.firstChild);
    return nodo;
}

// Fechas: se guardan en UTC y se muestran en hora de Argentina.
function fechaHora(iso) {
    return new Date(iso).toLocaleString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires', dateStyle: 'short', timeStyle: 'short' });
}

function fecha(iso) {
    return new Date(iso).toLocaleDateString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires' });
}

// Botones de escritura: se deshabilitan mientras dura el pedido y el error se muestra en el aviso.
async function conBoton(boton, accion) {
    if (boton) boton.disabled = true;
    try {
        return await accion();
    } catch (e) {
        mostrarMensaje(e.message, 'error');
        return undefined;
    } finally {
        if (boton) boton.disabled = false;
    }
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
