// Reportes (Fase 7): ventas, libro de IVA ventas, rentabilidad y cierres de caja, por razon social y modo del
// contexto y por periodo, con descarga CSV. Los ve cualquier rol. Todo con el() / textContent.
'use strict';

const PESTANAS_REPORTES = [['ventas', 'Ventas'], ['libro', 'Libro de IVA ventas'], ['rentabilidad', 'Rentabilidad'], ['caja', 'Cierres de caja']];
const RUTAS_REPORTES = { ventas: 'ventas', libro: 'libro-iva', rentabilidad: 'rentabilidad', caja: 'caja' };
const AGRUPAR_RENTABILIDAD = [['articulo', 'Artículo'], ['categoria', 'Categoría'], ['punto_venta', 'Punto de venta'], ['dia', 'Día']];

function fechaIsoLocal(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function tablaReporte(encabezados, filas, vacio) {
    return el('div', { class: 'tabla-scroll' }, el('table', {},
        el('thead', {}, el('tr', {}, encabezados.map(h => el('th', {}, h)))),
        el('tbody', {}, filas.length ? filas : el('tr', {}, el('td', { colspan: encabezados.length, class: 'vacio' }, vacio || 'Sin datos en el período.')))));
}

function celdaImporte(texto) { return el('td', { class: 'mono sin-corte' }, formatoConSigno(texto)); }

async function vistaReportes(contenedor) {
    const vigente = redibujar(contenedor);
    let op;
    try {
        op = await api('/api/reportes/opciones');
    } catch (e) {
        if (vigente()) contenedor.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' }, e.message)));
        return;
    }
    if (!vigente()) return;
    const hoy = new Date();
    const desde = el('input', { type: 'date', value: fechaIsoLocal(new Date(hoy.getFullYear(), hoy.getMonth(), 1)) });
    const hasta = el('input', { type: 'date', value: fechaIsoLocal(hoy) });
    const selPv = el('select', {}, el('option', { value: '' }, 'Todos'),
        op.puntos_venta.map(p => el('option', { value: p.id }, numeroPv(p.numero) + (p.descripcion ? ' ' + p.descripcion : ''))));
    const selAgrupar = el('select', {}, AGRUPAR_RENTABILIDAD.map(([v, t]) => el('option', { value: v }, t)));
    const campoPv = el('label', {}, 'Punto de venta', selPv);
    const campoAgrupar = el('label', { class: 'oculto' }, 'Agrupar por', selAgrupar);
    const descargar = el('button', { type: 'button', class: 'secundario' }, 'Descargar CSV');
    const zona = el('div', {});
    let actual = 'ventas';

    const botones = PESTANAS_REPORTES.map(([clave, texto]) => {
        const b = el('button', { type: 'button' }, texto);
        b.addEventListener('click', () => { actual = clave; cargar(); });
        b._clave = clave;
        return b;
    });

    function consulta() {
        const q = new URLSearchParams();
        if (desde.value) q.set('desde', desde.value);
        if (hasta.value) q.set('hasta', hasta.value);
        if (selPv.value && actual !== 'caja') q.set('punto_venta_id', selPv.value);
        if (actual === 'rentabilidad') q.set('agrupar', selAgrupar.value);
        return q.toString();
    }

    async function cargar() {
        for (const b of botones) { b.classList.toggle('secundario', b._clave !== actual); b.setAttribute('aria-pressed', b._clave === actual ? 'true' : 'false'); }
        campoAgrupar.classList.toggle('oculto', actual !== 'rentabilidad');
        campoPv.classList.toggle('oculto', actual === 'caja');
        let d;
        try { d = await api('/api/reportes/' + RUTAS_REPORTES[actual] + '?' + consulta()); }
        catch (e) { mostrarMensaje(e.message, 'error'); return; }
        vaciar(zona);
        ({ ventas: pintarVentas, libro: pintarLibro, rentabilidad: pintarRentabilidad, caja: pintarCaja })[actual](d);
    }
    descargar.addEventListener('click', () => { window.location.href = '/api/reportes/' + RUTAS_REPORTES[actual] + '.csv?' + consulta(); });
    for (const i of [desde, hasta, selPv, selAgrupar]) i.addEventListener('change', cargar);

    function pintarVentas(d) {
        const totales = d.totales.length ? d.totales.map(t => el('dl', { class: 'datos' },
            el('dt', {}, 'Moneda'), el('dd', { class: 'mono' }, t.moneda),
            el('dt', {}, 'Comprobantes'), el('dd', {}, String(t.comprobantes)),
            el('dt', {}, 'Facturado'), el('dd', { class: 'mono' }, formatoConSigno(t.facturado)),
            el('dt', {}, 'Notas de crédito'), el('dd', { class: 'mono' }, formatoConSigno(t.notas_credito)),
            el('dt', {}, 'Neto'), el('dd', { class: 'mono' }, el('strong', {}, formatoConSigno(t.neto)))))
            : [el('p', { class: 'ayuda' }, 'Sin comprobantes en el período.')];
        const filas = (lista, etiqueta) => lista.map(g => el('tr', {}, el('td', {}, etiqueta(g)), el('td', { class: 'mono' }, g.moneda),
            el('td', { class: 'mono' }, String(g.cantidad)), celdaImporte(g.total)));
        zona.append(
            el('div', { class: 'tarjeta' }, el('h2', {}, 'Totales del período'), el('div', { class: 'dos-columnas' }, totales),
                el('p', { class: 'ayuda' }, 'Las notas de crédito restan. Modo ' + d.modo + ': ' + (d.modo === 'empresa' ? 'no incluye nada de prueba.' : 'solo comprobantes de homologación, sin validez fiscal.'))),
            el('div', { class: 'dos-columnas' },
                el('div', { class: 'tarjeta' }, el('h2', {}, 'Por tipo de comprobante'),
                    tablaReporte(['Comprobante', 'Moneda', 'Cantidad', 'Total'], filas(d.por_tipo, g => g.nombre))),
                el('div', { class: 'tarjeta' }, el('h2', {}, 'Por condición de venta'),
                    tablaReporte(['Condición', 'Moneda', 'Cantidad', 'Total'], filas(d.por_condicion_venta, g => g.condicion_venta))),
                el('div', { class: 'tarjeta' }, el('h2', {}, 'Por punto de venta'),
                    tablaReporte(['Punto de venta', 'Moneda', 'Cantidad', 'Total'], filas(d.por_punto_venta, g => numeroPv(g.punto_venta)))),
                el('div', { class: 'tarjeta' }, el('h2', {}, 'Por día'),
                    tablaReporte(['Fecha', 'Moneda', 'Cantidad', 'Total'], filas(d.por_dia, g => fecha(g.fecha))))));
    }

    function pintarLibro(d) {
        const filas = d.filas.map(f => el('tr', {},
            el('td', { class: 'sin-corte' }, fecha(f.fecha)), el('td', {}, f.comprobante, el('div', { class: 'sub mono' }, numeroPv(f.punto_venta) + '-' + String(f.numero).padStart(8, '0'))),
            el('td', {}, f.receptor, el('div', { class: 'sub mono' }, f.doc_nro !== '0' ? f.doc_nro : '')),
            el('td', { class: 'mono' }, f.moneda), celdaImporte(f.neto), celdaImporte(f.iva), celdaImporte(f.total), el('td', { class: 'mono' }, f.cae || '')));
        for (const t of d.totales) {
            filas.push(el('tr', { class: 'total' }, el('td', { colspan: 3 }, 'Total ' + t.comprobantes + ' comprobantes'), el('td', { class: 'mono' }, t.moneda),
                celdaImporte(t.neto), celdaImporte(t.iva), celdaImporte(t.total), el('td', {})));
        }
        zona.append(el('div', { class: 'tarjeta' }, el('h2', {}, 'Libro de IVA ventas'),
            el('p', { class: 'ayuda' }, 'Comprobantes electrónicos del período. Las notas de crédito van en negativo. El CSV trae también no gravado, exento, tributos y cotización.'),
            tablaReporte(['Fecha', 'Comprobante', 'Receptor', 'Moneda', 'Neto', 'IVA', 'Total', 'CAE'], filas)));
    }

    function pintarRentabilidad(d) {
        const etiqueta = { articulo: 'SKU', categoria: 'Categoría', punto_venta: 'Punto de venta', dia: 'Fecha' }[d.agrupar];
        const filas = d.filas.map(f => el('tr', {},
            el('td', {}, d.agrupar === 'dia' ? fecha(f.clave) : f.clave, f.descripcion ? el('div', { class: 'sub' }, f.descripcion) : null),
            el('td', { class: 'mono' }, f.moneda), el('td', { class: 'mono' }, f.cantidad.replace('.', ',')),
            celdaImporte(f.ventas), celdaImporte(f.costo), celdaImporte(f.margen),
            el('td', { class: 'mono sin-corte' }, f.porcentaje !== null ? f.porcentaje.replace('.', ',') + ' %' : el('span', { class: 'sub' }, 'sin costo'))));
        for (const t of d.totales) {
            filas.push(el('tr', { class: 'total' }, el('td', {}, 'Total'), el('td', { class: 'mono' }, t.moneda), el('td', {}),
                celdaImporte(t.ventas), celdaImporte(t.costo), celdaImporte(t.margen),
                el('td', { class: 'mono sin-corte' }, t.porcentaje !== null ? t.porcentaje.replace('.', ',') + ' %' : el('span', { class: 'sub' }, 'líneas sin costo: ' + t.lineas_sin_costo))));
        }
        zona.append(el('div', { class: 'tarjeta' }, el('h2', {}, 'Rentabilidad: margen bruto'),
            el('p', { class: 'ayuda' }, 'Ventas (precio final cobrado, con las ofertas aplicadas) menos el costo ACTUAL del artículo por la cantidad. No es contabilidad. Las líneas sin artículo o en otra moneda que pesos quedan sin costo y el porcentaje no se calcula.'),
            tablaReporte([etiqueta, 'Moneda', 'Cantidad', 'Ventas', 'Costo', 'Margen', 'Margen %'], filas)));
    }

    function pintarCaja(d) {
        const acumulado = d.por_medio.map(t => el('tr', {}, el('td', {}, t.medio), el('td', { class: 'mono' }, t.moneda), celdaImporte(t.entradas), celdaImporte(t.salidas),
            el('td', {}, el('span', { class: 'etiqueta ' + (t.diferencia === '0.00' ? 'ok' : 'error') }, formatoConSigno(t.diferencia))), el('td', { class: 'mono' }, String(t.planillas))));
        const categorias = d.por_categoria.map(c => el('tr', {}, el('td', {}, c.categoria), el('td', { class: 'mono' }, c.moneda), celdaImporte(c.entradas), celdaImporte(c.salidas)));
        zona.append(el('div', { class: 'dos-columnas' },
            el('div', { class: 'tarjeta' }, el('h2', {}, 'Acumulado por medio de pago'),
                tablaReporte(['Medio de pago', 'Moneda', 'Entradas', 'Salidas', 'Diferencias de arqueo', 'Planillas'], acumulado)),
            el('div', { class: 'tarjeta' }, el('h2', {}, 'Acumulado por categoría'),
                tablaReporte(['Categoría', 'Moneda', 'Entradas', 'Salidas'], categorias, 'Sin movimientos manuales en el período.'))));
        for (const p of d.planillas) {
            const abierta = p.estado === 'abierta';
            zona.append(el('div', { class: 'tarjeta' },
                el('div', { class: 'titulo-tarjeta' }, el('h2', {}, p.caja + ', ' + fecha(p.fecha) + ' ', el('span', { class: 'etiqueta ' + (abierta ? 'ok' : '') }, abierta ? 'Abierta' : 'Cerrada'))),
                el('p', { class: 'ayuda' }, 'Abrió ' + (p.abierta_por || '-') + (p.cerrada_en ? '; cerró ' + (p.cerrada_por || '-') + ' el ' + fechaHora(p.cerrada_en) : '') + (p.observaciones ? '. ' + p.observaciones : '')),
                tablaReporte(['Medio de pago', 'Moneda', 'Fondo', 'Entradas', 'Salidas', 'Saldo esperado', 'Contado', 'Diferencia'],
                    p.medios.map(m => el('tr', {}, el('td', {}, m.medio), el('td', { class: 'mono' }, m.moneda), celdaImporte(m.fondo), celdaImporte(m.entradas),
                        celdaImporte(m.salidas), celdaImporte(m.saldo), el('td', { class: 'mono' }, m.contado !== null ? formatoConSigno(m.contado) : '-'),
                        el('td', {}, m.diferencia !== null ? el('span', { class: 'etiqueta ' + (m.diferencia === '0.00' ? 'ok' : 'error') }, formatoConSigno(m.diferencia)) : '-'))))));
        }
        if (!d.planillas.length) zona.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' }, 'Sin planillas de caja en el período.')));
    }

    contenedor.append(
        el('div', { class: 'tarjeta' },
            el('div', { class: 'pestanas' }, botones),
            el('div', { class: 'filtros-reporte' }, el('label', {}, 'Desde', desde), el('label', {}, 'Hasta', hasta), campoPv, campoAgrupar, descargar)),
        zona);
    await cargar();
}
