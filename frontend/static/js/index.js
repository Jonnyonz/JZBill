// Pantalla de ingreso: alta del primer administrador o login.
'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    const formLogin = document.getElementById('form-login');
    const formSetup = document.getElementById('form-setup');
    try {
        const estado = await api('/api/auth/setup/status');
        (estado.needs_setup ? formSetup : formLogin).classList.remove('oculto');
    } catch (e) {
        mostrarMensaje('No se pudo conectar con el servicio.', 'error');
        return;
    }

    formLogin.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const boton = formLogin.querySelector('button');
        boton.disabled = true;
        try {
            await api('/api/auth/login', { method: 'POST', body: {
                usuario: document.getElementById('login-usuario').value,
                clave: document.getElementById('login-clave').value,
            } });
            window.location.href = '/panel';
        } catch (e) {
            mostrarMensaje(e.message, 'error');
        } finally {
            boton.disabled = false;
        }
    });

    formSetup.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const boton = formSetup.querySelector('button');
        boton.disabled = true;
        try {
            await api('/api/auth/setup/admin', { method: 'POST', body: {
                token: document.getElementById('setup-token').value,
                usuario: document.getElementById('setup-usuario').value,
                nombre: document.getElementById('setup-nombre').value,
                clave: document.getElementById('setup-clave').value,
            } });
            window.location.href = '/panel';
        } catch (e) {
            mostrarMensaje(e.message, 'error');
        } finally {
            boton.disabled = false;
        }
    });
});
