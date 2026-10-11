# Facturación Automática de Casetas CAMS (Diverza)

Aplicación que automatiza la consulta, generación y descarga de facturas
(**XML** y **PDF**) desde el portal de casetas CAMS de Diverza a partir de
una lista de tickets en texto plano. Usa **Chromium/Chrome** mediante
**Selenium** y una GUI de escritorio con **NiceGUI**.

Los datos fiscales del cliente (RFC, razón social, CP, correo) se cargan
desde un archivo `.env`. Cada `.exe` se compila con su propio `.env`
embebido, de modo que un build es para un único cliente.

---

## 📋 Requisitos

1. **Sistema operativo:** Windows 10/11, Linux o macOS.
2. **Navegador:** Chromium o Google Chrome instalado (Selenium 4 lo
   detecta). No se necesita Firefox.
3. **Para ejecutar desde código fuente:** Python 3.10+ y Bash.
4. **Para generar el .exe con Nuitka:** compilador C (gcc, MSVC o
   Visual Studio Build Tools en Windows).

> **En Windows** los scripts `.sh` funcionan con **Git Bash** o **WSL**.
> Si usas PowerShell/CMD nativo, ejecuta el comando crudo equivalente
> que aparece en cada sección.

---

## ⚙️ Configuración previa (datos del cliente)

1. Copia `.env.example` como `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edita `.env` y rellena los datos fiscales reales del cliente:

```
FACTURACION_RFC=           # RFC del cliente
FACTURACION_NOMBRE=        # Razón social
FACTURACION_CP=            # Código postal fiscal
FACTURACION_REGIMEN=       # 601 (General PM) por defecto
FACTURACION_USO_CFDI=      # G03 (Gastos en general) por defecto
FACTURACION_EMAIL=         # Correo receptor de las facturas
```

> ⚠️ **Importante:** `.env` contiene datos sensibles y **NO debe subirse al
> repositorio** (ya está excluido en `.gitignore`).

---

## 🚀 Ejecutar desde código fuente

### Con el script
```bash
bash run.sh
```

### Comando directo (sin script)
```bash
python3 -m venv .venv
source .venv/bin/activate    # Linux/macOS
# o:  .venv\Scripts\activate   # Git Bash en Windows
pip install -r requirements.txt
python facturas_cams.py
```

> `run.sh` crea el venv, instala dependencias y lanza la app automáticamente.

---

## 📝 Formato del archivo de tickets

Crea un archivo `tickets.txt` con un ticket por línea. Separadores
aceptados: coma, punto y coma, tabulación o espacios.

**Formato:** `NUMERO_DE_TICKET, FECHA (DD/MM/AAAA), COSTO`

```text
# Ejemplos válidos (descomenta para probar):
02052267371268253513, 07/09/2026, 103
14738911919617451912, 08/09/2026, $103.00
10442482273152509895; 09/09/2026; 103
01480323412731734018 | 10/09/2026 | 103
```

> Las líneas vacías o que inicien con `#` o `//` se ignoran.

Las facturas generadas se guardan automáticamente como `Factura_<folio>.xml`
y `Factura_<folio>.pdf` en la carpeta de destino.

---

## 🔨 Compilar el `.exe` (Modo A — .env embebido)

**Cada build se compila con un `.env` distinto (un cliente por build).**

### Con el script (Nuitka — recomendado)
```bash
bash build.sh
```

Nuitka compila Python → C → binario nativo:
- Arranque más rápido
- Binario más difícil de decompilar (protege los datos fiscales embebidos)
- Salida en la **raíz del proyecto**:
  - Windows → `facturas_cams.exe`
  - Linux/macOS → `facturas_cams.bin`

> El script **borra automáticamente** los artefactos temporales de
> Nuitka (`*.dist/`, `*.build/`, `*.onefile-build/`) al inicio de cada
> build. Si ves esos directorios tras un build fallido, puedes
> eliminarlos manualmente — son solo caché.

### Comando directo Nuitka
```bash
pip install -r requirements.txt nuitka ordered-set
python -m nuitka \
    --standalone --onefile \
    --output-filename=facturas_cams.exe \
    --include-data-file=.env=.env \
    --include-data-file=tickets.txt=tickets.txt \
    --include-package=nicegui \
    --include-package=selenium \
    --include-package=dotenv \
    --enable-plugin=anti-bloat \
    facturas_cams.py
```

### Alternativa: PyInstaller (si no tienes compilador C)
```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile \
    --name facturas_cams \
    --add-data ".env;." --add-data ".env.example;." \
    --add-data "tickets.txt;." \
    --collect-all nicegui --collect-all selenium --collect-all dotenv \
    facturas_cams.py
```

Salida: `dist/facturas_cams.exe`.

### Cambiar de cliente
1. Edita `.env` con los nuevos datos del cliente.
2. Ejecuta `bash build.sh` (o el comando Nuitka/PyInstaller).
3. Entrega el nuevo `.exe` al cliente.

### ⚠️ Sobre el `.exe` vs `.bin`
El script detecta el SO donde se ejecuta el build:
- **Corres en Windows** (Git Bash / WSL / nativo) → produces `.exe`
- **Corres en Linux/macOS** → produces `.bin` (binario ELF no ejecutable
  en Windows directamente)

Si necesitas un `.exe` para Windows pero solo tienes Linux, las opciones
son: ejecutar el build en una **VM Windows**, en **WSL**, o mediante
**Wine** (engorroso). No hay cross-compilation oficial.

---

## 🔒 Privacidad y datos sensibles

| Archivo               | ¿Se sube al repo? | Contenido                          |
|-----------------------|-------------------|------------------------------------|
| `facturas_cams.py`    | ✅ Sí             | Código fuente genérico             |
| `.env.example`        | ✅ Sí             | Plantilla con placeholders         |
| `tickets.example.txt` | ✅ Sí             | Plantilla de tickets con ejemplos  |
| `.env`                | ❌ No (.gitignore)| **Datos fiscales del cliente**     |
| `tickets.txt`         | ❌ No (.gitignore)| Tickets reales de casetas          |
| `Facturas_CAMS/`      | ❌ No (.gitignore)| Facturas generadas (datos reales)  |

El `.env` se embebe dentro del `.exe` durante la compilación.
Quien reciba el binario podrá usarlo, pero los datos quedan aislados
al `.exe` que se le entrega.

---

## ⚙️ Características

- **Multiplataforma:** Windows, Linux y macOS.
- **GUI nativa** con NiceGUI (sin navegador web).
- **Modo headless** (Chromium oculto) o visible para depurar.
- **Detección automática** de campos: reconoce folio, fecha y monto
  con `$`, decimales o formatos de fecha variables.
- **Re-descarga** automática si el ticket ya fue facturado previamente.
- **.env embebido**: cada build es independiente y portable.