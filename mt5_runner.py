#!/usr/bin/env python3
"""
Wine MT5 Runner v7 — Arranca terminal64.exe, loguea IC Markets demo,
y mantiene MT5 vivo para que MetaTrader5 Python pueda conectarse via IPC.

Uso:
  python3 mt5_runner.py start    → arranca MT5 en background
  python3 mt5_runner.py stop     → mata MT5
  python3 mt5_runner.py status   → estado de MT5
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time

# Config
WINE = os.environ.get("WINE", "wine")
WINE_PREFIX = os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine"))
XVFB_RUN = os.environ.get("XVFB_RUN", "xvfb-run")
MT5_DIR = os.path.expanduser("~/.wine/drive_c/Program Files/MetaTrader 5")
MT5_TERMINAL = os.path.join(MT5_DIR, "terminal64.exe")
MT5_LOGIN = "12760229"
MT5_PASSWORD = "tsqx65"
MT5_SERVER = "ICMarketsSC-Demo01"
PID_FILE = "/tmp/mt5_terminal.pid"


def _run_wine_python(script_code: str, timeout: int = 30) -> dict:
    """Ejecuta código Python dentro de Wine y captura JSON."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir="/tmp"
    ) as f:
        f.write(script_code)
        script_path = f.name
    try:
        cmd = [XVFB_RUN, "-a", WINE, os.path.expanduser("~/.wine/drive_c/Python312/python.exe"), script_path]
        env = os.environ.copy()
        env["WINEPREFIX"] = WINE_PREFIX
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        stdout = result.stdout.strip()
        lines = [l for l in stdout.split("\n") if l.strip()]
        last_line = lines[-1] if lines else ""
        try:
            data = json.loads(last_line)
        except (json.JSONDecodeError, IndexError):
            data = {"status": "error", "error": "No se pudo parsear JSON", "stdout": stdout[:1000]}
        data["_exit_code"] = result.returncode
        return data
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def run_wine_initialize():
    """Prueba mt5.initialize() con terminal64.exe ya corriendo o no."""
    script = '''
import sys, json, os, threading, time
sys.path.insert(0, 'Z:\\\\root\\\\.wine\\\\drive_c\\\\Python312\\\\Lib\\\\site-packages')
import MetaTrader5 as mt5

result = []
def try_init():
    try:
        init = mt5.initialize(
            path=r"C:\\\\Program Files\\\\MetaTrader 5\\\\terminal64.exe"
        )
        err = str(mt5.last_error()) if not init and hasattr(mt5, 'last_error') else None
        result.append({"init": bool(init), "error": err})
        if init:
            log_ok = mt5.login(login=''' + MT5_LOGIN + ''', password="''' + MT5_PASSWORD + '''", server="''' + MT5_SERVER + '''")
            result[0]["login"] = bool(log_ok)
            if log_ok:
                acc = mt5.account_info()
                if acc:
                    result[0]["account"] = {"balance": acc.balance, "equity": acc.equity, "server": acc.server}
            mt5.shutdown()
    except Exception as e:
        result.append({"init": False, "error": str(e)})

# Primero verificar si terminal64.exe está ejecutándose
import subprocess as sp
try:
    out = sp.run(["wine", r"C:\\\\Program Files\\\\MetaTrader 5\\\\terminal64.exe", "--version"],
                  capture_output=True, timeout=3)
except:
    pass

t = threading.Thread(target=try_init)
t.daemon = True
t.start()
t.join(timeout=15)
if result:
    print(json.dumps(result[0]))
else:
    print(json.dumps({"init": False, "error": "timeout"}))
'''
    return _run_wine_python(script, timeout=25)


def start_mt5():
    """Arranca terminal64.exe y loguea la demo."""
    if os.path.exists(PID_FILE):
        try:
            pid = int(open(PID_FILE).read().strip())
            os.kill(pid, 0)
            print(f"MT5 ya está corriendo (PID {pid})")
            return True
        except (ProcessLookupError, ValueError):
            pass

    # Lanzar terminal64.exe con xvfb
    env = os.environ.copy()
    env["WINEPREFIX"] = WINE_PREFIX
    cmd = [XVFB_RUN, "-a", WINE, MT5_TERMINAL]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Escribir PID
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    
    print(f"MT5 terminal lanzado (PID {proc.pid})")
    print(f"Esperando 10s para que inicialice...")
    time.sleep(10)
    
    # Verificar que sigue vivo
    if proc.poll() is None:
        print(f"✅ terminal64.exe vivo (PID {proc.pid})")
        return True
    else:
        print(f"❌ terminal64.exe murió (exit code {proc.returncode})")
        os.unlink(PID_FILE)
        return False


def stop_mt5():
    """Mata terminal64.exe."""
    if os.path.exists(PID_FILE):
        pid = int(open(PID_FILE).read().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"MT5 detenido (PID {pid})")
        except ProcessLookupError:
            print("MT5 ya no estaba corriendo")
        os.unlink(PID_FILE)
    else:
        print("No hay PID guardado")


def status_mt5():
    """Estado de MT5."""
    if os.path.exists(PID_FILE):
        pid = int(open(PID_FILE).read().strip())
        try:
            os.kill(pid, 0)
            print(f"✅ MT5 corriendo (PID {pid})")
            
            # Probar initialize
            result = run_wine_initialize()
            if result.get("init"):
                print(f"✅ mt5.initialize() OK")
                print(f"   Balance: ${result.get('account', {}).get('balance', '?')}")
                print(f"   Server: {result.get('account', {}).get('server', '?')}")
            else:
                print(f"❌ mt5.initialize() falló: {result.get('error', '?')}")
                print(f"   Sugerencia: el terminal64.exe de 2022 puede no ser compatible")
                print(f"   con MetaTrader5 {result.get('version', '?')}")
            return True
        except ProcessLookupError:
            print("❌ PID file existe pero proceso no encontrado")
            return False
    else:
        print("❌ MT5 no está corriendo")
        return False


def main():
    if len(sys.argv) < 2:
        print("Uso: mt5_runner.py <start|stop|status|check>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "start":
        start_mt5()
    elif cmd == "stop":
        stop_mt5()
    elif cmd == "status":
        status_mt5()
    elif cmd == "check":
        result = run_wine_initialize()
        print(json.dumps(result, indent=2))
    else:
        print(f"Comando desconocido: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
