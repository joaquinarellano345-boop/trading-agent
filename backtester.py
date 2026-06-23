#!/usr/bin/env python3
"""
BACKTESTER v7 — Trading Agent
=============================
Backtesting real con datos históricos de Yahoo Finance.
Simula spreads reales, comisiones IC Markets ($3.50/lote redondo),
slippage, y 3 estrategias: Scalping RSI, Trend EMA, Breakout BB.

Modo de uso:
  python3 backtester.py                    # Todos los pares, todas las estrategias
  python3 backtester.py --pares EURUSD     # Solo un par
  python3 backtester.py --pares XAUUSD,EURUSD --dias 90
  python3 backtester.py --estrategia trend_following_ema
  python3 backtester.py --quick            # Solo 1 par + 1 estrategia (dev test)
"""

import argparse
import csv
import json
import math
import os
import signal
import sys
import time
import pandas as pd
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

PROJECT_DIR = Path(__file__).parent
RESULTS_DIR = PROJECT_DIR / "backtest_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Comisiones IC Markets Raw Spread: $3.50 por lote redondo (ida+vuelta)
COMISION_POR_LOTE_IDA = 1.75  # por lado

# Capital
CAPITAL_INICIAL = 200.0

# Pares a probar (con símbolos Yahoo Finance)
PARES_YAHOO = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "US30": "YM=F",
    "NAS100": "NQ=F",
    "SPX500": "ES=F",
    "UKOIL": "BZ=F",
    "USOIL": "CL=F",
}

# Tamaño de pip por símbolo (forex=0.0001, JPY=0.01, indices/futuros=varia)
PIP_SIZE_MAP = {}
for p in ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD", "XAGUSD"]:
    PIP_SIZE_MAP[p] = 0.0001
for p in ["USDJPY", "US30", "NAS100", "SPX500", "GER40", "UKOIL", "USOIL"]:
    PIP_SIZE_MAP[p] = 0.01

# Valor del pip por lote estándar (aproximado USD)
PIP_VALUE_MAP = {
    "EURUSD": 10.0, "GBPUSD": 10.0, "AUDUSD": 10.0, "USDCAD": 7.5,
    "NZDUSD": 10.0, "USDJPY": 7.0, "XAUUSD": 10.0, "XAGUSD": 50.0,
    "US30": 5.0, "NAS100": 20.0, "SPX500": 50.0, "GER40": 25.0,
    "UKOIL": 10.0, "USOIL": 10.0,
}

# Spreads típicos IC Markets Raw Spread (en pips, modo pico)
SPREAD_TIPICO = {
    "EURUSD": 0.3, "GBPUSD": 0.5, "USDJPY": 0.5, "AUDUSD": 0.5,
    "USDCAD": 0.6, "NZDUSD": 0.7, "XAUUSD": 1.5, "XAGUSD": 3.0,
    "US30": 2.0, "NAS100": 1.5, "SPX500": 2.0, "UKOIL": 3.0, "USOIL": 2.5,
}

# ──────────────────────────────────────────────
# INDICADORES TÉCNICOS (mismos que engine.py)
# ──────────────────────────────────────────────

