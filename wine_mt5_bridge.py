#!/usr/bin/env python3
"""
Wine MT5 Bridge v7
===================
Bridge entre el agente Python (Linux nativo) y MetaTrader5 corriendo en Wine.

Problema conocido: mt5.initialize() crashea con "unimplemented function ucrtbase.dll.crealf"
porque numpy compilado para Windows usa funciones ucrtbase que Wine 9.0 no implementa.
Además terminal64.exe no está presente (no se incluye en el installer base de MetaQuotes).

Este bridge reporta estado exacto para que el connector decida el modo correcto.

Uso:
  python3 wine_mt5_bridge.py <check|account>
  
Formato salida: JSON siempre.
"""

import json
import os
import subprocess
import sys
import tempfile

# Config
WINE = os.environ.get("WINE", "wine")
WINE_PYTHON = os.environ.get(
    "WINE_PYTHON",
    os.path.expanduser("~/.wine/drive_c/Python312/python.exe")
)
WINE_PREFIX = os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine"))
XVFB_RUN = os.environ.get("XVFB_RUN", "xvfb-run")

# Credenciales demo IC Markets
MT5_LOGIN = os.environ.get("MT5_LOGIN", "12760229")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "tsqx65")
MT5_SERVER = os.environ.get("MT5_SERVER", "ICMarketsSC-Demo01")
MT5_TERMINAL_PATH = "C:\\\\Program Files\\\\MetaTrader 5"


