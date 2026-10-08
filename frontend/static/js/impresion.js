// Boton de la pagina de impresion del comprobante (CSP: sin manejadores inline).
'use strict';

document.addEventListener('DOMContentLoaded', () => {
    const boton = document.getElementById('imprimir');
    if (boton) boton.addEventListener('click', () => window.print());
});