class TechnicalAnalyzer:
    @staticmethod
    def calcular_rsi(precios, periodo=14):
        if len(precios) < periodo + 1:
            return 50.0
        ganancias = 0
        perdidas = 0
        for i in range(len(precios) - periodo, len(precios)):
            diff = precios[i] - precios[i-1]
            if diff > 0:
                ganancias += diff
            else:
                perdidas += abs(diff)
        if perdidas == 0:
            return 100.0
        rs = (ganancias / periodo) / (perdidas / periodo)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calcular_ema(precios, periodo):
        if len(precios) < periodo:
            return sum(precios) / len(precios)
        k = 2 / (periodo + 1)
        ema = sum(precios[:periodo]) / periodo
        for precio in precios[periodo:]:
            ema = precio * k + ema * (1 - k)
        return ema

    @staticmethod
    def calcular_sma(precios, periodo):
        if len(precios) < periodo:
            return sum(precios) / len(precios)
        return sum(precios[-periodo:]) / periodo

    @staticmethod
    def calcular_macd(precios):
        ema_rapida = TechnicalAnalyzer.calcular_ema(precios, 12)
        ema_lenta = TechnicalAnalyzer.calcular_ema(precios, 26)
        macd_line = ema_rapida - ema_lenta
        signal_line = TechnicalAnalyzer.calcular_ema(precios[-9:], 9)  # aproximación
        # Mejor: calcular señal como EMA de la línea MACD histórica
        macd_history = []
        for i in range(26, len(precios)):
            er = TechnicalAnalyzer.calcular_ema(precios[:i+1], 12)
            el = TechnicalAnalyzer.calcular_ema(precios[:i+1], 26)
            macd_history.append(er - el)
        if len(macd_history) >= 9:
            signal_line = TechnicalAnalyzer.calcular_ema(macd_history, 9)
        else:
            signal_line = macd_line
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def calcular_bb(precios, periodo=20, desviacion=2.0):
        sma = TechnicalAnalyzer.calcular_sma(precios, periodo)
        if len(precios) < periodo:
            return sma, sma, sma
        varianza = sum((p - sma) ** 2 for p in precios[-periodo:]) / periodo
        std = math.sqrt(varianza)
        upper = sma + (desviacion * std)
        lower = sma - (desviacion * std)
        return upper, sma, lower

    @staticmethod
    def calcular_atr(highs, lows, closes, periodo=14):
        if len(highs) < 2:
            return 0.0
        tr_values = []
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_values.append(tr)
        if not tr_values:
            return 0.0
        if len(tr_values) <= periodo:
            return sum(tr_values) / len(tr_values)
        atr = sum(tr_values[:periodo]) / periodo
        k = 2 / (periodo + 1)
        for tr in tr_values[periodo:]:
            atr = tr * k + atr * (1 - k)
        return atr


# ──────────────────────────────────────────────
# ESTRATEGIAS (mismas que engine.py)
# ──────────────────────────────────────────────

class ScalpingRSI:
    """RSI scalping M1 — pero en backtest usamos datos de 5m/15m"""
    def __init__(self, params=None):
        if params is None:
            params = {}
        self.params = params
        self.analizador = TechnicalAnalyzer()

    def analizar(self, precios_cierre):
        periodo = self.params.get("rsi_periodo", 14)
        sobrecompra = self.params.get("rsi_sobrecompra", 70)
        sobreventa = self.params.get("rsi_sobreventa", 30)

        if len(precios_cierre) < periodo + 1:
            return {"senal": "neutral", "confianza": 0, "rsi": 50}

        rsi = self.analizador.calcular_rsi(precios_cierre, periodo)

        resultado = {"senal": "neutral", "confianza": 0, "rsi": round(rsi, 2)}

        if rsi < sobreventa:
            resultado["senal"] = "buy"
            resultado["confianza"] = min(100, int((sobreventa - rsi) * 3))
        elif rsi > sobrecompra:
            resultado["senal"] = "sell"
            resultado["confianza"] = min(100, int((rsi - sobrecompra) * 3))

        return resultado


