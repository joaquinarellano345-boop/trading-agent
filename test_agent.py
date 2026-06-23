#!/usr/bin/env python3
"""Test rápido del trading agent"""
import sys
sys.path.insert(0, '/root/.hermes/projects/trading-agent')

import yaml
from connector import TradingConnector
from engine import StrategyEngine

# Cargar config
with open('/root/.hermes/projects/trading-agent/config.yaml') as f:
    config = yaml.safe_load(f)

print("="*50)
print("TRADING AGENT - TEST DE COMPONENTES")
print("="*50)

# 1. Inicializar conector
print("\n[1/4] Inicializando conector...")
connector = TradingConnector(config)
estado = connector.obtener_estado()
print(f"  Balance: ${estado['balance']:.2f}")
print(f"  Modo: {connector.modo}")
print(f"  Símbolos: {len(connector.todos_los_simbolos)}")
for s in connector.todos_los_simbolos[:5]:
    tick = connector.obtener_tick(s)
    print(f"  {s}: bid={tick.bid:.5f} ask={tick.ask:.5f}")

# 2. Inicializar motor
print("\n[2/4] Inicializando motor de trading...")
engine = StrategyEngine(config, connector)
print(f"  Estrategias activas: {len(engine.estrategias)}")
for nombre, est in engine.estrategias.items():
    print(f"  ✓ {est}")

# 3. Probar análisis
print("\n[3/4] Probando análisis de mercado...")
for simbolo in ["EURUSD", "XAUUSD", "US30"]:
    resultados = engine.analizar_simbolo(simbolo)
    for r in resultados:
        if r.get("senal") in ["buy", "sell"]:
            print(f"  {simbolo} → {r['senal'].upper()} ({r['confianza']}%) - {r['estrategia']}")

# 4. Probar decisión y ejecución
print("\n[4/4] Probando ciclo de decisión...")
decision = engine.decidir_operacion(100.0, 100.0)
print(f"  Decisión: {decision['accion']}")

if decision['accion'] == 'operar':
    resultado = engine.ejecutar_operacion(decision)
    print(f"  Ejecución: {'✅' if resultado.get('exito') else '❌'} {resultado.get('razon', '')}")
    if resultado.get('exito'):
        print(f"  Ticket: #{resultado['ticket']}")
        print(f"  Símbolo: {resultado['simbolo']}")
        print(f"  Tipo: {resultado['tipo'].upper()}")
        print(f"  Lotes: {resultado['lotes']}")
        print(f"  Precio: ${resultado['precio']}")
        
        # Cerramos la orden para probar
        order = connector.cerrar_orden(resultado['ticket'])
        print(f"  Cierre: P&L=${order.profit_neto:.2f}")
else:
    print(f"  Razón: {decision.get('razon', 'sin señal')}")

# Ver ordenes abiertas
abiertas = connector.obtener_ordenes_abiertas()
print(f"\n  Órdenes abiertas: {len(abiertas)}")

# Estado final
estado_final = connector.obtener_estado()
print(f"\n  Balance final: ${estado_final['balance']:.2f}")
print(f"  Trades totales: {estado_final['trades_totales']}")

print("\n" + "="*50)
print("✅ TEST COMPLETADO")
print("="*50)
