from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import make_msgid
from dotenv import load_dotenv
from google.cloud import storage
from google.oauth2 import service_account
import mysql.connector
import smtplib
import time
import os
import locale

try:
    locale.setlocale(locale.LC_TIME, "es_MX.UTF-8")
except Exception:
    pass

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
DOWNLOADS_FOLDER = os.path.join(BASE_DIR, "pdfs")

ALIAS_NAME = "VTO LOGIX"
SMTP_FROM = "andres.mirazo@ventologix.com"
FROM_ADDRESS = "vto@ventologix.com"
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

LOGO_PATH = os.path.join(PROJECT_ROOT, "public", "Logo vento firma.jpg")
VENTOLOGIX_LOGO_PATH = os.path.join(PROJECT_ROOT, "public", "ventologix firma.jpg")

GCS_KEY_FILE = os.path.join(PROJECT_ROOT, "lib", "gcs-storage-key.json")
GCS_BUCKET_NAME = "vento-save-archive"

ADMIN_CORREOS = [
    # "hector.tovar@ventologix.com",
    "andres.mirazo@ventologix.com",
]

FORZAR_SEMANALES = os.getenv("FORZAR_SEMANALES", "0") == "1"
SOLO_TIPO = os.getenv("REPORTE_TIPO", "").strip().lower()
FECHA_HOY = datetime.now()


# ==================== UTILIDADES ====================

@contextmanager
def db_connection():
    """Context manager para conexion a MySQL usando variables de entorno."""
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_DATABASE"),
    )
    try:
        yield conn
    finally:
        conn.close()


def upload_to_gcs(file_path: str, client_name: str = "", folio: str = "") -> bool:
    """Sube un archivo PDF a Google Cloud Storage dentro de la carpeta del folio.
    Path: mantenimiento/{year}/{month}/{client_name}/{folio}/{filename}
    """
    try:
        credentials = service_account.Credentials.from_service_account_file(GCS_KEY_FILE)
        gcs_client = storage.Client(credentials=credentials, project=credentials.project_id)
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        now = datetime.now()
        clean_client = client_name.strip().replace('/', '-') if client_name else "sin-cliente"
        clean_folio = folio.strip().replace('/', '-') if folio else "sin-folio"
        blob_name = (
            f"mantenimiento/{now.strftime('%Y')}/{now.strftime('%m')}"
            f"/{clean_client}/{clean_folio}/{os.path.basename(file_path)}"
        )
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(file_path, content_type='application/pdf')
        try:
            blob.make_public()
        except Exception:
            pass
        print(f"  Subido a GCS: {blob_name}")
        return True
    except Exception as e:
        print(f"  Error subiendo a GCS: {e}")
        return False


