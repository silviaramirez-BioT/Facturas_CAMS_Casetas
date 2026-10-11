#!/usr/bin/env python3
"""
Facturador Automático de Casetas CAMS (Diverza) con GUI.
Utiliza Chromium/Chrome y NiceGUI. Listo para empaquetar con PyInstaller.

Los datos fiscales del cliente (RFC, nombre, CP, email) se cargan desde
un archivo .env. Cada build (.exe) embebe su propio .env personalizado.
"""

import os
import sys
import re
import time
import ssl
import shutil
import asyncio
import subprocess
import multiprocessing
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    print("\n[ERROR] Falta python-dotenv. Instálalo con: pip install python-dotenv")
    sys.exit(1)

try:
    from nicegui import ui
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
except ModuleNotFoundError as e:
    print(f"\n[ERROR] Falta una dependencia requerida ({e.name}).")
    print("Instala las dependencias con: pip install -r requirements.txt")
    sys.exit(1)


# =============================================================
# CARGA DE CONFIGURACIÓN (.env)
# =============================================================
def _cargar_env():
    """Carga el .env desde la carpeta del .exe (cuando está congelado)
    o desde la carpeta del script (modo desarrollo)."""
    if getattr(sys, 'frozen', False):
        env_dir = os.path.dirname(sys.executable)
    else:
        env_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = Path(env_dir) / '.env'
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # Intentar junto al binario congelado (sys._MEIPASS)
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            alt = Path(meipass) / '.env'
            if alt.exists():
                load_dotenv(alt)


_cargar_env()


URL_PORTAL = "https://tickets.diverza.com/cams/facturar-ticket"

DATOS_FACTURACION = {
    'rfc':      os.getenv('FACTURACION_RFC', '').strip(),
    'nombre':   os.getenv('FACTURACION_NOMBRE', '').strip(),
    'cp':       os.getenv('FACTURACION_CP', '').strip(),
    'regimen':  os.getenv('FACTURACION_REGIMEN', '601').strip(),
    'uso_cfdi': os.getenv('FACTURACION_USO_CFDI', 'G03').strip(),
    'email':    os.getenv('FACTURACION_EMAIL', '').strip(),
}


def _validar_configuracion():
    """Verifica que los datos fiscales mínimos estén configurados."""
    campos_obligatorios = ('rfc', 'nombre', 'cp', 'email')
    faltantes = [c for c in campos_obligatorios if not DATOS_FACTURACION.get(c)]
    if faltantes:
        msg = (
            "\n[ERROR] Faltan datos de facturación en el archivo .env:\n"
            + "\n".join(f"  - FACTURACION_{c.upper()}" for c in faltantes)
            + "\n\nEdita el archivo .env junto al programa y completa los valores."
        )
        print(msg)
        try:
            input("\nPresiona Enter para salir...")
        except EOFError:
            pass
        sys.exit(1)


_validar_configuracion()


# =============================================================
# UTILIDADES
# =============================================================
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def normalize_date(date_str):
    date_str = date_str.strip().replace('-', '/')
    parts = date_str.split('/')
    if len(parts) == 3:
        if len(parts[0]) == 4:
            return f"{int(parts[2]):02d}/{int(parts[1]):02d}/{parts[0]}"
        return f"{int(parts[0]):02d}/{int(parts[1]):02d}/{int(parts[2])}"
    return date_str


