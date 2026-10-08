// Panel: barra lateral, avatar con el selector "division empresa" (razon social, modo, sucursal y punto de venta
// de esta sesion; se elige solo al entrar), vistas por hash y cambio de contraseña.
// La barra superior toma el color de la razon social; en modo prueba se ve a rayas.
'use strict';

const ROLES = { administrador: 'Administrador', supervisor: 'Supervisor', cajero: 'Cajero', solo_lectura: 'Solo lectura' };
const MODOS = { empresa: 'Empresa', prueba: 'Prueba' };
const TITULOS = { inicio: 'Inicio', razones: 'Razones sociales', sucursales: 'Sucursales', usuarios: 'Usuarios',
                  auditoria: 'Auditoría', cuenta: 'Mi cuenta' };
const VISTAS_ADMIN = ['razones', 'sucursales', 'usuarios', 'auditoria'];

const Panel = { yo: null, contexto: null, opciones: [], sucursales: [] };

function esAdmin() { return Panel.yo && Panel.yo.rol === 'administrador'; }

function iniciales(texto) {
    const partes = String(texto || '?').trim().split(/\s+/).filter(Boolean);
    return ((partes[0] || '?')[0] + (partes[1] ? partes[1][0] : '')).toUpperCase();
}

function numeroPv(numero) { return String(numero).padStart(5, '0'); }

// --- Contexto de la sesion ---
async function cargarContexto() {
    const datos = await api('/api/contexto');
    Panel.contexto = datos.actual;
    Panel.opciones = datos.opciones;
    Panel.sucursales = datos.sucursales;
    const c = Panel.contexto;
    const prueba = !!(c && c.modo === 'prueba');
    document.body.classList.toggle('modo-prueba', prueba);
    if (c && /^#[0-9a-f]{6}$/i.test(c.color)) document.documentElement.style.setProperty('--color-rs', c.color);
    else document.documentElement.style.removeProperty('--color-rs');
    const chip = vaciar(document.getElementById('contexto-chip'));
    if (c) {
        // append() del DOM convierte null en el texto "null": se filtran las partes vacias.
        chip.append(...[puntoColor(c.color),
            el('strong', {}, c.nombre_fantasia || c.nombre_legal),
            el('span', { class: 'mono' }, c.cuit),
            c.sucursal_nombre ? el('span', {}, c.sucursal_nombre) : null,
            c.punto_venta_numero ? el('span', { class: 'mono' }, 'PV ' + numeroPv(c.punto_venta_numero)) : null,
            el('span', { class: 'etiqueta ' + (prueba ? 'aviso' : 'acento') }, MODOS[c.modo])].filter(Boolean));
    } else {
        chip.append(el('span', {}, 'Sin razón social asignada'));
    }
    armarMenu();
}

async function elegirContexto(cuerpo, boton) {
    const r = await conBoton(boton, () => api('/api/contexto', { method: 'PUT', body: cuerpo }));
    if (r === undefined) return;
    await cargarContexto();
    cerrarMenu();
    mostrarVista(vistaActual());
}

// --- Menu del avatar ---
function armarMenu() {
    const menu = vaciar(document.getElementById('menu-avatar'));
    const c = Panel.contexto;
    menu.append(
        el('div', {}, el('strong', {}, Panel.yo.nombre || Panel.yo.usuario), ' ',
            el('span', { class: 'etiqueta neutra' }, ROLES[Panel.yo.rol] || Panel.yo.rol)),
        el('h3', {}, 'División empresa'));
    let selectorSucursal = null;
    if (Panel.sucursales.length) {
        selectorSucursal = el('select', { 'aria-label': 'Sucursal' });
        for (const s of Panel.sucursales) {
            selectorSucursal.append(el('option', { value: s.sucursal_id, selected: c ? c.sucursal_id === s.sucursal_id : s.predeterminada },
                s.nombre + (s.predeterminada ? ' (predeterminada)' : '')));
        }
        menu.append(el('label', {}, 'Sucursal', selectorSucursal));
    }
    if (!Panel.opciones.length) {
        menu.append(el('p', { class: 'ayuda' }, esAdmin()
            ? 'Todavía no hay razones sociales activas. Creá una en Razones sociales.'
            : 'No tiene razones sociales asignadas. Pedíselas a un administrador.'));
    }
    for (const op of Panel.opciones) {
        const esActual = c && c.razon_social_id === op.razon_social_id;
        const botones = op.modos.map(modo => {
            const elegido = esActual && c.modo === modo;
            const b = el('button', { type: 'button', class: elegido ? '' : 'secundario', 'aria-pressed': elegido ? 'true' : 'false' }, MODOS[modo]);
            b.addEventListener('click', () => {
                const cuerpo = { razon_social_id: op.razon_social_id, modo };
                if (selectorSucursal) cuerpo.sucursal_id = selectorSucursal.value;
                elegirContexto(cuerpo, b);
            });
            return b;
        });
        menu.append(el('div', { class: 'opcion-rs' + (esActual ? ' actual' : '') },
            el('div', { class: 'contexto-chip' }, puntoColor(op.color), el('strong', {}, op.nombre_fantasia || op.nombre_legal)),
            el('div', { class: 'sub mono' }, op.cuit),
            el('div', { class: 'acciones' }, botones)));
    }
    menu.append(el('hr'),
        el('button', { type: 'button', class: 'secundario', onclick: () => { cerrarMenu(); location.hash = '#cuenta'; } }, 'Cambiar contraseña'),
        el('button', { type: 'button', class: 'secundario', onclick: cerrarTodas }, 'Cerrar sesión en todos los dispositivos'));
}

function abrirMenu() {
    document.getElementById('menu-avatar').classList.remove('oculto');
    document.getElementById('avatar-btn').setAttribute('aria-expanded', 'true');
}

function cerrarMenu() {
    document.getElementById('menu-avatar').classList.add('oculto');
    document.getElementById('avatar-btn').setAttribute('aria-expanded', 'false');
}

async function salir() {
    try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) { /* se va igual */ }
    window.location.href = '/';
}

