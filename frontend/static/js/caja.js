// Caja (Fase 6): planilla diaria por caja y modo, apertura con fondo inicial, movimientos manuales con categoria,
// retiro a otra caja (tesoreria o dueño) con movimiento espejo, cierre con arqueo por medio de pago y moneda, y
// configuracion de cajas, medios de pago y categorias (administrador y supervisor). Todo con el() / textContent.
'use strict';

const TIPOS_CAJA = { local: 'Local', tesoreria: 'Tesorería', dueno: 'Dueño' };

function puedeOperarCaja() { return Panel.yo && ['administrador', 'supervisor', 'cajero'].includes(Panel.yo.rol); }
function puedeConfigurarCaja() { return Panel.yo && ['administrador', 'supervisor'].includes(Panel.yo.rol); }

function hora(iso) {
    return new Date(iso).toLocaleTimeString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires', hour: '2-digit', minute: '2-digit' });
}

// "-10.00" -> "-10,00" (la diferencia del arqueo puede ser negativa; formatoImporte solo toma positivos).
function formatoConSigno(texto) {
    const t = String(texto);
    return (t.startsWith('-') ? '-' : '') + formatoImporte(t.replace('-', ''));
}

function etiquetaDiferencia(diferencia) {
    return el('span', { class: 'etiqueta ' + (diferencia === '0.00' ? 'ok' : 'error') }, formatoConSigno(diferencia));
}

// Caja sugerida para esta terminal: una abierta de la sucursal del contexto (o sin sucursal); si no, la primera.
function cajaSugerida(cajas) {
    const suc = Panel.contexto && Panel.contexto.sucursal_id;
    const deSucursal = c => !c.sucursal_id || !suc || c.sucursal_id === suc;
    return cajas.find(c => c.abierta && deSucursal(c)) || cajas.find(deSucursal) || cajas[0] || null;
}

function ventanaCaja(dialogo, titulo, contenido) {
    const cerrar = el('button', { type: 'button', class: 'secundario cerrar-ventana', 'aria-label': 'Cerrar' }, '×');
    cerrar.addEventListener('click', () => dialogo.close());
    vaciar(dialogo).append(el('div', { class: 'tarjeta' }, el('div', { class: 'titulo-tarjeta' }, el('h2', {}, titulo), cerrar), contenido));
    if (!dialogo.open) dialogo.showModal();
}

function botonCaja(texto, accion, clase) {
    const b = el('button', { type: 'button', class: clase || '' }, texto);
    b.addEventListener('click', () => accion(b));
    return b;
}

