#!/usr/bin/env python3
"""
OPTIMIZADOR v7 — Encuentra los mejores parámetros SL/TP para cada estrategia
============================================================================
Prueba múltiples combinaciones de SL, TP, y umbrales de confianza
para maximizar PnL y Profit Factor.
"""

import itertools
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Re-importar del backtester
sys.path.insert(0, str(Path(__file__).parent))

# Parámetros a optimizar
SL_RANGES = {
    "scalping_rsi": [5, 8, 10, 12, 15],
    "trend_following_ema": [10, 12, 15, 18, 20, 25],
    "breakout_bb": [8, 10, 12, 15, 18],
}

TP_RATIOS = [1.5, 2.0, 2.5, 3.0]  # Risk:Reward (TP = SL * ratio)

CONFIANZA_MIN = [40, 50, 60]

PARES_PRINCIPALES = ["EURUSD", "NZDUSD", "GBPUSD"]

from backtester import (
    PARES_YAHOO, PIP_SIZE_MAP, PIP_VALUE_MAP, SPREAD_TIPICO,
    TechnicalAnalyzer, ScalpingRSI, TrendFollowingEMA, BreakoutBB,
    ESTRATEGIAS_CLASES, BacktestEngine, fetch_yahoo_data, generar_reporte_csv
)

def optimizar():
    print("=" * 70)
    print("  OPTIMIZADOR v7 — Búsqueda de parámetros óptimos")
    print("=" * 70)
    print(f"\n  Rangos a probar:")
    print(f"  SL: {SL_RANGES}")
    print(f"  Risk:Reward ratios: {TP_RATIOS}")
    print(f"  Confianza mínima: {CONFIANZA_MIN}")
    print(f"  Pares: {PARES_PRINCIPALES}")

    mejores_resultados = []
    total_combinaciones = (
        sum(len(v) for v in SL_RANGES.values())
        * len(TP_RATIOS)
        * len(CONFIANZA_MIN)
        * len(PARES_PRINCIPALES)
    )

    print(f"\n  Total de combinaciones: ~{total_combinaciones}")
    print(f"\n  {'='*70}")

    corriendo = 0

    for simbolo in PARES_PRINCIPALES:
        print(f"\n📡 Descargando {simbolo}...")
        velas = fetch_yahoo_data(simbolo, "5m", 30)
        if not velas:
            print(f"  ⏭ Sin datos para {simbolo}")
            continue
        print(f"  ✅ {len(velas)} velas")

        for est_nombre, sl_list in SL_RANGES.items():
            clase = ESTRATEGIAS_CLASES.get(est_nombre)
            if not clase:
                continue

            for sl_pips in sl_list:
                for tp_ratio in TP_RATIOS:
                    tp_pips = int(sl_pips * tp_ratio)
                    for conf_min in CONFIANZA_MIN:
                        corriendo += 1
                        print(f"\r  [{corriendo}/{total_combinaciones}] {simbolo} {est_nombre} "
                              f"SL={sl_pips} TP={tp_pips} R:R=1:{tp_ratio} conf>={conf_min}", end="")

                        estrategia_obj = clase()
                        engine = BacktestEngine(200.0)

                        # Ejecutar backtest con estos parámetros
                        from backtester import BacktestTrade
                        # Reusamos la lógica del backtester pero con control fino
                        resultado = _run_optimization(
                            velas, simbolo, est_nombre, estrategia_obj,
                            sl_pips, tp_pips, conf_min
                        )

                        if resultado and resultado.get("trades", 0) >= 10:
                            resultado["sl_pips"] = sl_pips
                            resultado["tp_pips"] = tp_pips
                            resultado["conf_min"] = conf_min
                            resultado["rr_ratio"] = tp_ratio
                            mejores_resultados.append(resultado)

    # Mostrar mejores
    if mejores_resultados:
        print(f"\n\n  {'='*70}")
        print(f"  🏆 TOP 10 COMBINACIONES")
        print(f"  {'='*70}")

        # Filtrar solo las que tienen PF > 1.1 y WR > 30%
        filtrados = [r for r in mejores_resultados
                     if isinstance(r.get("profit_factor"), (int, float))
                     and r["profit_factor"] > 1.1
                     and r["win_rate"] > 30]
        filtrados.sort(key=lambda x: x["pnl_total"], reverse=True)

        if not filtrados:
            filtrados = sorted(mejores_resultados, key=lambda x: x["pnl_total"], reverse=True)[:10]

        for i, r in enumerate(filtrados[:10]):
            print(f"\n  {i+1}. {r['simbolo']} + {r['estrategia']}")
            print(f"     SL={r['sl_pips']} TP={r['tp_pips']} R:R=1:{r['rr_ratio']} conf>={r['conf_min']}")
            print(f"     → ${r['pnl_total']:.2f} | {r['trades']}t | WR {r['win_rate']}% | "
                  f"PF {r['profit_factor']} | DD {r['max_drawdown']}%")

        # Guardar
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(__file__).parent / "backtest_results" / f"optimizacion_{ts}.json"
        with open(path, "w") as f:
            json.dump(filtrados[:20], f, indent=2, default=str)
        print(f"\n  📄 Mejores guardados en: {path}")

    return 0


