// Facturacion (Fase 3) y listado de comprobantes, en el contexto de la sesion (razon social, modo y punto de venta).
// El total en pantalla es una vista previa calculada con enteros (milesimos y centavos, BigInt): el que vale es el
// del servidor, que usa Decimal con el mismo redondeo. Todo se arma con el() / textContent.
'use strict';

// "1.234,5" o "1234.5" -> "1234.5"; null si no es un numero con hasta `decimales` decimales.
function normalizarNumero(texto, decimales) {
    let t = String(texto || '').trim().replace(/\s/g, '');
    if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.');
    const re = new RegExp('^\\d{1,12}(\\.\\d{0,' + decimales + '})?$');
    if (!re.test(t)) return null;
    return t.endsWith('.') ? t.slice(0, -1) : t;
}

// Valor decimal en string -> BigInt escalado (por ejemplo "1.5" con escala 3 -> 1500n).
function aEntero(texto, escala) {
    const [entero, frac = ''] = texto.split('.');
    return BigInt(entero + (frac + '0'.repeat(escala)).slice(0, escala));
}

// Importe en centavos de cantidad x precio, redondeado a centavos mitad hacia arriba (igual que el servidor).
function importeCentavos(cantidad, precio) {
    const producto = aEntero(cantidad, 3) * aEntero(precio, 2);   // milesimos x centavos
    return (producto + 500n) / 1000n;
}

