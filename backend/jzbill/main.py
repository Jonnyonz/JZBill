from jztech_core.logging_setup import configure_logging, install_generic_error_handler

configure_logging()

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jztech_core.security_headers import SecurityHeadersMiddleware

from jzbill import __version__, auditoria, auth, certificados, contexto, db, razones_sociales, usuarios

logger = logging.getLogger(__name__)

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

# CSP estricta desde el primer dia: sin JavaScript ni estilos inline (todo en archivos de frontend/).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

# Rutas publicas a proposito (sin sesion). Toda otra ruta exige require_usuario: lo verifica
# el test de deny-by-default (fuera del repo publico). Las paginas HTML son publicas pero no traen datos: los piden a la API.
RUTAS_PUBLICAS = [
    "/",
    "/panel",
    "/api/health",
    "/api/auth/setup/status",
    "/api/auth/setup/admin",
    "/api/auth/login",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.iniciar()
    logger.info(f"JZBill {__version__} iniciado.")
    yield
    await db.cerrar()


# Sin documentacion interactiva publica: el mapa de la API no se expone.
app = FastAPI(title="JZBill", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
install_generic_error_handler(app, "jzbill", field="detail")
app.add_middleware(SecurityHeadersMiddleware, csp=CSP, permissions_policy="geolocation=(), microphone=(), camera=()")

app.include_router(auth.router)
app.include_router(contexto.router)
app.include_router(razones_sociales.router)
app.include_router(certificados.router)
app.include_router(usuarios.router)
app.include_router(auditoria.router)


@app.get("/api/health")
async def health(conn=Depends(db.get_conn)):
    """Para el chequeo del instalador y del actualizador: la app responde y la base tambien."""
    version_esquema = await conn.fetchval("SELECT COALESCE(MAX(version), 0) FROM schema_version")
    return {"status": "ok", "version": __version__, "schema_version": version_esquema}


@app.get("/")
async def pagina_inicio():
    return FileResponse(FRONTEND / "index.html")


@app.get("/panel")
async def pagina_panel():
    return FileResponse(FRONTEND / "panel.html")


app.mount("/static", StaticFiles(directory=FRONTEND / "static"), name="static")