def parse_tickets_text(text_data):
    tickets = []
    lines = text_data.strip().split('\n')
    for line in lines:
        clean_line = line.strip()
        if not clean_line or clean_line.startswith('#') or clean_line.startswith('//'):
            continue

        if ',' in clean_line:
            parts = [p.strip() for p in clean_line.split(',')]
        elif ';' in clean_line:
            parts = [p.strip() for p in clean_line.split(';')]
        elif '|' in clean_line:
            parts = [p.strip() for p in clean_line.split('|')]
        elif '\t' in clean_line:
            parts = [p.strip() for p in clean_line.split('\t')]
        else:
            parts = [p.strip() for p in re.split(r'\s{2,}', clean_line) if p.strip()]
            if len(parts) < 3:
                parts = [p.strip() for p in clean_line.split()]

        joined = " ".join(parts).lower()
        if any(h in joined for h in ['ticket', 'folio', 'fecha', 'costo']) and \
                not any(len(p) > 6 and p.isdigit() for p in parts):
            continue

        if len(parts) < 3:
            continue

        ticket_num, fecha, costo = "", "", ""
        remaining = []
        for p in parts:
            if re.search(r'\d{1,4}[/-]\d{1,2}[/-]\d{1,4}', p):
                fecha = normalize_date(p)
            else:
                remaining.append(p)

        if fecha and len(remaining) >= 2:
            for p in remaining:
                clean_cost = re.sub(r'[^\d.]', '', p)
                if clean_cost and (p.startswith('$') or '.' in p or
                                   (clean_cost.isdigit() and len(clean_cost) <= 6)):
                    costo = clean_cost
                else:
                    ticket_num = re.sub(r'[\s-]', '', p)

        if not (ticket_num and fecha and costo) and len(parts) >= 3:
            ticket_num = re.sub(r'[\s-]', '', parts[0])
            fecha = normalize_date(parts[1])
            costo = re.sub(r'[^\d.]', '', parts[2])

        if costo.endswith('.00'):
            costo = costo[:-3]
        elif costo.endswith('.0'):
            costo = costo[:-2]

        if ticket_num and fecha and costo:
            tickets.append({"numero": ticket_num, "fecha": fecha, "monto": costo})

    return tickets


# =============================================================
# DESCARGA
# =============================================================
def download_file(url, destination_path):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                               'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}
    )
    with urllib.request.urlopen(req, context=ctx) as response, open(destination_path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)


def extract_download_links(driver):
    """Extrae XML y PDF del modal de descarga (IDs xml_download / pdf_download)."""
    xml_url, pdf_url = None, None

    for el_id, target in [('xml_download', 'xml'), ('pdf_download', 'pdf')]:
        try:
            el = driver.find_element(By.ID, el_id)
            href = (el.get_attribute('href') or '').strip()
            if href and href != '#':
                if target == 'xml':
                    xml_url = href
                else:
                    pdf_url = href
        except Exception:
            pass

    if not xml_url or not pdf_url:
        for el in driver.find_elements(By.TAG_NAME, 'a'):
            try:
                href = (el.get_attribute('href') or '').strip()
                text = (el.text or '').lower()
                if not href or href == '#':
                    continue
                if 'xml' in href.lower() or 'xml' in text:
                    if not xml_url:
                        xml_url = href
                elif 'pdf' in href.lower() or 'pdf' in text:
                    if not pdf_url:
                        pdf_url = href
            except Exception:
                continue

    if not xml_url or not pdf_url:
        try:
            html = driver.page_source
            if not xml_url:
                m = re.search(r'https?://[^\s"\'<>]+\.xml[^\s"\'<>]*', html, re.I)
                if m:
                    xml_url = m.group(0)
            if not pdf_url:
                m = re.search(r'https?://[^\s"\'<>]+\.pdf[^\s"\'<>]*', html, re.I)
                if m:
                    pdf_url = m.group(0)
        except Exception:
            pass

    return xml_url, pdf_url


def wait_for_downloads(download_dir, initial_files, timeout=60, log_func=None):
    end = time.time() + timeout
    while time.time() < end:
        try:
            current = set(os.listdir(download_dir))
        except FileNotFoundError:
            time.sleep(1)
            continue
        new_files = current - initial_files
        partial = [f for f in new_files if f.endswith('.crdownload') or f.endswith('.tmp')]
        complete = [f for f in new_files if not (f.endswith('.crdownload') or f.endswith('.tmp'))]
        if partial and log_func:
            log_func(f"    (descargando {len(partial)} archivo(s)...)")
        if complete and not partial:
            return complete
        time.sleep(1)
    try:
        return [f for f in (set(os.listdir(download_dir)) - initial_files)
                if not f.endswith('.crdownload')]
    except FileNotFoundError:
        return []


def rename_downloaded_files(files, ticket_num, output_dir, log_func=None):
    renamed = []
    for f in files:
        src = os.path.join(output_dir, f)
        low = f.lower()
        if low.endswith('.xml'):
            dst = os.path.join(output_dir, f"Factura_{ticket_num}.xml")
        elif low.endswith('.pdf'):
            dst = os.path.join(output_dir, f"Factura_{ticket_num}.pdf")
        else:
            continue
        try:
            if os.path.exists(dst):
                os.remove(dst)
            os.rename(src, dst)
            renamed.append(dst)
            if log_func:
                log_func(f"    Guardado: {os.path.basename(dst)}")
        except Exception as e:
            if log_func:
                log_func(f"    [!] No se pudo renombrar {f}: {e}")
    return renamed