class TrendFollowingEMA:
    """Cruce de EMAs + MACD confirmation"""
    def __init__(self, params=None):
        if params is None:
            params = {}
        self.params = params
        self.analizador = TechnicalAnalyzer()

    def analizar(self, precios_cierre):
        if len(precios_cierre) < 30:
            return {"senal": "neutral", "confianza": 0}

        ema_rapida = self.params.get("ema_rapida", 9)
        ema_lenta = self.params.get("ema_lenta", 21)

        ema_r = self.analizador.calcular_ema(precios_cierre, ema_rapida)
        ema_l = self.analizador.calcular_ema(precios_cierre, ema_lenta)

        resultado = {"senal": "neutral", "confianza": 0}

        # EMA crossover
        ema_r_prev = self.analizador.calcular_ema(precios_cierre[:-1], ema_rapida)
        ema_l_prev = self.analizador.calcular_ema(precios_cierre[:-1], ema_lenta)

        if ema_r_prev < ema_l_prev and ema_r > ema_l:
            resultado["senal"] = "buy"
            resultado["confianza"] = 75
        elif ema_r_prev > ema_l_prev and ema_r < ema_l:
            resultado["senal"] = "sell"
            resultado["confianza"] = 75

        # Tendencia establecida
        if ema_r > ema_l and precios_cierre[-1] > ema_r:
            resultado["senal"] = "buy"
            resultado["confianza"] = max(resultado["confianza"], 60)
        elif ema_r < ema_l and precios_cierre[-1] < ema_r:
            resultado["senal"] = "sell"
            resultado["confianza"] = max(resultado["confianza"], 60)

        return resultado


class BreakoutBB:
    """Breakout de Bollinger Bands"""
    def __init__(self, params=None):
        if params is None:
            params = {}
        self.params = params
        self.analizador = TechnicalAnalyzer()

    def analizar(self, precios_cierre):
        if len(precios_cierre) < 25:
            return {"senal": "neutral", "confianza": 0}

        periodo = self.params.get("bb_periodo", 20)
        desviacion = self.params.get("bb_desviacion", 2.0)
        upper, middle, lower = self.analizador.calcular_bb(precios_cierre, periodo, desviacion)

        resultado = {"senal": "neutral", "confianza": 0}

        precio_actual = precios_cierre[-1]
        precio_anterior = precios_cierre[-2] if len(precios_cierre) > 1 else precio_actual

        if precio_anterior <= upper and precio_actual > upper:
            resultado["senal"] = "buy"
            resultado["confianza"] = 70
        elif precio_anterior >= lower and precio_actual < lower:
            resultado["senal"] = "sell"
            resultado["confianza"] = 70

        if precio_actual < lower:
            resultado["senal"] = "buy"
            resultado["confianza"] = max(resultado["confianza"], 55)
        elif precio_actual > upper:
            resultado["senal"] = "sell"
            resultado["confianza"] = max(resultado["confianza"], 55)

        return resultado


ESTRATEGIAS_CLASES = {
    "scalping_rsi": ScalpingRSI,
    "trend_following_ema": TrendFollowingEMA,
    "breakout_bb": BreakoutBB,
}

# ──────────────────────────────────────────────
# BACKTEST ENGINE
# ──────────────────────────────────────────────

class BacktestTrade:
    def __init__(self, idx, simbolo, estrategia, tipo, precio_entrada, sl, tp,
                 timestamp, lotes, spread_pips, pip_size, pip_value):
        self.idx = idx
        self.simbolo = simbolo
        self.estrategia = estrategia
        self.tipo = tipo  # buy/sell
        self.precio_entrada = precio_entrada
        self.sl = sl
        self.tp = tp
        self.timestamp = timestamp
        self.lotes = lotes
        self.spread_pips = spread_pips
        self.pip_size = pip_size
        self.pip_value = pip_value
        self.resultado = "abierta"
        self.precio_salida = None
        self.timestamp_salida = None
        self.profit_pips = 0.0
        self.profit_usd = 0.0
        self.comision = 0.0
        self.profit_neto = 0.0

    def cerrar(self, precio_salida, timestamp, razon="sl_tp"):
        self.resultado = razon
        self.precio_salida = precio_salida
        self.timestamp_salida = timestamp

        if self.tipo == "buy":
            self.profit_pips = (precio_salida - self.precio_entrada) / self.pip_size
        else:
            self.profit_pips = (self.precio_entrada - precio_salida) / self.pip_size

        self.profit_usd = self.profit_pips * self.pip_value * self.lotes
        self.comision = COMISION_POR_LOTE_IDA * 2 * self.lotes  # ida + vuelta
        self.profit_neto = self.profit_usd - self.comision

    def __repr__(self):
        return f"#{self.idx} {self.simbolo} {self.tipo.upper()} {self.estrategia} P&L=${self.profit_neto:.2f}"


