# Imagen de JZBill para la instalacion con Docker (install-docker.sh + compose.yml). La instalacion nativa
# (install-native.sh) sigue siendo la recomendada para equipos con pocos recursos.
#
# Mismas reglas que la nativa: Python 3.11 (el piso soportado, el mismo con el que se genera el lockfile),
# dependencias solo como wheels y verificando los hashes de requirements.txt, sin compilador. La imagen no lleva
# secretos: la configuracion, la clave maestra y el certificado HTTPS se montan al correr (ver compose.yml).
FROM python:3.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JZB_INSTALACION=docker

WORKDIR /app

COPY requirements.txt .
# setuptools y wheel vienen con la imagen base y la app no los usa: fuera (menos superficie, pip-audit limpio).
RUN pip install --require-hashes --only-binary=:all: -r requirements.txt \
    && pip uninstall -y setuptools wheel

COPY backend/jzbill backend/jzbill
COPY db db
COPY frontend frontend

# Usuario sin privilegios y sin shell. El codigo es de root: la app solo lo lee.
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin jzbill
USER 10001:10001

# HTTPS propio (sin proxy). El chequeo es local: no valida el certificado, solo que la app responda.
EXPOSE 9443
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import ssl, urllib.request; urllib.request.urlopen('https://127.0.0.1:9443/api/health', timeout=4, context=ssl._create_unverified_context())"]

CMD ["uvicorn", "jzbill.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "9443", \
     "--ssl-certfile", "/run/secrets/tls_cert", "--ssl-keyfile", "/run/secrets/tls_key", \
     "--workers", "1", "--no-proxy-headers", "--no-server-header"]
