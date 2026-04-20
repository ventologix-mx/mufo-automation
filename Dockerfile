# ============================================
# Dockerfile para RTU Stack Completo
# Corre: acrel.py, pressure.py, mqtt_to_mysql.py
# ============================================
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/acrel.py ./acrel.py
COPY scripts/pressure.py ./pressure.py
COPY scripts/mqtt_to_mysql.py ./mqtt_to_mysql.py
COPY scripts/dooble.py ./dooble.py

RUN mkdir -p /var/log/supervisor

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD supervisorctl status | grep -c RUNNING || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
