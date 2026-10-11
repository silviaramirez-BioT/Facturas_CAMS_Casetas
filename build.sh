#!/usr/bin/env bash
set -e

# =============================================================
# Compilador del Facturador CAMS (PyInstaller)
# =============================================================
# Genera un ejecutable standalone con el .env EMBEBIDO dentro.
# Multiplataforma: Linux, macOS y Windows (Git Bash / WSL).
#
# Cada build es para un único cliente: edita .env y vuelve a
# ejecutar este script para cambiar de cliente.
#
# Salida:
#   Windows: facturas_cams.exe
#   Linux/macOS: facturas_cams.bin
# =============================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=================================================================="
echo "  COMPILADOR — Facturador CAMS (PyInstaller)"
echo "=================================================================="
echo "  El archivo .env actual se EMBEBE dentro del ejecutable."
echo "  Cada build es para un único cliente."
echo ""

# 1) Detectar Python
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
elif command -v py &> /dev/null; then
    PYTHON_CMD=py
else
    echo "[ERROR] No se encontró Python en el PATH."
    echo "Instala Python 3.10+ desde https://www.python.org/downloads/"
    exit 1
fi

echo "[INFO] Usando Python: $($PYTHON_CMD --version)"

# 1b) Limpiar artefactos de builds previos (PyInstaller)
echo "[0/4] Limpiando artefactos de builds anteriores..."
rm -rf build dist *.spec 2>/dev/null || true

# 2) Crear/activar venv
if [ ! -d ".venv" ]; then
    echo "[1/4] Creando entorno virtual (.venv)..."
    $PYTHON_CMD -m venv .venv
fi

if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
    PYTHON_CMD=python
elif [ -f ".venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source ".venv/Scripts/activate"
    PYTHON_CMD=python
fi

# 3) Instalar dependencias + PyInstaller
echo "[2/4] Instalando dependencias y PyInstaller..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
python -m pip install pyinstaller --quiet

# 4) Verificar .env
if [ ! -f ".env" ]; then
    echo ""
    echo "[ADVERTENCIA] No se encontró archivo .env."
    echo "Copiando .env.example como .env — edítalo con datos reales."
    cp .env.example .env
    echo ""
fi

# 5) Detectar SO y ajustar separador de --add-data y nombre de salida
case "$OSTYPE" in
    msys*|cygwin*|win32*|mingw*)
        SEP=";"
        OUTPUT_NAME="facturas_cams.exe"
        ;;
    *)
        SEP=":"
        OUTPUT_NAME="facturas_cams.bin"
        ;;
esac

# Incluir tickets.txt solo si existe
EXTRA_DATA=()
if [ -f "tickets.txt" ]; then
    EXTRA_DATA+=(--add-data "tickets.txt${SEP}.")
fi

echo "[3/4] Compilando con PyInstaller (puede tardar 1-3 min)..."
echo "      Incluye Chromium/Chrome, NiceGUI, .env embebido."

python -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --console \
    --name facturas_cams \
    --add-data ".env${SEP}." \
    --add-data ".env.example${SEP}." \
    "${EXTRA_DATA[@]}" \
    --collect-all nicegui \
    --collect-all selenium \
    --collect-all dotenv \
    --hidden-import webview \
    --hidden-import urllib3 \
    --hidden-import websocket \
    --hidden-import pywebview \
    facturas_cams.py

# 6) Mover el binario desde dist/ a la raíz con el nombre final
if [ -f "dist/facturas_cams.exe" ]; then
    mv -f "dist/facturas_cams.exe" "$OUTPUT_NAME"
elif [ -f "dist/facturas_cams" ]; then
    mv -f "dist/facturas_cams" "$OUTPUT_NAME"
fi

echo ""
echo "=================================================================="
echo "  ¡COMPILACIÓN EXITOSA!"
echo "  Ejecutable generado: $DIR/$OUTPUT_NAME"
echo "=================================================================="
echo ""
echo "  El archivo .env ya está EMBEBIDO dentro del binario."
echo "  Para cambiar de cliente:"
echo "      1) Edita .env con los nuevos datos"
echo "      2) Ejecuta 'bash build.sh' de nuevo"
echo "      3) Envía el nuevo $OUTPUT_NAME"
echo "=================================================================="