# =============================================================
# LLENADO DEL FORMULARIO DE FACTURACIÓN
# =============================================================
def _set_input(driver, input_id, value, log_func=None, label=''):
    """Escribe un valor en un input de texto por su ID."""
    try:
        el = driver.find_element(By.ID, input_id)
        el.clear()
        el.send_keys(value)
        if log_func and label:
            log_func(f"    {label}: {value}")
        return True
    except Exception as e:
        if log_func and label:
            log_func(f"    [!] No se pudo escribir {label}: {e}")
        return False


def _set_select(driver, select_id, value, log_func=None, label=''):
    """Selecciona una opción en un <select> por su ID usando el value del <option>."""
    try:
        el = driver.find_element(By.ID, select_id)
        sel = Select(el)
        sel.select_by_value(value)
        if log_func and label:
            log_func(f"    {label}: {value}")
        return True
    except Exception as e:
        if log_func and label:
            log_func(f"    [!] No se pudo seleccionar {label} ({value}): {e}")
        return False


def _ensure_privacy_checked(driver, checkbox_id, log_func=None):
    """Marca el checkbox de privacidad, intentando por label, input y JS."""
    try:
        check = driver.find_element(By.ID, checkbox_id)
        if check.is_selected():
            return True
        try:
            label = driver.find_element(By.XPATH, f"//label[@for='{checkbox_id}']")
            driver.execute_script("arguments[0].click();", label)
        except Exception:
            pass
        if not check.is_selected():
            driver.execute_script("arguments[0].click();", check)
        if not check.is_selected():
            driver.execute_script(
                "arguments[0].checked = true; "
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                check
            )
        if log_func:
            log_func(f"    Checkbox privacidad marcado: {check.is_selected()}")
        return check.is_selected()
    except Exception as e:
        if log_func:
            log_func(f"    [!] No se pudo marcar checkbox privacidad: {e}")
        return False


def process_billing_data(driver, wait, log_func):
    """Rellena el formulario de facturación de CAMS con los datos del .env."""
    try:
        time.sleep(2)

        tiene_bill_form = len(driver.find_elements(By.ID, "ticket-bill-form_rfc")) > 0
        tiene_divide_form = len(driver.find_elements(By.ID, "ticket-bill-form-divide_rfc1")) > 0

        if not tiene_bill_form and not tiene_divide_form:
            log_func(" -> No se detectó formulario de facturación (posiblemente ya facturado).")
            return

        if tiene_bill_form:
            log_func(" -> Llenando formulario de facturación (formato normal)...")

            _set_input(driver, "ticket-bill-form_rfc",  DATOS_FACTURACION['rfc'],    log_func, "RFC")
            _set_input(driver, "ticket-bill-form_name", DATOS_FACTURACION['nombre'], log_func, "Nombre")
            _set_input(driver, "ticket-bill-form_zip_code",
                       DATOS_FACTURACION['cp'], log_func, "Código Postal")

            _set_select(driver, "ticket-bill-form_tax_regime",
                        DATOS_FACTURACION['regimen'], log_func, "Régimen Fiscal")
            _set_select(driver, "ticket-bill-form_document_use",
                        DATOS_FACTURACION['uso_cfdi'], log_func, "Uso de CFDI")

            _set_input(driver, "ticket-bill-form_email",
                       DATOS_FACTURACION['email'], log_func, "Email")
            _set_input(driver, "ticket-bill-form_confirm_email",
                       DATOS_FACTURACION['email'], log_func, "Confirmar Email")

            _ensure_privacy_checked(driver, "ticket-bill-form_privacy", log_func)

            time.sleep(1.5)
            return

        if tiene_divide_form:
            log_func(" -> Llenando formulario de facturación (formato dividido)...")
            for sufijo in ('1', '2'):
                _set_input(driver, f"ticket-bill-form-divide_rfc{sufijo}",
                           DATOS_FACTURACION['rfc'], log_func, f"RFC{sufijo}")
                _set_input(driver, f"ticket-bill-form-divide_name{sufijo}",
                           DATOS_FACTURACION['nombre'], log_func, f"Nombre{sufijo}")
                _set_input(driver, f"ticket-bill-form-divide_zip_code{sufijo}",
                           DATOS_FACTURACION['cp'], log_func, f"CP{sufijo}")
                _set_select(driver, f"ticket-bill-form-divide_tax_regime{sufijo}",
                            DATOS_FACTURACION['regimen'], log_func, f"Régimen{sufijo}")
                _set_select(driver, f"ticket-bill-form-divide_document_use{sufijo}",
                            DATOS_FACTURACION['uso_cfdi'], log_func, f"Uso CFDI{sufijo}")
                _set_input(driver, f"ticket-bill-form-divide_email{sufijo}",
                           DATOS_FACTURACION['email'], log_func, f"Email{sufijo}")
                _set_input(driver, f"ticket-bill-form-divide_confirm_email{sufijo}",
                           DATOS_FACTURACION['email'], log_func, f"Confirmar Email{sufijo}")
                _ensure_privacy_checked(driver, f"ticket-bill-form-divide_privacy{sufijo}", log_func)

            time.sleep(1.5)
            return

    except Exception as e:
        log_func(f" -> Error procesando formulario: {e}")


