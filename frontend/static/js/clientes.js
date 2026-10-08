// Clientes (compartidos entre las razones sociales) y grupos economicos. formularioCliente() se usa en la pantalla
// Clientes y en Facturar ("Crear cliente nuevo"), sin salir de la venta. Todo con el() / textContent.
'use strict';

// Tipos de documento y condiciones frente al IVA de ARCA (los mismos que usa Facturar).
async function opcionesFiscales() {
    const op = await api('/api/facturacion/opciones');
    return { documentos: op.documentos, condiciones: op.condiciones };
}

// Formulario de alta o edicion. alGuardar(cliente) recibe el cliente guardado.
function formularioCliente(fiscales, grupos, cliente, alGuardar, alCancelar) {
    const cuitDoc = fiscales.documentos.find(d => normalTexto(d.descripcion) === 'cuit');
    const selDoc = el('select', { name: 'doc_tipo', required: true }, fiscales.documentos.map(d =>
        el('option', { value: d.codigo, selected: cliente ? String(cliente.doc_tipo) === d.codigo : (cuitDoc && d.codigo === cuitDoc.codigo) }, d.descripcion)));
    const nro = el('input', { name: 'doc_nro', required: true, maxlength: 13, inputmode: 'numeric', value: cliente ? cliente.doc_nro : '' });
    const nombre = el('input', { name: 'nombre', required: true, maxlength: 200, value: cliente ? cliente.nombre : '' });
    const selCondicion = el('select', { name: 'condicion_iva', required: true }, fiscales.condiciones.map(c =>
        el('option', { value: c.codigo, selected: cliente ? String(cliente.condicion_iva) === c.codigo : false }, c.descripcion)));
    const domicilio = el('input', { name: 'domicilio', maxlength: 300, value: cliente ? cliente.domicilio : '' });
    const email = el('input', { name: 'email', type: 'email', maxlength: 200, value: cliente ? cliente.email : '' });
    const selGrupo = el('select', { name: 'grupo_id' }, el('option', { value: '' }, 'Sin grupo'),
        grupos.map(g => el('option', { value: g.id, selected: cliente ? cliente.grupo_id === g.id : false }, g.nombre)));
    const activo = el('input', { type: 'checkbox', name: 'activo', checked: cliente ? cliente.activo : true });
    const guardar = el('button', { type: 'submit' }, cliente ? 'Guardar cambios' : 'Crear cliente');
    const cancelar = el('button', { type: 'button', class: 'secundario' }, 'Cancelar');
    cancelar.addEventListener('click', () => alCancelar && alCancelar());
    const avisoArca = el('div', {});
    const buscarArca = el('button', { type: 'button', class: 'secundario' }, 'Buscar en ARCA');
    buscarArca.addEventListener('click', async () => {
        const datos = await conBoton(buscarArca, () => api('/api/padron/' + encodeURIComponent(nro.value.replace(/\D/g, ''))));
        if (!datos) return;
        vaciar(avisoArca);
        if (datos.cliente_existente && !cliente) {
            avisoArca.append(el('p', { class: 'aviso-form error' }, 'Ese CUIT ya está cargado como cliente: buscalo en la lista.'));
            return;
        }
        if (datos.doc_tipo) selDoc.value = String(datos.doc_tipo);
        if (datos.nombre) nombre.value = datos.nombre;
        if (datos.domicilio) domicilio.value = datos.domicilio;
        if (datos.condicion_sugerida) selCondicion.value = String(datos.condicion_sugerida);
        form._origen = 'arca';
        const detalle = [];
        if (datos.estado_clave) detalle.push('Clave ' + datos.estado_clave);
        if (datos.monotributo) detalle.push('Monotributo: ' + datos.monotributo);
        const iva = datos.impuestos.filter(i => i.id === '30');
        if (iva.length) detalle.push('IVA: ' + iva.map(i => i.estado).join(', '));
        if (datos.actividad) detalle.push('Actividad: ' + datos.actividad);
        avisoArca.append(el('div', { class: 'aviso-form' },
            el('strong', {}, 'Datos de ARCA cargados. Revisalos y confirmá la condición frente al IVA antes de guardar.'),
            detalle.length ? el('div', { class: 'sub' }, detalle.join(' · ')) : null,
            datos.condicion_sugerida ? null : el('div', { class: 'sub' }, 'ARCA no permite deducir la condición frente al IVA con seguridad: elegila vos.'),
            ...datos.errores.map(e => el('div', { class: 'sub' }, 'ARCA: ' + e))));
    });
    const form = el('form', { class: 'form-cliente' },
        avisoArca,
        el('div', { class: 'grilla-form' },
            el('label', {}, 'Tipo de documento', selDoc),
            el('label', {}, 'Número', el('div', { class: 'fila-form' }, nro, buscarArca)),
            el('label', {}, 'Nombre o razón social', nombre), el('label', {}, 'Condición frente al IVA', selCondicion),
            el('label', {}, 'Domicilio', domicilio), el('label', {}, 'Email', email), el('label', {}, 'Grupo', selGrupo)),
        cliente ? el('label', { class: 'casilla' }, activo, 'Activo') : null,
        el('div', { class: 'acciones' }, guardar, alCancelar ? cancelar : null));
    form._origen = 'manual';
    form._campos = { selDoc, nro, nombre, selCondicion, domicilio, avisoArca };
    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const cuerpo = { doc_tipo: Number(selDoc.value), doc_nro: nro.value, nombre: nombre.value,
            condicion_iva: Number(selCondicion.value), domicilio: domicilio.value, email: email.value,
            grupo_id: selGrupo.value || null, origen: form._origen };
        if (cliente) cuerpo.activo = activo.checked;
        const r = await conBoton(guardar, () => api(cliente ? '/api/clientes/' + encodeURIComponent(cliente.id) : '/api/clientes',
            { method: cliente ? 'PUT' : 'POST', body: cuerpo }));
        if (r) { mostrarMensaje(cliente ? 'Cliente guardado.' : 'Cliente creado.', 'ok'); alGuardar(r); }
    });
    return form;
}

