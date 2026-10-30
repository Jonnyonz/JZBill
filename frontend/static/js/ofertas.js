// Ofertas (Fase 5): descuento por porcentaje o monto sobre todos los articulos, una categoria o una lista de
// articulos, con vigencia y opcional por medio de pago. Todo con el() / textContent.
'use strict';

// Misma lista que el servidor (ofertas.CONDICIONES_VENTA): es el "medio de pago" de la oferta y de la factura.
const CONDICIONES_VENTA = ['Contado', 'Cuenta corriente', 'Tarjeta de débito', 'Tarjeta de crédito', 'Transferencia', 'Cheque', 'Otra'];
const ESTADOS_OFERTA = { vigente: ['Vigente', 'ok'], futura: ['Futura', ''], vencida: ['Vencida', ''], inactiva: ['Inactiva', ''] };

function puedeEditarOfertas() { return Panel.yo && ['administrador', 'supervisor'].includes(Panel.yo.rol); }

function alcanceTexto(o) {
    if (o.alcance === 'todo') return 'Todos los artículos';
    if (o.alcance === 'categoria') return 'Categoría ' + o.categoria;
    return o.cantidad_articulos + (o.cantidad_articulos === 1 ? ' artículo' : ' artículos');
}

function vigenciaTexto(o) {
    return 'desde ' + fecha(o.vigencia_desde) + (o.vigencia_hasta ? ' hasta ' + fecha(o.vigencia_hasta) : ', sin fin');
}