def _wait_until_form_ready(driver, log_func):
    """Espera hasta que aparezca el formulario con los campos requeridos."""
    for _ in range(15):
        if driver.find_elements(By.ID, "ticket-bill-form_rfc") or \
           driver.find_elements(By.ID, "ticket-bill-form-divide_rfc1"):
            return True
        time.sleep(1)
    log_func("    [!] El formulario de facturación no apareció a tiempo.")
    return False


# =============================================================
# TAREA PRINCIPAL DE SELENIUM
# =============================================================
def run_selenium_task(tickets, output_dir, headless, log_queue):
    def log(msg):
        log_queue.append(msg)

    os.makedirs(output_dir, exist_ok=True)

    options = Options()
    if headless:
        options.add_argument("--headless=new")

    prefs = {
        "download.default_directory": os.path.abspath(output_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-features=DownloadBubble,DownloadBubbleV2")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    log("-> Iniciando navegador Chromium/Chrome...")
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        log(f"[Error] No se pudo iniciar Chrome: {e}")
        return

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        )
    except Exception:
        pass

    wait = WebDriverWait(driver, 15)
    total_descargadas = 0
    total_tickets = len(tickets)

    try:
        for idx, ticket in enumerate(tickets, 1):
            num = ticket["numero"]
            fecha = ticket["fecha"]
            monto = ticket["monto"]

            log(f"\n[{idx}/{total_tickets}] Ticket: {num} | Fecha: {fecha} | Monto: ${monto}")

            try:
                driver.get(URL_PORTAL)
                time.sleep(2)

                input_folio = wait.until(EC.element_to_be_clickable((By.ID, "search-ticket-form_folio")))
                input_fecha = driver.find_element(By.ID, "search-ticket-form_fecha")
                input_monto = driver.find_element(By.ID, "search-ticket-form_monto")

                input_folio.clear(); input_folio.send_keys(num)
                input_fecha.clear(); input_fecha.send_keys(fecha)
                input_monto.clear(); input_monto.send_keys(monto)

                btn_buscar = driver.find_element(
                    By.XPATH, "//button[contains(@class, 'search_button') and contains(., 'Buscar')]"
                )
                driver.execute_script("arguments[0].click();", btn_buscar)
                log(" -> Búsqueda enviada...")
                time.sleep(3)

                body_text = driver.find_element(By.TAG_NAME, "body").text
                if "descarga la última factura" in body_text.lower():
                    log(" -> Ticket ya facturado. Descargando...")
                    xml_url, pdf_url = extract_download_links(driver)
                    if xml_url:
                        download_file(xml_url, os.path.join(output_dir, f"Factura_{num}.xml"))
                    if pdf_url:
                        download_file(pdf_url, os.path.join(output_dir, f"Factura_{num}.pdf"))
                    total_descargadas += 1
                    continue

                btn_continuar = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@id='continue_button'] | "
                                                          "//button[contains(., 'Continuar')]"))
                )
                driver.execute_script("arguments[0].click();", btn_continuar)
                log(" -> Avanzando al formulario de facturación...")

                if not _wait_until_form_ready(driver, log):
                    raise RuntimeError("El formulario de facturación no apareció.")

                process_billing_data(driver, wait, log)

                initial_files = set(os.listdir(output_dir))

                btn_facturar = wait.until(EC.element_to_be_clickable((By.ID, "billing_button")))
                driver.execute_script("arguments[0].click();", btn_facturar)
                log(" -> Generando comprobante...")

                xml_url, pdf_url = None, None
                detected_by_dir = False

                for _ in range(20):
                    time.sleep(2)
                    xml_url, pdf_url = extract_download_links(driver)
                    if xml_url or pdf_url:
                        break
                    try:
                        new_now = set(os.listdir(output_dir)) - initial_files
                        if any(not f.endswith('.crdownload') for f in new_now):
                            detected_by_dir = True
                            break
                    except FileNotFoundError:
                        pass

                if xml_url or pdf_url:
                    log(" -> ¡Éxito! Descargando por URL...")
                    if xml_url:
                        download_file(xml_url, os.path.join(output_dir, f"Factura_{num}.xml"))
                    if pdf_url:
                        download_file(pdf_url, os.path.join(output_dir, f"Factura_{num}.pdf"))
                    total_descargadas += 1

                elif detected_by_dir:
                    log(" -> Descarga detectada por el navegador, esperando archivos...")
                    files = wait_for_downloads(output_dir, initial_files, timeout=60, log_func=log)
                    renamed = rename_downloaded_files(files, num, output_dir, log_func=log)
                    if renamed:
                        total_descargadas += 1
                    else:
                        log(" -> [!] Archivos detectados pero no son XML/PDF válidos.")

                else:
                    log(f" -> [!] No se detectaron descargas para el ticket {num}.")
                    try:
                        png = os.path.join(output_dir, f"debug_{num}.png")
                        html = os.path.join(output_dir, f"debug_{num}.html")
                        driver.save_screenshot(png)
                        with open(html, "w", encoding="utf-8") as fp:
                            fp.write(driver.page_source)
                        log(f" -> Diagnóstico guardado: {os.path.basename(png)} y {os.path.basename(html)}")
                    except Exception as e:
                        log(f" -> No se pudo guardar diagnóstico: {e}")

            except Exception as e:
                log(f" -> [Error] Excepción en ticket {num}: {str(e)[:150]}...")

    finally:
        driver.quit()
        log("\n--- PROCESO FINALIZADO ---")
        log(f"Facturas descargadas: {total_descargadas}/{total_tickets}")
        log(f"Ruta: {os.path.abspath(output_dir)}")


