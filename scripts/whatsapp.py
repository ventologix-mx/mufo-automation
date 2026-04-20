import mysql.connector
from twilio.rest import Client
import json
import dotenv
import os

dotenv.load_dotenv()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_DATABASE", "ventologix")
}

def format_whatsapp_number(number):
    if not number.startswith("whatsapp:"):
        print(f"DEBUG: Agregando prefijo whatsapp: al número {number}")
        return "whatsapp:" + number
    return number

def enviar_alertas():
    print("DEBUG: Iniciando conexión a la base de datos")
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)

    print("DEBUG: Consultando alertas activas")
    cursor.execute("SELECT * FROM alertas WHERE activo = TRUE")
    alertas = cursor.fetchall()
    print(f"DEBUG: Se encontraron {len(alertas)} alertas activas")

    for alerta in alertas:
        print(f"DEBUG: Procesando alerta ID {alerta['id']} para cliente {alerta['nombre_cliente']}")

        params = (
            alerta['dispositivo_id'],
            alerta['identificador_proyecto'],
            alerta['nombre_linea'],
            alerta['segundos_por_registro'],
            alerta['voltaje'],
        )

        cursor.callproc('ResumenAyer', params)

        for result in cursor.stored_results():
            resumen = result.fetchone()
            if not resumen:
                print(f"DEBUG: No hay datos para alerta ID {alerta['id']}")
                continue

            horas_noload = resumen['HorasNoLoad']
            horas_trabajadas = resumen['HorasTrabajadas']

            if horas_trabajadas == 0:
                print(f"DEBUG: Horas trabajadas es 0 para alerta ID {alerta['id']}, se enviará mensaje sin cálculo")

                content_vars = {
                    "1": alerta['nombre_cliente'],
                    "2": "SIN DATOS",
                    "3": "No se registraron horas trabajadas ayer en el sistema.",
                    "4": "0.00",
                    "5": "0.00",
                    "6": "0.00"
                }
                plantilla_sid = alerta['plantilla']
                if not plantilla_sid.startswith("HX"):
                    print(f"WARNING: El content_sid parece no ser un SID válido: {plantilla_sid}")

                numero_destino = format_whatsapp_number(alerta['numero_whatsapp'])
                print(f"DEBUG: Enviando mensaje a {numero_destino} usando plantilla {plantilla_sid} con variables {json.dumps(content_vars)}")

                try:
                    message = client.messages.create(
                        from_=TWILIO_WHATSAPP_FROM,
                        to=numero_destino,
                        content_sid=plantilla_sid,
                        content_variables=json.dumps(content_vars)
                    )
                    print(f"DEBUG: Mensaje enviado a {alerta['nombre_cliente']} - SID: {message.sid}")
                except Exception as e:
                    print(f"ERROR: Enviando mensaje a {alerta['nombre_cliente']}: {e}")
                continue

            porcentaje_noload = (horas_noload / horas_trabajadas) * 100
            print(f"DEBUG: Porcentaje NOLOAD para alerta ID {alerta['id']}: {porcentaje_noload:.2f}%")

            if porcentaje_noload < 10:
                estado = "BAJO"
                explicacion = "compresor con muy poco tiempo sin carga, reflejando falta de descansos y posible sobreuso."
            elif porcentaje_noload > 20:  # Cambio aquí, ahora > 10 es ALTO
                estado = "ALTO"
                explicacion = "compresor trabajando sin producir aire útil, generando consumo energético innecesario y costos adicionales."
            else:
                estado = "NORMAL"
                explicacion = "funcionamiento dentro de los parámetros esperados para un uso eficiente."

            content_vars = {
                "1": alerta['nombre_cliente'],
                "2": estado,
                "3": explicacion,
                "4": f"{horas_noload:.2f}",
                "5": f"{horas_trabajadas:.2f}",
                "6": f"{porcentaje_noload:.2f}"
            }

            if estado == "NORMAL":
                print(f"DEBUG: Estado NORMAL para {alerta['nombre_cliente']}, no se envía mensaje.")
                continue

            plantilla_sid = alerta['plantilla']
            if not plantilla_sid.startswith("HX"):
                print(f"WARNING: El content_sid parece no ser un SID válido: {plantilla_sid}")

            numero_destino = format_whatsapp_number(alerta['numero_whatsapp'])
            print(f"DEBUG: Enviando mensaje a {numero_destino} usando plantilla {plantilla_sid} con variables {json.dumps(content_vars)}")

            try:
                message = client.messages.create(
                    from_=TWILIO_WHATSAPP_FROM,
                    to=numero_destino,
                    content_sid=plantilla_sid,
                    content_variables=json.dumps(content_vars)
                )
                print(f"DEBUG: Mensaje enviado a {alerta['nombre_cliente']} - SID: {message.sid}")
            except Exception as e:
                print(f"ERROR: Enviando mensaje a {alerta['nombre_cliente']}: {e}")

    cursor.close()
    cnx.close()
    print("DEBUG: Proceso finalizado")

if __name__ == "__main__":
    enviar_alertas()