def _run_optimization(velas, simbolo, est_nombre, estrategia_obj,
                       sl_pips, tp_pips, conf_min):
    """Versión simplificada del backtest para optimización"""
    pip_size = PIP_SIZE_MAP.get(simbolo, 0.0001)
    pip_value = PIP_VALUE_MAP.get(simbolo, 10.0)
    spread_pips = SPREAD_TIPICO.get(simbolo, 1.0)
    precios_close = [v["close"] for v in velas]

    capital = 200.0
    peak = 200.0
    max_dd = 0.0
    trades = []
    ultimo_idx = -999
    cooldown = 3

    for i in range(len(velas)):
        if i - ultimo_idx < cooldown:
            continue

        ventana = precios_close[:i+1]
        if len(ventana) < 30:
            continue

        senal = estrategia_obj.analizar(ventana)
        if senal["senal"] not in ("buy", "sell") or senal["confianza"] < conf_min:
            continue

        close = velas[i]["close"]
        # Risk sizing
        riesgo_usd = capital * 0.02
        lotes = riesgo_usd / (sl_pips * max(1, pip_value * 0.1))
        lotes = max(0.01, min(lotes, capital / 1000))
        lotes = round(lotes * 100) / 100

        # Entry con spread
        if senal["senal"] == "buy":
            entry = close * (1 + spread_pips * pip_size)
            sl = entry - (sl_pips * pip_size)
            tp = entry + (tp_pips * pip_size)
        else:
            entry = close * (1 - spread_pips * pip_size)
            sl = entry + (sl_pips * pip_size)
            tp = entry - (tp_pips * pip_size)

        # Simular trade
        resultado = "abierto"
        precio_salida = None
        for j in range(i, min(i + 20, len(velas))):
            v = velas[j]
            if senal["senal"] == "buy":
                if v["low"] <= sl:
                    precio_salida = sl
                    resultado = "sl"
                    break
                elif v["high"] >= tp:
                    precio_salida = tp
                    resultado = "tp"
                    break
            else:
                if v["high"] >= sl:
                    precio_salida = sl
                    resultado = "sl"
                    break
                elif v["low"] <= tp:
                    precio_salida = tp
                    resultado = "tp"
                    break

        if resultado == "abierto":
            precio_salida = velas[-1]["close"]
            resultado = "fin"

        # Calcular PnL
        if senal["senal"] == "buy":
            profit_pips = (precio_salida - entry) / pip_size
        else:
            profit_pips = (entry - precio_salida) / pip_size

        profit_usd = profit_pips * pip_value * lotes
        comision = 1.75 * 2 * lotes
        profit_neto = profit_usd - comision
        capital += profit_neto

        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak
        max_dd = max(max_dd, dd)

        trades.append(profit_neto)
        ultimo_idx = i

    if len(trades) < 5:
        return None

    ganancias = [t for t in trades if t > 0]
    perdedores = [t for t in trades if t <= 0]

    return {
        "simbolo": simbolo,
        "estrategia": est_nombre,
        "trades": len(trades),
        "pnl_total": round(sum(trades), 2),
        "win_rate": round(len(ganancias) / len(trades) * 100, 1),
        "profit_factor": round(abs(sum(ganancias) / sum(perdedores)), 2) if perdedores and sum(perdedores) != 0 else 0,
        "max_drawdown": round(max_dd * 100, 1),
        "capital_final": round(capital, 2),
    }


if __name__ == "__main__":
    optimizar()