def _run_wine_script(script_code: str, timeout: int = 30) -> dict:
    """Ejecuta código Python dentro de Wine y captura JSON de salida."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir="/tmp"
    ) as f:
        f.write(script_code)
        script_path = f.name

    try:
        cmd = [XVFB_RUN, "-a", WINE, WINE_PYTHON, script_path]
        env = os.environ.copy()
        env["WINEPREFIX"] = WINE_PREFIX

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        lines = [l for l in stdout.split("\n") if l.strip()]
        last_line = lines[-1] if lines else ""

        try:
            data = json.loads(last_line)
        except (json.JSONDecodeError, IndexError):
            data = {
                "status": "error",
                "error": "No se pudo parsear JSON output",
                "stdout": stdout[:2000],
                "stderr": stderr[:2000],
                "exit_code": result.returncode,
            }

        data["_raw_stdout"] = stdout[:2000]
        data["_raw_stderr"] = stderr[:2000]
        data["_exit_code"] = result.returncode

        return data

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "timeout", "timeout_s": timeout}
    except FileNotFoundError as e:
        return {"status": "error", "error": f"FileNotFound: {e}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def cmd_check() -> dict:
    """Verifica si MT5 está disponible (solo file check, no initialize())."""
    script = '''
import sys, json, os, threading, time

# Timeout safety
def _timeout_kill():
    time.sleep(15)
    print(json.dumps({"status": "timeout", "error": "script hung for 15s"}))
    os._exit(1)

threading.Thread(target=_timeout_kill, daemon=True).start()

sys.path.insert(0, 'C:\\\\Python312\\\\Lib\\\\site-packages')

# Check if MetaTrader5 module loads at all
try:
    import MetaTrader5 as mt5
    mt5_version = getattr(mt5, '__version__', 'unknown')
except ImportError as e:
    print(json.dumps({"status": "no_module", "error": str(e)}))
    sys.exit(0)
except Exception as e:
    print(json.dumps({"status": "module_error", "error": str(e)}))
    sys.exit(0)

# Check files
terminal64 = os.path.exists(r"C:\\Program Files\\MetaTrader 5\\terminal64.exe")
metaeditor = os.path.exists(r"C:\\Program Files\\MetaTrader 5\\MetaEditor64.exe")
metatester = os.path.exists(r"C:\\Program Files\\MetaTrader 5\\metatester64.exe")

# Check what files exist in the MT5 directory
mt5_dir = r"C:\\Program Files\\MetaTrader 5"
mt5_files = []
if os.path.exists(mt5_dir):
    try:
        mt5_files = os.listdir(mt5_dir)
    except:
        pass

# Attempt initialize ONLY if terminal64 exists (skip if not, to avoid hang)
init_result = None
init_error = None
if terminal64:
    try:
        init_result = mt5.initialize(path=r"C:\\Program Files\\MetaTrader 5")
        if not init_result:
            init_error = str(mt5.last_error()) if hasattr(mt5, 'last_error') else 'unknown'
        elif init_result:
            # Quick account info
            login_ok = mt5.login(
                login=''' + str(MT5_LOGIN) + ''',
                password="''' + MT5_PASSWORD + '''",
                server="''' + MT5_SERVER + '''"
            )
            init_result = "login_ok" if login_ok else "login_failed"
            if not login_ok:
                init_error = str(mt5.last_error()) if hasattr(mt5, 'last_error') else 'login_failed'
        mt5.shutdown()
    except Exception as e:
        init_error = str(e)
        init_result = "exception"

result = {
    "status": "no_terminal" if not terminal64 else ("initialized" if init_result == "login_ok" else "init_failed"),
    "terminal64_exists": terminal64,
    "metaeditor_exists": metaeditor,
    "metatester_exists": metatester,
    "mt5_files": mt5_files[:30],
    "mt5_version": mt5_version,
    "init_result": init_result,
    "init_error": init_error,
}

print(json.dumps(result))
'''
    return _run_wine_script(script, timeout=45)


def cmd_account() -> dict:
    """Intenta obtener info de cuenta MT5 via Wine."""
    script = '''
import sys, json, os, threading, time

def _timeout_kill():
    time.sleep(20)
    print(json.dumps({"status": "timeout", "error": "account query hung"}))
    os._exit(1)

threading.Thread(target=_timeout_kill, daemon=True).start()

sys.path.insert(0, 'C:\\\\Python312\\\\Lib\\\\site-packages')
try:
    import MetaTrader5 as mt5
except ImportError as e:
    print(json.dumps({"status": "no_module", "error": str(e)}))
    sys.exit(0)

if not os.path.exists(r"C:\\Program Files\\MetaTrader 5\\terminal64.exe"):
    print(json.dumps({"status": "no_terminal", "note": "terminal64.exe not found"}))
    sys.exit(0)

try:
    init = mt5.initialize(path=r"C:\\Program Files\\MetaTrader 5")
    if not init:
        print(json.dumps({"status": "init_failed", "error": str(mt5.last_error())}))
        sys.exit(0)
    
    login_ok = mt5.login(login=''' + str(MT5_LOGIN) + ''', password="''' + MT5_PASSWORD + '''", server="''' + MT5_SERVER + '''")
    if not login_ok:
        print(json.dumps({"status": "login_failed", "error": str(mt5.last_error())}))
        mt5.shutdown()
        sys.exit(0)
    
    acc = mt5.account_info()
    if acc:
        result = {
            "status": "ok",
            "balance": acc.balance,
            "equity": acc.equity,
            "margin": acc.margin,
            "margin_free": acc.margin_free,
            "margin_level": acc.margin_level,
            "leverage": acc.leverage,
            "name": acc.name,
            "server": acc.server,
            "currency": acc.currency,
            "login": acc.login,
        }
    else:
        result = {"status": "no_account_info"}
    
    mt5.shutdown()
    print(json.dumps(result))
except Exception as e:
    import traceback
    print(json.dumps({"status": "exception", "error": str(e), "traceback": traceback.format_exc()}))
'''
    return _run_wine_script(script, timeout=45)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "status": "error",
            "error": "Uso: wine_mt5_bridge.py <check|account>"
        }))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        result = cmd_check()
    elif cmd == "account":
        result = cmd_account()
    else:
        result = {"status": "error", "error": f"Comando desconocido: {cmd}"}

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
