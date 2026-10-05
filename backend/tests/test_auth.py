"""Login, logout, cambio de clave e invalidacion de sesiones (criterios de aceptacion de la Fase 0).
Necesitan la base de prueba: ver conftest.py."""

from conftest import SETUP_TOKEN, csrf

CLAVE = "clave-inicial-1"


def _login(cliente, usuario="admin", clave=CLAVE):
    return cliente.post("/api/auth/login", json={"usuario": usuario, "clave": clave})


def test_health_y_cabeceras(nuevo_cliente):
    c = nuevo_cliente()
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["schema_version"] >= 1
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_setup_inicial(nuevo_cliente):
    c = nuevo_cliente()
    assert c.get("/api/auth/setup/status").json() == {"needs_setup": True}
    malo = c.post("/api/auth/setup/admin", json={"token": "otro", "usuario": "x", "clave": "una-clave-larga"})
    assert malo.status_code == 403
    corta = c.post("/api/auth/setup/admin", json={"token": SETUP_TOKEN, "usuario": "x", "clave": "corta"})
    assert corta.status_code == 400
    ok = c.post("/api/auth/setup/admin", json={"token": SETUP_TOKEN, "usuario": " Admin ", "clave": CLAVE})
    assert ok.status_code == 200 and ok.json() == {"usuario": "admin"}
    assert c.get("/api/auth/me").json()["usuario"] == "admin"
    assert c.get("/api/auth/setup/status").json() == {"needs_setup": False}
    otra = nuevo_cliente().post("/api/auth/setup/admin", json={"token": SETUP_TOKEN, "usuario": "y", "clave": CLAVE})
    assert otra.status_code == 403


def test_cookies_de_sesion(admin):
    cookie = admin.cookies.jar
    sesion = next(k for k in cookie if k.name == "session_token")
    assert sesion.has_nonstandard_attr("HttpOnly")
    assert "csrf_token" in admin.cookies


def test_login_correcto_e_incorrecto(admin, nuevo_cliente):
    otro = nuevo_cliente()
    assert _login(otro, clave="clave-mal-1").status_code == 401
    assert _login(otro, usuario="nadie").status_code == 401
    assert otro.get("/api/auth/me").status_code == 401
    assert _login(otro).status_code == 200
    assert otro.get("/api/auth/me").status_code == 200


def test_escritura_sin_csrf_rechazada(admin):
    assert admin.post("/api/auth/logout").status_code == 403
    assert admin.post("/api/auth/logout", headers={"X-CSRF-Token": "x" * 64}).status_code == 403
    assert admin.get("/api/auth/me").status_code == 200   # sigue con sesion


def test_csrf_de_otra_sesion_no_sirve(admin, nuevo_cliente):
    otro = nuevo_cliente()
    assert _login(otro).status_code == 200
    assert admin.post("/api/auth/logout", headers=csrf(otro)).status_code == 403


def test_logout_invalida_el_token(admin):
    token = admin.cookies.get("session_token")
    assert admin.post("/api/auth/logout", headers=csrf(admin)).status_code == 200
    assert admin.get("/api/auth/me").status_code == 401
    # Aunque alguien hubiera copiado la cookie, el token ya no vale.
    admin.cookies.set("session_token", token)
    assert admin.get("/api/auth/me").status_code == 401


def test_cambio_de_clave_cierra_las_otras_sesiones(admin, nuevo_cliente):
    otro = nuevo_cliente()
    assert _login(otro).status_code == 200
    mala = admin.post("/api/auth/clave", headers=csrf(admin), json={"clave_actual": "no-es", "clave_nueva": "nueva-clave-22"})
    assert mala.status_code == 400
    igual = admin.post("/api/auth/clave", headers=csrf(admin), json={"clave_actual": CLAVE, "clave_nueva": CLAVE})
    assert igual.status_code == 400
    ok = admin.post("/api/auth/clave", headers=csrf(admin), json={"clave_actual": CLAVE, "clave_nueva": "nueva-clave-22"})
    assert ok.status_code == 200
    assert admin.get("/api/auth/me").status_code == 200      # este dispositivo sigue (sesion nueva)
    assert otro.get("/api/auth/me").status_code == 401       # el otro quedo afuera
    tercero = nuevo_cliente()
    assert _login(tercero).status_code == 401
    assert _login(tercero, clave="nueva-clave-22").status_code == 200


def test_cerrar_todas_las_sesiones(admin, nuevo_cliente):
    otro = nuevo_cliente()
    assert _login(otro).status_code == 200
    assert admin.post("/api/auth/sesiones/cerrar", headers=csrf(admin)).status_code == 200
    assert admin.get("/api/auth/me").status_code == 401
    assert otro.get("/api/auth/me").status_code == 401


def test_usuario_desactivado_pierde_la_sesion(admin, ejecutar_sql):
    ejecutar_sql("UPDATE usuarios SET activo = false WHERE usuario = 'admin'")
    assert admin.get("/api/auth/me").status_code == 401
    assert _login(admin).status_code == 401


def test_limite_de_intentos(admin, nuevo_cliente):
    otro = nuevo_cliente()
    for _ in range(5):
        assert _login(otro, clave="clave-mal-1").status_code == 401
    # Bloqueado: ni con la clave correcta.
    assert _login(otro).status_code == 429


def test_limite_por_ip_con_usuarios_distintos(admin, nuevo_cliente):
    otro = nuevo_cliente()
    for i in range(20):
        assert _login(otro, usuario=f"nadie{i}").status_code == 401
    assert _login(otro).status_code == 429


def test_clave_demasiado_larga_rechazada(admin):
    assert _login(admin, clave="x" * 129).status_code == 422


def test_auditoria_registra_sin_secretos(admin, ejecutar_sql):
    _login(admin, clave="clave-mal-1")
    filas = ejecutar_sql("SELECT accion, detalle FROM auditoria ORDER BY id")
    acciones = [f["accion"] for f in filas]
    assert "SETUP_ADMIN" in acciones and "LOGIN_FALLIDO" in acciones
    texto = " ".join(f["detalle"] for f in filas)
    assert CLAVE not in texto and "clave-mal-1" not in texto and SETUP_TOKEN not in texto