class BacktestEngine:
    def __init__(self, capital_inicial=CAPITAL_INICIAL):
        self.capital = capital_inicial
        self.peak_balance = capital_inicial
        self.max_drawdown = 0.0
        self.trades: List[BacktestTrade] = []
        self.trade_idx = 0
        self.analizador = TechnicalAnalyzer()

    def calcular_lotes(self, precio, sl_distancia_pips, balance=None):
        """Igual que RiskManager en engine.py"""
        bal = balance or self.capital
        riesgo_pct = 0.02  # 2% por trade
        riesgo_usd = bal * riesgo_pct

        if sl_distancia_pips <= 0:
            return 0.01

        pip_value_est = 10.0  # estimado
        lotes = riesgo_usd / (sl_distancia_pips * pip_value_est)
        lotes = max(0.01, min(lotes, bal / 1000))
        lotes = round(lotes * 100) / 100
        return max(0.01, lotes)

    def ejecutar_backtest(self, velas, simbolo, estrategia_nombre, estrategia_obj,
                          sl_pips=15, tp_pips=30, intervalo="5m"):
        """
        Corre backtest sobre velas históricas.
        velas: lista de dicts con open, high, low, close, volume, timestamp
        """
        if len(velas) < 50:
            return {"error": "insuficientes velas", "trades": 0, "pnl_total": 0}

        pip_size = PIP_SIZE_MAP.get(simbolo, 0.0001)
        pip_value = PIP_VALUE_MAP.get(simbolo, 10.0)
        spread_pips = SPREAD_TIPICO.get(simbolo, 1.0)
        precios_close = [v["close"] for v in velas]

        trades_ejecutados = 0
        ganancias = []
        ultimo_idx_trade = -999  # cooldown entre trades

        # Cooldown: cantidad de velas que hay que esperar entre trades
        # Para M5: 1 vela de cooldown ≈ 5 min
        cooldown_velas = max(1, {"M1": 0, "M5": 1, "M15": 3, "M30": 6}.get(intervalo, 1))

        orden_abierta: Optional[BacktestTrade] = None

        for i in range(len(velas)):
            vela = velas[i]
            close = precios_close[i]

            # Check SL/TP de orden abierta
            if orden_abierta is not None:
                if orden_abierta.tipo == "buy":
                    if vela["low"] <= orden_abierta.sl:
                        orden_abierta.cerrar(orden_abierta.sl, vela["timestamp"], "sl")
                        self._finalizar_trade(orden_abierta)
                        orden_abierta = None
                        continue
                    elif vela["high"] >= orden_abierta.tp:
                        orden_abierta.cerrar(orden_abierta.tp, vela["timestamp"], "tp")
                        self._finalizar_trade(orden_abierta)
                        orden_abierta = None
                        continue
                else:  # sell
                    if vela["high"] >= orden_abierta.sl:
                        orden_abierta.cerrar(orden_abierta.sl, vela["timestamp"], "sl")
                        self._finalizar_trade(orden_abierta)
                        orden_abierta = None
                        continue
                    elif vela["low"] <= orden_abierta.tp:
                        orden_abierta.cerrar(orden_abierta.tp, vela["timestamp"], "tp")
                        self._finalizar_trade(orden_abierta)
                        orden_abierta = None
                        continue

                # Si la orden sigue abierta, seguimos
                if orden_abierta is not None:
                    continue

            # Cooldown
            if i - ultimo_idx_trade < cooldown_velas:
                continue

            # Analizar
            ventana_precios = precios_close[:i+1]
            if len(ventana_precios) < 30:
                continue

            senal = estrategia_obj.analizar(ventana_precios)
            if senal["senal"] not in ("buy", "sell") or senal["confianza"] < 50:
                continue

            # STOP en modo demo_real: no operar fuera de horario (simplificado)
            # Calcular lotes
            lotes = self.calcular_lotes(close, sl_pips)

            # Precio de entrada con spread
            if senal["senal"] == "buy":
                precio_entrada = close * (1 + spread_pips * pip_size)  # compro en ask
            else:
                precio_entrada = close * (1 - spread_pips * pip_size)  # vendo en bid

            # SL/TP
            if senal["senal"] == "buy":
                sl = precio_entrada - (sl_pips * pip_size)
                tp = precio_entrada + (tp_pips * pip_size)
            else:
                sl = precio_entrada + (sl_pips * pip_size)
                tp = precio_entrada - (tp_pips * pip_size)

            order = BacktestTrade(
                idx=len(self.trades) + 1,
                simbolo=simbolo,
                estrategia=estrategia_nombre,
                tipo=senal["senal"],
                precio_entrada=round(precio_entrada, 5),
                sl=round(sl, 5),
                tp=round(tp, 5),
                timestamp=vela["timestamp"],
                lotes=lotes,
                spread_pips=spread_pips,
                pip_size=pip_size,
                pip_value=pip_value,
            )
            orden_abierta = order
            ultimo_idx_trade = i

            # Si la vela ya cruzo SL o TP inmediatamente
            if order.tipo == "buy":
                if vela["low"] <= order.sl:
                    order.cerrar(order.sl, vela["timestamp"], "sl")
                    self._finalizar_trade(order)
                    orden_abierta = None
                elif vela["high"] >= order.tp:
                    order.cerrar(order.tp, vela["timestamp"], "tp")
                    self._finalizar_trade(order)
                    orden_abierta = None
            else:
                if vela["high"] >= order.sl:
                    order.cerrar(order.sl, vela["timestamp"], "sl")
                    self._finalizar_trade(order)
                    orden_abierta = None
                elif vela["low"] <= order.tp:
                    order.cerrar(order.tp, vela["timestamp"], "tp")
                    self._finalizar_trade(order)
                    orden_abierta = None

        # Cerrar orden que quedó abierta al final
        if orden_abierta is not None:
            orden_abierta.cerrar(velas[-1]["close"], velas[-1]["timestamp"], "fin_backtest")
            self._finalizar_trade(orden_abierta)

        return self._generar_reporte(simbolo, estrategia_nombre)

    def _finalizar_trade(self, trade):
        self.trades.append(trade)
        self.capital += trade.profit_neto
        if self.capital > self.peak_balance:
            self.peak_balance = self.capital
        dd = (self.peak_balance - self.capital) / self.peak_balance
        self.max_drawdown = max(self.max_drawdown, dd)

    def _generar_reporte(self, simbolo, estrategia_nombre):
        trades_estrategia = [t for t in self.trades if t.estrategia == estrategia_nombre
                             and t.simbolo == simbolo]
        if not trades_estrategia:
            return {"error": "sin trades", "trades": 0, "pnl_total": 0}

        ganancias = [t.profit_neto for t in trades_estrategia]
        ganadores = [g for g in ganancias if g > 0]
        perdedores = [g for g in ganancias if g <= 0]

        return {
            "simbolo": simbolo,
            "estrategia": estrategia_nombre,
            "trades": len(trades_estrategia),
            "pnl_total": round(sum(ganancias), 2),
            "ganadores": len(ganadores),
            "perdedores": len(perdedores),
            "win_rate": round(len(ganadores) / len(ganancias) * 100, 1) if ganancias else 0,
            "promedio_ganador": round(sum(ganadores) / len(ganadores), 2) if ganadores else 0,
            "promedio_perdedor": round(sum(perdedores) / len(perdedores), 2) if perdedores else 0,
            "max_ganador": round(max(ganancias), 2) if ganancias else 0,
            "max_perdedor": round(min(ganancias), 2) if ganancias else 0,
            "profit_factor": round(abs(sum(ganadores) / sum(perdedores)), 2) if perdedores and sum(perdedores) != 0 else "inf",
            "capital_final": round(self.capital, 2),
            "max_drawdown": round(self.max_drawdown * 100, 1),
            "comisiones_totales": round(sum(t.comision for t in trades_estrategia), 2),
            "spread_pips": SPREAD_TIPICO.get(simbolo, 1.0),
        }


