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
    const selCondicion = el('select', {});

    // --- Lineas ---
    const cuerpoLineas = el('tbody');
    const totalTexto = el('strong', { class: 'total-comprobante' }, '0,00');

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
            const precio = normalizarNumero(fila._precio.value, 2);
            const importe = cant !== null && precio !== null ? importeCentavos(cant, precio) : null;
            fila._importe.textContent = importe === null ? '-' : formatoCentavos(importe);
            if (importe !== null) total += importe;
        }
        totalTexto.textContent = selMoneda.value + ' ' + formatoCentavos(total);
    }

    function agregarLinea() {
        const descripcion = el('input', { maxlength: 250, required: true, placeholder: 'Descripción', 'aria-label': 'Descripción' });
        const cantidad = el('input', { inputmode: 'decimal', value: '1', required: true, 'aria-label': 'Cantidad' });
        const precio = el('input', { inputmode: 'decimal', required: true, placeholder: '0,00', 'aria-label': 'Precio unitario' });
        const importe = el('span', { class: 'mono' }, '-');
        const quitar = el('button', { type: 'button', class: 'peligro', title: 'Quitar línea' }, 'Quitar');
        const fila = el('tr', {}, el('td', { class: 'col-descripcion' }, descripcion), el('td', { class: 'col-numero' }, cantidad),
            el('td', { class: 'col-numero' }, precio), el('td', { class: 'col-importe' }, importe), el('td', {}, quitar));
        fila._descripcion = descripcion; fila._cantidad = cantidad; fila._precio = precio; fila._importe = importe;
        for (const i of [cantidad, precio]) i.addEventListener('input', recalcular);
        quitar.addEventListener('click', () => {
            if (cuerpoLineas.children.length > 1) { fila.remove(); recalcular(); }
        });
        cuerpoLineas.append(fila);
        descripcion.focus();
    }

    selFormulario.addEventListener('change', actualizarCabecera);
    selConcepto.addEventListener('change', actualizarCabecera);
    selMoneda.addEventListener('change', recalcular);
    selDoc.addEventListener('change', () => { if (selDoc.value === '99') nroDoc.value = '0'; });

    const botonAgregar = el('button', { type: 'button', class: 'secundario' }, 'Agregar línea');
    botonAgregar.addEventListener('click', agregarLinea);
    const botonEmitir = el('button', { type: 'submit' }, 'Emitir');
    const resultado = el('div', {});

    const form = el('form', { class: 'facturacion' },
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Comprobante'),
            el('div', { class: 'grilla-form' },
                el('label', {}, 'Tipo de comprobante', selFormulario), el('label', {}, 'Concepto', selConcepto),
                el('label', {}, 'Moneda', selMoneda), campoAsociado),
            campoServicio),
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Receptor'),
            el('div', { class: 'grilla-form' },
                el('label', {}, 'Tipo de documento', selDoc), el('label', {}, 'Número', nroDoc),
                el('label', {}, 'Nombre o razón social', nombre), el('label', {}, 'Condición frente al IVA', selCondicion))),
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Detalle'),
            el('div', { class: 'tabla-scroll' }, el('table', { class: 'tabla-lineas' },
                el('thead', {}, el('tr', {}, el('th', {}, 'Descripción'), el('th', {}, 'Cantidad'),
                    el('th', {}, 'Precio unitario'), el('th', {}, 'Importe'), el('th', {}, ''))),
                cuerpoLineas)),
            el('div', { class: 'acciones' }, botonAgregar)),
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
            lineas.push({ descripcion: fila._descripcion.value.trim(), cantidad, precio_unitario: precio });
        }
        const cuerpo = {
            formulario_id: f.id, concepto: Number(selConcepto.value), moneda: selMoneda.value, lineas,
            receptor: { doc_tipo: Number(selDoc.value || 0), doc_nro: nroDoc.value || '0', nombre: nombre.value,
                        condicion_iva: Number(selCondicion.value || 0) }
        };
        if (f.es_nota) cuerpo.asociado_id = selAsociado.value || null;
        if (['2', '3'].includes(selConcepto.value)) {
            cuerpo.servicio_desde = desde.value || null; cuerpo.servicio_hasta = hasta.value || null;
            cuerpo.vencimiento_pago = vence.value || null;
        }
        const c = await conBoton(botonEmitir, () => api('/api/comprobantes', { method: 'POST', body: cuerpo }));
        if (!c) return;
        mostrarMensaje(`${c.nombre} ${numeroComprobante(c)} emitido.`, 'ok');
        mostrarEmitido(resultado, c, () => vistaFacturar(contenedor));
        resultado.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    contenedor.append(form);
    actualizarCabecera();
    agregarLinea();
    recalcular();
}

function mostrarEmitido(zona, c, nuevo) {
    const imprimir = el('button', { type: 'button' }, 'Imprimir');
    imprimir.addEventListener('click', () => abrirImpresion(c.id));
    const otro = el('button', { type: 'button', class: 'secundario' }, 'Nuevo comprobante');
    otro.addEventListener('click', nuevo);
    vaciar(zona).append(el('div', { class: 'tarjeta emitido' },
        el('h2', {}, `${c.nombre} ${numeroComprobante(c)}`),
        el('dl', { class: 'datos' },
            el('dt', {}, 'Fecha'), el('dd', {}, fecha(c.fecha)),
            el('dt', {}, 'Total'), el('dd', {}, `${c.moneda} ${formatoImporte(c.total)}`),
            c.cae ? el('dt', {}, 'CAE') : null, c.cae ? el('dd', { class: 'mono' }, c.cae) : null,
            c.cae ? el('dt', {}, 'Vencimiento del CAE') : null, c.cae ? el('dd', {}, fecha(c.cae_vencimiento)) : null),
        el('div', { class: 'acciones' }, imprimir, otro)));
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
            cuerpo.append(el('tr', {},
                el('td', { class: 'sin-corte' }, fecha(c.fecha)),
                el('td', {}, c.nombre, el('div', { class: 'sub mono' }, numeroComprobante(c))),
                el('td', {}, c.receptor.nombre || 'Consumidor final',
                    c.receptor.doc_nro !== '0' ? el('div', { class: 'sub mono' }, c.receptor.doc_nro) : null),
                el('td', { class: 'sin-corte' }, `${c.moneda} ${formatoImporte(c.total)}`),
                el('td', { class: 'mono' }, c.cae || el('span', { class: 'etiqueta' }, 'No electrónico')),
                el('td', {}, imprimir)));
        }
        ultimo = lista.length ? lista[lista.length - 1].creado_en : ultimo;
        mas.classList.toggle('oculto', lista.length < 50);
    }

    mas.addEventListener('click', () => conBoton(mas, cargar));
    await cargar();
}
