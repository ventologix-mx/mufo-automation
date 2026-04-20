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
    "database": os.getenv("DB_DATABASE_DOOBLE")
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)

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

def cerrar_conexion():
    if conn.is_connected():
        cursor.close()
        conn.close()
        logging.info("🔴 Conexión a base cerrada")

atexit.register(cerrar_conexion)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("🟢 Conectado al broker MQTT")
        client.subscribe(MQTT_TOPIC)
    else:
        logging.error(f"🔴 Error de conexión MQTT: {rc}")

def on_message(client, userdata, msg):
    global conn, cursor

    try:
        payload = json.loads(msg.payload.decode())
        logging.info(f"📨 Mensaje recibido: {payload}")

        id_kpm = payload.get("id")
        if not id_kpm:
            logging.error("❌ No se encontró 'id' en payload")
            return

        cursor.execute(
            "SELECT id, id_cliente FROM dispositivos WHERE id_kpm = %s",
            (id_kpm,)
        )
        dispositivo = cursor.fetchone()
        if not dispositivo:
            logging.error(f"❌ Dispositivo desconocido, ignorando mensaje: {id_kpm}")
            return

        device_id  = dispositivo["id"]
        id_cliente = dispositivo["id_cliente"]

        time_str = payload.get("time")
        if not time_str:
            logging.error("❌ No se encontró 'time' en payload")
            return
        time_fmt = datetime.strptime(time_str, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")

        ua = float(payload.get("ua", 0))
        ub = float(payload.get("ub", 0))
        uc = float(payload.get("uc", 0))
        ia = float(payload.get("ia", 0))
        ib = float(payload.get("ib", 0))
        ic = float(payload.get("ic", 0))

        values = (device_id, ua, ub, uc, ia, ib, ic, time_fmt)

        cursor.execute("""
            INSERT INTO telemetria (device_id, ua, ub, uc, ia, ib, ic, time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, values)

        conn.commit()
        logging.info(f"✅ Insertado | device_id={device_id} | cliente={id_cliente} | {time_fmt}")

    except mysql.connector.Error as db_err:
        logging.error(f"❌ Error en base de datos: {db_err}")
        if not conn.is_connected():
            logging.warning("🔄 Reconectando a base de datos...")
            conn = conectar_db()
            cursor = conn.cursor(dictionary=True)
    except Exception as e:
        logging.error(f"❌ Error general: {str(e)}")

client = mqtt.Client(protocol=mqtt.MQTTv311)
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()