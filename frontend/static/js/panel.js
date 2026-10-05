// Panel: barra lateral, avatar con el selector "division empresa" (razon social y modo de esta sesion),
// vistas por hash (#inicio, #razones, #usuarios, #auditoria, #cuenta) y cambio de contraseña.
'use strict';

const ROLES = { administrador: 'Administrador', supervisor: 'Supervisor', cajero: 'Cajero', solo_lectura: 'Solo lectura' };
const MODOS = { empresa: 'Empresa', prueba: 'Prueba' };
const TITULOS = { inicio: 'Inicio', razones: 'Razones sociales', usuarios: 'Usuarios', auditoria: 'Auditoría', cuenta: 'Mi cuenta' };
const VISTAS_ADMIN = ['razones', 'usuarios', 'auditoria'];

const Panel = { yo: null, contexto: null, opciones: [] };

function esAdmin() { return Panel.yo && Panel.yo.rol === 'administrador'; }

function iniciales(texto) {
    const partes = String(texto || '?').trim().split(/\s+/).filter(Boolean);
    return ((partes[0] || '?')[0] + (partes[1] ? partes[1][0] : '')).toUpperCase();
}

// --- Contexto (razon social y modo de esta sesion) ---
async function cargarContexto() {
    const datos = await api('/api/contexto');
    Panel.contexto = datos.actual;
    Panel.opciones = datos.opciones;
    const chip = vaciar(document.getElementById('contexto-chip'));
    const prueba = Panel.contexto && Panel.contexto.modo === 'prueba';
    document.body.classList.toggle('modo-prueba', !!prueba);
    if (Panel.contexto) {
        chip.append(
            el('strong', {}, Panel.contexto.nombre_fantasia || Panel.contexto.nombre_legal),
            el('span', { class: 'mono' }, Panel.contexto.cuit),
            el('span', { class: 'etiqueta ' + (prueba ? 'aviso' : 'acento') }, MODOS[Panel.contexto.modo]));
    } else {
        chip.append(el('span', {}, 'Sin razón social elegida'));
    }
    armarMenu();
}

async function elegirContexto(razonSocialId, modo, boton) {
    const r = await conBoton(boton, () => api('/api/contexto', { method: 'PUT', body: { razon_social_id: razonSocialId, modo } }));
    if (r === undefined) return;
    await cargarContexto();
    cerrarMenu();
    mostrarVista(vistaActual());
    mostrarMensaje(`Trabajando en modo ${MODOS[modo].toLowerCase()}.`, 'ok');
}

// --- Menu del avatar ---
function armarMenu() {
    const menu = vaciar(document.getElementById('menu-avatar'));
    menu.append(
        el('div', {}, el('strong', {}, Panel.yo.nombre || Panel.yo.usuario), ' ',
            el('span', { class: 'etiqueta neutra' }, ROLES[Panel.yo.rol] || Panel.yo.rol)),
        el('h3', {}, 'División empresa'));
    if (!Panel.opciones.length) {
        menu.append(el('p', { class: 'ayuda' }, esAdmin()
            ? 'Todavía no hay razones sociales activas. Creá una en Razones sociales.'
            : 'No tiene razones sociales asignadas. Pedíselas a un administrador.'));
    }
    for (const op of Panel.opciones) {
        const esActual = Panel.contexto && Panel.contexto.razon_social_id === op.razon_social_id;
        const botones = op.modos.map(modo => {
            const elegido = esActual && Panel.contexto.modo === modo;
            const b = el('button', { type: 'button', class: elegido ? '' : 'secundario', 'aria-pressed': elegido ? 'true' : 'false' },
                MODOS[modo]);
            b.addEventListener('click', () => elegirContexto(op.razon_social_id, modo, b));
            return b;
        });
        menu.append(el('div', { class: 'opcion-rs' + (esActual ? ' actual' : '') },
            el('div', {}, el('strong', {}, op.nombre_fantasia || op.nombre_legal)),
            el('div', { class: 'sub mono' }, op.cuit),
            el('div', { class: 'acciones' }, botones)));
    }
    menu.append(el('hr'),
        el('button', { type: 'button', class: 'secundario', onclick: () => { cerrarMenu(); location.hash = '#cuenta'; } }, 'Cambiar contraseña'),
        el('button', { type: 'button', class: 'secundario', onclick: cerrarTodas }, 'Cerrar sesión en todos los dispositivos'),
        el('button', { type: 'button', onclick: salir }, 'Salir'));
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
    else if (nombre === 'usuarios') vistaUsuarios(contenedor);
    else if (nombre === 'auditoria') vistaAuditoria(contenedor);
}

function vistaInicio(contenedor) {
    vaciar(contenedor);
    const tarjeta = el('div', { class: 'tarjeta' });
    if (Panel.contexto) {
        tarjeta.append(
            el('h2', {}, Panel.contexto.nombre_legal),
            el('dl', { class: 'datos' },
                el('dt', {}, 'CUIT'), el('dd', { class: 'mono' }, Panel.contexto.cuit),
                el('dt', {}, 'Modo'), el('dd', {}, MODOS[Panel.contexto.modo]),
                el('dt', {}, 'Rol'), el('dd', {}, ROLES[Panel.yo.rol])),
            el('p', { class: 'ayuda' }, 'La facturación llega en las próximas versiones. Para cambiar de razón social o de modo, usá el menú del avatar.'));
    } else {
        tarjeta.append(el('h2', {}, 'Elegí con qué razón social trabajar'),
            el('p', { class: 'ayuda' }, 'Abrí el menú del avatar (abajo a la izquierda) y elegí una razón social y el modo: Empresa (real) o Prueba (homologación de ARCA, sin validez fiscal).'),
            el('div', { class: 'acciones' }, el('button', { type: 'button', onclick: (ev) => { ev.stopPropagation(); abrirMenu(); } }, 'Elegir razón social')));
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
    document.querySelectorAll('.nav-btn[data-vista]').forEach(b => b.addEventListener('click', () => { location.hash = '#' + b.dataset.vista; }));

    document.getElementById('avatar-btn').addEventListener('click', (ev) => {
        ev.stopPropagation();
        if (document.getElementById('menu-avatar').classList.contains('oculto')) abrirMenu(); else cerrarMenu();
    });
    document.getElementById('menu-avatar').addEventListener('click', (ev) => ev.stopPropagation());
    document.addEventListener('click', cerrarMenu);
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') cerrarMenu(); });

    prepararCuenta();
    try {
        await cargarContexto();
    } catch (e) {
        mostrarMensaje(e.message, 'error');
    }
    window.addEventListener('hashchange', () => mostrarVista(vistaActual()));
    mostrarVista(vistaActual());
});
