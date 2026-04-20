import json
import os
from datetime import datetime, timedelta
import pytz
import mysql.connector
from mysql.connector import Error
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

print("Antes de load_dotenv()")
load_dotenv()
print("Después de load_dotenv()")

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_TOPIC = "ADW300/TEST1"

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_DATABASE = os.getenv("DB_DATABASE")

def find_val(points, id):
    return next((p["val"] for p in points if p["id"] == id), 0)

def redondear_a_30s(timestamp_ms):
    # Convertir timestamp UTC a datetime UTC
    dt_utc = datetime.utcfromtimestamp(timestamp_ms / 1000.0).replace(tzinfo=pytz.UTC)

    # Convertir a hora de Monterrey
    monterrey_tz = pytz.timezone("America/Monterrey")
    dt_mty = dt_utc.astimezone(monterrey_tz)

    # Redondear segundos a 0 o 30
    segundos = dt_mty.second
    if segundos < 15:
        nuevos_segundos = 0
    elif segundos < 45:
        nuevos_segundos = 30
    else:
        nuevos_segundos = 0
        dt_mty += timedelta(minutes=1)

    return dt_mty.replace(second=nuevos_segundos, microsecond=0)


def insert_data(payload):
    try:
        # Conexión a MySQL
        connection = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_DATABASE
        )

        if connection.is_connected():
            cursor = connection.cursor(dictionary=True)

            # Paso 1: Extraer id_kpm
            id_kpm = next((p["val"] for p in payload["data"][0]["point"] if p["id"] == 0), None)
            if not id_kpm:
                print("ID_KPM no encontrado en el mensaje.")
                return

            # Paso 2: Buscar id_cliente
            select_query = f"SELECT id_cliente FROM dispositivo WHERE id_kpm = '{id_kpm}'"
            cursor.execute(select_query)
            result = cursor.fetchone()
            if not result:
                print(f"No se encontró id_cliente para id_kpm={id_kpm}")
                return
            id_cliente = result["id_cliente"]

            # Paso 3: Obtener y redondear timestamp `tp` del payload
            tp_raw = payload["data"][0].get("tp")
            if tp_raw is None:
                print("Timestamp 'tp' no encontrado en el payload.")
                return

            # Convertir y redondear a :00 o :30
            formatted_time = redondear_a_30s(tp_raw).strftime("%Y-%m-%d %H:%M:%S")

            # Paso 3.5: Verificar si el compresor requiere multiplicar corrientes x2
            cursor.execute(
                "SELECT multiplicar_por_dos FROM compresores WHERE id_cliente = %s LIMIT 1",
                (id_cliente,)
            )
            comp_result = cursor.fetchone()
            multiplicar_por_dos = bool(comp_result and comp_result.get('multiplicar_por_dos') == 1)

            # Paso 4: Valores eléctricos
            points = payload["data"][0].get("point", [])
            ua = find_val(points, 1)
            ub = find_val(points, 2)
            uc = find_val(points, 3)
            ia = find_val(points, 7)
            ib = find_val(points, 8)
            ic = find_val(points, 9)

            if multiplicar_por_dos:
                ia *= 2
                ib *= 2
                ic *= 2
                print(f"⚡ Corrientes multiplicadas x2 para id_cliente {id_cliente}")

            insert_electrico = """
                INSERT INTO pruebas (device_id, ua, ub, uc, ia, ib, ic, time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """

            insert_hoy = """
                INSERT INTO hoy (device_id, ua, ub, uc, ia, ib, ic, time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """
            
            # Insertar en tabla pruebas
            cursor.execute(insert_electrico, (id_cliente, ua, ub, uc, ia, ib, ic, formatted_time))
            print(f"  ✓ Insertado en tabla 'pruebas' - id_cliente {id_cliente}")
            
            # Insertar en tabla hoy
            cursor.execute(insert_hoy, (id_cliente, ua, ub, uc, ia, ib, ic, formatted_time))
            print(f"  ✓ Insertado en tabla 'hoy' - id_cliente {id_cliente}")

            # Confirmar cambios
            connection.commit()
            print(f"✅ Datos confirmados para id_cliente {id_cliente} a {formatted_time} - UA:{ua} UB:{ub} UC:{uc} IA:{ia} IB:{ib} IC:{ic}")

    except Error as e:
        print("❌ Error en MySQL:", e)

    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# Callback cuando se recibe un mensaje MQTT
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        insert_data(payload)
    except Exception as e:
        print("❌ Error procesando mensaje MQTT:", e)

# Configurar cliente MQTT
client = mqtt.Client(protocol=mqtt.MQTTv311)
client.on_message = on_message

print("Conectando a MQTT...")
client.connect(MQTT_BROKER, MQTT_PORT)
client.subscribe(MQTT_TOPIC)
print(f"Escuchando en topic: {MQTT_TOPIC}")

# Ejecutar para siempre
client.loop_forever()