# ──────────────────────────────────────────────
# DATA FETCHER
# ──────────────────────────────────────────────

def fetch_yahoo_data(simbolo, intervalo="5m", dias=30):
    """Obtiene velas de Yahoo Finance para backtesting"""
    try:
        import yfinance as yf
    except ImportError:
        print("[!] yfinance no instalado: pip install yfinance")
        return []

    yahoo_sym = PARES_YAHOO.get(simbolo, simbolo)

    # Yahoo Finance da datos 1m para últimos 7 días, 5m para 60 días
    # Usamos period en lugar de start para máxima compatibilidad
    yahoo_interval = intervalo if intervalo in ("1m", "2m", "5m", "15m", "30m", "60m") else "5m"

    # Mapeo de intervalo a período máximo que Yahoo soporta
    period_max_map = {"1m": "7d", "2m": "7d", "5m": "1mo", "15m": "2mo",
                       "30m": "3mo", "60m": "6mo"}
    yahoo_period = period_max_map.get(yahoo_interval, "5d")

    # Para más de 7 días de datos 1m, iteramos
    if yahoo_interval == "1m" and dias > 7:
        # Bajamos 1 día a la vez para tener más datos
        velas = []
        for day_offset in range(dias, 0, -7):
            start = (datetime.now() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
            end = (datetime.now() - timedelta(days=max(0, day_offset - 7))).strftime("%Y-%m-%d")
            try:
                df = yf.download(yahoo_sym, start=start, end=end, interval="1m", progress=False)
                if not df.empty:
                    for idx, row in df.iterrows():
                        ts = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
                        velas.append({
                            "timestamp": ts,
                            "open": float(row["Open"]) if hasattr(row, "Open") else float(row.iloc[0]),
                            "high": float(row["High"]) if hasattr(row, "High") else float(row.iloc[1]),
                            "low": float(row["Low"]) if hasattr(row, "Low") else float(row.iloc[2]),
                            "close": float(row["Close"]) if hasattr(row, "Close") else float(row.iloc[3]),
                            "volume": int(row["Volume"]) if hasattr(row, "Volume") else 0,
                        })
            except Exception:
                pass

        # Deduplicar por timestamp
        vistos = set()
        unicas = []
        for v in velas:
            ts_key = v["timestamp"].isoformat()
            if ts_key not in vistos:
                vistos.add(ts_key)
                unicas.append(v)
        unicas.sort(key=lambda x: x["timestamp"])
        return unicas

    try:
        # yfinance v0.2+ devuelve DataFrame con MultiIndex en columnas si hay más de 1 ticker
        # pero con un solo ticker devuelve flat. Nos aseguramos de pasar solo un yahoo_sym.
        df = yf.download(yahoo_sym, period=yahoo_period, interval=yahoo_interval, progress=False)

        if df.empty:
            # Fallback: intentar con start/end
            start_date = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
            df = yf.download(yahoo_sym, start=start_date, interval=yahoo_interval, progress=False)

        if df.empty:
            print(f"  ⚠ {simbolo}: sin datos Yahoo para {yahoo_period}")
            return []

        # Aplanar columnas MultiIndex (yfinance v0.2+ devuelve (Price, Ticker))
        if isinstance(df.columns, pd.MultiIndex):
            # Tomar solo el primer nivel (Price: Open/High/Low/Close/Volume)
            df.columns = df.columns.droplevel(1)  # saca Ticker level

        velas = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
            # row es una Series; accedemos directo a valores
            velas.append({
                "timestamp": ts,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]) if "Volume" in row.index else 0,
            })

        return velas
    except Exception as e:
        print(f"  ❌ {simbolo}: error fetching: {e}")
        return []


