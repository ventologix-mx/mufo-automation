from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import mysql.connector
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import smtplib
from email.message import EmailMessage
import time

# Cargar variables de entorno
load_dotenv()

# Configuración base de datos y correo
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_DATABASE = os.getenv("DB_DATABASE")

alias_name = "VTO LOGIX"
smtp_from = "andres.mirazo@ventologix.com"
smtp_password = os.getenv("SMTP_PASSWORD")
smtp_server = "smtp.gmail.com"
smtp_port = 587

admin_correos = [
    "hector.tovar@ventologix.com",
    "andres.mirazo@ventologix.com"
]

# Inicializar FastAPI (opcional)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def send_emergency_email(subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = admin_correos
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_from, smtp_password)
            server.send_message(msg)
        print(f"[{datetime.now()}] 📧 Correo de alerta enviado.")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error enviando correo: {e}")

def check_data():
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_DATABASE
        )
        cursor = conn.cursor()

        now = datetime.now()
        half_hour_ago = now - timedelta(minutes=30)

        start_time = half_hour_ago.strftime('%Y-%m-%d %H:%M:%S')
        end_time = now.strftime('%Y-%m-%d %H:%M:%S')

        query = """
        SELECT COUNT(*) FROM pruebas
        WHERE time BETWEEN %s AND %s
        """

        cursor.execute(query, (start_time, end_time))
        result = cursor.fetchone()

        if result and result[0] == 0:
            subject = f"🚨 Alerta: No se recibieron datos en 'pruebas'"
            body = f"No se encontraron registros en la tabla 'pruebas' entre {start_time} y {end_time}."
            send_emergency_email(subject, body)
        else:
            print(f"[{datetime.now()}] ✅ {result[0]} registros entre {start_time} y {end_time}")

    except mysql.connector.Error as err:
        print(f"[{datetime.now()}] ❌ Error de base de datos: {err}")
        subject = "🚨 Alerta: Error de conexión a base de datos"
        body = f"No se pudo conectar o consultar en la base de datos:\n{err}"
        send_emergency_email(subject, body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Ciclo infinito ejecutando cada 30 minutos
if __name__ == "__main__":
    while True:
        check_data()
        time.sleep(900)  # 900 segundos = 15 minutos