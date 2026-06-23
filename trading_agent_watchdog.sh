#!/bin/bash
# Watchdog del Trading Agent v7
# Corre cada 5 minutos vía cronjob de Hermes
# Si el agente no está corriendo y es horario de trading, lo reinicia

AGENT_DIR="/root/.hermes/projects/trading-agent"
AGENT_SCRIPT="agent_v7.py"
PID_FILE="/tmp/trading_agent_v7.pid"
DASHBOARD_PORT=8765

cd "$AGENT_DIR" || exit 1

# Verificar si el agente está corriendo
AGENT_RUNNING=false
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        AGENT_RUNNING=true
    else
        rm -f "$PID_FILE"
    fi
fi

# Verificar si el dashboard responde
DASHBOARD_OK=false
if curl -s "http://localhost:$DASHBOARD_PORT" >/dev/null 2>&1; then
    DASHBOARD_OK=true
fi

# Log
LOG_FILE="$AGENT_DIR/logs/watchdog.log"
mkdir -p "$AGENT_DIR/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Reportar estado
if $AGENT_RUNNING && $DASHBOARD_OK; then
    # Silencioso si todo bien
    exit 0
fi

# Si no está corriendo, reiniciar
if ! $AGENT_RUNNING; then
    log "AGENT CAÍDO — reiniciando..."
    cd "$AGENT_DIR"
    nohup python3 "$AGENT_SCRIPT" > /dev/null 2>&1 &
    echo $! > "$PID_FILE"
    sleep 3
    
    # Verificar que arrancó
    if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        log "✅ Agente v7 reiniciado (PID $(cat $PID_FILE))"
        echo "[WATCHDOG] Trading Agent v7 reiniciado automáticamente a las $(date '+%H:%M:%S')"
    else
        log "❌ FALLO AL REINICIAR"
        echo "[WATCHDOG] ERROR: No se pudo reiniciar Trading Agent v7"
        exit 1
    fi
fi

if ! $DASHBOARD_OK; then
    log "⚠️ Dashboard no responde en puerto $DASHBOARD_PORT — intentando levantar"
    # El dashboard lo levanta el agente automáticamente
fi

exit 0
