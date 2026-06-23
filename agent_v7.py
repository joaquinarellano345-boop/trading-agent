#!/usr/bin/env python3
"""
Trading Agent v7 — IC Markets
==============================
Basado en backtesting real con datos Yahoo Finance.
Usa AdaptiveRiskManager con martingale inverso, session filter, stop diario.

Estrategias activas (backtest-verificadas):
  - EURUSD + BreakoutBB: +$62.51/30d, WR 38.6%, PF 1.39
  - NZDUSD + TrendEMA: +$55.35/30d, WR 43.8%, PF 1.64

Meta: $200 → $1,000 con gestión de riesgo adaptativa
"""

import json
import os
import sys
import time
import threading
import yaml
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from connector import TradingConnector
from engine import StrategyEngine
from risk_manager_v7 import AdaptiveRiskManager
from dashboard import DashboardServer


def load_config():
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


class TradingAgentV7:
    """Agente v7 con AdaptiveRiskManager y estrategias validadas por backtest"""

    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "trading-agent")
        self.capital_inicial = config.get("bot", {}).get("capital_inicial", 200.0)
        self.capital_objetivo = config.get("bot", {}).get("capital_objetivo", 1000.0)

        print(f"\n{'='*55}")
        print(f"  🤖 TRADING AGENT v7")
        print(f"  {'='*55}")
        print(f"  Broker: IC Markets")
        print(f"  Capital: ${self.capital_inicial:.2f}")
        print(f"  Objetivo: ${self.capital_objetivo:.2f}")
        print(f"  Modo: {config.get('bot', {}).get('modo', 'simulado')}")
        print(f"  {'='*55}\n")

        # Inicializar componentes
        print("[INIT] Inicializando conector...")
        self.connector = TradingConnector(config)

        state_data = self._load_state_data()

        print("[INIT] Inicializando motor de trading...")
        self.engine = StrategyEngine(config, self.connector, state_data)

        print("[INIT] Inicializando Risk Manager v7...")
        rm_state = state_data.get("risk_manager_v7", {}) if state_data else {}
        self.risk_manager = AdaptiveRiskManager.from_dict(config, rm_state)

        print("[INIT] Inicializando dashboard...")
        self.dashboard = DashboardServer(config, self.connector, self.engine)

        # Estado del agente
        self.running = False
        self.cycle_count = 0

        # Logs
        self.log_path = Path(__file__).parent / "logs"
        self.log_path.mkdir(exist_ok=True)
        self.metrics_path = Path(__file__).parent / "metrics"
        self.metrics_path.mkdir(exist_ok=True)

        # Estado persistente
        self.state_path = Path(__file__).parent / "state.json"
        self._load_state()

    def _load_state_data(self) -> dict:
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _load_state(self):
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    state = json.load(f)
                today = datetime.now().date().isoformat()
                if state.get("dia") == today:
                    self.cycle_count = state.get("cycle_count", 0)
                    # Restaurar cooldown
                    cooldown = state.get("cooldown", {})
                    if cooldown and hasattr(self.engine, 'ultimo_trade_por_par_estrategia'):
                        for clave, ts_str in cooldown.items():
                            try:
                                self.engine.ultimo_trade_por_par_estrategia[clave] = datetime.fromisoformat(ts_str)
                            except Exception:
                                pass
                    self.log(f"🔄 Estado recuperado: ciclos={self.cycle_count}", "INFO")
                else:
                    self.log(f"📅 Nuevo día ({today}) — estado reseteado")
            else:
                self.log("📁 state.json no encontrado — estado fresco")
        except Exception as e:
            self.log(f"⚠️ Error cargando estado: {e}", "WARN")

    def _save_state(self):
        try:
            state = {
                "dia": datetime.now().date().isoformat(),
                "cycle_count": self.cycle_count,
                "risk_manager_v7": self.risk_manager.to_dict(),
                "cooldown": {
                    k: v.isoformat() if hasattr(v, 'isoformat') else str(v)
                    for k, v in self.engine.ultimo_trade_por_par_estrategia.items()
                } if hasattr(self.engine, 'ultimo_trade_por_par_estrategia') else {},
                "timestamp": datetime.now().isoformat()
            }
            with open(self.state_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.log(f"⚠️ Error guardando estado: {e}", "WARN")

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        log_file = self.log_path / f"trading_{datetime.now().strftime('%Y%m%d')}.log"
        with open(log_file, "a") as f:
            f.write(log_line + "\n")

    def save_metrics(self):
        estado = self.connector.obtener_estado()
        rm_summary = self.risk_manager.get_summary()
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "balance": estado["balance"],
            "equity": estado["equity"],
            "ganancia": estado["ganancia"],
            "ganancia_pct": estado["ganancia_pct"],
            "trades_totales": estado["trades_totales"],
            "ordenes_abiertas": estado["ordenes_abiertas"],
            "cycle": self.cycle_count,
            "risk_pct": rm_summary["risk_pct"],
            "streak": rm_summary["streak"],
            "daily_pnl": rm_summary["daily_pnl"],
            "daily_halted": rm_summary["daily_halted"],
            "session": rm_summary["session"],
            "drawdown": rm_summary["drawdown"],
        }
        metrics_file = self.metrics_path / "metrics.jsonl"
        with open(metrics_file, "a") as f:
            f.write(json.dumps(metrics) + "\n")
        self._save_state()

    def check_objectives(self) -> bool:
        balance = self.connector.account.balance
        if balance >= self.capital_objetivo:
            self.log(f"🎉 OBJETIVO ALCANZADO! ${balance:.2f} >= ${self.capital_objetivo:.2f}", "SUCCESS")
            return True
        if balance <= self.capital_inicial * 0.3:
            self.log(f"🛑 STOP TOTAL: ${balance:.2f} ({(balance/self.capital_inicial-1)*100:.1f}%)", "ERROR")
            return True
        return False

    def run_cycle(self):
        """Ciclo principal v7 con Risk Manager adaptativo"""
        self.cycle_count += 1
        cycle_start = time.time()

        try:
            # 1. Verificar órdenes abiertas (SL/TP)
            cerradas = self.engine.verificar_ordenes_abiertas()
            for order in cerradas:
                self.risk_manager.registrar_trade(order.profit_neto)
                self.dashboard.record_trade_result(order.profit_neto)
                self.log(
                    f"TRADE CERRADO #{order.ticket}: {order.simbolo} {order.tipo.upper()} "
                    f"P&L: ${order.profit_neto:.2f} | Estrategia: {order.estrategia} | "
                    f"Racha: {self.risk_manager.current_streak} | "
                    f"Riesgo: {self.risk_manager.current_risk_pct*100:.1f}%"
                )
                self._save_trade_to_learning(order)
                self._save_state()

            # 2. Apply trailing stops
            self.engine.aplicar_trailing_stop()

            # 3. Estado actual
            estado = self.connector.obtener_estado()
            balance = estado["balance"]

            # 4. Risk manager check (session filter, stop diario, etc)
            puede, razon = self.risk_manager.puede_operar(balance, estado["equity"])
            if not puede:
                if self.cycle_count % 20 == 0:
                    self.log(f"⏳ {razon} | Balance: ${balance:.2f}")
                    self.dashboard.set_last_action(razon)
                self.save_metrics()
                cycle_time = time.time() - cycle_start
                return True, max(10.0, 30.0 - cycle_time)

            # 5. Verificar objetivos
            if self.check_objectives():
                self.dashboard.set_last_action(f"Objetivo: ${balance:.2f}")
                return False

            # 6. Decidir operación
            decision = self.engine.decidir_operacion(balance, estado["equity"])
            if decision is None:
                decision = {"accion": "esperar", "razon": "sin decisión"}

            # 7. Ejecutar
            if decision["accion"] == "operar":
                # Usar el riesgo adaptativo del risk manager
                self.engine.risk_manager.max_riesgo_por_operacion = self.risk_manager.current_risk_pct
                resultado = self.engine.ejecutar_operacion(decision)

                if resultado.get("exito"):
                    self.log(
                        f"✅ ORDEN #{resultado['ticket']}: {resultado['simbolo']} "
                        f"{resultado['tipo'].upper()} {resultado['lotes']} lotes "
                        f"@ ${resultado['precio']} | SL: ${resultado['sl']} TP: ${resultado['tp']} | "
                        f"Riesgo: {self.risk_manager.current_risk_pct*100:.1f}%"
                    )
                    self.dashboard.set_last_action(
                        f"Abrió {resultado['tipo'].upper()} {resultado['simbolo']} "
                        f"@{resultado['precio']} ({resultado['estrategia']})"
                    )
                    self.risk_manager.daily_trades += 1
                else:
                    self.log(f"❌ Orden rechazada: {resultado.get('razon', 'error desconocido')}")
                    self.dashboard.set_last_action(f"Rechazado: {resultado.get('razon', 'error')}")
            else:
                if self.cycle_count % 20 == 0:
                    rm_info = self.risk_manager.get_summary()
                    self.log(
                        f"⏳ {decision.get('razon', 'sin señal')} "
                        f"| Balance: ${balance:.2f} "
                        f"| Abiertas: {estado['ordenes_abiertas']} "
                        f"| Riesgo: {rm_info['risk_pct']}% "
                        f"| Racha: {rm_info['streak']} {rm_info['streak_type'] or ''} "
                        f"| Hoy: ${rm_info['daily_pnl']:+.2f}"
                    )
                    self.dashboard.set_last_action(f"Analizando... {decision.get('razon', '')}")

            # 8. Métricas
            if self.cycle_count % 10 == 0:
                self.save_metrics()

            # 9. Reporte periódico
            if self.cycle_count % 60 == 0:
                self._generate_mini_report()

            cycle_time = time.time() - cycle_start
            wait_time = max(1.0, 15.0 - cycle_time)  # 15s entre ciclos
            return True, wait_time

        except Exception as e:
            self.log(f"ERROR en ciclo: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
            return True, 15.0

    def _save_trade_to_learning(self, order):
        aprendizaje_dir = Path(__file__).parent / "memory"
        aprendizaje_dir.mkdir(exist_ok=True)
        learning_file = aprendizaje_dir / "learning_data_v7.json"

        trade_data = {
            "ticket": order.ticket,
            "simbolo": order.simbolo,
            "tipo": order.tipo,
            "volumen": order.volumen,
            "precio_apertura": order.precio_apertura,
            "precio_cierre": order.precio_cierre,
            "profit": order.profit_neto,
            "strategia": order.estrategia,
            "exito": order.profit_neto > 0,
            "timestamp": datetime.now().isoformat()
        }

        try:
            existing = []
            if learning_file.exists():
                with open(learning_file) as f:
                    for line in f:
                        if line.strip():
                            existing.append(json.loads(line))
            existing.append(trade_data)
            if len(existing) > 1000:
                existing = existing[-1000:]
            with open(learning_file, "w") as f:
                for item in existing:
                    f.write(json.dumps(item) + "\n")
        except Exception as e:
            self.log(f"Error guardando aprendizaje: {e}", "WARN")

    def _generate_mini_report(self):
        estado = self.connector.obtener_estado()
        rend = self.engine.obtener_rendimiento()
        rm = self.risk_manager.get_summary()

        progreso = (estado["balance"] / self.capital_objetivo) * 100

        report = (
            f"\n📊 REPORTE v7 #{self.cycle_count}"
            f"\n   Balance: ${estado['balance']:.2f} ({estado['ganancia_pct']:+.2f}%)"
            f"\n   Objetivo: {progreso:.1f}% hacia $1,000"
            f"\n   Trades: {estado['trades_totales']} | Abiertas: {estado['ordenes_abiertas']}"
            f"\n   Riesgo actual: {rm['risk_pct']}% | Racha: {rm['streak']} {rm['streak_type'] or ''}"
            f"\n   Hoy: ${rm['daily_pnl']:+.2f} ({rm['daily_trades']} trades)"
            f"\n   Drawdown: {rm['drawdown']}% | Sesión: {rm['session']}"
        )

        for nombre, r in rend.items():
            if r.get("trades", 0) > 0:
                report += (
                    f"\n   📈 {nombre}: {r['trades']}t | WR: {r.get('win_rate',0)*100:.0f}% "
                    f"| P&L: ${r.get('total_pnl',0):+.2f}"
                )

        self.log(report)
        report_path = Path(__file__).parent / "reports"
        report_path.mkdir(exist_ok=True)
        report_file = report_path / f"report_v7_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        with open(report_file, "w") as f:
            f.write(report)

    def run(self):
        """Bucle principal v7"""
        self.running = True
        self.log("🤖 AGENTE v7 INICIADO — Trading autónomo con riesgo adaptativo")
        self.log(f"   Capital inicial: ${self.capital_inicial:.2f}")
        self.log(f"   Objetivo: ${self.capital_objetivo:.2f}")
        self.log(f"   Modo: {self.connector.modo.upper()}")
        self.log(f"   Estrategias: {', '.join(k for k in self.engine.estrategias.keys())}")
        self.log(f"   Risk manager: martingale inverso + session filter + stop diario")

        try:
            while self.running:
                result = self.run_cycle()
                if result is False:
                    self.log("Ciclo detenido por condición de salida.")
                    break
                elif isinstance(result, tuple):
                    _, wait_time = result
                    time.sleep(wait_time)
                else:
                    time.sleep(15)
        except KeyboardInterrupt:
            self.log("👋 Agente detenido por el usuario")
        except Exception as e:
            self.log(f"💥 Error fatal: {e}", "CRITICAL")
            import traceback
            self.log(traceback.format_exc(), "CRITICAL")
        finally:
            self.running = False
            self._print_final_summary()

    def _print_final_summary(self):
        estado = self.connector.obtener_estado()
        rend = self.engine.obtener_rendimiento()
        rm = self.risk_manager.get_summary()

        print(f"\n{'='*55}")
        print(f"  📊 RESUMEN FINAL v7")
        print(f"  {'='*55}")
        print(f"  Ciclos ejecutados: {self.cycle_count}")
        print(f"  Balance final: ${estado['balance']:.2f}")
        print(f"  Ganancia total: ${estado['ganancia']:.2f} ({estado['ganancia_pct']:+.2f}%)")
        print(f"  Trades totales: {estado['trades_totales']}")
        print(f"  Max Drawdown: {rm['drawdown']}%")
        print(f"  Mejor racha: {rm.get('win_streak', 0)} wins seguidos")
        print(f"  Riesgo final: {rm['risk_pct']}%")

        for nombre, r in rend.items():
            if r.get("trades", 0) > 0:
                print(f"  {nombre}: {r['trades']}t | {r.get('win_rate',0)*100:.0f}% | ${r.get('total_pnl',0):+.2f}")
        print(f"  {'='*55}")


def main():
    config = load_config()
    agent = TradingAgentV7(config)

    dashboard_thread = threading.Thread(
        target=lambda: run_dashboard_in_thread(config, agent.connector, agent.engine),
        daemon=True
    )
    dashboard_thread.start()
    time.sleep(1)
    agent.run()


def run_dashboard_in_thread(config, connector, engine):
    dashboard = DashboardServer(config, connector, engine)
    dashboard.start()


if __name__ == "__main__":
    main()
