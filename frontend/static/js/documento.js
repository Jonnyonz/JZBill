// Paginas de texto (privacidad y terminos): Volver va a la pantalla anterior si la hay y, si la pagina se abrio
// suelta, al inicio. Esc hace lo mismo. Va en archivo aparte porque la CSP no permite scripts en linea.
function volver(ev) {
    if (ev) ev.preventDefault();
    if (history.length > 1) history.back(); else location.href = '/';
}
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-volver]').forEach(e => e.addEventListener('click', volver));
});
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') volver(); });