# =============================================================
# INTERFAZ GRÁFICA
# =============================================================
@ui.page('/')
def index():
    ui.colors(primary='#2563eb', secondary='#10b981', accent='#f59e0b')

    with ui.column().classes('w-full max-w-3xl mx-auto p-4 items-center'):
        ui.label('Facturador Automático CAMS').classes('text-3xl font-bold mb-2')
        ui.label('Portal Diverza · CFDI 4.0').classes('text-gray-500 mb-6')

        with ui.card().classes('w-full'):
            ui.label('1. Pega aquí los tickets (Formato: Folio, Fecha, Monto)').classes('font-bold')
            text_area = ui.textarea(
                placeholder='Ej: 02052267371268253513, 07/09/2026, 103'
            ).classes('w-full font-mono text-sm')

            ui.label('2. Configuración').classes('font-bold mt-4')
            output_dir = ui.input(
                'Carpeta de destino',
                value=os.path.join(get_app_dir(), 'Facturas_CAMS')
            ).classes('w-full')
            headless_check = ui.checkbox('Modo oculto (no mostrar el navegador)', value=True)

            log_terminal = ui.log().classes('w-full h-64 mt-4 bg-gray-900 text-green-400 font-mono text-xs')

            async def start_process():
                tickets = parse_tickets_text(text_area.value or '')
                if not tickets:
                    ui.notify('No se encontraron tickets válidos en el texto.', color='negative')
                    return

                log_terminal.clear()
                log_terminal.push(f"Iniciando proceso para {len(tickets)} ticket(s)...")
                btn_start.disable()

                log_queue = []
                loop = asyncio.get_running_loop()
                future = loop.run_in_executor(
                    None, run_selenium_task,
                    tickets, output_dir.value, headless_check.value, log_queue
                )

                while not future.done():
                    while log_queue:
                        log_terminal.push(log_queue.pop(0))
                    await asyncio.sleep(0.5)

                while log_queue:
                    log_terminal.push(log_queue.pop(0))

                btn_start.enable()
                ui.notify('Proceso completado', color='positive')

            btn_start = ui.button('Iniciar Facturación', on_click=start_process).classes('w-full mt-4 bg-blue-600')


if __name__ in {"__main__", "__mp_main__"}:
    multiprocessing.freeze_support()
    ui.run(
        title="Facturador CAMS",
        port=8080,
        native=True,
        window_size=(900, 750),
        reload=False,
        show=True,
    )