// Formulario de alta o edicion. alGuardar(oferta) recibe la oferta guardada.
function formularioOferta(opciones, oferta, alGuardar, alCancelar) {
    const nombre = el('input', { required: true, maxlength: 80, value: oferta ? oferta.nombre : '', placeholder: 'Por ejemplo: Semana del bazar' });
    const selTipo = el('select', {}, el('option', { value: 'porcentaje', selected: !oferta || oferta.tipo === 'porcentaje' }, 'Porcentaje de descuento'),
        el('option', { value: 'monto', selected: oferta && oferta.tipo === 'monto' }, 'Monto fijo por unidad (pesos)'));
    const valor = el('input', { type: 'number', min: '0.01', step: '0.01', required: true, inputmode: 'decimal', value: oferta ? oferta.valor : '' });
    const selAlcance = el('select', {}, el('option', { value: 'todo', selected: !oferta || oferta.alcance === 'todo' }, 'Todos los artículos'),
        el('option', { value: 'categoria', selected: oferta && oferta.alcance === 'categoria' }, 'Una categoría'),
        el('option', { value: 'articulos', selected: oferta && oferta.alcance === 'articulos' }, 'Artículos elegidos'));
    const selCategoria = el('select', {}, el('option', { value: '' }, 'Elegí la categoría'));
    for (const c of (opciones.categorias || [])) selCategoria.append(el('option', { value: c.categoria, selected: oferta && oferta.categoria === c.categoria }, c.categoria + ' (' + c.articulos + ')'));
    if (oferta && oferta.categoria && ![...selCategoria.options].some(o => o.value === oferta.categoria)) selCategoria.append(el('option', { value: oferta.categoria, selected: true }, oferta.categoria));
    const selCondicion = el('select', {}, el('option', { value: '' }, 'Cualquiera'), CONDICIONES_VENTA.map(c => el('option', { value: c, selected: oferta && oferta.condicion_venta === c }, c)));
    const desde = el('input', { type: 'date', required: true, value: oferta ? oferta.vigencia_desde : hoyIso() });
    const hasta = el('input', { type: 'date', value: oferta && oferta.vigencia_hasta ? oferta.vigencia_hasta : '' });
    const activa = el('input', { type: 'checkbox', checked: oferta ? oferta.activa : true });

    // Articulos elegidos: buscador y lista con quitar.
    const elegidos = new Map((oferta ? oferta.articulos || [] : []).map(a => [a.id, a]));
    const listaElegidos = el('div', { class: 'resultados-cliente' });
    const buscador = el('input', { type: 'search', placeholder: 'Buscar artículo por SKU o descripción y agregarlo', 'aria-label': 'Buscar artículo', maxlength: 100 });
    const resultados = el('div', {});
    function pintarElegidos() {
        vaciar(listaElegidos);
        if (!elegidos.size) { listaElegidos.append(el('p', { class: 'ayuda' }, 'Todavía no elegiste artículos.')); return; }
        for (const a of elegidos.values()) {
            const quitar = el('button', { type: 'button', class: 'secundario' }, 'Quitar');
            quitar.addEventListener('click', () => { elegidos.delete(a.id); pintarElegidos(); });
            listaElegidos.append(el('div', { class: 'cliente-elegido' }, el('span', {}, el('strong', { class: 'mono' }, a.sku), ' ', a.descripcion), quitar));
        }
    }
    let espera = null;
    buscador.addEventListener('input', () => {
        clearTimeout(espera);
        const texto = buscador.value.trim();
        if (texto.length < 2) { vaciar(resultados); return; }
        espera = setTimeout(async () => {
            let lista = [];
            try { lista = await api('/api/articulos?limite=8&q=' + encodeURIComponent(texto)); } catch (e) { mostrarMensaje(e.message, 'error'); }
            vaciar(resultados).append(...(lista.length ? lista.map(a => {
                const b = el('button', { type: 'button', class: 'opcion-cliente' }, el('span', {}, el('strong', { class: 'mono' }, a.sku), ' ', a.descripcion));
                b.addEventListener('click', () => { elegidos.set(a.id, a); pintarElegidos(); buscador.value = ''; vaciar(resultados); buscador.focus(); });
                return b;
            }) : [el('p', { class: 'ayuda' }, 'Sin resultados.')]));
        }, 250);
    });
    pintarElegidos();

    const campoCategoria = el('label', {}, 'Categoría', selCategoria);
    const zonaArticulos = el('div', {}, el('div', { class: 'buscador-cliente' }, buscador, resultados), listaElegidos);
    function mostrarAlcance() {
        campoCategoria.classList.toggle('oculto', selAlcance.value !== 'categoria');
        zonaArticulos.classList.toggle('oculto', selAlcance.value !== 'articulos');
        selCategoria.required = selAlcance.value === 'categoria';
    }
    selAlcance.addEventListener('change', mostrarAlcance);
    mostrarAlcance();

    const guardar = el('button', { type: 'submit' }, oferta ? 'Guardar cambios' : 'Crear oferta');
    const cancelar = el('button', { type: 'button', class: 'secundario' }, 'Cancelar');
    cancelar.addEventListener('click', () => alCancelar && alCancelar());
    const form = el('form', { class: 'form-cliente' },
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Nombre', nombre), el('label', {}, 'Tipo de descuento', selTipo), el('label', {}, 'Valor', valor),
            el('label', {}, 'Alcance', selAlcance), campoCategoria,
            el('label', {}, 'Medio de pago', selCondicion),
            el('label', {}, 'Vigente desde', desde), el('label', {}, 'Hasta (opcional)', hasta)),
        zonaArticulos,
        oferta ? el('label', { class: 'casilla' }, activa, 'Activa') : null,
        el('div', { class: 'acciones' }, guardar, alCancelar ? cancelar : null));
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const cuerpo = { nombre: nombre.value.trim(), tipo: selTipo.value, valor: valor.value, alcance: selAlcance.value,
            categoria: selAlcance.value === 'categoria' ? selCategoria.value : '',
            articulos: selAlcance.value === 'articulos' ? [...elegidos.keys()] : [],
            condicion_venta: selCondicion.value || null, vigencia_desde: desde.value, vigencia_hasta: hasta.value || null,
            activa: oferta ? activa.checked : true };
        const r = await conBoton(guardar, () => api(oferta ? '/api/ofertas/' + encodeURIComponent(oferta.id) : '/api/ofertas',
            { method: oferta ? 'PUT' : 'POST', body: cuerpo }));
        if (r) { mostrarMensaje(oferta ? 'Oferta guardada.' : 'Oferta creada.', 'ok'); alGuardar(r); }
    });
    return form;
}