async function vistaCaja(contenedor) {
    const vigente = redibujar(contenedor);
    let op;
    try {
        op = await api('/api/caja/opciones');
    } catch (e) {
        if (vigente()) contenedor.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' }, e.message)));
        return;
    }
    if (!vigente()) return;
    const dialogo = el('dialog', { class: 'ventana', 'aria-label': 'Caja' });
    const selCaja = el('select', { 'aria-label': 'Caja' });
    const zonaPlanilla = el('div', {});
    const zonaHistorial = el('div', {});
    const zonaSelector = el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Caja'));
    let planilla = null;

    function cajaElegida() { return op.cajas.find(c => c.id === selCaja.value) || null; }

    function llenarSelector() {
        const previa = selCaja.value;
        vaciar(selCaja);
        for (const c of op.cajas) selCaja.append(el('option', { value: c.id }, c.nombre + (c.abierta ? ' (abierta)' : '')));
        const elegida = op.cajas.find(c => c.id === previa) || cajaSugerida(op.cajas);
        if (elegida) selCaja.value = elegida.id;
        if (op.cajas.length && !selCaja.isConnected) zonaSelector.append(el('label', {}, 'Caja ', selCaja));
    }

    async function recargarOpciones() {
        try { op = await api('/api/caja/opciones'); } catch (e) { mostrarMensaje(e.message, 'error'); }
        llenarSelector();
    }

    async function verPlanilla(id) {
        try { planilla = await api('/api/caja/planillas/' + encodeURIComponent(id)); }
        catch (e) { mostrarMensaje(e.message, 'error'); planilla = null; }
        pintarPlanilla();
    }

    async function cargarPlanilla() {
        const c = cajaElegida();
        if (c && c.abierta) await verPlanilla(c.abierta.planilla_id);
        else { planilla = null; pintarPlanilla(); }
        cargarHistorial();
    }

    async function cargarHistorial() {
        const c = cajaElegida();
        vaciar(zonaHistorial);
        if (!c) return;
        let lista = [];
        try { lista = await api('/api/caja/planillas?caja_id=' + encodeURIComponent(c.id) + '&limite=30'); }
        catch (e) { mostrarMensaje(e.message, 'error'); }
        const cuerpo = el('tbody');
        if (!lista.length) cuerpo.append(el('tr', {}, el('td', { colspan: 5, class: 'vacio' }, 'Esta caja todavía no tiene planillas en este modo.')));
        for (const p of lista) {
            const ver = botonCaja('Ver', () => { verPlanilla(p.id); zonaPlanilla.scrollIntoView({ behavior: 'smooth' }); }, 'secundario');
            cuerpo.append(el('tr', {},
                el('td', { class: 'sin-corte' }, fecha(p.fecha)),
                el('td', {}, el('span', { class: 'etiqueta ' + (p.estado === 'abierta' ? 'ok' : '') }, p.estado === 'abierta' ? 'Abierta' : 'Cerrada')),
                el('td', {}, p.abierta_por || '-', el('div', { class: 'sub' }, fechaHora(p.abierta_en))),
                el('td', {}, p.cerrada_en ? [p.cerrada_por || '-', el('div', { class: 'sub' }, fechaHora(p.cerrada_en))] : '-'),
                el('td', {}, ver)));
        }
        zonaHistorial.append(el('div', { class: 'tarjeta' }, el('h2', {}, 'Planillas de ' + c.nombre),
            el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'Fecha'), el('th', {}, 'Estado'), el('th', {}, 'Apertura'), el('th', {}, 'Cierre'), el('th', {}, ''))),
                cuerpo))));
    }

    function pintarPlanilla() {
        vaciar(zonaPlanilla);
        const c = cajaElegida();
        if (!c) return;
        if (!planilla) {
            zonaPlanilla.append(el('div', { class: 'tarjeta' }, el('h2', {}, c.nombre + ': sin planilla abierta'),
                el('p', { class: 'ayuda' }, 'No hay una planilla abierta en modo ' + MODOS[Panel.contexto.modo].toLowerCase() + '. Abrila para registrar cobros y movimientos.'),
                puedeOperarCaja() ? el('div', { class: 'acciones' }, botonCaja('Abrir caja', abrirCaja)) : null));
            return;
        }
        const p = planilla;
        const abierta = p.estado === 'abierta';
        const acciones = [];
        if (abierta && puedeOperarCaja()) {
            acciones.push(botonCaja('Movimiento manual', () => nuevoMovimiento(false)),
                botonCaja('Retiro a otra caja', () => nuevoMovimiento(true), 'secundario'),
                botonCaja('Cerrar caja', cerrarCaja, 'secundario'));
        }
        if (!abierta && puedeConfigurarCaja()) acciones.push(botonCaja('Reabrir', reabrir, 'secundario'));
        const encabezado = el('div', { class: 'tarjeta' },
            el('div', { class: 'titulo-tarjeta' },
                el('h2', {}, p.caja + ': planilla del ' + fecha(p.fecha) + ' ', el('span', { class: 'etiqueta ' + (abierta ? 'ok' : '') }, abierta ? 'Abierta' : 'Cerrada')),
                el('div', { class: 'acciones' }, acciones)),
            el('dl', { class: 'datos' },
                el('dt', {}, 'Apertura'), el('dd', {}, fechaHora(p.abierta_en) + (p.abierta_por ? ' por ' + p.abierta_por : '')),
                el('dt', {}, 'Fondo inicial'), el('dd', { class: 'mono' }, 'PES ' + formatoImporte(p.fondo_inicial)),
                p.cerrada_en ? el('dt', {}, 'Cierre') : null,
                p.cerrada_en ? el('dd', {}, fechaHora(p.cerrada_en) + (p.cerrada_por ? ' por ' + p.cerrada_por : '')) : null,
                p.observaciones ? el('dt', {}, 'Observaciones') : null, p.observaciones ? el('dd', {}, p.observaciones) : null));

        // Totales por medio de pago; con la planilla cerrada, el arqueo al lado.
        const conArqueo = p.arqueo.length > 0;
        const filasMedios = p.totales.por_medio.map(t => {
            const a = p.arqueo.find(x => x.medio_pago_id === t.medio_pago_id && x.moneda === t.moneda);
            return el('tr', {}, el('td', {}, t.medio), el('td', { class: 'mono' }, t.moneda),
                el('td', { class: 'mono' }, formatoImporte(t.fondo)), el('td', { class: 'mono' }, formatoImporte(t.entradas)),
                el('td', { class: 'mono' }, formatoImporte(t.salidas)), el('td', { class: 'mono' }, el('strong', {}, formatoImporte(t.saldo))),
                conArqueo ? el('td', { class: 'mono' }, a && a.contado !== null ? formatoImporte(a.contado) : '-') : null,
                conArqueo ? el('td', {}, a && a.diferencia !== null ? etiquetaDiferencia(a.diferencia) : '-') : null);
        });
        for (const a of p.arqueo) {
            if (p.totales.por_medio.some(t => t.medio_pago_id === a.medio_pago_id && t.moneda === a.moneda)) continue;
            filasMedios.push(el('tr', {}, el('td', {}, a.medio), el('td', { class: 'mono' }, a.moneda), el('td', { class: 'mono' }, '0,00'),
                el('td', { class: 'mono' }, '0,00'), el('td', { class: 'mono' }, '0,00'), el('td', { class: 'mono' }, el('strong', {}, '0,00')),
                el('td', { class: 'mono' }, a.contado !== null ? formatoImporte(a.contado) : '-'),
                el('td', {}, a.diferencia !== null ? etiquetaDiferencia(a.diferencia) : '-')));
        }
        const tablaMedios = el('table', {},
            el('thead', {}, el('tr', {}, el('th', {}, 'Medio de pago'), el('th', {}, 'Moneda'), el('th', {}, 'Fondo'), el('th', {}, 'Entradas'),
                el('th', {}, 'Salidas'), el('th', {}, 'Saldo'), conArqueo ? el('th', {}, 'Contado') : null, conArqueo ? el('th', {}, 'Diferencia') : null)),
            el('tbody', {}, filasMedios.length ? filasMedios : el('tr', {}, el('td', { colspan: 8, class: 'vacio' }, 'Sin movimientos.'))));
        const tablaCategorias = el('table', {},
            el('thead', {}, el('tr', {}, el('th', {}, 'Categoría'), el('th', {}, 'Moneda'), el('th', {}, 'Entradas'), el('th', {}, 'Salidas'))),
            el('tbody', {}, p.totales.por_categoria.length ? p.totales.por_categoria.map(t => el('tr', {}, el('td', {}, t.categoria),
                el('td', { class: 'mono' }, t.moneda), el('td', { class: 'mono' }, formatoImporte(t.entradas)), el('td', { class: 'mono' }, formatoImporte(t.salidas))))
                : el('tr', {}, el('td', { colspan: 4, class: 'vacio' }, 'Sin movimientos manuales.'))));

        const cuerpoMovs = el('tbody');
        for (const m of p.movimientos) {
            const quitar = botonCaja('Quitar', () => quitarMovimiento(m), 'peligro');
            cuerpoMovs.append(el('tr', {},
                el('td', { class: 'sin-corte' }, hora(m.hora)),
                el('td', {}, m.comprobante || m.descripcion || (m.origen === 'manual' ? 'Movimiento manual' : 'Retiro'),
                    m.comprobante && m.descripcion && m.descripcion !== m.comprobante ? el('div', { class: 'sub' }, m.descripcion) : null,
                    m.caja_espejo ? el('div', { class: 'sub' }, (m.tipo === 'salida' ? 'Hacia ' : 'Desde ') + m.caja_espejo) : null),
                el('td', {}, m.categoria || el('span', { class: 'sub' }, m.tipo === 'entrada' ? 'Cobro' : 'Devolución')),
                el('td', {}, m.medio),
                el('td', { class: 'mono sin-corte ' + (m.tipo === 'entrada' ? 'importe-entrada' : 'importe-salida') },
                    (m.tipo === 'entrada' ? '+ ' : '- ') + m.moneda + ' ' + formatoImporte(m.importe)),
                el('td', {}, m.usuario || '-'),
                el('td', {}, abierta && puedeOperarCaja() && m.origen !== 'comprobante' ? quitar : null)));
        }
        if (!p.movimientos.length) cuerpoMovs.append(el('tr', {}, el('td', { colspan: 7, class: 'vacio' }, 'Todavía no hay movimientos en esta planilla.')));
        zonaPlanilla.append(encabezado,
            el('div', { class: 'dos-columnas' },
                el('div', { class: 'tarjeta' }, el('h2', {}, 'Por medio de pago'), el('div', { class: 'tabla-scroll' }, tablaMedios)),
                el('div', { class: 'tarjeta' }, el('h2', {}, 'Por categoría'), el('div', { class: 'tabla-scroll' }, tablaCategorias))),
            el('div', { class: 'tarjeta' }, el('h2', {}, 'Movimientos'),
                el('div', { class: 'tabla-scroll' }, el('table', {},
                    el('thead', {}, el('tr', {}, el('th', {}, 'Hora'), el('th', {}, 'Detalle'), el('th', {}, 'Categoría'), el('th', {}, 'Medio de pago'),
                        el('th', {}, 'Importe'), el('th', {}, 'Usuario'), el('th', {}, ''))),
                    cuerpoMovs))));
    }

    function abrirCaja() {
        const c = cajaElegida();
        const fondo = el('input', { inputmode: 'decimal', value: '0', 'aria-label': 'Fondo inicial' });
        const guardar = el('button', { type: 'submit' }, 'Abrir');
        const form = el('form', {}, el('label', {}, 'Fondo inicial en efectivo (pesos)', fondo), el('div', { class: 'acciones' }, guardar));
        form.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const v = normalizarNumero(fondo.value, 2);
            if (v === null) { mostrarMensaje('Fondo inicial inválido.', 'error'); return; }
            const r = await conBoton(guardar, () => api('/api/caja/cajas/' + encodeURIComponent(c.id) + '/abrir', { method: 'POST', body: { fondo_inicial: v } }));
            if (!r) return;
            dialogo.close();
            planilla = r;
            await recargarOpciones();
            pintarPlanilla();
            cargarHistorial();
            mostrarMensaje('Caja abierta.', 'ok');
        });
        ventanaCaja(dialogo, 'Abrir ' + c.nombre, form);
        fondo.focus();
        fondo.select();
    }

    function nuevoMovimiento(retiro) {
        const destinos = op.cajas.filter(x => x.id !== planilla.caja_id);
        if (retiro && !destinos.length) {
            mostrarMensaje('No hay otra caja activa en esta razón social: creala en Configuración de caja.', 'error');
            return;
        }
        const selTipo = el('select', {}, el('option', { value: 'salida' }, 'Salida (egreso)'), el('option', { value: 'entrada' }, 'Entrada (ingreso)'));
        const selDestino = el('select', {}, destinos.map(x => el('option', { value: x.id }, x.nombre + ' (' + TIPOS_CAJA[x.tipo] + ')')));
        const categoriaRetiro = retiro ? op.categorias.find(x => /retiro/i.test(x.nombre)) : null;
        const selCategoria = el('select', {}, op.categorias.map(x => el('option', { value: x.id, selected: categoriaRetiro && x.id === categoriaRetiro.id }, x.nombre)));
        const selMedio = el('select', {}, op.medios.map(x => el('option', { value: x.id, selected: x.efectivo }, x.nombre)));
        const moneda = el('input', { value: 'PES', maxlength: 3, required: true, 'aria-label': 'Moneda' });
        const importe = el('input', { inputmode: 'decimal', required: true, placeholder: '0,00' });
        const descripcion = el('input', { maxlength: 250, placeholder: retiro ? 'Opcional' : 'Qué se pagó o se cobró' });
        const guardar = el('button', { type: 'submit' }, 'Guardar');
        const form = el('form', {},
            retiro ? el('p', { class: 'ayuda' }, 'Sale de ' + planilla.caja + ' y entra en la caja de destino con el mismo importe; los dos movimientos quedan enlazados.') : null,
            el('div', { class: 'grilla-form' },
                retiro ? el('label', {}, 'Caja de destino', selDestino) : el('label', {}, 'Tipo', selTipo),
                el('label', {}, 'Categoría', selCategoria), el('label', {}, 'Medio de pago', selMedio),
                el('label', {}, 'Importe', importe), el('label', {}, 'Moneda', moneda), el('label', {}, 'Descripción', descripcion)),
            el('div', { class: 'acciones' }, guardar));
        form.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const v = normalizarNumero(importe.value, 2);
            if (v === null || aEntero(v, 2) === 0n) { mostrarMensaje('Importe inválido.', 'error'); return; }
            const cuerpo = { tipo: retiro ? 'salida' : selTipo.value, categoria_id: selCategoria.value, medio_pago_id: selMedio.value,
                             moneda: moneda.value.trim().toUpperCase(), importe: v, descripcion: descripcion.value };
            if (retiro) cuerpo.caja_destino_id = selDestino.value;
            const r = await conBoton(guardar, () => api('/api/caja/planillas/' + encodeURIComponent(planilla.id) + '/movimientos', { method: 'POST', body: cuerpo }));
            if (!r) return;
            dialogo.close();
            planilla = r;
            pintarPlanilla();
            if (retiro) recargarOpciones();   // la caja de destino pudo abrirse sola
        });
        ventanaCaja(dialogo, retiro ? 'Retiro a otra caja' : 'Movimiento manual', form);
        importe.focus();
    }

    async function quitarMovimiento(m) {
        if (!window.confirm('¿Quitar este movimiento' + (m.caja_espejo ? ' y su espejo en ' + m.caja_espejo : '') + '?')) return;
        try {
            planilla = await api('/api/caja/planillas/' + encodeURIComponent(planilla.id) + '/movimientos/' + encodeURIComponent(m.id), { method: 'DELETE' });
            pintarPlanilla();
        } catch (e) {
            mostrarMensaje(e.message, 'error');
        }
    }

    function cerrarCaja() {
        const filas = planilla.totales.por_medio.map(t => {
            const contado = el('input', { inputmode: 'decimal', placeholder: 'Sin contar', 'aria-label': 'Contado ' + t.medio });
            const fila = el('tr', {}, el('td', {}, t.medio), el('td', { class: 'mono' }, t.moneda), el('td', { class: 'mono' }, formatoImporte(t.saldo)), el('td', {}, contado));
            fila._t = t;
            fila._contado = contado;
            return fila;
        });
        const observaciones = el('textarea', { maxlength: 500, rows: 2, placeholder: 'Opcional' });
        const guardar = el('button', { type: 'submit' }, 'Cerrar caja');
        const form = el('form', {},
            el('p', { class: 'ayuda' }, 'Contá lo que hay por cada medio de pago. Lo esperado sale de la planilla: fondo inicial más entradas menos salidas. Lo que dejes vacío queda sin contar.'),
            filas.length ? el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'Medio de pago'), el('th', {}, 'Moneda'), el('th', {}, 'Esperado'), el('th', {}, 'Contado'))),
                el('tbody', {}, filas))) : el('p', { class: 'ayuda' }, 'La planilla no tiene movimientos.'),
            el('label', {}, 'Observaciones', observaciones), el('div', { class: 'acciones' }, guardar));
        form.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const arqueo = [];
            for (const f of filas) {
                if (!f._contado.value.trim()) continue;
                const v = normalizarNumero(f._contado.value, 2);
                if (v === null) { mostrarMensaje('Importe contado inválido en ' + f._t.medio + '.', 'error'); return; }
                arqueo.push({ medio_pago_id: f._t.medio_pago_id, moneda: f._t.moneda, contado: v });
            }
            const r = await conBoton(guardar, () => api('/api/caja/planillas/' + encodeURIComponent(planilla.id) + '/cerrar',
                { method: 'POST', body: { arqueo, observaciones: observaciones.value } }));
            if (!r) return;
            dialogo.close();
            planilla = r;
            await recargarOpciones();
            pintarPlanilla();
            cargarHistorial();
            mostrarMensaje('Caja cerrada.', 'ok');
        });
        ventanaCaja(dialogo, 'Cerrar ' + planilla.caja, form);
    }

    async function reabrir(b) {
        if (!window.confirm('¿Reabrir la planilla? Se borra el arqueo del cierre.')) return;
        const r = await conBoton(b, () => api('/api/caja/planillas/' + encodeURIComponent(planilla.id) + '/reabrir', { method: 'POST' }));
        if (!r) return;
        planilla = r;
        await recargarOpciones();
        pintarPlanilla();
        cargarHistorial();
    }

    // --- Configuracion: cajas, medios de pago y categorias (administrador y supervisor) ---
    function zonaConfiguracion() {
        const zona = el('div', {});
        const detalles = el('details', { class: 'tarjeta' }, el('summary', {}, 'Configuración de caja'),
            el('p', { class: 'ayuda' }, 'Cajas, medios de pago y categorías de esta razón social. Nada se borra: se desactiva.'), zona);

        function guardarForm(titulo, campos, cuerpo, metodo, url) {
            const guardar = el('button', { type: 'submit' }, 'Guardar');
            const form = el('form', {}, el('div', { class: 'grilla-form' }, campos), el('div', { class: 'acciones' }, guardar));
            form.addEventListener('submit', async (ev) => {
                ev.preventDefault();
                const r = await conBoton(guardar, () => api(url, { method: metodo, body: cuerpo() }));
                if (!r) return;
                dialogo.close();
                await recargarOpciones();
                pintar();
                if (!cajaElegida()) planilla = null;
                cargarPlanilla();
            });
            ventanaCaja(dialogo, titulo, form);
            campos[0].querySelector('input, select').focus();
        }

        function formCaja(c) {
            const nombre = el('input', { required: true, maxlength: 80, value: c ? c.nombre : '', placeholder: 'Por ejemplo: Mostrador, Tesorería' });
            const selTipo = el('select', {}, Object.entries(TIPOS_CAJA).map(([v, t]) => el('option', { value: v, selected: c ? c.tipo === v : v === 'local' }, t)));
            const selSucursal = el('select', {}, el('option', { value: '' }, 'Cualquier sucursal'),
                op.sucursales.map(s => el('option', { value: s.id, selected: c && c.sucursal_id === s.id }, s.nombre)));
            const activa = el('input', { type: 'checkbox', checked: c ? c.activa : true });
            guardarForm(c ? 'Editar caja' : 'Nueva caja',
                [el('label', {}, 'Nombre', nombre), el('label', {}, 'Tipo', selTipo), el('label', {}, 'Sucursal', selSucursal), el('label', { class: 'casilla' }, activa, 'Activa')],
                () => ({ nombre: nombre.value, tipo: selTipo.value, sucursal_id: selSucursal.value || null, activa: activa.checked }),
                c ? 'PUT' : 'POST', c ? '/api/caja/cajas/' + encodeURIComponent(c.id) : '/api/caja/cajas');
        }

        function formMedio(m) {
            const nombre = el('input', { required: true, maxlength: 60, value: m ? m.nombre : '', placeholder: 'Por ejemplo: Mercado Pago' });
            const efectivo = el('input', { type: 'checkbox', checked: m ? m.efectivo : false });
            const activo = el('input', { type: 'checkbox', checked: m ? m.activo : true });
            guardarForm(m ? 'Editar medio de pago' : 'Nuevo medio de pago',
                [el('label', {}, 'Nombre', nombre), el('label', { class: 'casilla' }, efectivo, 'Es efectivo (se cuenta en el arqueo)'), el('label', { class: 'casilla' }, activo, 'Activo')],
                () => ({ nombre: nombre.value, efectivo: efectivo.checked, activo: activo.checked }),
                m ? 'PUT' : 'POST', m ? '/api/caja/medios-pago/' + encodeURIComponent(m.id) : '/api/caja/medios-pago');
        }

        function formCategoria(c) {
            const nombre = el('input', { required: true, maxlength: 80, value: c ? c.nombre : '', placeholder: 'Por ejemplo: Fletes' });
            const activa = el('input', { type: 'checkbox', checked: c ? c.activa : true });
            guardarForm(c ? 'Editar categoría' : 'Nueva categoría',
                [el('label', {}, 'Nombre', nombre), el('label', { class: 'casilla' }, activa, 'Activa')],
                () => ({ nombre: nombre.value, activa: activa.checked }),
                c ? 'PUT' : 'POST', c ? '/api/caja/categorias/' + encodeURIComponent(c.id) : '/api/caja/categorias');
        }

        async function pintar() {
            let cajas, medios, categorias;
            try {
                [cajas, medios, categorias] = await Promise.all([api('/api/caja/cajas?incluir_inactivas=true'),
                    api('/api/caja/medios-pago?incluir_inactivos=true'), api('/api/caja/categorias?incluir_inactivas=true')]);
            } catch (e) { mostrarMensaje(e.message, 'error'); return; }
            const estado = activo => el('span', { class: 'etiqueta ' + (activo ? 'ok' : '') }, activo ? 'Activa' : 'Inactiva');
            const tabla = (titulo, encabezados, filas, nueva) => el('div', { class: 'tarjeta' },
                el('div', { class: 'titulo-tarjeta' }, el('h3', {}, titulo), nueva),
                el('div', { class: 'tabla-scroll' }, el('table', {}, el('thead', {}, el('tr', {}, encabezados.map(h => el('th', {}, h)))),
                    el('tbody', {}, filas.length ? filas : el('tr', {}, el('td', { colspan: encabezados.length, class: 'vacio' }, 'Nada todavía.'))))));
            vaciar(zona).append(
                tabla('Cajas', ['Nombre', 'Tipo', 'Sucursal', 'Estado', ''], cajas.map(c => el('tr', {}, el('td', {}, c.nombre), el('td', {}, TIPOS_CAJA[c.tipo] || c.tipo),
                    el('td', {}, c.sucursal_nombre || 'Cualquiera'), el('td', {}, estado(c.activa)), el('td', {}, botonCaja('Editar', () => formCaja(c), 'secundario')))),
                    botonCaja('Nueva caja', () => formCaja(null))),
                tabla('Medios de pago', ['Nombre', 'Efectivo', 'Estado', ''], medios.map(m => el('tr', {}, el('td', {}, m.nombre), el('td', {}, m.efectivo ? 'Sí' : 'No'),
                    el('td', {}, estado(m.activo)), el('td', {}, botonCaja('Editar', () => formMedio(m), 'secundario')))),
                    botonCaja('Nuevo medio de pago', () => formMedio(null))),
                tabla('Categorías de caja', ['Nombre', 'Estado', ''], categorias.map(c => el('tr', {}, el('td', {}, c.nombre), el('td', {}, estado(c.activa)),
                    el('td', {}, botonCaja('Editar', () => formCategoria(c), 'secundario')))),
                    botonCaja('Nueva categoría', () => formCategoria(null))));
        }
        detalles.addEventListener('toggle', () => { if (detalles.open && !zona.firstChild) pintar(); });
        if (!op.cajas.length) { detalles.open = true; pintar(); }
        return detalles;
    }

    selCaja.addEventListener('change', cargarPlanilla);
    llenarSelector();
    contenedor.append(
        el('div', { class: 'tarjeta' }, zonaSelector,
            el('p', { class: 'ayuda' }, 'Planilla diaria por caja y modo: los cobros de los comprobantes, los movimientos manuales con categoría y los retiros a otra caja. Lo del modo prueba no se suma a la caja real.'),
            !op.cajas.length ? el('p', { class: 'ayuda' }, puedeConfigurarCaja()
                ? 'Todavía no hay cajas: creá la primera en Configuración de caja, acá abajo.'
                : 'Todavía no hay cajas. Pedile a un supervisor o administrador que las cree.') : null),
        zonaPlanilla, zonaHistorial,
        puedeConfigurarCaja() ? zonaConfiguracion() : null,
        dialogo);
    await cargarPlanilla();
}