function formatoCentavos(centavos) {
    const negativo = centavos < 0n;
    const v = negativo ? -centavos : centavos;
    const entero = (v / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return (negativo ? '-' : '') + entero + ',' + (v % 100n).toString().padStart(2, '0');
}

function formatoImporte(texto) {
    return formatoCentavos(aEntero(normalizarNumero(texto, 2) || '0', 2));
}

function numeroComprobante(c) {
    return String(c.punto_venta).padStart(5, '0') + '-' + String(c.numero).padStart(8, '0');
}

function normalTexto(t) {
    return String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').trim().toLowerCase();
}

// Stock segun la ultima foto de Tracker360 (Fase 8): solo avisa, nunca frena la venta.
function formatoStock(texto) { return String(texto).replace(/\.?0+$/, '').replace('.', ',') || '0'; }

function etiquetaStock(a) {
    if (a.stock !== null && a.stock !== undefined) return el('span', { class: 'etiqueta ' + (Number(a.stock) > 0 ? 'ok' : 'error') }, 'Stock ' + formatoStock(a.stock));
    if (a.en_tracker === false) return el('span', { class: 'etiqueta aviso' }, 'No está en Tracker360');
    return null;
}

function abrirImpresion(id) {
    window.open('/comprobantes/' + encodeURIComponent(id) + '/imprimir', '_blank', 'noopener');
}

// ===== Pantalla Facturar =====
async function vistaFacturar(contenedor) {
    const vigente = redibujar(contenedor);
    let op;
    try {
        op = await api('/api/facturacion/opciones');
    } catch (e) {
        if (vigente()) contenedor.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' }, e.message)));
        return;
    }
    if (!vigente()) return;
    if (!op.punto_venta) {
        contenedor.append(el('div', { class: 'tarjeta' }, el('h2', {}, 'Sin punto de venta'),
            el('p', { class: 'ayuda' }, 'No tiene un punto de venta asignado en esta sucursal. Elegí otra sucursal desde el avatar o pedíselo a un administrador.')));
        return;
    }
    const formularios = op.formularios.filter(f => f.soportado);
    if (!formularios.length) {
        contenedor.append(el('div', { class: 'tarjeta' }, el('h2', {}, 'Sin formularios'),
            el('p', { class: 'ayuda' }, esAdmin()
                ? 'Este punto de venta todavía no tiene formularios. Crealos en Razones sociales, tarjeta Formularios.'
                : 'Este punto de venta todavía no tiene formularios. Pedíselos a un administrador.')));
        return;
    }
    if (!op.parametros) {
        contenedor.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' },
            'Faltan los parámetros fiscales de ARCA de este modo: un administrador tiene que actualizarlos desde Razones sociales, Conexión con ARCA.')));
    }
    let cajaOp = { medios: [], cajas: [] };
    try { cajaOp = await api('/api/caja/opciones'); } catch (e) { /* sin caja: se emite sin registrar el cobro */ }
    if (!vigente()) return;

    // --- Cabecera: formulario, concepto, moneda y comprobante asociado ---
    const selFormulario = el('select', { required: true },
        formularios.map(f => el('option', { value: f.id }, f.nombre + (f.electronico ? '' : ' (no electrónico)'))));
    const selConcepto = el('select', {}, op.conceptos.length
        ? op.conceptos.map(c => el('option', { value: c.codigo }, c.descripcion))
        : [el('option', { value: '1' }, 'Productos')]);
    const selMoneda = el('select', {}, op.monedas.length
        ? op.monedas.map(m => el('option', { value: m.codigo, selected: m.codigo === 'PES' }, m.descripcion + ' (' + m.codigo + ')'))
        : [el('option', { value: 'PES' }, 'Pesos argentinos (PES)')]);
    const selAsociado = el('select', {}, el('option', { value: '' }, 'Elegí el comprobante'),
        op.asociables.map(a => el('option', { value: a.id },
            `${a.nombre} ${numeroComprobante(a)} del ${fecha(a.fecha)}, ${a.moneda} ${formatoImporte(a.total)}`)));
    const campoAsociado = el('label', {}, 'Comprobante asociado', selAsociado);
    const desde = el('input', { type: 'date' });
    const hasta = el('input', { type: 'date' });
    const vence = el('input', { type: 'date' });
    const campoServicio = el('div', { class: 'grilla-form' },
        el('label', {}, 'Período desde', desde), el('label', {}, 'Período hasta', hasta),
        el('label', {}, 'Vencimiento del pago', vence));

    // --- Receptor ---
    const docCF = op.documentos.find(d => d.codigo === '99');
    const selDoc = el('select', {}, op.documentos.length ? op.documentos.map(d =>
        el('option', { value: d.codigo, selected: docCF ? d.codigo === '99' : false }, d.descripcion))
        : [el('option', { value: '0' }, 'Sin informar')]);
    const nroDoc = el('input', { inputmode: 'numeric', maxlength: 13, placeholder: '0 para consumidor final', value: '0' });
    const nombre = el('input', { maxlength: 200, placeholder: 'Consumidor final' });
    const domicilio = el('input', { maxlength: 300, placeholder: 'Obligatorio si no es consumidor final' });
    const selVenta = el('select', {}, CONDICIONES_VENTA.map(v => el('option', { value: v }, v)));
    const selCondicion = el('select', {});
    let clienteId = null;
    let clienteEmail = '';
    const buscadorCliente = el('input', { type: 'search', placeholder: 'Buscar cliente por nombre o documento', 'aria-label': 'Buscar cliente', maxlength: 100 });
    const resultados = el('div', { class: 'resultados-cliente' });
    const elegido = el('div', {});
    const zonaNuevo = el('div', {});
    const crearCliente = el('button', { type: 'button', class: 'secundario' }, 'Crear cliente nuevo');

    function usarCliente(c) {
        clienteId = c.id;
        clienteEmail = c.email || '';
        selDoc.value = String(c.doc_tipo);
        nroDoc.value = c.doc_nro;
        nombre.value = c.nombre;
        domicilio.value = c.domicilio;
        if ([...selCondicion.options].some(o => o.value === String(c.condicion_iva))) selCondicion.value = String(c.condicion_iva);
        else mostrarMensaje('La condición frente al IVA del cliente no corresponde a este tipo de comprobante.', 'error');
        vaciar(resultados);
        buscadorCliente.value = '';
        const quitar = el('button', { type: 'button', class: 'secundario' }, 'Quitar');
        quitar.addEventListener('click', () => {
            clienteId = null; clienteEmail = ''; vaciar(elegido);
            nroDoc.value = '0'; nombre.value = ''; domicilio.value = '';
            if (docCF) selDoc.value = '99';
            actualizarCabecera();
        });
        vaciar(elegido).append(el('div', { class: 'cliente-elegido' }, el('span', {}, 'Cliente: ', el('strong', {}, c.nombre)), quitar));
    }

    let esperaCliente = null;
    buscadorCliente.addEventListener('input', () => {
        clearTimeout(esperaCliente);
        const texto = buscadorCliente.value.trim();
        if (texto.length < 2) { vaciar(resultados); return; }
        esperaCliente = setTimeout(async () => {
            let lista = [];
            try { lista = await api('/api/clientes?limite=8&q=' + encodeURIComponent(texto)); } catch (e) { mostrarMensaje(e.message, 'error'); }
            vaciar(resultados).append(...(lista.length ? lista.map(c => {
                const b = el('button', { type: 'button', class: 'opcion-cliente' }, el('strong', {}, c.nombre), el('span', { class: 'sub mono' }, c.doc_formateado));
                b.addEventListener('click', () => usarCliente(c));
                return b;
            }) : [el('p', { class: 'ayuda' }, 'Sin resultados. Podés crearlo con "Crear cliente nuevo".')]));
        }, 250);
    });

    crearCliente.addEventListener('click', async () => {
        if (zonaNuevo.firstChild) { vaciar(zonaNuevo); return; }
        let grupos = [];
        try { grupos = await api('/api/grupos-clientes'); } catch (e) { /* sin grupos */ }
        const form = formularioCliente({ documentos: op.documentos, condiciones: op.condiciones }, grupos, null,
            c => { vaciar(zonaNuevo); usarCliente(c); }, () => vaciar(zonaNuevo));
        vaciar(zonaNuevo).append(el('div', { class: 'alta-rapida' }, el('h3', {}, 'Cliente nuevo'), form));
    });

    // --- Lineas ---
    const cuerpoLineas = el('tbody');
    const totalTexto = el('strong', { class: 'total-comprobante' }, '0,00');
    let totalActual = 0n;

    function formularioElegido() { return formularios.find(f => f.id === selFormulario.value); }

    function actualizarCabecera() {
        const f = formularioElegido();
        campoAsociado.classList.toggle('oculto', !f.es_nota);
        campoServicio.classList.toggle('oculto', !['2', '3'].includes(selConcepto.value));
        // Condiciones frente al IVA validas para la letra del comprobante (dato de ARCA, no constante).
        const previa = selCondicion.value;
        vaciar(selCondicion);
        const validas = op.condiciones.filter(c => !f.letra || c.clases.includes(f.letra));
        for (const c of validas) selCondicion.append(el('option', { value: c.codigo }, c.descripcion));
        if (!validas.length) selCondicion.append(el('option', { value: '0' }, 'Sin informar'));
        const cf = validas.find(c => normalTexto(c.descripcion) === 'consumidor final');
        if (validas.some(c => c.codigo === previa)) selCondicion.value = previa;
        else if (cf) selCondicion.value = cf.codigo;
    }

    function recalcular() {
        let total = 0n;
        for (const fila of cuerpoLineas.children) {
            const cant = normalizarNumero(fila._cantidad.value, 3);
            // Con oferta, el importe sale del precio final que calculo el servidor para el precio de lista tipeado.
            const precio = fila._oferta && fila._oferta.precio_lista === normalizarNumero(fila._precio.value, 2)
                ? fila._oferta.precio_final : normalizarNumero(fila._precio.value, 2);
            const importe = cant !== null && precio !== null ? importeCentavos(cant, precio) : null;
            fila._importe.textContent = importe === null ? '-' : formatoCentavos(importe);
            if (importe !== null) total += importe;
        }
        totalTexto.textContent = selMoneda.value + ' ' + formatoCentavos(total);
        totalActual = total;
        actualizarResto();
    }

    // Ofertas: el servidor propone la mejor para cada linea con articulo (medio de pago y moneda de la cabecera);
    // el cajero la ve bajo la descripcion y puede quitarla (la linea queda sin oferta hasta volver a cargarla).
    let esperaOfertas = null;
    function pintarOferta(fila) {
        vaciar(fila._zonaOferta);
        if (!fila._oferta) return;
        const quitar = el('button', { type: 'button', class: 'secundario', title: 'Quitar la oferta de esta línea' }, 'Quitar');
        quitar.addEventListener('click', () => { fila._oferta = null; fila._sinOferta = true; pintarOferta(fila); recalcular(); });
        fila._zonaOferta.append(el('div', { class: 'oferta-linea' },
            el('span', { class: 'etiqueta ok' }, 'Oferta'), ' ', fila._oferta.detalle, ': ',
            el('span', { class: 'mono' }, formatoImporte(fila._oferta.precio_lista) + ' \u2192 ' + formatoImporte(fila._oferta.precio_final)), ' ', quitar));
    }
    async function evaluarOfertas() {
        const filas = [...cuerpoLineas.children].filter(f => f._articuloId && !f._sinOferta && normalizarNumero(f._precio.value, 2) !== null);
        if (!filas.length) return;
        let r;
        try {
            r = await api('/api/ofertas/evaluar', { method: 'POST', body: { condicion_venta: selVenta.value, moneda: selMoneda.value,
                lineas: filas.map(f => ({ articulo_id: f._articuloId, precio_unitario: normalizarNumero(f._precio.value, 2) })) } });
        } catch (e) { mostrarMensaje(e.message, 'error'); return; }
        filas.forEach((f, i) => { if (f.isConnected) { f._oferta = r[i] || null; pintarOferta(f); } });
        recalcular();
    }
    function evaluarOfertasLuego() { clearTimeout(esperaOfertas); esperaOfertas = setTimeout(evaluarOfertas, 250); }

    // Stock de la linea segun la foto de Tracker360: en rojo si la cantidad supera lo leido. Solo avisa.
    function pintarStock(fila) {
        vaciar(fila._zonaStock);
        if (fila._stock === null) return;
        const cant = normalizarNumero(fila._cantidad.value, 3);
        const falta = cant !== null && Number(cant) > Number(fila._stock);
        fila._zonaStock.append(el('span', { class: 'etiqueta ' + (falta ? 'error' : Number(fila._stock) > 0 ? 'ok' : 'aviso') },
            'Stock Tracker360: ' + formatoStock(fila._stock)));
    }

    // Linea libre (sin articulo) o desde un articulo del catalogo: descripcion y precio quedan copiados y editables.
    function agregarLinea(articulo) {
        const descripcion = el('input', { maxlength: 250, required: true, placeholder: 'Descripción', 'aria-label': 'Descripción', value: articulo ? articulo.descripcion : '' });
        const cantidad = el('input', { inputmode: 'decimal', value: '1', required: true, 'aria-label': 'Cantidad' });
        const precio = el('input', { inputmode: 'decimal', required: true, placeholder: '0,00', 'aria-label': 'Precio unitario', value: articulo && articulo.precio !== null ? String(articulo.precio).replace('.', ',') : '' });
        const importe = el('span', { class: 'mono' }, '-');
        const quitar = el('button', { type: 'button', class: 'peligro', title: 'Quitar línea' }, 'Quitar');
        const zonaOferta = el('div', {});
        const zonaStock = el('div', {});
        const fila = el('tr', {}, el('td', { class: 'col-descripcion' }, articulo ? el('div', { class: 'sub mono' }, articulo.sku) : null, descripcion, zonaOferta, zonaStock),
            el('td', { class: 'col-numero' }, cantidad), el('td', { class: 'col-numero' }, precio), el('td', { class: 'col-importe' }, importe), el('td', {}, quitar));
        fila._descripcion = descripcion; fila._cantidad = cantidad; fila._precio = precio; fila._importe = importe;
        fila._articuloId = articulo ? articulo.id : null;
        fila._zonaOferta = zonaOferta; fila._oferta = null; fila._sinOferta = false;
        fila._zonaStock = zonaStock; fila._stock = articulo && articulo.stock !== null && articulo.stock !== undefined ? articulo.stock : null;
        for (const i of [cantidad, precio]) i.addEventListener('input', recalcular);
        cantidad.addEventListener('input', () => pintarStock(fila));
        if (articulo) precio.addEventListener('input', evaluarOfertasLuego);
        quitar.addEventListener('click', () => {
            if (cuerpoLineas.children.length > 1) { fila.remove(); recalcular(); }
        });
        // Una linea libre vacia se reemplaza por la del articulo.
        const primera = cuerpoLineas.firstChild;
        if (articulo && cuerpoLineas.children.length === 1 && !primera._articuloId && !primera._descripcion.value && !primera._precio.value) primera.remove();
        cuerpoLineas.append(fila);
        recalcular();
        pintarStock(fila);
        if (articulo) evaluarOfertas();
        (articulo ? cantidad : descripcion).focus();
        if (articulo) cantidad.select();
    }

    // Precio vigente del articulo en la moneda del comprobante (sin precio en esa moneda: se tipea).
    function precioVigente(detalle, moneda) {
        const hoy = new Date().toISOString().slice(0, 10);
        const p = (detalle.precios || []).filter(x => x.moneda === moneda && x.vigencia_desde <= hoy).sort((a, b) => b.vigencia_desde < a.vigencia_desde ? -1 : 1)[0];
        return p ? p.importe : null;
    }

    const buscadorArticulo = el('input', { type: 'search', placeholder: 'Buscar artículo por SKU o descripción y agregarlo', 'aria-label': 'Buscar artículo', maxlength: 100 });
    const resultadosArticulo = el('div', {});
    let esperaArticulo = null;
    // Enter: agrega el primer resultado (un lector de codigo de barras tipea el SKU y manda Enter).
    buscadorArticulo.addEventListener('keydown', async (ev) => {
        if (ev.key !== 'Enter') return;
        ev.preventDefault();
        const texto = buscadorArticulo.value.trim();
        if (!texto) return;
        clearTimeout(esperaArticulo);
        let lista = [];
        try { lista = await api('/api/articulos?limite=8&q=' + encodeURIComponent(texto)); } catch (e) { mostrarMensaje(e.message, 'error'); return; }
        const exacto = lista.find(a => a.sku.toUpperCase() === texto.toUpperCase()) || (lista.length === 1 ? lista[0] : null);
        if (!exacto) { buscadorArticulo.dispatchEvent(new Event('input')); if (!lista.length) mostrarMensaje('No hay artículos que coincidan.', 'error'); return; }
        await elegirArticulo(exacto);
    });
    async function elegirArticulo(a) {
        let detalle = a;
        try { detalle = await api('/api/articulos/' + encodeURIComponent(a.id)); } catch (e) { mostrarMensaje(e.message, 'error'); return; }
        agregarLinea({ id: a.id, sku: a.sku, descripcion: a.descripcion, precio: precioVigente(detalle, selMoneda.value), stock: detalle.stock });
        buscadorArticulo.value = ''; vaciar(resultadosArticulo); buscadorArticulo.focus();
    }
    buscadorArticulo.addEventListener('input', () => {
        clearTimeout(esperaArticulo);
        const texto = buscadorArticulo.value.trim();
        if (texto.length < 2) { vaciar(resultadosArticulo); return; }
        esperaArticulo = setTimeout(async () => {
            let lista = [];
            try { lista = await api('/api/articulos?limite=8&q=' + encodeURIComponent(texto)); } catch (e) { mostrarMensaje(e.message, 'error'); }
            vaciar(resultadosArticulo).append(...(lista.length ? lista.map(a => {
                const b = el('button', { type: 'button', class: 'opcion-cliente' }, el('span', {}, el('strong', { class: 'mono' }, a.sku), ' ', a.descripcion),
                    el('span', { class: 'sub mono' }, a.precio === null ? 'sin precio' : selMoneda.value === 'PES' ? formatoImporte(a.precio) : ''), etiquetaStock(a));
                b.addEventListener('click', () => elegirArticulo(a));
                return b;
            }) : [el('p', { class: 'ayuda' }, 'Sin resultados. Podés cargar una línea libre con "Agregar línea".')]));
        }, 250);
    });

    selFormulario.addEventListener('change', actualizarCabecera);
    selConcepto.addEventListener('change', actualizarCabecera);
    selMoneda.addEventListener('change', () => { recalcular(); evaluarOfertas(); });
    selVenta.addEventListener('change', () => {
        evaluarOfertas();
        const primera = cuerpoPagos.firstChild;
        if (primera && !primera._manual) { const m = medioPara(selVenta.value); if (m) primera._medio.value = m.id; }
        pintarCobro();
        actualizarResto();
    });
    selDoc.addEventListener('change', () => { if (selDoc.value === '99') nroDoc.value = '0'; });

    // --- Cobro (Fase 6): caja con planilla abierta y el total repartido por medio de pago. Sin caja abierta o en
    // cuenta corriente, el comprobante se emite sin movimiento de caja. ---
    const cajasAbiertas = cajaOp.cajas.filter(c => c.abierta);
    const selCaja = el('select', { 'aria-label': 'Caja' }, cajasAbiertas.map(c => el('option', { value: c.id }, c.nombre)));
    const sugerida = cajasAbiertas.length ? cajaSugerida(cajasAbiertas) : null;
    if (sugerida) selCaja.value = sugerida.id;
    const registrarCobro = el('input', { type: 'checkbox', checked: true });
    const cuerpoPagos = el('tbody');
    const restoTexto = el('span', { class: 'resto-cobro' }, '');
    const zonaCobro = el('div', {});

    function cobraEnCaja() { return cajasAbiertas.length > 0 && cajaOp.medios.length > 0 && registrarCobro.checked && selVenta.value !== 'Cuenta corriente'; }

    // Medio de pago sugerido por la condicion de venta: Contado -> efectivo; si no, el del mismo nombre.
    function medioPara(condicion) {
        const n = normalTexto(condicion);
        return cajaOp.medios.find(m => n === 'contado' ? m.efectivo : normalTexto(m.nombre) === n) || cajaOp.medios[0] || null;
    }

    function agregarPago(medio) {
        const selMedio = el('select', { 'aria-label': 'Medio de pago' }, cajaOp.medios.map(m => el('option', { value: m.id, selected: medio && m.id === medio.id }, m.nombre)));
        const importe = el('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Importe' });
        const quitar = el('button', { type: 'button', class: 'peligro', title: 'Quitar medio de pago' }, 'Quitar');
        const fila = el('tr', {}, el('td', {}, selMedio), el('td', { class: 'col-numero' }, importe), el('td', {}, quitar));
        fila._medio = selMedio; fila._importe = importe; fila._manual = false;
        importe.addEventListener('input', () => { fila._manual = true; actualizarResto(); });
        quitar.addEventListener('click', () => { if (cuerpoPagos.children.length > 1) { fila.remove(); actualizarResto(); } });
        cuerpoPagos.append(fila);
        return fila;
    }

    // La primera fila que el cajero no toco toma el resto (el total menos lo tipeado en las demas).
    function actualizarResto() {
        if (!cobraEnCaja()) { restoTexto.textContent = ''; return; }
        let asignado = 0n;
        let libre = null;
        for (const f of cuerpoPagos.children) {
            if (!f._manual && libre === null) { libre = f; continue; }
            const v = normalizarNumero(f._importe.value, 2);
            if (v !== null) asignado += aEntero(v, 2);
        }
        if (libre) {
            const resto = totalActual - asignado;
            libre._importe.value = resto > 0n ? formatoCentavos(resto) : '0';
            if (resto > 0n) asignado += resto;
        }
        const diferencia = totalActual - asignado;
        restoTexto.textContent = diferencia === 0n ? '' : (diferencia > 0n ? 'Faltan ' : 'Sobran ') + formatoCentavos(diferencia < 0n ? -diferencia : diferencia);
    }

    const botonPago = el('button', { type: 'button', class: 'secundario' }, 'Agregar medio de pago');
    botonPago.addEventListener('click', () => {
        const fila = agregarPago(medioPara(selVenta.value));
        fila._manual = true;
        actualizarResto();
        fila._importe.focus();
    });

    function pintarCobro() {
        vaciar(zonaCobro);
        if (!cajasAbiertas.length || !cajaOp.medios.length) {
            zonaCobro.append(el('p', { class: 'ayuda' }, 'No hay una caja abierta en este modo: el comprobante se emite sin registrar el cobro. Abrila desde Caja.'));
            return;
        }
        if (selVenta.value === 'Cuenta corriente') {
            zonaCobro.append(el('p', { class: 'ayuda' }, 'Cuenta corriente: no se registra cobro en la caja.'));
            return;
        }
        zonaCobro.append(el('label', { class: 'casilla' }, registrarCobro, 'Registrar el cobro en la caja'),
            el('div', { class: 'zona-pagos' + (registrarCobro.checked ? '' : ' oculto') },
                el('label', {}, 'Caja', selCaja),
                el('div', { class: 'tabla-scroll' }, el('table', { class: 'tabla-lineas' },
                    el('thead', {}, el('tr', {}, el('th', {}, 'Medio de pago'), el('th', {}, 'Importe'), el('th', {}, ''))), cuerpoPagos)),
                el('div', { class: 'acciones' }, botonPago, restoTexto)));
    }
    registrarCobro.addEventListener('change', () => { pintarCobro(); actualizarResto(); });
    if (cajaOp.medios.length) agregarPago(medioPara(selVenta.value));

    const botonAgregar = el('button', { type: 'button', class: 'secundario' }, 'Agregar línea');
    botonAgregar.addEventListener('click', () => agregarLinea(null));
    const botonEmitir = el('button', { type: 'submit' }, 'Emitir');
    const resultado = el('div', {});

    const form = el('form', { class: 'facturacion' },
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Comprobante'),
            el('div', { class: 'grilla-form' },
                el('label', {}, 'Tipo de comprobante', selFormulario), el('label', {}, 'Concepto', selConcepto),
                el('label', {}, 'Moneda', selMoneda), el('label', {}, 'Condiciones de venta', selVenta), campoAsociado),
            campoServicio),
        el('div', { class: 'tarjeta' },
            el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Receptor'), crearCliente),
            el('div', { class: 'buscador-cliente' }, buscadorCliente, resultados),
            elegido, zonaNuevo,
            el('div', { class: 'grilla-form' },
                el('label', {}, 'Tipo de documento', selDoc), el('label', {}, 'Número', nroDoc),
                el('label', {}, 'Nombre o razón social', nombre), el('label', {}, 'Condición frente al IVA', selCondicion),
                el('label', {}, 'Domicilio', domicilio))),
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Detalle'),
            el('div', { class: 'buscador-cliente' }, buscadorArticulo, resultadosArticulo),
            el('div', { class: 'tabla-scroll' }, el('table', { class: 'tabla-lineas' },
                el('thead', {}, el('tr', {}, el('th', {}, 'Descripción'), el('th', {}, 'Cantidad'),
                    el('th', {}, 'Precio unitario'), el('th', {}, 'Importe'), el('th', {}, ''))),
                cuerpoLineas)),
            el('div', { class: 'acciones' }, botonAgregar)),
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Cobro'), zonaCobro),
        el('div', { class: 'tarjeta pie-factura' },
            el('div', {}, el('span', { class: 'sub' }, 'Total'), totalTexto),
            el('div', { class: 'acciones' }, botonEmitir)),
        resultado);

    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const f = formularioElegido();
        const lineas = [];
        for (const fila of cuerpoLineas.children) {
            const cantidad = normalizarNumero(fila._cantidad.value, 3);
            const precio = normalizarNumero(fila._precio.value, 2);
            if (!fila._descripcion.value.trim() || cantidad === null || precio === null) {
                mostrarMensaje('Revisá las líneas: descripción, cantidad (hasta 3 decimales) y precio (hasta 2).', 'error');
                return;
            }
            lineas.push({ descripcion: fila._descripcion.value.trim(), cantidad, precio_unitario: precio, articulo_id: fila._articuloId || null,
                          oferta_id: fila._oferta && fila._oferta.precio_lista === precio ? fila._oferta.oferta_id : null });
        }
        const cuerpo = {
            formulario_id: f.id, concepto: Number(selConcepto.value), moneda: selMoneda.value, lineas,
            condicion_venta: selVenta.value,
            receptor: { doc_tipo: Number(selDoc.value || 0), doc_nro: nroDoc.value || '0', nombre: nombre.value,
                        domicilio: domicilio.value,
                        condicion_iva: Number(selCondicion.value || 0) }
        };
        if (cobraEnCaja()) {
            const pagos = [];
            let suma = 0n;
            for (const fila of cuerpoPagos.children) {
                const v = normalizarNumero(fila._importe.value, 2);
                if (v === null) { mostrarMensaje('Revisá los importes del cobro.', 'error'); return; }
                if (aEntero(v, 2) === 0n) continue;
                pagos.push({ medio_pago_id: fila._medio.value, importe: v });
                suma += aEntero(v, 2);
            }
            if (suma !== totalActual) {
                mostrarMensaje('Los pagos suman ' + formatoCentavos(suma) + ' y el total es ' + formatoCentavos(totalActual) + '.', 'error');
                return;
            }
            cuerpo.pagos = pagos;
            cuerpo.caja_id = selCaja.value;
        }
        if (f.es_nota) cuerpo.asociado_id = selAsociado.value || null;
        if (clienteId) cuerpo.cliente_id = clienteId;
        if (['2', '3'].includes(selConcepto.value)) {
            cuerpo.servicio_desde = desde.value || null; cuerpo.servicio_hasta = hasta.value || null;
            cuerpo.vencimiento_pago = vence.value || null;
        }
        const c = await conBoton(botonEmitir, () => api('/api/comprobantes', { method: 'POST', body: cuerpo }));
        if (!c) return;
        mostrarMensaje(`${c.nombre} ${numeroComprobante(c)} emitido.`, 'ok');
        mostrarEmitido(resultado, c, () => vistaFacturar(contenedor), clienteEmail);
        resultado.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    contenedor.append(form);
    actualizarCabecera();
    pintarCobro();
    agregarLinea(null);
    recalcular();
}

