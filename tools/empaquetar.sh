#!/bin/bash
# Arma el paquete de una version para publicarlo en GitHub Releases (lo descarga jz-bill-actualizar):
#   dist/jz-bill-<version>.tar.gz          contenido del commit actual (git archive), carpeta jz-bill-<version>/
#   dist/jz-bill-<version>.tar.gz.sha256   hash para verificarlo (formato de sha256sum)
# Correr desde la raiz del repo, con el arbol limpio y la version ya subida en backend/jzbill/__init__.py:
#   tools/empaquetar.sh
#   gh release create v<version> dist/jz-bill-<version>.tar.gz dist/jz-bill-<version>.tar.gz.sha256 --notes-file ...
# El paquete no lleva tests, docs ni CLAUDE.md (no estan en git).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' backend/jzbill/__init__.py | tr -d '\r')"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Version invalida en backend/jzbill/__init__.py" >&2; exit 1; }
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Hay cambios sin commitear: el paquete tiene que salir de un commit." >&2
  exit 1
fi
mkdir -p dist
NOMBRE="jz-bill-$VERSION.tar.gz"
git archive --format=tar.gz --prefix="jz-bill-$VERSION/" -o "dist/$NOMBRE" HEAD
(cd dist && sha256sum "$NOMBRE" > "$NOMBRE.sha256")
echo "Listo: dist/$NOMBRE ($(git rev-parse --short HEAD))"
cat "dist/$NOMBRE.sha256"
