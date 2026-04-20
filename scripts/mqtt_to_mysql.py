import paho.mqtt.client as mqtt
import mysql.connector
import json
from datetime import datetime
import logging
import sys
from dotenv import load_dotenv
import os
import time
import atexit

# Cargar variables de entorno
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC")

db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_DATABASE")
}

# Configurar logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)

# Conexión persistente a base
def conectar_db():
    while True:
        try:
            conn = mysql.connector.connect(**db_config)
            if conn.is_connected():
                logging.info("🟢 Conectado a la base de datos")
                return conn
        except Exception as e:
            logging.error(f"❌ Error al conectar a la base de datos: {e}")
            time.sleep(3)

conn = conectar_db()
cursor = conn.cursor(dictionary=True)

# Cerrar conexión al terminar
def cerrar_conexion():
    if conn.is_connected():
        cursor.close()
        conn.close()
        logging.info("🔴 Conexión a base cerrada")

atexit.register(cerrar_conexion)

# Callback al conectar al broker
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("🟢 Conectado al broker MQTT")
        client.subscribe(MQTT_TOPIC)
    else:
        logging.error(f"🔴 Error de conexión MQTT: {rc}")

# Callback al recibir mensaje
def on_message(client, userdata, msg):
    global conn, cursor

    try:
        payload = json.loads(msg.payload.decode())
        logging.info(f"📨 Mensaje recibido completo: {payload}")

        # Obtener id_kpm directamente del campo 'id'
        id_kpm = payload.get("id")
        if not id_kpm:
            logging.error("❌ No se encontró 'id' en payload")
            return
        
        # Consultar id_cliente con id_kpm
        cursor.execute("SELECT id_cliente FROM dispositivo WHERE id_kpm = %s", (id_kpm,))
        result = cursor.fetchone()
        if not result:
            logging.error(f"Dispositivo no encontrado: {id_kpm}")
            return
        id_device = result['id_cliente']

        # Verificar si el compresor requiere multiplicar corrientes x2
        cursor.execute(
            "SELECT multiplicar_por_dos FROM compresores WHERE id_cliente = %s LIMIT 1",
            (id_device,)
        )
        comp_result = cursor.fetchone()
        multiplicar_por_dos = bool(comp_result and comp_result.get('multiplicar_por_dos') == 1)

        # Parsear timestamp en 'time' (string 'YYYYMMDDHHMMSS')
        time_str = payload.get("time")
        if not time_str:
            logging.error("❌ No se encontró 'time' en payload")
            return
        time_fmt = datetime.strptime(time_str, "%Y%m%d%H%M%S").strftime('%Y-%m-%d %H:%M:%S')

        # Extraer variables eléctricas (usar 0.0 si falta)
        ua = float(payload.get("ua", 0))
        ub = float(payload.get("ub", 0))
        uc = float(payload.get("uc", 0))
        ia = float(payload.get("ia", 0))
        ib = float(payload.get("ib", 0))
        ic = float(payload.get("ic", 0))

        # Multiplicar corrientes x2 si está configurado
        if multiplicar_por_dos:
            ia *= 2
            ib *= 2
            ic *= 2
            logging.info(f"⚡ Corrientes multiplicadas x2 para device {id_device}")
        # Insertar en BD
        insert_query = """
            INSERT INTO pruebas (device_id, ua, ub, uc, ia, ib, ic, time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_hoy = """
            INSERT INTO hoy (device_id, ua, ub, uc, ia, ib, ic, time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (id_device, ua, ub, uc, ia, ib, ic, time_fmt)
        cursor.execute(insert_query, values)
        cursor.execute(insert_hoy, values)
        conn.commit()

        logging.info(f"✅ Insertado Device {id_device} | {time_fmt}")

    except mysql.connector.Error as db_err:
        logging.error(f"❌ Error en base de datos: {db_err}")
        if not conn.is_connected():
            logging.warning("🔄 Reintentando conexión a base de datos...")
            conn = conectar_db()
            cursor = conn.cursor(dictionary=True)
    except Exception as e:
        logging.error(f"❌ Error general: {str(e)}")

# Configurar cliente MQTT
client = mqtt.Client(protocol=mqtt.MQTTv311)
client.on_connect = on_connect
client.on_message = on_message

# Conectar al broker MQTT y loop infinito
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()