// Envio del comprobante por correo (Fase 7): dialogo con la direccion, prellenada con la del cliente si se conoce.
function enviarPorCorreo(c, emailSugerido, alEnviar) {
    const dialogo = el('dialog', { class: 'ventana', 'aria-label': 'Enviar por correo' });
    const email = el('input', { type: 'email', required: true, maxlength: 200, value: emailSugerido || '', placeholder: 'cliente@ejemplo.com' });
    const enviar = el('button', { type: 'submit' }, 'Enviar');
    const cerrar = el('button', { type: 'button', class: 'secundario cerrar-ventana', 'aria-label': 'Cerrar' }, '×');
    cerrar.addEventListener('click', () => dialogo.close());
    dialogo.addEventListener('close', () => dialogo.remove());
    const form = el('form', {}, el('label', {}, 'Dirección de correo', email), el('div', { class: 'acciones' }, enviar));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const r = await conBoton(enviar, () => api('/api/comprobantes/' + encodeURIComponent(c.id) + '/enviar', { method: 'POST', body: { destinatario: email.value } }));
        if (!r) return;
        dialogo.close();
        mostrarMensaje(`${c.nombre} ${numeroComprobante(c)} enviado a ${r.destinatario}.`, 'ok');
        if (alEnviar) alEnviar(r);
    });
    dialogo.append(el('div', { class: 'tarjeta' }, el('div', { class: 'titulo-tarjeta' }, el('h2', {}, `Enviar ${c.nombre} ${numeroComprobante(c)}`), cerrar), form));
    document.body.append(dialogo);
    dialogo.showModal();
    email.focus();
}