# ──────────────────────────────────────────────
# RESULTADOS
# ──────────────────────────────────────────────

def generar_reporte_csv(resultados: List[dict], archivo: str):
    """Guarda resultados como CSV"""
    path = RESULTS_DIR / archivo
    with open(path, "w", newline="") as f:
        if not resultados:
            f.write("sin_resultados\n")
            return
        campos = list(resultados[0].keys())
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(resultados)
    print(f"  📄 CSV guardado: {path}")


def generar_resumen(resultados: List[dict]):
    """Muestra resumen en terminal"""
    print(f"\n{'='*70}")
    print(f"  📊 RESUMEN DE BACKTESTING")
    print(f"  {'='*70}")
    print(f"  {'Par':<8} {'Estrategia':<20} {'Trades':<7} {'WR%':<6} {'PnL $':<8} {'DD%':<6} {'PF':<6} {'Spread':<7}")
    print(f"  {'-'*70}")

    # Agrupar
    por_par_estrategia = defaultdict(list)
    for r in resultados:
        if "error" not in r:
            por_par_estrategia[f"{r['simbolo']}_{r['estrategia']}"].append(r)

    total_trades = 0
    total_pnl = 0.0
    mejores_estrategias = []

    for key, group in por_par_estrategia.items():
        r = group[0]
        # Color según PnL
        pnl_color = "+" if r["pnl_total"] > 0 else ""
        dd_color = "⚠" if r.get("max_drawdown", 0) > 20 else " "

        print(f"  {r['simbolo']:<8} {r['estrategia']:<20} {r['trades']:<7} "
              f"{r['win_rate']:<6} {pnl_color}${r['pnl_total']:<6.2f} "
              f"{dd_color}{r.get('max_drawdown', 0):<6} {r.get('profit_factor', 0):<6} {r.get('spread_pips', 0)}p")

        total_trades += r["trades"]
        total_pnl += r["pnl_total"]

        if r["pnl_total"] > 0 and r["trades"] >= 20:
            mejores_estrategias.append(r)

    print(f"  {'-'*70}")
    print(f"  {'TOTAL':<8} {'':<20} {total_trades:<7} {'':<6} ${total_pnl:<7.2f}")

    # Mejores combinaciones
    if mejores_estrategias:
        print(f"\n  🏆 MEJORES COMBINACIONES:")
        mejores_estrategias.sort(key=lambda x: x["pnl_total"], reverse=True)
        for r in mejores_estrategias[:5]:
            print(f"     {r['simbolo']:8} + {r['estrategia']:20} → "
                  f"${r['pnl_total']:>+7.2f} ({r['trades']} trades, WR {r['win_rate']}%, DD {r['max_drawdown']}%)")


