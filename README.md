# mufo-automation

Repositorio central de automatización para **Grupo Mufo**. Contiene los scripts que recolectan datos vía MQTT y los insertan en MySQL, tanto para **Ventologix** (compresores Acrel, sensores de presión, RTU) como para **Dooble** (telemetría de dispositivos). Todo corre en un solo contenedor Docker supervisado.

## Requisitos

- Docker
- Git

## Instalación en VM

```bash
# 1. Clonar el repositorio
git clone <url-del-repo> mufo-automation
cd mufo-automation

# 2. Configurar credenciales
cp .env.example .env
nano .env

# 3. Build
docker build -t mufo-automation .

# 4. Correr
docker run -d \
  --name rtu-stack \
  --env-file .env \
  --network host \
  -v $(pwd)/logs:/var/log/supervisor \
  --restart unless-stopped \
  mufo-automation
```

Listo. Los 4 scripts corren automáticamente.

## Verificar que funciona

```bash
# Estado de los procesos
docker exec -it rtu-stack supervisorctl status

# Logs por script
tail -f logs/acrel.log
tail -f logs/pressure.log
tail -f logs/mqtt_to_mysql.log
tail -f logs/dooble.log
```

## Actualizar después de cambios

```bash
git pull
docker stop rtu-stack && docker rm rtu-stack
docker build --no-cache -t mufo-automation .
docker run -d \
  --name rtu-stack \
  --env-file .env \
  --network host \
  -v $(pwd)/logs:/var/log/supervisor \
  --restart unless-stopped \
  mufo-automation
```

## Estructura del proyecto

```
mufo-automation/
├── Dockerfile             # Imagen con supervisor (corre los 4 scripts)
├── supervisord.conf       # Config de supervisor
├── requirements.txt       # Dependencias Python
├── .env                   # Credenciales (no versionar)
├── .env.example           # Template de variables de entorno
└── scripts/
    ├── acrel.py           # MQTT → tabla pruebas/hoy y pruebeas/pruebas (dispositivos Acrel) [Ventologix]
    ├── pressure.py        # MQTT → tabla pruebas/presion (sensores de presión/RTU) [Ventologix]
    ├── mqtt_to_mysql.py   # MQTT → tabla pruebas/hoy y pruebas/pruebas (topics dinámicos desde BD) [Ventologix]
    └── dooble.py          # MQTT → tabla Dooble/datos (dispositivos Dooble) [Dooble]
```

## Variables de entorno requeridas

| Variable             | Descripción                    |
| -------------------- | ------------------------------ |
| `MQTT_BROKER`        | IP del broker MQTT             |
| `MQTT_PORT`          | Puerto MQTT (default 1883)     |
| `MQTT_TOPIC`         | Topic principal a escuchar     |
| `DB_HOST`            | IP del servidor MySQL          |
| `DB_USER`            | Usuario de la base de datos    |
| `DB_PASSWORD`        | Contraseña de la base de datos |
| `DB_DATABASE`        | Base de datos Ventologix       |
| `DB_DATABASE_DOOBLE` | Base de datos Dooble           |