function mostrarEmitido(zona, c, nuevo, emailSugerido) {
    const imprimir = el('button', { type: 'button' }, 'Imprimir');
    imprimir.addEventListener('click', () => abrirImpresion(c.id));
    const otro = el('button', { type: 'button', class: 'secundario' }, 'Nuevo comprobante');
    otro.addEventListener('click', nuevo);
    const correo = el('button', { type: 'button', class: 'secundario' }, 'Enviar por correo');
    const envios = el('span', { class: 'sub' }, (c.envios || []).map(e => (e.estado === 'enviado' ? 'Enviado a ' : 'Error al enviar a ') + e.destinatario).join('; '));
    correo.addEventListener('click', () => enviarPorCorreo(c, emailSugerido, r => { envios.textContent = 'Enviado a ' + r.destinatario; }));
    vaciar(zona).append(el('div', { class: 'tarjeta emitido' },
        el('h2', {}, `${c.nombre} ${numeroComprobante(c)}`),
        el('dl', { class: 'datos' },
            el('dt', {}, 'Fecha'), el('dd', {}, fecha(c.fecha)),
            el('dt', {}, 'Total'), el('dd', {}, `${c.moneda} ${formatoImporte(c.total)}`),
            c.pagos && c.pagos.length ? el('dt', {}, 'Cobro') : null,
            c.pagos && c.pagos.length ? el('dd', {}, c.pagos.map(p => p.medio + ' ' + formatoImporte(p.importe)).join('; ') + ' (' + c.pagos[0].caja + ')') : null,
            c.cae ? el('dt', {}, 'CAE') : null, c.cae ? el('dd', { class: 'mono' }, c.cae) : null,
            c.cae ? el('dt', {}, 'Vencimiento del CAE') : null, c.cae ? el('dd', {}, fecha(c.cae_vencimiento)) : null),
        el('div', { class: 'acciones' }, imprimir, correo, otro), envios));
}

