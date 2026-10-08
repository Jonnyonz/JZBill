// Tema claro u oscuro, igual que el resto de JZTech Suite: atributo data-theme en <html> y la misma clave de
// localStorage (jztech-theme), asi el tema elegido se comparte. Sin eleccion guardada, sigue al sistema.
// Se carga en el <head> (sin defer) para que la pagina no aparezca un instante con el tema equivocado.
'use strict';

(function () {
    let tema = null;
    try { tema = localStorage.getItem('jztech-theme'); } catch (e) { /* almacenamiento bloqueado: sigue al sistema */ }
    if (tema !== 'dark' && tema !== 'light') {
        tema = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    document.documentElement.setAttribute('data-theme', tema);
})();

function alternarTema() {
    const nuevo = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', nuevo);
    try { localStorage.setItem('jztech-theme', nuevo); } catch (e) { /* se aplica igual, sin recordarlo */ }
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-alternar-tema]').forEach(b => b.addEventListener('click', alternarTema));
});