def generar_pdf(url: str, output_path: str, timeout: int = 300000) -> str | None:
    """
    Genera un PDF a partir de una URL usando Playwright.
    Espera la senal window.status === 'pdf-ready' o 'data-error'.
    Retorna la ruta del PDF o None si falla.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_viewport_size({"width": 1920, "height": 1080})

            try:
                page.goto(url, timeout=timeout)
                page.wait_for_function(
                    "window.status === 'pdf-ready' || window.status === 'data-error'",
                    timeout=timeout,
                )

                if page.evaluate("() => window.status") == "data-error":
                    print(f"  data-error para {url}")
                    browser.close()
                    return None

                full_height = page.evaluate(
                    "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                )
                safe_height = max(int(full_height) - 2, 1)

                page.pdf(
                    path=output_path,
                    width="1920px",
                    height=f"{safe_height}px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            except Exception as e:
                print(f"  Error Playwright: {e}")
                browser.close()
                return None

            browser.close()

        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"  PDF generado ({size} bytes): {os.path.basename(output_path)}")
            return output_path
        return None
    except Exception as e:
        print(f"  Error general PDF: {e}")
        return None


def get_fecha_reporte(tipo: str, fecha_base: datetime = None) -> str:
    """Genera etiqueta de fecha para nombres de archivo."""
    fecha_base = fecha_base or datetime.now()
    if tipo == "diario":
        return (fecha_base - timedelta(days=1)).strftime("%Y-%m-%d")
    lunes = fecha_base - timedelta(days=fecha_base.weekday() + 7)
    domingo = lunes + timedelta(days=6)
    fecha = fecha_base.strftime("%Y-%m-%d")
    try:
        mes = domingo.strftime("%B")
    except Exception:
        mes = domingo.strftime("%m")
    return f"{fecha} (Semana del {lunes.day} al {domingo.day} {mes})"


# ==================== CONSULTAS BD ====================

def obtener_clientes(tipo: str) -> list[dict]:
    """
    Obtiene clientes+compresores que necesitan reportes.
    Solo incluye compresores con al menos un destinatario válido en usuarios_auth.
    """
    flag = "envio_diario" if tipo == "diario" else "envio_semanal"
    with db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"""
            SELECT DISTINCT c.id_cliente, c.nombre_cliente, comp.linea, comp.Alias AS alias
            FROM clientes c
            JOIN compresores comp ON comp.id_cliente = c.id_cliente
            JOIN usuarios_auth ua ON ua.numeroCliente = c.numero_cliente
            WHERE ua.{flag} = 1
              AND ua.email IS NOT NULL AND ua.email != ''
              AND ua.email NOT LIKE '##%%'
        """)
        rows = cursor.fetchall()
        cursor.close()
    return rows


def obtener_destinatarios(tipo: str) -> dict:
    """
    Obtiene destinatarios desde BD agrupados por (id_cliente, linea).
    Usa tablas: clientes, compresores, usuarios_auth.
    Retorna: {(id_cliente, linea): {'nombre_cliente', 'alias', 'to': [...], 'cc': [...]}}
    """
    flag = "envio_diario" if tipo == "diario" else "envio_semanal"

    query = f"""
        SELECT DISTINCT
            c.id_cliente, c.nombre_cliente,
            comp.linea, comp.Alias,
            ua.email, ua.rol
        FROM clientes c
        JOIN compresores comp ON comp.id_cliente = c.id_cliente
        JOIN usuarios_auth ua ON ua.numeroCliente = c.numero_cliente
        WHERE ua.{flag} = 1
          AND ua.email IS NOT NULL AND ua.email != ''
          AND ua.email NOT LIKE '##%%'
        ORDER BY c.id_cliente, comp.Alias
    """

    with db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()

    destinatarios = {}
    for row in rows:
        key = (row['id_cliente'], row['linea'])
        if key not in destinatarios:
            destinatarios[key] = {
                'nombre_cliente': row['nombre_cliente'],
                'alias': row['Alias'] or "",
                'to': [],
                'cc': [],
            }
        email = row['email']
        rol = row['rol'] if row['rol'] is not None else 4
        bucket = 'cc' if rol in (0, 1, 2) else 'to'
        if email not in destinatarios[key][bucket]:
            destinatarios[key][bucket].append(email)

    return destinatarios


def obtener_registros_mtto_pendientes() -> list[dict]:
    """Registros de mantenimiento donde Generado IS NULL o 0."""
    with db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, numero_serie, timestamp, cliente, carpeta_fotos, email, tecnico
            FROM registros_mantenimiento_tornillo
            WHERE Generado IS NULL OR Generado = 0
            ORDER BY timestamp DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
    return rows


def marcar_reporte_generado(registro_id: int, link_pdf: str = None) -> bool:
    """Marca un registro de mantenimiento como generado."""
    with db_connection() as conn:
        cursor = conn.cursor()
        if link_pdf:
            cursor.execute(
                "UPDATE registros_mantenimiento_tornillo SET Generado = 1, link_pdf = %s WHERE id = %s",
                (link_pdf, registro_id),
            )
        else:
            cursor.execute(
                "UPDATE registros_mantenimiento_tornillo SET Generado = 1 WHERE id = %s",
                (registro_id,),
            )
        conn.commit()
        ok = cursor.rowcount > 0
        cursor.close()
    return ok


# ==================== EMAIL ====================

def send_mail(to: list[str], cc: list[str], bcc: list[str],
              subject: str, body_html: str, pdf_path: str = None) -> bool:
    """Envia un correo con PDF adjunto y logos embebidos."""
    if not to:
        return False

    msg = EmailMessage()
    msg['From'] = f"{ALIAS_NAME} <{FROM_ADDRESS}>"
    msg['To'] = ", ".join(to)
    if cc:
        msg['Cc'] = ", ".join(cc)
    msg['Subject'] = subject

    logo_cid = make_msgid(domain='ventologix.com')
    vento_cid = make_msgid(domain='ventologix.com')

    full_body = body_html + f"""
    <br><p><img src="cid:{logo_cid[1:-1]}" alt="Logo" /></p>
    <p><img src="cid:{vento_cid[1:-1]}" alt="Ventologix" /></p>
    <br>VTO logix<br>
    <a href='mailto:vto@ventologix.com'>vto@ventologix.com</a><br>
    <a href='https://www.ventologix.com'>www.ventologix.com</a><br>
    """
    msg.set_content("Este mensaje requiere un cliente con soporte HTML.")
    msg.add_alternative(full_body, subtype='html')

    for img_path, cid in [(LOGO_PATH, logo_cid), (VENTOLOGIX_LOGO_PATH, vento_cid)]:
        if os.path.isfile(img_path):
            with open(img_path, 'rb') as img:
                msg.get_payload()[1].add_related(
                    img.read(), maintype='image', subtype='jpeg', cid=cid
                )

    if pdf_path and os.path.isfile(pdf_path):
        with open(pdf_path, 'rb') as f:
            msg.add_attachment(
                f.read(), maintype='application', subtype='pdf',
                filename=os.path.basename(pdf_path),
            )

    all_addrs = list(to) + list(cc) + list(bcc)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(SMTP_FROM, SMTP_PASSWORD)
                smtp.send_message(msg, to_addrs=all_addrs)
            return True
        except Exception as e:
            print(f"  Error SMTP enviando a {to} (intento {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                wait = attempt * 5
                print(f"  Reintentando en {wait}s...")
                time.sleep(wait)
    return False


def send_error_mail(failed_pdfs: list = None, missing_files: list = None):
    """Envia alerta de errores a admins."""
    if not failed_pdfs and not missing_files:
        return

    body = "<h3>Reporte de Errores - Ventologix</h3>"
    if failed_pdfs:
        body += "<h4>PDFs fallidos:</h4><ul>"
        for p in failed_pdfs:
            body += f"<li><b>{p['nombre_cliente']} - {p.get('alias','')}</b> ({p['tipo']})"
            if 'error' in p:
                body += f" - {p['error']}"
            body += "</li>"
        body += "</ul>"
    if missing_files:
        body += "<h4>Archivos no encontrados:</h4><ul>"
        for f in missing_files:
            body += f"<li>{f}</li>"
        body += "</ul>"
    body += f"<br><p><b>Fecha:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"

    send_mail(
        to=ADMIN_CORREOS, cc=[], bcc=[],
        subject="Reporte - Errores en generacion/envio de PDFs",
        body_html=body,
    )


# ==================== GENERACION DE PDFs ====================

def generar_pdf_cliente(id_cliente: int, linea: str, nombre_cliente: str,
                        alias: str, tipo: str, etiqueta_fecha: str) -> str | None:
    """Genera PDF de reporte diario o semanal para un compresor."""
    alias_limpio = (alias or "").strip()
    tipo_label = "Diario" if tipo == "diario" else "Semanal"
    nombre_archivo = f"Reporte {tipo_label} {nombre_cliente} {alias_limpio} {etiqueta_fecha}.pdf"
    pdf_path = os.path.join(DOWNLOADS_FOLDER, nombre_archivo)

    ruta = "reportesD" if tipo == "diario" else "reportesS"
    url = f"http://localhost:3000/automation/{ruta}?id_cliente={id_cliente}&linea={linea}"
    print(f"  [{tipo_label}] {nombre_cliente} - {alias_limpio}")

    return generar_pdf(url, pdf_path)


def generar_pdf_mantenimiento(registro_id: int, numero_serie: str,
                              cliente: str, fecha: str) -> str | None:
    """Genera PDF de reporte de mantenimiento."""
    cliente_limpio = cliente.replace("/", "-").replace("\\", "-")
    nombre_archivo = f"Reporte Mantenimiento {cliente_limpio} {numero_serie} {fecha}.pdf"
    pdf_path = os.path.join(DOWNLOADS_FOLDER, nombre_archivo)

    url = f"http://localhost:3000/automation/mtto-report?id={registro_id}"
    print(f"  [Mtto] {cliente} - {numero_serie}")

    result = generar_pdf(url, pdf_path, timeout=180000)
    if result:
        marcar_reporte_generado(registro_id)
    return result


# ==================== ORQUESTACION ====================

def generar_todos_los_pdfs(clientes: list[dict], tipo: str) -> tuple[dict, list]:
    """
    Genera PDFs para cada cliente. Sube a Drive si es semanal.
    Retorna: (pdfs_generados: {(id_cliente,linea): path}, fallidos: list)
    """
    os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)
    generados = {}
    fallidos = []

    for i, c in enumerate(clientes, 1):
        id_cliente = c['id_cliente']
        linea = c['linea']
        nombre_cliente = c['nombre_cliente']
        alias = (c.get('alias') or "").strip()
        etiqueta = get_fecha_reporte(tipo, FECHA_HOY)

        print(f"\n[{i}/{len(clientes)}] {nombre_cliente} - {alias}")
        inicio = time.time()

        pdf_path = generar_pdf_cliente(id_cliente, linea, nombre_cliente, alias, tipo, etiqueta)
        elapsed = time.time() - inicio

        if pdf_path:
            generados[(id_cliente, linea)] = pdf_path
            if tipo == "semanal":
                upload_to_gcs(pdf_path, client_name=nombre_cliente, folio=etiqueta)
            print(f"  OK ({elapsed:.1f}s)")
        else:
            fallidos.append({
                'nombre_cliente': nombre_cliente, 'alias': alias,
                'tipo': tipo, 'id_cliente': id_cliente, 'linea': linea,
            })
            print(f"  FALLO ({elapsed:.1f}s)")

    print(f"\nResumen {tipo}: {len(generados)} OK, {len(fallidos)} fallidos")
    return generados, fallidos


def enviar_reportes(tipo: str, pdfs_generados: dict):
    """
    Envia los PDFs generados a los destinatarios obtenidos de BD.
    pdfs_generados: {(id_cliente, linea): pdf_path}
    """
    destinatarios = obtener_destinatarios(tipo)
    tipo_label = "Diario" if tipo == "diario" else "Semanal"
    fecha_str = get_fecha_reporte(tipo, FECHA_HOY)
    enviados = 0
    sin_destino = []

    for i, (key, pdf_path) in enumerate(pdfs_generados.items()):
        dest = destinatarios.get(key)
        if not dest or not dest['to']:
            sin_destino.append(os.path.basename(pdf_path))
            continue

        if i > 0:
            time.sleep(2)

        subject = f"Reporte {tipo_label} VENTOLOGIX - {dest['nombre_cliente']} {dest['alias']} ({fecha_str})"
        body = f"""
        <p>Estimado equipo de <b>{dest['nombre_cliente']}</b>:</p>
        <p>Adjunto el reporte <b>{tipo_label.lower()}</b> del compresor
        <b>{dest['alias']}</b> correspondiente al {fecha_str}.</p>
        <p>Los datos han sido analizados y procesados automaticamente.</p>
        <p><b>IQ YOUR CFMs!</b></p>
        """

        if send_mail(
            to=dest['to'], cc=dest['cc'], bcc=ADMIN_CORREOS,
            subject=subject, body_html=body, pdf_path=pdf_path,
        ):
            enviados += 1
            try:
                os.remove(pdf_path)
            except Exception:
                pass

    print(f"Correos enviados: {enviados} | Sin destinatario: {len(sin_destino)}")
    if sin_destino:
        print(f"  Sin destino: {sin_destino}")


def procesar_mantenimientos() -> tuple[int, int]:
    """Genera PDFs de mantenimiento pendientes y los sube a Drive."""
    registros = obtener_registros_mtto_pendientes()
    if not registros:
        print("No hay reportes de mantenimiento pendientes")
        return 0, 0

    print(f"\nMantenimientos pendientes: {len(registros)}")
    exitosos, fallidos_count = 0, 0

    for i, reg in enumerate(registros, 1):
        registro_id = reg['id']
        numero_serie = reg['numero_serie']
        cliente = reg.get('cliente', 'Cliente')

        timestamp = reg.get('timestamp')
        if timestamp:
            try:
                dt = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp))
                fecha = dt.strftime('%Y-%m-%d')
            except Exception:
                fecha = datetime.now().strftime('%Y-%m-%d')
        else:
            fecha = datetime.now().strftime('%Y-%m-%d')

        print(f"\n[{i}/{len(registros)}] Mtto ID:{registro_id} - {cliente} - {numero_serie}")

        pdf_path = generar_pdf_mantenimiento(registro_id, numero_serie, cliente, fecha)
        if pdf_path:
            upload_to_gcs(pdf_path, client_name=cliente, folio=str(registro_id))
            exitosos += 1
        else:
            fallidos_count += 1

    print(f"\nResumen mantenimiento: {exitosos} OK, {fallidos_count} fallidos")
    return exitosos, fallidos_count


def verificar_conectividad():
    """Verifica que Next.js y Playwright esten disponibles."""
    import requests
    checks = [
        ("Next.js (3000)", "http://localhost:3000/"),
    ]
    for name, url in checks:
        try:
            r = requests.get(url, timeout=10)
            print(f"  {name}: {'OK' if r.status_code == 200 else f'codigo {r.status_code}'}")
        except Exception as e:
            print(f"  {name}: NO DISPONIBLE - {e}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        print("  Playwright: OK")
    except Exception as e:
        print(f"  Playwright: ERROR - {e}")


def clean_pdfs_folder():
    """Limpia PDFs de la carpeta de descargas."""
    os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)
    count = 0
    for f in os.listdir(DOWNLOADS_FOLDER):
        if f.endswith(".pdf"):
            try:
                os.remove(os.path.join(DOWNLOADS_FOLDER, f))
                count += 1
            except Exception:
                pass
    if count:
        print(f"  {count} PDFs eliminados")


def debe_generar_semanales(fecha: datetime) -> bool:
    return FORZAR_SEMANALES or fecha.weekday() == 0

# ==================== TEST ====================
TEST_EMAILS = [
    "andres.mirazo@ventologix.com",
    "octavio.murillo@ventologix.com",
    "hector.tovar@ventologix.com",
]


def test():
    """
    Genera TODOS los reportes diarios y los envia unicamente
    a los correos de prueba (TEST_EMAILS), sin tocar a los clientes.
    """
    print("=== TEST MODE - REPORTES DIARIOS ===")
    print(f"Destinatarios de prueba: {TEST_EMAILS}")
    print(f"Fecha: {FECHA_HOY.strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n--- Verificando conectividad ---")
    verificar_conectividad()

    print("\n--- Limpiando PDFs ---")
    clean_pdfs_folder()

    inicio = time.time()

    clientes = obtener_clientes("diario")
    print(f"\nClientes diarios: {len(clientes)}")

    if not clientes:
        print("No hay clientes con reportes diarios.")
        return

    pdfs, fallidos = generar_todos_los_pdfs(clientes, "diario")

    if not pdfs:
        print("No se genero ningun PDF.")
        if fallidos:
            send_error_mail(failed_pdfs=fallidos)
        return

    # Enviar todos los PDFs a los correos de prueba
    tipo_label = "Diario"
    fecha_str = get_fecha_reporte("diario", FECHA_HOY)
    enviados = 0

    for i, (_, pdf_path) in enumerate(pdfs.items()):
        nombre_archivo = os.path.basename(pdf_path)

        subject = f"[TEST] Reporte {tipo_label} - {nombre_archivo} ({fecha_str})"
        body = f"""
        <p><b>[MODO TEST]</b> - Este correo es solo de prueba.</p>
        <p>Adjunto el reporte <b>{tipo_label.lower()}</b> correspondiente al {fecha_str}.</p>
        <p>Archivo: <b>{nombre_archivo}</b></p>
        """

        if i > 0:
            time.sleep(2)

        if send_mail(
            to=TEST_EMAILS, cc=[], bcc=[],
            subject=subject, body_html=body, pdf_path=pdf_path,
        ):
            enviados += 1
            try:
                os.remove(pdf_path)
            except Exception:
                pass

    elapsed = time.time() - inicio
    print(f"\n=== TEST COMPLETADO en {elapsed:.1f}s ===")
    print(f"PDFs generados: {len(pdfs)} | Fallidos: {len(fallidos)} | Correos enviados: {enviados}")

    if fallidos:
        send_error_mail(failed_pdfs=fallidos)


# ==================== MAIN ====================

def main():
    print(f"=== AUTOMATION VENTOLOGIX ===")
    print(f"Fecha: {FECHA_HOY.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Tipo: {SOLO_TIPO or 'auto'} | Forzar semanales: {FORZAR_SEMANALES}")

    print("\n--- Verificando conectividad ---")
    verificar_conectividad()

    print("\n--- Limpiando PDFs ---")
    clean_pdfs_folder()

    inicio = time.time()

    ejecutar_diarios = SOLO_TIPO in ("", "diario")
    ejecutar_semanales = SOLO_TIPO in ("", "semanal") and debe_generar_semanales(FECHA_HOY)

    # --- DIARIOS ---
    if ejecutar_diarios:
        print("\n========== REPORTES DIARIOS ==========")
        clientes = obtener_clientes("diario")
        print(f"Clientes diarios: {len(clientes)}")

        if clientes:
            pdfs, fallidos = generar_todos_los_pdfs(clientes, "diario")
            enviar_reportes("diario", pdfs)
            if fallidos:
                send_error_mail(failed_pdfs=fallidos)

        # Mantenimientos se ejecutan junto con diarios
        print("\n========== MANTENIMIENTOS PENDIENTES ==========")
        procesar_mantenimientos()
    else:
        print("\nDiarios omitidos")

    # --- SEMANALES ---
    if ejecutar_semanales:
        print("\n========== REPORTES SEMANALES ==========")
        clientes = obtener_clientes("semanal")
        print(f"Clientes semanales: {len(clientes)}")

        if clientes:
            pdfs, fallidos = generar_todos_los_pdfs(clientes, "semanal")
            enviar_reportes("semanal", pdfs)
            if fallidos:
                send_error_mail(failed_pdfs=fallidos)
    else:
        dia = FECHA_HOY.strftime('%A')
        print(f"\nSemanales omitidos (hoy es {dia})")

    elapsed = time.time() - inicio
    print(f"\n=== COMPLETADO en {elapsed:.1f}s ===")


if __name__ == "__main__":
    import sys
    modo = sys.argv[1] if len(sys.argv) > 1 else "main"

    try:
        if modo == "test":
            test()
        else:
            main()
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
        clean_pdfs_folder()
    except Exception as e:
        print(f"\nError critico: {e}")
        try:
            send_error_mail(failed_pdfs=[{
                'nombre_cliente': 'Sistema', 'alias': 'Error General',
                'tipo': 'critico', 'error': str(e),
            }])
        except Exception:
            pass