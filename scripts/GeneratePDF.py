import os
import pickle
from datetime import datetime
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import gspread
from pathlib import Path

# -----------------------------
# CONFIGURACIÓN
# -----------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # dashboard-ventologix
LIB_DIR = PROJECT_ROOT / "lib"

OAUTH_CREDENTIALS_FILE = str(LIB_DIR / "oauth_credentials.json")
TOKEN_FILE = str(LIB_DIR / "token.pickle")
    
SPREADSHEET_ID = "1SOmQD9uUMVlsGP4OBbZ3lJSBeet1J2fsmbxqYz200mI"
SHEET_NAME = "Resumen Formulario"

TEMPLATE_ID = "1KfpcLGUoM4H_UCVijhIGHLcMwzePk3-WpxXdmMJx_h8"
ROOT_FOLDER_ID = "1go0dsxXDmJ5FyHiUmVa4oXwacIh690g5"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets"
]

# -----------------------------
# AUTENTICACIÓN
# -----------------------------
creds = None
if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, 'rb') as token:
        creds = pickle.load(token)
if not creds:
    flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, 'wb') as token:
        pickle.dump(creds, token)

# Servicios
drive_service = build('drive', 'v3', credentials=creds)
docs_service = build('docs', 'v1', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)

# Gspread para leer hojas
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
all_rows = sheet.get_all_values()