async function cerrarTodas() {
    if (!window.confirm('Se va a cerrar la sesión en todos los dispositivos, incluido este. ¿Continuar?')) return;
    try { await api('/api/auth/sesiones/cerrar', { method: 'POST' }); } catch (e) { /* se va igual */ }
    window.location.href = '/';
}

// --- Barra lateral en celular (cajon) ---
function alternarLateral(abrir) {
    document.getElementById('lateral').classList.toggle('abierta', abrir);
    document.getElementById('fondo-lateral').classList.toggle('abierta', abrir);
    document.getElementById('abrir-lateral').setAttribute('aria-expanded', abrir ? 'true' : 'false');
}

// --- Vistas ---
function vistaActual() {
    const nombre = (location.hash || '#inicio').slice(1);
    if (!TITULOS[nombre] || (VISTAS_ADMIN.includes(nombre) && !esAdmin())) return 'inicio';
    return nombre;
}

function mostrarVista(nombre) {
    for (const v of Object.keys(TITULOS)) {
        document.getElementById('vista-' + v).classList.toggle('oculto', v !== nombre);
    }
    document.querySelectorAll('.nav-btn[data-vista]').forEach(b => b.classList.toggle('activo', b.dataset.vista === nombre));
    document.getElementById('titulo-vista').textContent = TITULOS[nombre];
    const contenedor = document.getElementById('vista-' + nombre);
    if (nombre === 'inicio') vistaInicio(contenedor);
    else if (nombre === 'razones') vistaRazones(contenedor);
    else if (nombre === 'sucursales') vistaSucursales(contenedor);
    else if (nombre === 'usuarios') vistaUsuarios(contenedor);
    else if (nombre === 'auditoria') vistaAuditoria(contenedor);
}

