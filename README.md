# mufo-automation

Pipeline de automatización: MQTT → MySQL.

## Requisitos

- Docker >= 20.10
- Docker Compose >= 2.0
- Git

## Instalación en VM

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd mufo-automation

# 2. Configurar variables de entorno
cp .env.example .env
nano .env   # llenar credenciales

# 3. Levantar todo
docker compose up -d --build
```

Listo. Los 4 scripts corren automáticamente.

## Verificar que funciona

```bash
# Ver estado de los procesos
docker exec rtu-stack supervisorctl status

# Ver logs en tiempo real
docker compose logs -f

# Ver logs de un script específico
docker exec rtu-stack tail -f /var/log/supervisor/acrel.log
```

## Apagar / reiniciar

```bash
docker compose down           # apagar
docker compose restart        # reiniciar
docker compose up -d          # levantar sin rebuild
docker compose up -d --build  # rebuild + levantar
```

## Estructura del proyecto

```
mufo-automation/
├── docker-compose.yml     # Orquestación de servicios
├── Dockerfile             # Imagen con supervisor (corre los 4 scripts)
├── supervisord.conf       # Config de supervisor
├── requirements.txt       # Dependencias Python
├── .env                   # Credenciales (no versionar)
├── .env.example           # Template de variables de entorno
└── scripts/
    ├── acrel.py           # MQTT → tabla pruebas/hoy (dispositivos Acrel)
    ├── pressure.py        # MQTT → tabla pruebas/hoy (sensores de presión/RTU)
    ├── mqtt_to_mysql.py   # MQTT → tabla RTU_datos (topics dinámicos desde BD)
    └── dooble.py          # MQTT → tabla telemetria (base de datos Dooble)
```

## Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `MQTT_BROKER` | IP del broker MQTT |
| `MQTT_PORT` | Puerto MQTT (default 1883) |
| `MQTT_TOPIC` | Topic principal a escuchar |
| `DB_HOST` | IP del servidor MySQL |
| `DB_USER` | Usuario de la base de datos |
| `DB_PASSWORD` | Contraseña de la base de datos |
| `DB_DATABASE` | Base de datos principal |
| `DB_DATABASE_DOOBLE` | Base de datos Dooble |
