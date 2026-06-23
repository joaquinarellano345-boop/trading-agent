#!/usr/bin/env python3
"""
Trading Agent 24/7 — IC Markets
================================
Agente autónomo de trading que:
  1. Conecta a IC Markets (MT5/cTrader/Simulado)
  2. Analiza el mercado con indicadores técnicos
  3. Toma decisiones de compra/venta
  4. Gestiona riesgo automáticamente
  5. Aprende de resultados pasados
  6. Muestra todo en dashboard en vivo

Meta: $100 → $1,000
"""

import json
import os
import sys
import time
import threading
import yaml
from datetime import datetime
from pathlib import Path

# Añadir path
sys.path.insert(0, str(Path(__file__).parent))

from connector import TradingConnector
from engine import StrategyEngine, RiskManager
from dashboard import DashboardServer


def load_config():
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


class TradingAgent:
    """Agente principal de trading 24/7"""
    
    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "trading-agent")
        self.capital_inicial = config.get("bot", {}).get("capital_inicial", 100.0)
        self.capital_objetivo = config.get("bot", {}).get("capital_objetivo", 1000.0)
        
        print(f"\n{'='*50}")
        print(f"  🤖 TRADING AGENT v2.0")
        print(f"  {'='*50}")
        print(f"  Broker: IC Markets")
        print(f"  Capital: ${self.capital_inicial:.2f}")
        print(f"  Objetivo: ${self.capital_objetivo:.2f}")
        print(f"  Modo: {config.get('bot', {}).get('modo', 'simulado')}")
        print(f"  {'='*50}\n")
        
        # Inicializar componentes
        print("[INIT] Inicializando conector...")
        self.connector = TradingConnector(config)
        
        # Cargar estado persistente para pasar al engine
        state_data = self._load_state_data()
        
        print("[INIT] Inicializando motor de trading...")
        self.engine = StrategyEngine(config, self.connector, state_data)
        
        print("[INIT] Inicializando dashboard...")
        self.dashboard = DashboardServer(config, self.connector, self.engine)
        
        # Estado del agente
        self.running = False
        self.cycle_count = 0
        self.last_analysis_time = {}
        self.max_drawdown = 0.0
        self.peak_balance = self.capital_inicial
        
        # Log file (antes que _load_state porque log() lo necesita)
        self.log_path = Path(__file__).parent / "logs"
        self.log_path.mkdir(exist_ok=True)
        self.metrics_path = Path(__file__).parent / "metrics"
        self.metrics_path.mkdir(exist_ok=True)
        
        # Estado persistente (recuperar al arrancar)
        self.state_path = Path(__file__).parent / "state.json"
        self._load_state()
    
    def _load_state_data(self) -> dict:
        """Carga state.json crudo para pasarlo al engine (RiskManager)"""
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _load_state(self):
        """Recupera estado persistente desde state.json"""
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    state = json.load(f)
                
                # Verificar que el estado sea del mismo día
                today = datetime.now().date().isoformat()
                if state.get("dia") == today:
                    self.peak_balance = state.get("peak_balance", self.capital_inicial)
                    self.max_drawdown = state.get("max_drawdown", 0.0)
                    self.cycle_count = state.get("cycle_count", 0)
                    # Restaurar cooldown de estrategias
                    cooldown = state.get("cooldown", {})
                    if cooldown and hasattr(self.engine, 'ultimo_trade_por_par_estrategia'):
                        for clave, ts_str in cooldown.items():
                            try:
                                self.engine.ultimo_trade_por_par_estrategia[clave] = datetime.fromisoformat(ts_str)
                            except Exception:
                                pass
                    self.log(f"🔄 Estado recuperado: drawdown={self.max_drawdown:.2%}, peak=${self.peak_balance:.2f}, cooldown={len(cooldown)} bloqueos", "INFO")
                else:
                    self.log(f"📅 Nuevo día ({today}) — estado reseteado")
            else:
                self.log("📁 state.json no encontrado — estado fresco")
        except Exception as e:
            self.log(f"⚠️ Error cargando estado: {e}", "WARN")
    
    def _save_state(self):
        """Persiste estado actual a state.json"""
        try:
            state = {
                "dia": datetime.now().date().isoformat(),
                "peak_balance": self.peak_balance,
                "max_drawdown": self.max_drawdown,
                "cycle_count": self.cycle_count,
                "risk_manager": self.engine.risk_manager.to_dict() if hasattr(self.engine, 'risk_manager') else {},
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
        """Log con timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        
        # Escribir a archivo
        log_file = self.log_path / f"trading_{datetime.now().strftime('%Y%m%d')}.log"
        with open(log_file, "a") as f:
            f.write(log_line + "\n")
    
    def save_metrics(self):
        """Guarda métricas actuales"""
        estado = self.connector.obtener_estado()
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "balance": estado["balance"],
            "equity": estado["equity"],
            "ganancia": estado["ganancia"],
            "ganancia_pct": estado["ganancia_pct"],
            "trades_totales": estado["trades_totales"],
            "ordenes_abiertas": estado["ordenes_abiertas"],
            "peak_balance": self.peak_balance,
            "max_drawdown": self.max_drawdown,
            "cycle": self.cycle_count
        }
        
        metrics_file = self.metrics_path / "metrics.jsonl"
        with open(metrics_file, "a") as f:
            f.write(json.dumps(metrics) + "\n")
        
        # Persistir estado periódicamente (cada save_metrics)
        self._save_state()
    
    def check_objectives(self) -> bool:
        """Verifica si se alcanzaron los objetivos"""
        balance = self.connector.account.balance
        
        # Objetivo alcanzado
        if balance >= self.capital_objetivo:
            self.log(f"🎉 OBJETIVO ALCANZADO! ${balance:.2f} >= ${self.capital_objetivo:.2f}", "SUCCESS")
            return True
        
        # Stop loss total
        if balance <= self.capital_inicial * 0.3:  # perdió 70%
            self.log(f"🛑 STOP TOTAL: ${balance:.2f} ({(balance/self.capital_inicial-1)*100:.1f}%)", "ERROR")
            return True
        
        return False
    
    def update_risk_stats(self):
        """Actualiza estadísticas de riesgo"""
        balance = self.connector.account.balance
        
        if balance > self.peak_balance:
            self.peak_balance = balance
        
        current_drawdown = (self.peak_balance - balance) / self.peak_balance if self.peak_balance > 0 else 0
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
    
    def run_cycle(self):
        """
        Ciclo principal del agente:
        1. Verificar SL/TP de órdenes abiertas
        2. Aplicar trailing stops
        3. Analizar mercado
        4. Decidir si operar
        5. Ejecutar operación
        6. Registrar resultados
        """
        self.cycle_count += 1
        cycle_start = time.time()
        
        try:
            # 1. Verificar órdenes abiertas
            cerradas = self.engine.verificar_ordenes_abiertas()
            for order in cerradas:
                self.dashboard.record_trade_result(order.profit_neto)
                self.log(f"TRADE CERRADO #{order.ticket}: {order.simbolo} {order.tipo.upper()} "
                        f"P&L: ${order.profit_neto:.2f} | Estrategia: {order.estrategia}")
                
                # Guardar en historial de aprendizaje
                self._save_trade_to_learning(order)
                # Persistir estado después de cada trade cerrado
                self._save_state()
            
            # 2. Aplicar trailing stops
            self.engine.aplicar_trailing_stop()
            
            # 3. Obtener estado actual
            estado = self.connector.obtener_estado()
            balance = estado["balance"]
            
            # 4. Actualizar estadísticas
            self.update_risk_stats()
            
            # 5. Verificar objetivos
            if self.check_objectives():
                self.log("Objetivo alcanzado o stop activado. Deteniendo operaciones.")
                self.dashboard.set_last_action(f"Objetivo: ${balance:.2f}")
                return False
            
            # 6. Decidir siguiente operación
            decision = self.engine.decidir_operacion(balance, estado["equity"])
            
            # 7. Ejecutar si hay oportunidad
            if decision["accion"] == "operar":
                resultado = self.engine.ejecutar_operacion(decision)
                
                if resultado.get("exito"):
                    self.log(f"✅ ORDEN ABIERTA #{resultado['ticket']}: {resultado['simbolo']} "
                            f"{resultado['tipo'].upper()} {resultado['lotes']} lotes "
                            f"@ ${resultado['precio']} | SL: ${resultado['sl']} TP: ${resultado['tp']}")
                    self.dashboard.set_last_action(
                        f"Abrió {resultado['tipo'].upper()} {resultado['simbolo']} "
                        f"@{resultado['precio']} ({resultado['estrategia']})"
                    )
                else:
                    self.log(f"❌ Orden rechazada: {resultado.get('razon', 'error desconocido')}")
                    self.dashboard.set_last_action(f"Rechazado: {resultado.get('razon', 'error')}")
            else:
                if self.cycle_count % 20 == 0:  # Log cada 20 ciclos
                    self.log(f"⏳ Esperando: {decision.get('razon', 'sin señal')} "
                            f"| Balance: ${balance:.2f} "
                            f"| Abiertas: {estado['ordenes_abiertas']}")
                    self.dashboard.set_last_action(f"Analizando mercado... {decision.get('razon', '')}")
            
            # 8. Guardar métricas periódicamente
            if self.cycle_count % 10 == 0:
                self.save_metrics()
            
            # 9. Report
            if self.cycle_count % 60 == 0:  # cada ~5 min
                self._generate_mini_report()
            
            cycle_time = time.time() - cycle_start
            
            # Esperar antes del próximo ciclo
            wait_time = max(0.5, 5.0 - cycle_time)  # mínimo 500ms
            return True, wait_time
            
        except Exception as e:
            self.log(f"ERROR en ciclo: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
            return True, 5.0  # continuar después de error
    
    def _save_trade_to_learning(self, order):
        """Guarda trade para sistema de aprendizaje"""
        aprendizaje_dir = Path(__file__).parent / "memory"
        aprendizaje_dir.mkdir(exist_ok=True)
        
        learning_file = aprendizaje_dir / "learning_data.json"
        
        trade_data = {
            "ticket": order.ticket,
            "simbolo": order.simbolo,
            "tipo": order.tipo,
            "volumen": order.volumen,
            "precio_apertura": order.precio_apertura,
            "precio_cierre": order.precio_cierre,
            "profit": order.profit_neto,
            "sl_pips": abs(order.precio_apertura - order.sl) / (0.0001 if order.precio_apertura < 100 else 0.01) if order.sl > 0 else 0,
            "tp_pips": abs(order.precio_apertura - order.tp) / (0.0001 if order.precio_apertura < 100 else 0.01) if order.tp > 0 else 0,
            "strategia": order.estrategia,
            "duracion_seg": (order.timestamp_cierre - order.timestamp_apertura).total_seconds() if order.timestamp_cierre else 0,
            "exito": order.profit_neto > 0,
            "timestamp": datetime.now().isoformat()
        }
        
        # Append
        try:
            existing = []
            if learning_file.exists():
                with open(learning_file) as f:
                    for line in f:
                        if line.strip():
                            existing.append(json.loads(line))
            
            existing.append(trade_data)
            
            # Mantener solo últimos 1000
            if len(existing) > 1000:
                existing = existing[-1000:]
            
            with open(learning_file, "w") as f:
                for item in existing:
                    f.write(json.dumps(item) + "\n")
        except Exception as e:
            self.log(f"Error guardando aprendizaje: {e}", "WARN")
    
    def _generate_mini_report(self):
        """Genera mini reporte periódico"""
        estado = self.connector.obtener_estado()
        rend = self.engine.obtener_rendimiento()
        
        progreso = (estado["balance"] / self.capital_objetivo) * 100
        
        report = (
            f"\n📊 REPORTE #{self.cycle_count}"
            f"\n   Balance: ${estado['balance']:.2f} "
            f"({estado['ganancia_pct']:+.2f}%)"
            f"\n   Objetivo: {progreso:.1f}% hacia $1,000"
            f"\n   Trades: {estado['trades_totales']} "
            f"| Abiertas: {estado['ordenes_abiertas']}"
            f"\n   Drawdown: {self.max_drawdown:.2%}"
        )
        
        # Estrategias
        for nombre, r in rend.items():
            if r.get("trades", 0) > 0:
                report += (
                    f"\n   📈 {nombre}: {r['trades']} trades "
                    f"| WR: {r.get('win_rate',0)*100:.0f}% "
                    f"| P&L: ${r.get('total_pnl',0):+.2f}"
                )
        
        self.log(report)
        
        # Guardar reporte
        report_path = Path(__file__).parent / "reports"
        report_path.mkdir(exist_ok=True)
        report_file = report_path / f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        with open(report_file, "w") as f:
            f.write(report)
    
    def run(self):
        """Bucle principal del agente"""
        self.running = True
        self.log("🤖 AGENTE INICIADO - Trading 24/7")
        self.log(f"   Capital inicial: ${self.capital_inicial:.2f}")
        self.log(f"   Objetivo: ${self.capital_objetivo:.2f}")
        self.log(f"   Modo: {self.connector.modo.upper()}")
        
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
                    time.sleep(5)
                    
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
        """Resumen final al detener"""
        estado = self.connector.obtener_estado()
        rend = self.engine.obtener_rendimiento()
        
        print(f"\n{'='*50}")
        print(f"  📊 RESUMEN FINAL")
        print(f"  {'='*50}")
        print(f"  Ciclos ejecutados: {self.cycle_count}")
        print(f"  Balance final: ${estado['balance']:.2f}")
        print(f"  Ganancia total: ${estado['ganancia']:.2f} ({estado['ganancia_pct']:+.2f}%)")
        print(f"  Trades totales: {estado['trades_totales']}")
        print(f"  Max Drawdown: {self.max_drawdown:.2%}")
        
        for nombre, r in rend.items():
            if r.get("trades", 0) > 0:
                print(f"  {nombre}: {r['trades']}t | {r.get('win_rate',0)*100:.0f}% | ${r.get('total_pnl',0):+.2f}")
        
        print(f"  {'='*50}")


def run_dashboard_in_thread(config, connector, engine):
    """Ejecuta el dashboard en un thread separado"""
    dashboard = DashboardServer(config, connector, engine)
    dashboard.start()


def main():
    config = load_config()
    
    # Crear agente
    agent = TradingAgent(config)
    
    # Iniciar dashboard en thread separado
    dashboard_thread = threading.Thread(
        target=run_dashboard_in_thread,
        args=(config, agent.connector, agent.engine),
        daemon=True
    )
    dashboard_thread.start()
    
    # Dar tiempo al dashboard para arrancar
    time.sleep(1)
    
    # Ejecutar agente
    agent.run()


if __name__ == "__main__":
    main()
