#!/bin/bash
# Script para correr MetaTrader 5 dentro de Docker y exponer datos via HTTP
# Usa la imagen chota5511/mt5 que ya tiene MT5 + Wine + XFCE

set -e

CONTAINER_NAME="mt5-server"
IMAGE="chota5511/mt5"
PORT_MT5_API="8570"  # Puerto para el API de datos MT5

echo "[MT5-DOCKER] Iniciando contenedor MT5..."

# Crear directorio para compartir config
mkdir -p /tmp/mt5-docker

# Script Python que corre DENTRO del contenedor para exponer datos MT5
cat > /tmp/mt5-docker/mt5_http_server.py << 'PYEOF'
#!/usr/bin/env python3
"""
MT5 HTTP API Server — corre dentro del contenedor Docker.
Expone datos de MetaTrader5 via HTTP para que el agente los consuma.
"""
import json, os, sys
sys.path.insert(0, '/config/mt5/python')
from http.server import HTTPServer, BaseHTTPRequestHandler

# Paths dentro del contenedor
MT5_TERMINAL = "/config/mt5/terminal64.exe"

class MT5Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/check":
            result = self._check_mt5()
        elif self.path == "/account":
            result = self._get_account()
        elif self.path.startswith("/tick/"):
            symbol = self.path.split("/")[-1]
            result = self._get_tick(symbol)
        elif self.path.startswith("/bars/"):
            parts = self.path.split("/")
            symbol = parts[2] if len(parts) > 2 else "EURUSD"
            n = int(parts[3]) if len(parts) > 3 else 20
            result = self._get_bars(symbol, n)
        else:
            result = {"status": "error", "error": "unknown endpoint"}
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
    
    def _init_mt5(self):
        import MetaTrader5 as mt5
        if not mt5.initialize(path=MT5_TERMINAL):
            return None, str(mt5.last_error())
        return mt5, None
    
    def _login(self, mt5):
        ok = mt5.login(login=12760229, password="tsqx65", server="ICMarketsSC-Demo01")
        return ok
    
    def _check_mt5(self):
        try:
            import MetaTrader5 as mt5
            term = os.path.exists(MT5_TERMINAL)
            init = mt5.initialize(path=MT5_TERMINAL)
            if init:
                mt5.shutdown()
            return {"status": "ok", "terminal": term, "mt5_init": bool(init)}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _get_account(self):
        mt5, err = self._init_mt5()
        if err:
            return {"status": "error", "error": err}
        if not self._login(mt5):
            return {"status": "error", "error": "login failed"}
        acc = mt5.account_info()
        mt5.shutdown()
        if acc:
            return {"status": "ok", "balance": acc.balance, "equity": acc.equity,
                    "margin": acc.margin, "leverage": acc.leverage, "server": acc.server}
        return {"status": "error"}
    
    def _get_tick(self, symbol):
        mt5, err = self._init_mt5()
        if err:
            return {"status": "error", "error": err}
        if not self._login(mt5):
            return {"status": "error", "error": "login failed"}
        tick = mt5.symbol_info_tick(symbol)
        mt5.shutdown()
        if tick:
            return {"status": "ok", "bid": tick.bid, "ask": tick.ask, "spread": tick.spread}
        return {"status": "no_data", "symbol": symbol}
    
    def _get_bars(self, symbol, n):
        mt5, err = self._init_mt5()
        if err:
            return {"status": "error", "error": err}
        if not self._login(mt5):
            return {"status": "error", "error": "login failed"}
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, n)
        mt5.shutdown()
        if rates is not None:
            bars = [{"time": str(r.time), "open": r.open, "high": r.high, 
                     "low": r.low, "close": r.close, "volume": r.tick_volume} for r in rates]
            return {"status": "ok", "bars": bars}
        return {"status": "no_data", "symbol": symbol}
    
    def log_message(self, format, *args):
        pass  # silencio

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("MT5_API_PORT", "8570"))
    server = HTTPServer(("0.0.0.0", port), MT5Handler)
    print(f"[MT5-API] Servidor iniciado en puerto {port}")
    server.serve_forever()
PYEOF

echo "[MT5-DOCKER] Script API creado en /tmp/mt5-docker/mt5_http_server.py"
echo "[MT5-DOCKER] Para ejecutar:"
echo "  docker run -d --name mt5-server --rm -p 8570:8570 \\"
echo "    -v /tmp/mt5-docker:/scripts \\"
echo "    chota5511/mt5 bash -c 'python3 /scripts/mt5_http_server.py 8570'"
echo ""
echo "[MT5-DOCKER] Luego probar:"
echo "  curl -s http://localhost:8570/check"
echo "  curl -s http://localhost:8570/tick/EURUSD"
