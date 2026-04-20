#!/bin/bash

# ============================================
# RTU Stack Manager
# Script de gestión para el stack Docker
# ============================================

set -e

COMPOSE_FILE="docker-compose.yml"
CONTAINER_NAME="rtu-stack"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funciones auxiliares
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Verificar que docker-compose esté instalado
check_docker() {
    if ! command -v docker-compose &> /dev/null; then
        print_error "docker-compose no está instalado"
        exit 1
    fi
}

# Comandos
cmd_start() {
    print_header "Iniciando RTU Stack"
    docker-compose up -d
    print_success "Stack iniciado"
    echo ""
    cmd_status
}

cmd_stop() {
    print_header "Deteniendo RTU Stack"
    docker-compose down
    print_success "Stack detenido"
}

cmd_restart() {
    print_header "Reiniciando RTU Stack"
    docker-compose restart
    print_success "Stack reiniciado"
    echo ""
    cmd_status
}

cmd_build() {
    print_header "Construyendo imagen Docker"
    docker-compose build --no-cache
    print_success "Imagen construida"
}

cmd_logs() {
    print_header "Logs del RTU Stack"
    print_info "Presiona Ctrl+C para salir"
    echo ""

    if [ -z "$1" ]; then
        docker-compose logs -f --tail=50
    else
        docker-compose logs -f --tail=50 | grep "$1"
    fi
}

cmd_status() {
    print_header "Estado del RTU Stack"

    # Estado del container
    if docker ps | grep -q "$CONTAINER_NAME"; then
        print_success "Container está corriendo"

        # Estado de los procesos
        echo ""
        print_info "Estado de los procesos:"
        docker exec -it $CONTAINER_NAME supervisorctl status
    else
        print_warning "Container no está corriendo"
    fi
}

cmd_shell() {
    print_header "Abriendo shell en el container"
    docker exec -it $CONTAINER_NAME bash
}

cmd_tail() {
    script=$1

    if [ -z "$script" ]; then
        print_error "Debes especificar el script: acrel, pressure, o mqtt_to_mysql"
        exit 1
    fi

    print_header "Logs de $script"
    print_info "Presiona Ctrl+C para salir"
    echo ""

    docker exec -it $CONTAINER_NAME tail -f /var/log/supervisor/${script}.out.log
}

cmd_restart_service() {
    script=$1

    if [ -z "$script" ]; then
        print_error "Debes especificar el script: acrel, pressure, mqtt_to_mysql, o all"
        exit 1
    fi

    print_header "Reiniciando servicio: $script"
    docker exec -it $CONTAINER_NAME supervisorctl restart $script
    print_success "Servicio reiniciado"
    echo ""
    docker exec -it $CONTAINER_NAME supervisorctl status $script
}

cmd_env_check() {
    print_header "Verificando configuración .env"

    if [ ! -f .env ]; then
        print_error "Archivo .env no encontrado"
        exit 1
    fi

    print_success "Archivo .env encontrado"
    echo ""

    # Variables críticas
    critical_vars=("DB_HOST" "DB_USER" "DB_PASSWORD" "DB_DATABASE" "MQTT_BROKER" "MQTT_PORT")

    missing=0
    for var in "${critical_vars[@]}"; do
        if grep -q "^${var}=" .env; then
            value=$(grep "^${var}=" .env | cut -d '=' -f2)
            if [ -z "$value" ]; then
                print_warning "$var está vacío"
                missing=1
            else
                print_success "$var configurado"
            fi
        else
            print_error "$var no encontrado"
            missing=1
        fi
    done

    if [ $missing -eq 0 ]; then
        echo ""
        print_success "Todas las variables críticas están configuradas"
    else
        echo ""
        print_error "Algunas variables críticas faltan o están vacías"
        exit 1
    fi
}

cmd_help() {
    cat << EOF
${BLUE}RTU Stack Manager${NC}

${GREEN}Uso:${NC}
  ./rtu-manager.sh [comando] [argumentos]

${GREEN}Comandos disponibles:${NC}
  start              Inicia el stack Docker
  stop               Detiene el stack Docker
  restart            Reinicia el stack Docker
  build              Reconstruye la imagen Docker
  logs [filtro]      Muestra logs en tiempo real (opcional: filtrar por palabra)
  status             Muestra el estado del stack y procesos
  shell              Abre una terminal dentro del container
  tail <script>      Muestra logs de un script específico (acrel, pressure, mqtt_to_mysql)
  restart-service <script>  Reinicia un servicio específico
  env-check          Verifica la configuración del .env
  help               Muestra esta ayuda

${GREEN}Ejemplos:${NC}
  ./rtu-manager.sh start
  ./rtu-manager.sh logs acrel
  ./rtu-manager.sh tail pressure
  ./rtu-manager.sh restart-service mqtt_to_mysql
  ./rtu-manager.sh env-check

EOF
}

# Main
check_docker

case "$1" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    build)
        cmd_build
        ;;
    logs)
        cmd_logs "$2"
        ;;
    status)
        cmd_status
        ;;
    shell)
        cmd_shell
        ;;
    tail)
        cmd_tail "$2"
        ;;
    restart-service)
        cmd_restart_service "$2"
        ;;
    env-check)
        cmd_env_check
        ;;
    help|"")
        cmd_help
        ;;
    *)
        print_error "Comando desconocido: $1"
        echo ""
        cmd_help
        exit 1
        ;;
esac