// ===== Pantalla Clientes =====
async function vistaClientes(contenedor) {
    const vigente = redibujar(contenedor);
    let fiscales, grupos;
    try {
        [fiscales, grupos] = await Promise.all([opcionesFiscales(), api('/api/grupos-clientes')]);
    } catch (e) {
        if (vigente()) contenedor.append(el('div', { class: 'tarjeta' }, el('p', { class: 'ayuda' }, e.message)));
        return;
    }
    if (!vigente()) return;
    const condicion = codigo => (fiscales.condiciones.find(c => c.codigo === String(codigo)) || {}).descripcion || codigo;
    const documento = codigo => (fiscales.documentos.find(d => d.codigo === String(codigo)) || {}).descripcion || codigo;
    const puedeEditar = emite();

    const zonaForm = el('div', {});
    const buscador = el('input', { type: 'search', placeholder: 'Buscar por nombre o número de documento', 'aria-label': 'Buscar cliente', maxlength: 100 });
    const inactivos = el('input', { type: 'checkbox' });
    const cuerpo = el('tbody');
    const nuevo = el('button', { type: 'button' }, 'Nuevo cliente');
    nuevo.addEventListener('click', () => abrirForm(null));

    function abrirForm(cliente) {
        vaciar(zonaForm).append(el('div', { class: 'tarjeta' }, el('h2', {}, cliente ? 'Editar cliente' : 'Nuevo cliente'),
            formularioCliente(fiscales, grupos, cliente, () => { vaciar(zonaForm); buscar(); }, () => vaciar(zonaForm))));
        zonaForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    let espera = null;
    async function buscar() {
        let lista;
        try {
            lista = await api('/api/clientes?limite=100&q=' + encodeURIComponent(buscador.value) + (inactivos.checked ? '&incluir_inactivos=true' : ''));
        } catch (e) { mostrarMensaje(e.message, 'error'); return; }
        vaciar(cuerpo);
        if (!lista.length) cuerpo.append(el('tr', {}, el('td', { colspan: 5, class: 'vacio' }, 'No hay clientes que coincidan.')));
        for (const c of lista) {
            const fila = el('tr', { class: puedeEditar ? 'seleccionable' : '' },
                el('td', {}, c.nombre, c.grupo ? el('div', { class: 'sub' }, 'Grupo: ' + c.grupo) : null),
                el('td', { class: 'mono sin-corte' }, documento(c.doc_tipo) + ' ' + c.doc_formateado),
                el('td', {}, condicion(c.condicion_iva)),
                el('td', {}, c.domicilio),
                el('td', {}, !c.activo ? el('span', { class: 'etiqueta' }, 'Inactivo')
                    : c.origen === 'arca' ? el('span', { class: 'etiqueta acento' }, 'Datos de ARCA')
                    : el('span', { class: 'etiqueta ok' }, 'Activo')));
            if (puedeEditar) fila.addEventListener('click', () => abrirForm(c));
            cuerpo.append(fila);
        }
    }
    buscador.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(buscar, 250); });
    inactivos.addEventListener('change', buscar);

    // Grupos economicos
    const listaGrupos = el('div', { class: 'acciones' });
    const pintarGrupos = () => vaciar(listaGrupos).append(...(grupos.length
        ? grupos.map(g => el('span', { class: 'etiqueta' }, `${g.nombre} (${g.clientes})`))
        : [el('span', { class: 'ayuda' }, 'Sin grupos.')]));
    const nombreGrupo = el('input', { maxlength: 120, placeholder: 'Nombre del grupo', 'aria-label': 'Nombre del grupo' });
    const formGrupo = el('form', { class: 'fila-form' }, nombreGrupo, el('button', { type: 'submit', class: 'secundario' }, 'Crear grupo'));
    formGrupo.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const g = await conBoton(formGrupo.querySelector('button'), () => api('/api/grupos-clientes', { method: 'POST', body: { nombre: nombreGrupo.value } }));
        if (g) { grupos.push(g); nombreGrupo.value = ''; pintarGrupos(); }
    });
    pintarGrupos();

    contenedor.append(
        el('div', { class: 'tarjeta' },
            el('div', { class: 'titulo-tarjeta' }, el('h2', {}, 'Clientes'), puedeEditar ? nuevo : null),
            el('p', { class: 'ayuda' }, 'Los clientes se comparten entre todas las razones sociales. Sus comprobantes siguen separados por razón social.'),
            el('div', { class: 'fila-form' }, buscador, el('label', { class: 'casilla' }, inactivos, 'Incluir inactivos')),
            el('div', { class: 'tabla-scroll' }, el('table', {},
                el('thead', {}, el('tr', {}, el('th', {}, 'Nombre'), el('th', {}, 'Documento'), el('th', {}, 'Condición IVA'),
                    el('th', {}, 'Domicilio'), el('th', {}, 'Estado'))), cuerpo))),
        zonaForm,
        el('div', { class: 'tarjeta' }, el('h2', {}, 'Grupos económicos'),
            el('p', { class: 'ayuda' }, 'Agrupan clientes que son del mismo comprador (por ejemplo, varias razones sociales de una misma empresa).'),
            listaGrupos, puedeEditar ? formGrupo : null));
    await buscar();
}
