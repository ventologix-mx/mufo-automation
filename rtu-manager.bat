@echo off
REM ============================================
REM RTU Stack Manager (Windows)
REM Script de gestión para el stack Docker
REM ============================================

setlocal enabledelayedexpansion

set CONTAINER_NAME=rtu-stack

if "%1"=="" goto help
if "%1"=="help" goto help
if "%1"=="start" goto start
if "%1"=="stop" goto stop
if "%1"=="restart" goto restart
if "%1"=="build" goto build
if "%1"=="logs" goto logs
if "%1"=="status" goto status
if "%1"=="shell" goto shell
if "%1"=="tail" goto tail
if "%1"=="restart-service" goto restart_service
if "%1"=="env-check" goto env_check

echo [ERROR] Comando desconocido: %1
echo.
goto help

:start
echo ========================================
echo   Iniciando RTU Stack
echo ========================================
docker-compose up -d
if %ERRORLEVEL% EQU 0 (
    echo [OK] Stack iniciado
    echo.
    goto status
) else (
    echo [ERROR] No se pudo iniciar el stack
    exit /b 1
)

:stop
echo ========================================
echo   Deteniendo RTU Stack
echo ========================================
docker-compose down
if %ERRORLEVEL% EQU 0 (
    echo [OK] Stack detenido
) else (
    echo [ERROR] No se pudo detener el stack
    exit /b 1
)
goto end

:restart
echo ========================================
echo   Reiniciando RTU Stack
echo ========================================
docker-compose restart
if %ERRORLEVEL% EQU 0 (
    echo [OK] Stack reiniciado
    echo.
    goto status
) else (
    echo [ERROR] No se pudo reiniciar el stack
    exit /b 1
)

:build
echo ========================================
echo   Construyendo imagen Docker
echo ========================================
docker-compose build --no-cache
if %ERRORLEVEL% EQU 0 (
    echo [OK] Imagen construida
) else (
    echo [ERROR] No se pudo construir la imagen
    exit /b 1
)
goto end

:logs
echo ========================================
echo   Logs del RTU Stack
echo ========================================
echo [INFO] Presiona Ctrl+C para salir
echo.
docker-compose logs -f --tail=50
goto end

:status
echo ========================================
echo   Estado del RTU Stack
echo ========================================
docker ps | findstr "%CONTAINER_NAME%" >nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Container esta corriendo
    echo.
    echo [INFO] Estado de los procesos:
    docker exec -it %CONTAINER_NAME% supervisorctl status
) else (
    echo [WARNING] Container no esta corriendo
)
goto end

:shell
echo ========================================
echo   Abriendo shell en el container
echo ========================================
docker exec -it %CONTAINER_NAME% bash
goto end

:tail
if "%2"=="" (
    echo [ERROR] Debes especificar el script: acrel, pressure, o mqtt_to_mysql
    exit /b 1
)
echo ========================================
echo   Logs de %2
echo ========================================
echo [INFO] Presiona Ctrl+C para salir
echo.
docker exec -it %CONTAINER_NAME% tail -f /var/log/supervisor/%2.out.log
goto end

:restart_service
if "%2"=="" (
    echo [ERROR] Debes especificar el script: acrel, pressure, mqtt_to_mysql, o all
    exit /b 1
)
echo ========================================
echo   Reiniciando servicio: %2
echo ========================================
docker exec -it %CONTAINER_NAME% supervisorctl restart %2
if %ERRORLEVEL% EQU 0 (
    echo [OK] Servicio reiniciado
    echo.
    docker exec -it %CONTAINER_NAME% supervisorctl status %2
) else (
    echo [ERROR] No se pudo reiniciar el servicio
    exit /b 1
)
goto end

:env_check
echo ========================================
echo   Verificando configuracion .env
echo ========================================
if not exist .env (
    echo [ERROR] Archivo .env no encontrado
    exit /b 1
)
echo [OK] Archivo .env encontrado
echo.
echo Verificando variables criticas:
findstr /B "DB_HOST=" .env >nul && echo [OK] DB_HOST configurado || echo [ERROR] DB_HOST no encontrado
findstr /B "DB_USER=" .env >nul && echo [OK] DB_USER configurado || echo [ERROR] DB_USER no encontrado
findstr /B "DB_PASSWORD=" .env >nul && echo [OK] DB_PASSWORD configurado || echo [ERROR] DB_PASSWORD no encontrado
findstr /B "DB_DATABASE=" .env >nul && echo [OK] DB_DATABASE configurado || echo [ERROR] DB_DATABASE no encontrado
findstr /B "MQTT_BROKER=" .env >nul && echo [OK] MQTT_BROKER configurado || echo [ERROR] MQTT_BROKER no encontrado
findstr /B "MQTT_PORT=" .env >nul && echo [OK] MQTT_PORT configurado || echo [ERROR] MQTT_PORT no encontrado
goto end

:help
echo RTU Stack Manager (Windows)
echo.
echo Uso:
echo   rtu-manager.bat [comando] [argumentos]
echo.
echo Comandos disponibles:
echo   start              Inicia el stack Docker
echo   stop               Detiene el stack Docker
echo   restart            Reinicia el stack Docker
echo   build              Reconstruye la imagen Docker
echo   logs               Muestra logs en tiempo real
echo   status             Muestra el estado del stack y procesos
echo   shell              Abre una terminal dentro del container
echo   tail ^<script^>      Muestra logs de un script especifico (acrel, pressure, mqtt_to_mysql^)
echo   restart-service ^<script^>  Reinicia un servicio especifico
echo   env-check          Verifica la configuracion del .env
echo   help               Muestra esta ayuda
echo.
echo Ejemplos:
echo   rtu-manager.bat start
echo   rtu-manager.bat logs
echo   rtu-manager.bat tail pressure
echo   rtu-manager.bat restart-service mqtt_to_mysql
echo   rtu-manager.bat env-check
echo.
goto end

:end
endlocal