function vistaInicio(contenedor) {
    vaciar(contenedor);
    const c = Panel.contexto;
    const tarjeta = el('div', { class: 'tarjeta' });
    if (c) {
        tarjeta.append(
            el('h2', { class: 'contexto-chip' }, puntoColor(c.color), c.nombre_legal),
            el('dl', { class: 'datos' },
                el('dt', {}, 'CUIT'), el('dd', { class: 'mono' }, c.cuit),
                el('dt', {}, 'Modo'), el('dd', {}, MODOS[c.modo]),
                el('dt', {}, 'Sucursal'), el('dd', {}, c.sucursal_nombre || 'Sin sucursal asignada'),
                el('dt', {}, 'Punto de venta'), el('dd', { class: 'mono' }, c.punto_venta_numero ? numeroPv(c.punto_venta_numero) : 'Sin asignar'),
                el('dt', {}, 'Rol'), el('dd', {}, ROLES[Panel.yo.rol])),
            el('p', { class: 'ayuda' }, 'La facturación llega en las próximas versiones. Para cambiar de razón social, modo o sucursal, usá el menú del avatar.'));
    } else {
        tarjeta.append(el('h2', {}, 'Sin razones sociales'),
            el('p', { class: 'ayuda' }, esAdmin()
                ? 'Creá la primera razón social en Razones sociales.'
                : 'Todavía no tiene razones sociales asignadas. Pedíselas a un administrador.'));
    }
    contenedor.append(tarjeta);
}

function prepararCuenta() {
    const form = document.getElementById('form-clave');
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const nueva = document.getElementById('clave-nueva').value;
        if (nueva !== document.getElementById('clave-repetida').value) {
            mostrarMensaje('Las dos contraseñas nuevas no coinciden.', 'error');
            return;
        }
        const r = await conBoton(form.querySelector('button'), () => api('/api/auth/clave', { method: 'POST', body: {
            clave_actual: document.getElementById('clave-actual').value, clave_nueva: nueva } }));
        if (r) { form.reset(); mostrarMensaje(r.mensaje, 'ok'); }
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    try {
        Panel.yo = await api('/api/auth/me');
    } catch (e) {
        return;   // api() ya redirige al ingreso si la sesion vencio
    }
    document.getElementById('avatar').textContent = iniciales(Panel.yo.nombre || Panel.yo.usuario);
    document.getElementById('avatar-nombre').textContent = Panel.yo.nombre || Panel.yo.usuario;
    if (esAdmin()) document.querySelectorAll('.nav-btn[data-admin]').forEach(b => b.classList.remove('oculto'));
    document.querySelectorAll('.nav-btn[data-vista]').forEach(b => b.addEventListener('click', () => {
        location.hash = '#' + b.dataset.vista;
        alternarLateral(false);
    }));
    document.getElementById('salir-btn').addEventListener('click', salir);
    document.getElementById('abrir-lateral').addEventListener('click', () =>
        alternarLateral(!document.getElementById('lateral').classList.contains('abierta')));
    document.getElementById('fondo-lateral').addEventListener('click', () => alternarLateral(false));

    document.getElementById('avatar-btn').addEventListener('click', (ev) => {
        ev.stopPropagation();
        if (document.getElementById('menu-avatar').classList.contains('oculto')) abrirMenu(); else cerrarMenu();
    });
    document.getElementById('menu-avatar').addEventListener('click', (ev) => ev.stopPropagation());
    document.addEventListener('click', cerrarMenu);
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { cerrarMenu(); alternarLateral(false); } });

    prepararCuenta();
    try {
        await cargarContexto();
    } catch (e) {
        mostrarMensaje(e.message, 'error');
    }
    window.addEventListener('hashchange', () => mostrarVista(vistaActual()));
    mostrarVista(vistaActual());
});
