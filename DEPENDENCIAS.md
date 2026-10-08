# JZBill - Dependencias y su justificación

Regla (CLAUDE.md): cada dependencia nueva se justifica por escrito: qué resuelve, por qué no alcanza la
biblioteca estándar y que exista como wheel precompilada (en el servidor no hay compilador).
Versiones exactas en `requirements.in`; lockfile con hashes en `requirements.txt`.

## Producción (`requirements.in`)

Mismo set común que JZ_Middle_ML-Tracker, sin `httpx` (en la Fase 0 la app no hace llamadas HTTP salientes).

| Paquete | Versión | Qué resuelve | Por qué no la stdlib | Wheel |
|---|---|---|---|---|
| fastapi | 0.141.1 | Rutas, validación de entrada y dependencias (autenticación por dependencia, verificada por el test deny-by-default) | Mismo framework que toda la Suite y que jztech-core | Python puro |
| uvicorn | 0.54.0 | Servidor ASGI que corre bajo systemd | La stdlib no trae servidor ASGI | Python puro |
| pydantic | 2.13.5 | Validación de los cuerpos JSON (largos máximos, tipos) | Lo exige fastapi | pydantic-core: wheel manylinux |
| asyncpg | 0.31.0 | Cliente PostgreSQL asíncrono, SQL parametrizado a mano | La stdlib no trae cliente PostgreSQL; jztech-core lo asume | wheel manylinux |
| cryptography | 50.0.2 | Cifrado en reposo de secretos (certificados y claves de ARCA, clave SMTP) con AES-256-GCM, y lectura de certificados X.509 | La stdlib no trae AES ni parser X.509; escribir criptografía propia está descartado. Es la librería estándar de facto (PyCA) | wheel abi3 manylinux (x86_64 y aarch64), glibc 2.34+: Debian 12/13 y Ubuntu 24.04. Reusa `cffi`. Se importa solo al usar un secreto, no en el arranque |
| segno | 1.6.6 | Código QR del comprobante impreso (especificación de ARCA), como SVG | La stdlib no codifica QR; escribir el codificador (Reed-Solomon, máscaras) es mucho código para mantener. Aprobada por Jonny el 2026-10-08. Licencia BSD, estable, sin dependencias en Python 3.10+, sin vulnerabilidades conocidas (OSV) | Python puro (`py3-none-any`) |
| jztech-core | 0.1.5 | Argon2id, sesiones opacas, CSRF, cabeceras, IP real, migraciones, logging | Librería propia de la Suite | Python puro (release de GitHub, con hash) |

Transitivas relevantes: `argon2-cffi` + `argon2-cffi-bindings` + `cffi` (vía jztech-core, wheels
manylinux), `starlette` 1.7.0 (vía fastapi).

## Desarrollo y CI (`requirements-dev.in`, no se instalan en el servidor)

| Paquete | Versión | Uso |
|---|---|---|
| pytest | 9.1.1 | Tests |
| httpx | 0.28.1 | Lo pide `fastapi.testclient.TestClient` |
| pip-audit | 2.10.1 | Auditoría de vulnerabilidades al cierre de cada fase |

## Pendientes de evaluar (no agregadas)

- Cliente ARCA (WSAA/WSFEv1): PyAfipWs o cliente propio. Decisión pendiente antes de la Fase 2.
- Generación de PDF con QR (Fase 3).
