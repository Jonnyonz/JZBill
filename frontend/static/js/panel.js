// Panel (Fase 0): usuario en sesion, cambio de contraseña y cierre de sesiones.
'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const yo = await api('/api/auth/me');
        // textContent: nunca se inserta HTML con datos que vienen de la base.
        document.getElementById('usuario').textContent = yo.nombre || yo.usuario;
    } catch (e) {
        return;   // api() ya redirige al ingreso si la sesion vencio
    }

    document.getElementById('salir').addEventListener('click', async () => {
        try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) { /* se va igual */ }
        window.location.href = '/';
    });

    document.getElementById('cerrar-todas').addEventListener('click', async () => {
        if (!window.confirm('Se va a cerrar la sesión en todos los dispositivos. ¿Continuar?')) return;
        try { await api('/api/auth/sesiones/cerrar', { method: 'POST' }); } catch (e) { /* se va igual */ }
        window.location.href = '/';
    });

    const formClave = document.getElementById('form-clave');
    formClave.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const nueva = document.getElementById('clave-nueva').value;
        if (nueva !== document.getElementById('clave-repetida').value) {
            mostrarMensaje('Las dos contraseñas nuevas no coinciden.', 'error');
            return;
        }
        const boton = formClave.querySelector('button');
        boton.disabled = true;
        try {
            const r = await api('/api/auth/clave', { method: 'POST', body: {
                clave_actual: document.getElementById('clave-actual').value,
                clave_nueva: nueva,
            } });
            formClave.reset();
            mostrarMensaje(r.mensaje, 'ok');
        } catch (e) {
            mostrarMensaje(e.message, 'error');
        } finally {
            boton.disabled = false;
        }
    });
});