// ===== Pantalla Comprobantes =====
async function vistaComprobantes(contenedor) {
    const vigente = redibujar(contenedor);
    const cuerpo = el('tbody');
    const mas = el('button', { type: 'button', class: 'secundario oculto' }, 'Ver más');
    const tarjeta = el('div', { class: 'tarjeta' }, el('h2', {}, 'Comprobantes emitidos'),
        el('p', { class: 'ayuda' }, 'De la razón social y el modo elegidos en el avatar, del más nuevo al más viejo.'),
        el('div', { class: 'tabla-scroll' }, el('table', {},
            el('thead', {}, el('tr', {}, el('th', {}, 'Fecha'), el('th', {}, 'Comprobante'), el('th', {}, 'Receptor'),
                el('th', {}, 'Total'), el('th', {}, 'CAE'), el('th', {}, ''))),
            cuerpo)),
        el('div', { class: 'acciones' }, mas));
    contenedor.append(tarjeta);
    let ultimo = null;

    async function cargar() {
        let lista;
        try {
            lista = await api('/api/comprobantes?limite=50' + (ultimo ? '&antes_de=' + encodeURIComponent(ultimo) : ''));
        } catch (e) {
            mostrarMensaje(e.message, 'error');
            return;
        }
        if (!vigente()) return;
        if (!lista.length && !ultimo) {
            cuerpo.append(el('tr', {}, el('td', { colspan: 6, class: 'vacio' }, 'Todavía no hay comprobantes en este modo.')));
        }
        for (const c of lista) {
            const imprimir = el('button', { type: 'button', class: 'secundario' }, 'Imprimir');
            imprimir.addEventListener('click', () => abrirImpresion(c.id));
            const correo = el('button', { type: 'button', class: 'secundario' }, 'Enviar');
            correo.addEventListener('click', () => enviarPorCorreo(c, ''));
            cuerpo.append(el('tr', {},
                el('td', { class: 'sin-corte' }, fecha(c.fecha)),
                el('td', {}, c.nombre, el('div', { class: 'sub mono' }, numeroComprobante(c))),
                el('td', {}, c.receptor.nombre || 'Consumidor final',
                    c.receptor.doc_nro !== '0' ? el('div', { class: 'sub mono' }, c.receptor.doc_nro) : null),
                el('td', { class: 'sin-corte' }, `${c.moneda} ${formatoImporte(c.total)}`),
                el('td', { class: 'mono' }, c.cae || el('span', { class: 'etiqueta' }, 'No electrónico')),
                el('td', { class: 'sin-corte' }, imprimir, ' ', emite() ? correo : null)));
        }
        ultimo = lista.length ? lista[lista.length - 1].creado_en : ultimo;
        mas.classList.toggle('oculto', lista.length < 50);
    }

    mas.addEventListener('click', () => conBoton(mas, cargar));
    await cargar();
}
