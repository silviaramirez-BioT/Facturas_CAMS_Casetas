#!/usr/bin/env bash
set -e

# =============================================================
# Lanzador del Facturador CAMS (modo código fuente)
# =============================================================
# Crea/activa el venv, instala dependencias y ejecuta la app.
# Multiplataforma: Linux, macOS y Windows (Git Bash / WSL).
# =============================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=================================================================="
echo "  Facturador CAMS — Lanzador desde código fuente"
echo "=================================================================="

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

# 2) Crear/activar venv
if [ ! -d ".venv" ]; then
    echo "[1/3] Creando entorno virtual (.venv)..."
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

# 3) Instalar dependencias (solo si faltan)
echo "[2/3] Verificando dependencias..."
if ! python -c "import nicegui, selenium, dotenv" 2>/dev/null; then
    echo "      Instalando requirements..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt
fi

# 4) Verificar .env
if [ ! -f ".env" ]; then
    echo ""
    echo "[ADVERTENCIA] No se encontró archivo .env."
    echo "Copiando .env.example como .env (debes editarlo con datos reales)."
    cp .env.example .env
    echo ""
fi

# 5) Ejecutar
echo "[3/3] Iniciando aplicación..."
echo "      (cierra la ventana o Ctrl+C para salir)"
echo ""
exec python facturas_cams.py "$@"