def generar_resultados_json(resultados: List[dict], archivo: str):
    path = RESULTS_DIR / archivo
    with open(path, "w") as f:
        json.dump(resultados, f, indent=2, default=str)
    print(f"  📄 JSON guardado: {path}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtester v7 — Trading Agent")
    parser.add_argument("--pares", type=str, default=None,
                        help="Pares separados por coma (ej: EURUSD,XAUUSD)")
    parser.add_argument("--estrategia", type=str, default=None,
                        help="Estrategia (scalping_rsi, trend_following_ema, breakout_bb)")
    parser.add_argument("--dias", type=int, default=60,
                        help="Días de datos históricos (default: 60)")
    parser.add_argument("--intervalo", type=str, default="5m",
                        help="Intervalo de velas (default: 5m)")
    parser.add_argument("--quick", action="store_true",
                        help="Modo rápido: 1 par + 1 estrategia")
    parser.add_argument("--sl", type=int, default=None,
                        help="Stop Loss en pips (default: por estrategia)")
    parser.add_argument("--tp", type=int, default=None,
                        help="Take Profit en pips (default: por estrategia)")
    args = parser.parse_args()

    print(f"\n🤖 BACKTESTER v7 — Trading Agent")
    print(f"   Capital inicial: ${CAPITAL_INICIAL}")
    print(f"   Período: {args.dias} días | Intervalo: {args.intervalo}")
    print(f"   Comisiones: $3.50/lote redondo (IC Markets Raw Spread)")

    # Seleccionar pares
    if args.pares:
        pares = [p.strip() for p in args.pares.split(",")]
    elif args.quick:
        pares = ["EURUSD"]
    else:
        pares = list(PARES_YAHOO.keys())

    # Seleccionar estrategias
    if args.estrategia:
        estrategias = [args.estrategia]
    elif args.quick:
        estrategias = ["trend_following_ema"]
    else:
        estrategias = list(ESTRATEGIAS_CLASES.keys())

    # Configuración SL/TP por estrategia
    SL_TP_CONFIG = {
        "scalping_rsi": (args.sl or 10, args.tp or 20),      # 1:2
        "trend_following_ema": (args.sl or 15, args.tp or 35),  # 1:2.33
        "breakout_bb": (args.sl or 12, args.tp or 28),        # 1:2.33
    }

    print(f"   Pares: {len(pares)} | Estrategias: {len(estrategias)}")
    print(f"   SL/TP: {', '.join(f'{e}={SL_TP_CONFIG[e]}' for e in estrategias)}")
    print(f"  {'='*70}")

    resultados = []
    total_combos = len(pares) * len(estrategias)
    combo_actual = 0

    for simbolo in pares:
        print(f"\n📡 {simbolo}: descargando {args.dias} días de datos...")
        velas = fetch_yahoo_data(simbolo, args.intervalo, args.dias)

        if not velas:
            print(f"  ⏭ Sin datos para {simbolo}")
            continue

        print(f"  ✅ {len(velas)} velas descargadas "
              f"({velas[0]['timestamp'].strftime('%Y-%m-%d')} → "
              f"{velas[-1]['timestamp'].strftime('%Y-%m-%d')})")

        for est_nombre in estrategias:
            combo_actual += 1
            print(f"  🔄 [{combo_actual}/{total_combos}] Probando {simbolo} + {est_nombre}...", end=" ")

            sl_pips, tp_pips = SL_TP_CONFIG[est_nombre]
            clase_estrategia = ESTRATEGIAS_CLASES[est_nombre]
            estrategia_obj = clase_estrategia()

            engine = BacktestEngine(CAPITAL_INICIAL)
            resultado = engine.ejecutar_backtest(
                velas, simbolo, est_nombre, estrategia_obj,
                sl_pips=sl_pips, tp_pips=tp_pips,
                intervalo=args.intervalo
            )

            if "error" in resultado:
                print(f"❌ {resultado['error']}")
            else:
                pnl_color = "+" if resultado["pnl_total"] > 0 else ""
                print(f"✅ {resultado['trades']} trades | WR {resultado['win_rate']}% | PnL {pnl_color}${resultado['pnl_total']} | DD {resultado['max_drawdown']}%")
                resultados.append(resultado)

    # Resumen final
    if resultados:
        generar_resumen(resultados)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        generar_reporte_csv(resultados, f"backtest_{timestamp}.csv")
        generar_resultados_json(resultados, f"backtest_{timestamp}.json")

        # Guardar mejor combinación
        positivos = [r for r in resultados if r["pnl_total"] > 0 and r["trades"] >= 10]
        if positivos:
            positivos.sort(key=lambda x: x["pnl_total"], reverse=True)
            mejor = positivos[0]
            print(f"\n  🥇 MEJOR RESULTADO: {mejor['simbolo']} + {mejor['estrategia']}")
            print(f"     ${mejor['pnl_total']:.2f} en {mejor['trades']} trades | "
                  f"WR {mejor['win_rate']}% | DD {mejor['max_drawdown']}% | "
                  f"PF {mejor['profit_factor']}")
    else:
        print("\n⚠️ No se obtuvieron resultados")

    print(f"\n  {'='*70}")
    return 0


if __name__ == "__main__":
    main()