// ===== Pantalla Ofertas =====
async function vistaOfertas(contenedor) {
    const vigente = redibujar(contenedor);
    let opciones;
    try {
        opciones = await api('/api/articulos/opciones');
    } catch (e) {
        if (vigente()) contenedor.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' }, e.message)));
        return;
    }
    if (!vigente()) return;
    const puedeEditar = puedeEditarOfertas();
    const zonaForm = el('dialog', { class: 'ventana', 'aria-label': 'Oferta' });
    const inactivas = el('input', { type: 'checkbox' });
    const cuerpo = el('tbody');
    const nueva = el('button', { type: 'button' }, 'Nueva oferta');
    nueva.addEventListener('click', () => abrirForm(null));

    async function abrirForm(resumen) {
        let oferta = null;
        if (resumen) {
            try { oferta = await api('/api/ofertas/' + encodeURIComponent(resumen.id)); }
            catch (e) { mostrarMensaje(e.message, 'error'); return; }
        }
        const cerrar = el('button', { type: 'button', class: 'secundario cerrar-ventana', 'aria-label': 'Cerrar' }, '×');
        cerrar.addEventListener('click', () => zonaForm.close());
        vaciar(zonaForm).append(el('div', { class: 'tarjeta' },
            el('div', { class: 'titulo-tarjeta' }, el('h2', {}, oferta ? 'Editar oferta' : 'Nueva oferta'), cerrar),
            formularioOferta(opciones, oferta, () => { zonaForm.close(); cargar(); }, () => zonaForm.close())));
        if (!zonaForm.open) zonaForm.showModal();
    }

    async function cargar() {
        let lista;
        try { lista = await api('/api/ofertas' + (inactivas.checked ? '?incluir_inactivas=true' : '')); }
        catch (e) { mostrarMensaje(e.message, 'error'); return; }
        vaciar(cuerpo);
        if (!lista.length) cuerpo.append(el('tr', {}, el('td', { colspan: 6, class: 'vacio' }, 'Todavía no hay ofertas.')));
        for (const o of lista) {
            const editar = el('button', { type: 'button', class: 'secundario' }, 'Editar');
            editar.addEventListener('click', () => abrirForm(o));
            const [texto, clase] = ESTADOS_OFERTA[o.estado] || [o.estado, ''];
            cuerpo.append(el('tr', {},
                el('td', {}, o.nombre),
                el('td', { class: 'sin-corte' }, o.tipo === 'porcentaje' ? o.valor.replace(/\.?0+$/, '') + ' %' : '$ ' + formatoImporte(o.valor) + ' por unidad'),
                el('td', {}, alcanceTexto(o), el('div', { class: 'sub' }, o.condicion_venta ? 'Solo ' + o.condicion_venta.toLowerCase() : 'Cualquier medio de pago')),
                el('td', {}, vigenciaTexto(o)),
                el('td', {}, el('span', { class: 'etiqueta ' + clase }, texto)),
                el('td', {}, puedeEditar ? editar : null)));
        }
    }
    inactivas.addEventListener('change', cargar);

    contenedor.append(
        el('div', { class: 'tarjeta' },
            el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Ofertas'), puedeEditar ? nueva : null),
            el('p', { class: 'ayuda' }, 'Descuentos sobre el precio de lista. Al facturar, el sistema propone la oferta en la línea y el cajero la ve y puede quitarla; el detalle queda guardado en el comprobante. Si a un artículo le aplican varias, gana la de mayor descuento. Un monto fijo está en pesos: en otra moneda solo aplican los porcentajes.'),
            el('div', { class: 'fila-form' }, el('label', { class: 'casilla' }, inactivas, 'Incluir inactivas')),
            el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'Nombre'), el('th', {}, 'Descuento'), el('th', {}, 'Alcance'),
                    el('th', {}, 'Vigencia'), el('th', {}, 'Estado'), el('th', {}, ''))), cuerpo))),
        zonaForm);
    await cargar();
}