# -----------------------------
# FUNCIONES AUXILIARES
# -----------------------------
def normalize_date(fecha_input):
    formatos = ["%d/%m/%y", "%d-%m-%y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
    for f in formatos:
        try:
            return datetime.strptime(fecha_input, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def verify_template_placeholders():
    """
    Verifica que la plantilla tenga los placeholders necesarios.
    """
    try:
        doc = docs_service.documents().get(documentId=TEMPLATE_ID).execute()
        content = doc.get('body').get('content')
        
        # Extraer todo el texto del documento
        full_text = ""
        for element in content:
            if 'paragraph' in element:
                for text_run in element['paragraph'].get('elements', []):
                    if 'textRun' in text_run:
                        full_text += text_run['textRun']['content']
        
        # Buscar placeholders
        import re
        placeholders_found = re.findall(r'\{\{[^}]+\}\}', full_text)
        
        print(f"\n📋 Placeholders encontrados en la plantilla: {len(placeholders_found)}")
        if placeholders_found:
            for ph in set(placeholders_found):
                print(f"  ✓ {ph}")
        else:
            print("  ⚠️ NO se encontraron placeholders en la plantilla!")
            print("  📝 La plantilla debe contener marcadores como: {{Cliente}}, {{NumeroSerie}}, etc.")
        
        return placeholders_found
    except HttpError as e:
        print("⚠️ Error verificando plantilla:", e)
        return []

def get_or_create_folder(parent_id, folder_name):
    results = drive_service.files().list(
        q=f"'{parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    folder = drive_service.files().create(body=file_metadata, fields='id').execute()
    return folder['id']

def delete_existing_files(parent_folder_id, filename):
    """
    Elimina todos los archivos existentes con el nombre especificado en la carpeta.
    Esto previene duplicados y mantiene solo la versión más reciente.
    """
    try:
        # Buscar archivos con el mismo nombre (tanto .pdf como docs)
        query = f"'{parent_folder_id}' in parents and name contains '{filename}' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        files = results.get('files', [])
        
        deleted_count = 0
        for file in files:
            try:
                drive_service.files().delete(fileId=file['id']).execute()
                print(f"🗑️ Eliminado duplicado: {file['name']} (ID: {file['id']})")
                deleted_count += 1
            except HttpError as e:
                print(f"⚠️ No se pudo eliminar {file['name']}: {e}")
        
        if deleted_count > 0:
            print(f"✅ Se eliminaron {deleted_count} archivo(s) duplicado(s)")
        return deleted_count
    except HttpError as e:
        print(f"⚠️ Error buscando archivos duplicados: {e}")
        return 0

def list_photos_in_folder(folder_id):
    try:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents and mimeType contains 'image/'",
            fields="files(id, name, mimeType)"
        ).execute()
        return results.get('files', [])
    except HttpError as e:
        print("⚠️ Error listando fotos:", e)
        return []

# -----------------------------
# Rellenar plantilla DOC
# -----------------------------
def fill_template(doc_id, row):
    """
    Rellena la plantilla con los datos de la fila del Sheet.
    Usa las llaves {{CAMPO}} en el template (en mayúsculas con guiones bajos).
    """
    # Asegurar que tenemos suficientes columnas, rellenar con string vacío si falta
    while len(row) < 30:
        row.append("")
    
    placeholders = {
        "{{TIMESTAMP}}": row[0] if row[0] else "",
        "{{CLIENTE}}": row[1] if row[1] else "",
        "{{TECNICO}}": row[2] if row[2] else "",
        "{{EMAIL}}": row[3] if row[3] else "",
        "{{COMPRESOR}}": row[4] if row[4] else "",
        "{{NUMERO_SERIE}}": row[5] if row[5] else "",
        "{{TIPO}}": row[6] if row[6] else "",
        "{{LINK_FORM}}": row[7] if row[7] else "",
        "{{CARPETA_FOTOS}}": row[8] if row[8] else "",
        "{{FECHA_MANTENIMIENTO}}": row[9] if row[9] else "",
        "{{FILTRO_AIRE}}": row[10] if row[10] else "",
        "{{FILTRO_ACEITE}}": row[11] if row[11] else "",
        "{{SEPARADOR_ACEITE}}": row[12] if row[12] else "",
        "{{ACEITE}}": row[13] if row[13] else "",
        "{{KIT_VALVULA_ADMISION}}": row[14] if row[14] else "",
        "{{KIT_VALVULA_MINIMA}}": row[15] if row[15] else "",
        "{{KIT_VALVULA_TERMOSTATICA}}": row[16] if row[16] else "",
        "{{COPLE_FLEXIBLE}}": row[17] if row[17] else "",
        "{{VALVULA_SOLENOIDE}}": row[18] if row[18] else "",
        "{{SENSOR_TEMPERATURA}}": row[19] if row[19] else "",
        "{{TRANSDUCTOR_PRESION}}": row[20] if row[20] else "",
        "{{CONTACTORES}}": row[21] if row[21] else "",
        "{{ANALISIS_BALEROS_COMPRESOR}}": row[22] if row[22] else "",
        "{{ANALISIS_BALEROS_VENTILADOR}}": row[23] if row[23] else "",
        "{{LUBRICACION_BALEROS_MOTOR}}": row[24] if row[24] else "",
        "{{LIMPIEZA_INTERNA_RADIADOR}}": row[25] if row[25] else "",
        "{{LIMPIEZA_EXTERNA_RADIADOR}}": row[26] if row[26] else "",
        "{{COMENTARIOS_GENERALES}}": row[27] if row[27] else "",
        "{{NUMERO_CLIENTE}}": row[28] if row[28] else "",
        "{{COMENTARIO_CLIENTE}}": row[29] if row[29] else ""
    }

    print("📝 Datos a rellenar:")
    for key, value in placeholders.items():
        if value:  # Solo mostrar los que tienen valor
            print(f"  {key}: {value[:50]}..." if len(value) > 50 else f"  {key}: {value}")

    requests = []
    for key, value in placeholders.items():
        requests.append({
            'replaceAllText': {
                'containsText': {'text': key, 'matchCase': True},
                'replaceText': value
            }
        })

    try:
        result = docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        print(f"✅ Plantilla rellenada exitosamente con {len(requests)} campos")
        return True
    except HttpError as e:
        print("⚠️ Error llenando plantilla:", e)
        return False

# -----------------------------
# Insertar fotos al final
# -----------------------------
def insert_images_at_end(doc_id, photos):
    if not photos:
        return

    # Asegurarse que sean públicas
    for photo in photos:
        try:
            drive_service.permissions().create(
                fileId=photo['id'],
                body={'role': 'reader', 'type': 'anyone'}
            ).execute()
        except HttpError:
            pass

    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc['body']['content'][-1]['endIndex']

    requests = []

    # Salto de página
    requests.append({'insertPageBreak': {'location': {'index': end_index - 1}}})
    end_index += 1

    # Título centrado
    title_text = "EVIDENCIAS\n"
    requests.append({'insertText': {'location': {'index': end_index}, 'text': title_text}})
    requests.append({
        'updateParagraphStyle': {
            'range': {'startIndex': end_index, 'endIndex': end_index + len(title_text)},
            'paragraphStyle': {'alignment': 'CENTER'},
            'fields': 'alignment'
        }
    })
    end_index += len(title_text)

    # Insertar fotos dos por página
    for i, photo in enumerate(photos):
        requests.append({
            'insertInlineImage': {
                'location': {'index': end_index},
                'uri': f"https://drive.google.com/uc?id={photo['id']}",
                'objectSize': {'width': {'magnitude': 250, 'unit': 'PT'}}
            }
        })
        end_index += 1
        if (i + 1) % 2 == 0 and (i + 1) < len(photos):
            requests.append({'insertPageBreak': {'location': {'index': end_index}}})
            end_index += 1

    try:
        docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
    except HttpError as e:
        print("⚠️ Error insertando fotos:", e)

# -----------------------------
# CREAR REPORTE
# -----------------------------
def create_report(numero_serie, fecha_input):
    fecha = normalize_date(fecha_input)
    if not fecha:
        print("❌ Fecha inválida")
        return

    print(f"🔍 Buscando: Número de serie={numero_serie}, Fecha={fecha}")
    
    filas_filtradas = [r for r in all_rows[1:] if len(r) > 5 and r[5] == numero_serie and normalize_date(r[0]) == fecha]
    
    if not filas_filtradas:
        print("❌ No se encontró ningún renglón con esos criterios.")
        print(f"   Total de filas en la hoja: {len(all_rows)-1}")
        # Mostrar números de serie disponibles para debug
        numeros_serie = set([r[5] for r in all_rows[1:] if len(r) > 5 and r[5]])
        print(f"   Números de serie disponibles: {', '.join(list(numeros_serie)[:5])}...")
        return
    
    row = filas_filtradas[0]
    print(f"✅ Registro encontrado con {len(row)} columnas")

    cliente_nombre = row[1] if len(row) > 1 else ""
    numero_cliente = row[28] if len(row) > 28 else ""
    carpeta_fotos_url = row[8] if len(row) > 8 else ""

    print(f"📁 Cliente: {numero_cliente} - {cliente_nombre}")
    print(f"📷 Carpeta de fotos: {carpeta_fotos_url[:50]}..." if len(carpeta_fotos_url) > 50 else f"📷 Carpeta de fotos: {carpeta_fotos_url}")

    # Crear estructura de carpetas
    client_folder = get_or_create_folder(ROOT_FOLDER_ID, f"{numero_cliente} {cliente_nombre}")
    comp_folder = get_or_create_folder(client_folder, f"Compresor - {numero_serie}")
    date_folder = get_or_create_folder(comp_folder, fecha)
    photo_folder = get_or_create_folder(date_folder, "Fotos")

    # Eliminar archivos duplicados antes de crear nuevos
    base_filename = f"Reporte_{numero_serie}_{fecha}"
    print(f"🔍 Verificando archivos duplicados para: {base_filename}")
    delete_existing_files(date_folder, base_filename)

    # Copiar plantilla
    copy_title = base_filename
    print(f"📄 Copiando plantilla como: {copy_title}")
    copied_file = drive_service.files().copy(
        fileId=TEMPLATE_ID,
        body={'name': copy_title, 'parents': [date_folder]}
    ).execute()
    doc_id = copied_file['id']
    print(f"✅ Documento creado con ID: {doc_id}")

    # Llenar plantilla
    print("🔄 Rellenando plantilla...")
    success = fill_template(doc_id, row)
    
    if not success:
        print("⚠️ Hubo problemas al rellenar la plantilla")

    # Insertar fotos
    if carpeta_fotos_url:
        photo_folder_id = carpeta_fotos_url.split('/')[-1]
        print(f"🖼️ Buscando fotos en carpeta: {photo_folder_id}")
        photos = list_photos_in_folder(photo_folder_id)
        print(f"📸 Se encontraron {len(photos)} foto(s)")
        if photos:
            insert_images_at_end(doc_id, photos)
    else:
        print("⚠️ No hay URL de carpeta de fotos")

    # Generar PDF
    print("📑 Generando PDF...")
    pdf_filename = f"{copy_title}.pdf"
    request = drive_service.files().export_media(fileId=doc_id, mimeType='application/pdf')
    pdf_path = os.path.join(os.getcwd(), pdf_filename)
    with open(pdf_path, 'wb') as f:
        f.write(request.execute())

    print(f"⬆️ Subiendo PDF a Google Drive...")
    media = MediaFileUpload(pdf_path, mimetype='application/pdf')
    uploaded_pdf = drive_service.files().create(
        body={'name': pdf_filename, 'parents': [date_folder]},
        media_body=media,
        fields='id'
    ).execute()

    drive_service.permissions().create(
        fileId=uploaded_pdf['id'],
        body={'role': 'reader', 'type': 'anyone'}
    ).execute()

    # Limpiar archivo local
    try:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            print(f"🗑️ Archivo local eliminado: {pdf_filename}")
    except PermissionError:
        print(f"⚠️ No se pudo eliminar el archivo local: {pdf_filename} (en uso)")
    except Exception as e:
        print(f"⚠️ Error al eliminar archivo: {e}")

    print(f"\n✅ ¡COMPLETADO! DOC y PDF generados en la carpeta de fecha: {fecha}")
    print(f"🔗 Ver documento: https://docs.google.com/document/d/{doc_id}/edit")
    print(f"🔗 Ver PDF: https://drive.google.com/file/d/{uploaded_pdf['id']}/view")

# -----------------------------
# EJECUCIÓN
# -----------------------------
print("=" * 60)
print("🔧 GENERADOR DE REPORTES PDF - VENTOLOGIX")
print("=" * 60)
print("\nOpciones:")
print("1. Generar reporte")
print("2. Verificar plantilla")

opcion = input("\nSelecciona una opción (1 o 2): ").strip()

if opcion == "2":
    print("\n🔍 Verificando plantilla...")
    verify_template_placeholders()
    print("\n✅ Verificación completada")
    print(f"🔗 Ver plantilla: https://docs.google.com/document/d/{TEMPLATE_ID}/edit")
elif opcion == "1":
    numero_serie = input("\nIngresa el número de serie: ").strip()
    fecha_input = input("Ingresa la fecha (ej. 5/11/2025, 05-11-2025, 2025-11-05): ").strip()
    print()
    create_report(numero_serie, fecha_input)
else:
    print("❌ Opción inválida")
