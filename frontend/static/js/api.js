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

// Punto con el color de una razon social. El color se fija por CSSOM (style.setProperty), que la CSP permite;
// nunca con un atributo style. Solo se aceptan colores #rrggbb.
function puntoColor(color) {
    const punto = el('span', { class: 'punto-color', 'aria-hidden': 'true' });
    if (/^#[0-9a-f]{6}$/i.test(color || '')) punto.style.setProperty('--punto', color);
    return punto;
}

function vaciar(nodo) {
    while (nodo.firstChild) nodo.removeChild(nodo.firstChild);
    return nodo;
}

// Redibujo de una tarjeta que espera a la API: vacia y devuelve vigente(). Si mientras espera empieza otro
// redibujo (dos botones seguidos), vigente() da false y el anterior no agrega nada (no se duplica).
function redibujar(nodo) {
    const n = (nodo._dibujo = (nodo._dibujo || 0) + 1);
    vaciar(nodo);
    return () => nodo._dibujo === n;
}

// Fechas: se guardan en UTC y se muestran en hora de Argentina.
function fechaHora(iso) {
    return new Date(iso).toLocaleString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires', dateStyle: 'short', timeStyle: 'short' });
}

function fecha(iso) {
    // Fecha sola (AAAA-MM-DD, por ejemplo la de un comprobante): es un dia calendario, sin hora ni zona. Pasarla por
    // Date la toma como medianoche UTC y en Argentina mostraria el dia anterior.
    const solo = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso));
    if (solo) return `${Number(solo[3])}/${Number(solo[2])}/${solo[1]}`;
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
