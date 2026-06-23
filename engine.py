"""
Trading Engine - Estrategias + Risk Manager + Analizador Técnico
================================================================
"""

import json
import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# ──────────────────────────────────────────────
# ANALIZADOR TÉCNICO
# ──────────────────────────────────────────────

class TechnicalAnalyzer:
    """Indicadores técnicos para análisis de mercado"""
    
    @staticmethod
    def calcular_rsi(precios: List[float], periodo: int = 14) -> float:
        """Relative Strength Index"""
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
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def calcular_ema(precios: List[float], periodo: int) -> float:
        """Exponential Moving Average"""
        if len(precios) < periodo:
            return sum(precios) / len(precios)
        
        k = 2 / (periodo + 1)
        ema = sum(precios[:periodo]) / periodo
        
        for precio in precios[periodo:]:
            ema = precio * k + ema * (1 - k)
        
        return ema
    
    @staticmethod
    def calcular_sma(precios: List[float], periodo: int) -> float:
        """Simple Moving Average"""
        if len(precios) < periodo:
            return sum(precios) / len(precios)
        return sum(precios[-periodo:]) / periodo
    
    @staticmethod
    def calcular_macd(precios: List[float]) -> Tuple[float, float, float]:
        """MACD: línea, señal, histograma"""
        ema_rapida = TechnicalAnalyzer.calcular_ema(precios, 12)
        ema_lenta = TechnicalAnalyzer.calcular_ema(precios, 26)
        macd_line = ema_rapida - ema_lenta
        signal = TechnicalAnalyzer.calcular_ema([macd_line], 9)
        histogram = macd_line - signal
        return macd_line, signal, histogram
    
    @staticmethod
    def calcular_bb(precios: List[float], periodo: int = 20, desviacion: float = 2.0) -> Tuple[float, float, float]:
        """Bollinger Bands: upper, middle, lower"""
        sma = TechnicalAnalyzer.calcular_sma(precios, periodo)
        if len(precios) < periodo:
            return sma, sma, sma
        
        varianza = sum((p - sma) ** 2 for p in precios[-periodo:]) / periodo
        std = math.sqrt(varianza)
        
        upper = sma + (desviacion * std)
        lower = sma - (desviacion * std)
        
        return upper, sma, lower
    
    @staticmethod
    def calcular_atr(highs: List[float], lows: List[float], closes: List[float], periodo: int = 14) -> float:
        """Average True Range"""
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
# RISK MANAGER
# ──────────────────────────────────────────────

class RiskManager:
    """Gestor de riesgo y sizing"""
    
    def __init__(self, config: dict, state: dict = None):
        self.config = config
        self.bot_config = config.get("bot", {})
        self.max_riesgo_por_operacion = self.bot_config.get("max_riesgo_por_operacion", 0.02)
        self.max_drawdown_diario = self.bot_config.get("max_drawdown_diario", 0.10)
        self.max_drawdown_total = self.bot_config.get("max_drawdown_total", 0.30)
        self.max_operaciones_dia = self.bot_config.get("max_operaciones_dia", 10)
        self.capital_inicial = self.bot_config.get("capital_inicial", 100.0)
        
        # Filtro de spread para scalping
        self.spread_max_pips = self.bot_config.get("spread_max_pips", 1.5)
        self.slippage_pips = self.bot_config.get("slippage_pips", 1)
        
        # Estado diario (recuperar desde state persistente si existe)
        if state and state.get("dia_actual") == datetime.now().date().isoformat():
            self.operaciones_hoy = state.get("operaciones_hoy", 0)
            self.pnl_hoy = state.get("pnl_hoy", 0.0)
            self.dia_actual = datetime.now().date()
            self.max_balance = state.get("max_balance", self.capital_inicial)
        else:
            self.operaciones_hoy = 0
            self.pnl_hoy = 0.0
            self.dia_actual = datetime.now().date()
            self.max_balance = self.capital_inicial
    
    def puede_operar(self, balance: float, equity: float, simbolo: str = None, estrategia: str = None, tick: object = None) -> Tuple[bool, str]:
        """Verifica si se puede operar según las reglas de riesgo"""
        now = datetime.now().date()
        
        # Reset diario
        if now != self.dia_actual:
            self.operaciones_hoy = 0
            self.pnl_hoy = 0.0
            self.dia_actual = now
        
        # Verificar drawdown total
        drawdown = (self.max_balance - balance) / self.max_balance if self.max_balance > 0 else 0
        if drawdown > self.max_drawdown_total:
            return False, f"DRAWDOWN TOTAL EXCEDIDO: {drawdown:.1%} > {self.max_drawdown_total:.1%}"
        
        # Verificar drawdown diario
        if balance < self.capital_inicial * (1 - self.max_drawdown_diario):
            return False, f"DRAWDOWN DIARIO EXCEDIDO"
        
        # Verificar máximo de operaciones
        if self.operaciones_hoy >= self.max_operaciones_dia:
            return False, f"MÁXIMO DE {self.max_operaciones_dia} OPERACIONES HOY ALCANZADO"
        
        # Verificar balance mínimo
        if balance < 1.0:
            return False, "BALANCE INSUFICIENTE"

        # Filtro de spread máximo (para scalping en M1)
        # Solo activo en modo real/ctrader — en simulado/demo_real los spreads son irreales
        if estrategia == "scalping_rsi" and simbolo and tick and self.config.get("bot", {}).get("modo") in ("real", "ctrader"):
            pip_size = 0.0001 if tick.get("ask", 0) < 100 else 0.01
            spread_pips = abs(tick.get("ask", 0) - tick.get("bid", 0)) / pip_size if pip_size > 0 else 0
            if spread_pips > self.spread_max_pips:
                return False, f"SPREAD DEMASIADO ALTO: {spread_pips:.1f} pips > {self.spread_max_pips} pips (máx. para scalping)"
        
        return True, "OK"
    
    def calcular_tamano_posicion(self, balance: float, precio: float, 
                                 stop_loss_distancia: float, riesgo_extra: float = 1.0) -> float:
        """
        Calcula el tamaño de la posición basado en riesgo.
        Usa el método de riesgo fijo: arriesgar X% del capital
        """
        riesgo_porcentaje = self.max_riesgo_por_operacion * riesgo_extra
        riesgo_usd = balance * riesgo_porcentaje
        
        if stop_loss_distancia <= 0:
            return 0.01  # lote mínimo
        
        # Calcular lotes: riesgo_usd / (distancia_sl * valor_del_pip * 100000)
        # Simplificado: para forex, $10 por pip por lote estándar
        pip_size = 0.0001 if precio < 100 else 0.01
        sl_en_pips = stop_loss_distancia / pip_size
        
        if sl_en_pips <= 0:
            return 0.01
        
        valor_por_pip_por_lote = 10.0  # $10 por pip para 1 lote estándar
        lotes = riesgo_usd / (sl_en_pips * valor_por_pip_por_lote)
        
        # Limitar a micro-lotes
        lotes = max(0.01, min(lotes, balance / 1000))  # máximo ~10% del capital en margen
        
        # Redondear a 0.01
        lotes = round(lotes * 100) / 100
        
        return max(0.01, lotes)
    
    def registrar_trade(self, profit: float):
        """Registra un trade para tracking diario"""
        self.operaciones_hoy += 1
        self.pnl_hoy += profit
        
        # Actualizar max balance
        if profit > 0:
            # Solo considerar balances que suben
            pass
    
    def to_dict(self) -> dict:
        """Serializa estado para persistencia"""
        return {
            "operaciones_hoy": self.operaciones_hoy,
            "pnl_hoy": self.pnl_hoy,
            "dia_actual": self.dia_actual.isoformat(),
            "max_balance": self.max_balance
        }


# ──────────────────────────────────────────────
# ESTRATEGIAS DE TRADING
# ──────────────────────────────────────────────

class StrategyBase:
    """Clase base para estrategias"""
    
    def __init__(self, nombre: str, config: dict, connector):
        self.nombre = nombre
        self.config = config
        self.connector = connector
        self.params = config.get("params", {})
        self.timeframe = config.get("timeframe", "M5")
        self.activa = config.get("activa", True)
        self.analizador = TechnicalAnalyzer()
    
    def analizar(self, simbolo: str) -> dict:
        """Analiza un símbolo y devuelve señal"""
        raise NotImplementedError
    
    def __str__(self):
        return f"{self.nombre} ({self.timeframe})"


class ScalpingRSI(StrategyBase):
    """Scalping basado en RSI - para M1/M5"""
    
    def analizar(self, simbolo: str) -> dict:
        velas = self.connector.obtener_velas(simbolo, 100)
        if len(velas) < 20:
            return {"senal": "neutral", "confianza": 0}
        
        precios_close = [v.close for v in velas]
        rsi = self.analizador.calcular_rsi(precios_close, self.params.get("rsi_periodo", 14))
        
        sobrecompra = self.params.get("rsi_sobrecompra", 70)
        sobreventa = self.params.get("rsi_sobreventa", 30)
        
        resultado = {
            "senal": "neutral",
            "confianza": 0,
            "rsi": round(rsi, 2),
            "tp_pips": self.params.get("take_profit_pips", 10),
            "sl_pips": self.params.get("stop_loss_pips", 5),
        }
        
        # Señales RSI
        if rsi < sobreventa:
            resultado["senal"] = "buy"
            resultado["confianza"] = min(100, int((sobreventa - rsi) * 3))
        elif rsi > sobrecompra:
            resultado["senal"] = "sell"
            resultado["confianza"] = min(100, int((rsi - sobrecompra) * 3))
        
        # Divergencia simple: RSI bajando pero precio subiendo = posible reversión
        if len(precios_close) > 20 and len(velas) > 10:
            rsi_anterior = self.analizador.calcular_rsi(precios_close[:-5], self.params.get("rsi_periodo", 14))
            precio_anterior = precios_close[-10]
            precio_actual = precios_close[-1]
            
            if rsi < rsi_anterior and precio_actual > precio_anterior:
                resultado["senal"] = "sell"  # Divergencia bajista
                resultado["confianza"] = max(resultado["confianza"], 60)
            elif rsi > rsi_anterior and precio_actual < precio_anterior:
                resultado["senal"] = "buy"  # Divergencia alcista
                resultado["confianza"] = max(resultado["confianza"], 60)
        
        return resultado


class TrendFollowingEMA(StrategyBase):
    """Tendencia basada en cruce de EMAs - para M15/H1"""
    
    def analizar(self, simbolo: str) -> dict:
        velas = self.connector.obtener_velas(simbolo, 100)
        if len(velas) < 30:
            return {"senal": "neutral", "confianza": 0}
        
        precios_close = [v.close for v in velas]
        ema_rapida = self.params.get("ema_rapida", 9)
        ema_lenta = self.params.get("ema_lenta", 21)
        
        ema_r = self.analizador.calcular_ema(precios_close, ema_rapida)
        ema_l = self.analizador.calcular_ema(precios_close, ema_lenta)
        
        # EMA anteriores para detectar cruce
        ema_r_prev = self.analizador.calcular_ema(precios_close[:-5], ema_rapida)
        ema_l_prev = self.analizador.calcular_ema(precios_close[:-5], ema_lenta)
        
        resultado = {
            "senal": "neutral",
            "confianza": 0,
            "ema_rapida": round(ema_r, 5),
            "ema_lenta": round(ema_l, 5),
            "tp_pips": self.params.get("take_profit_pips", 30),
            "sl_pips": self.params.get("stop_loss_pips", 15),
            "trailing_stop": self.params.get("trailing_stop", True)
        }
        
        # Detectar cruce
        if ema_r_prev < ema_l_prev and ema_r > ema_l:
            resultado["senal"] = "buy"
            resultado["confianza"] = 75
        elif ema_r_prev > ema_l_prev and ema_r < ema_l:
            resultado["senal"] = "sell"
            resultado["confianza"] = 75
        
        # Tendencia establecida
        if ema_r > ema_l and precios_close[-1] > ema_r:
            resultado["senal"] = "buy"
            resultado["confianza"] = max(resultado["confianza"], 60)
        elif ema_r < ema_l and precios_close[-1] < ema_r:
            resultado["senal"] = "sell"
            resultado["confianza"] = max(resultado["confianza"], 60)
        
        # MACD confirmation
        macd_line, signal, hist = self.analizador.calcular_macd(precios_close)
        if resultado["senal"] == "buy" and macd_line > signal:
            resultado["confianza"] = min(100, resultado["confianza"] + 15)
        elif resultado["senal"] == "sell" and macd_line < signal:
            resultado["confianza"] = min(100, resultado["confianza"] + 15)
        
        return resultado


class BreakoutBB(StrategyBase):
    """Breakout basado en Bollinger Bands - para M15/H1"""
    
    def analizar(self, simbolo: str) -> dict:
        velas = self.connector.obtener_velas(simbolo, 100)
        if len(velas) < 25:
            return {"senal": "neutral", "confianza": 0}
        
        precios_close = [v.close for v in velas]
        periodo = self.params.get("bb_periodo", 20)
        desviacion = self.params.get("bb_desviacion", 2.0)
        
        upper, middle, lower = self.analizador.calcular_bb(precios_close, periodo, desviacion)
        
        resultado = {
            "senal": "neutral",
            "confianza": 0,
            "bb_upper": round(upper, 5),
            "bb_middle": round(middle, 5),
            "bb_lower": round(lower, 5),
            "tp_pips": self.params.get("take_profit_pips", 25),
            "sl_pips": self.params.get("stop_loss_pips", 12),
        }
        
        precio_actual = precios_close[-1]
        precio_anterior = precios_close[-2] if len(precios_close) > 1 else precio_actual
        
        # Breakout de banda superior
        if precio_anterior <= upper and precio_actual > upper:
            resultado["senal"] = "buy"
            resultado["confianza"] = 70
        # Breakout de banda inferior
        elif precio_anterior >= lower and precio_actual < lower:
            resultado["senal"] = "sell"
            resultado["confianza"] = 70
        
        # Rebotando desde las bandas
        if precio_actual < lower * 0.998:  # muy cerca o tocando banda inferior
            resultado["senal"] = "buy"
            resultado["confianza"] = max(resultado["confianza"], 55)
        elif precio_actual > upper * 1.002:  # muy cerca o tocando banda superior
            resultado["senal"] = "sell"
            resultado["confianza"] = max(resultado["confianza"], 55)
        
        return resultado


class GridScalper(StrategyBase):
    """Grid scalping para mercado lateral"""
    
    def analizar(self, simbolo: str) -> dict:
        velas = self.connector.obtener_velas(simbolo, 50)
        if len(velas) < 20:
            return {"senal": "neutral", "confianza": 0}
        
        precios_close = [v.close for v in velas]
        precios_high = [v.high for v in velas]
        precios_low = [v.low for v in velas]
        
        rango = max(precios_high[-20:]) - min(precios_low[-20:])
        rango_pct = rango / precios_close[-1]
        
        resultado = {
            "senal": "neutral",
            "confianza": 0,
            "rango": round(rango, 5),
            "rango_pct": round(rango_pct * 100, 2),
            "tp_pips": self.params.get("take_profit_pips", 5),
            "sl_pips": self.params.get("stop_loss_pips", 50),
        }
        
        # Grid funciona mejor en mercado lateral (rango bajo)
        if rango_pct < 0.005:  # menos de 0.5% de rango
            resultado["senal"] = "grid"
            resultado["confianza"] = 80
            resultado["grid_pasos"] = self.params.get("grid_pasos", 5)
            resultado["distancia_pips"] = self.params.get("distancia_pips", 10)
        
        return resultado


# ──────────────────────────────────────────────
# ESTRATEGY ENGINE
# ──────────────────────────────────────────────

class StrategyEngine:
    """Motor que ejecuta todas las estrategias y toma decisiones"""
    
    def __init__(self, config: dict, connector, state: dict = None):
        self.config = config
        self.connector = connector
        self.risk_manager = RiskManager(config, state.get("risk_manager") if state else None)
        self.estrategias: Dict[str, StrategyBase] = {}
        self.aprendizaje_config = config.get("aprendizaje", {})
        self.historial_estrategias: Dict[str, List[dict]] = {}
        self.rendimiento_estrategias: Dict[str, dict] = {}
        
        # Sistema de Candle Lock (cooldown por vela)
        # clave: "EURUSD_trend_following_ema" -> timestamp del último trade
        self.ultimo_trade_por_par_estrategia: Dict[str, datetime] = {}
        self.cooldown_config = {}  # nombre_estrategia -> minutos de cooldown
        
        self._cargar_estrategias()
    
    def _cargar_estrategias(self):
        """Carga las estrategias desde la config"""
        mapa_estrategias = {
            "scalping_rsi": ScalpingRSI,
            "trend_following_ema": TrendFollowingEMA,
            "breakout_bb": BreakoutBB,
            "grid_scalper": GridScalper,
        }
        
        for est_config in self.config.get("estrategias", []):
            nombre = est_config.get("nombre", "")
            if nombre in mapa_estrategias and est_config.get("activa", False):
                clase = mapa_estrategias[nombre]
                self.estrategias[nombre] = clase(nombre, est_config, self.connector)
                self.historial_estrategias[nombre] = []
                self.rendimiento_estrategias[nombre] = {
                    "ganadoras": 0,
                    "perdedoras": 0,
                    "total_pnl": 0.0,
                    "win_rate": 0.0,
                    "trades": 0,
                    "promedio_pnl": 0.0,
                    "mejor_trade": 0.0,
                    "peor_trade": 0.0
                }
                # Magic numbers para MT5
                magic_numbers = {"scalping_rsi": 1001, "trend_following_ema": 1002,
                                 "breakout_bb": 1003, "grid_scalper": 1004}
                self.estrategias[nombre].magic_number = magic_numbers.get(nombre, 1000)
                
                # Cooldown: el timeframe de la estrategia en minutos
                tf_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
                tf = est_config.get("timeframe", "M15")
                self.cooldown_config[nombre] = tf_map.get(tf, 15)
    
    def analizar_simbolo(self, simbolo: str) -> List[dict]:
        """Analiza un símbolo con todas las estrategias activas"""
        resultados = []
        
        for nombre, estrategia in self.estrategias.items():
            try:
                resultado = estrategia.analizar(simbolo)
                resultado["estrategia"] = nombre
                resultado["simbolo"] = simbolo
                resultados.append(resultado)
            except Exception as e:
                resultados.append({
                    "estrategia": nombre,
                    "simbolo": simbolo,
                    "senal": "error",
                    "confianza": 0,
                    "error": str(e)
                })
        
        return resultados
    
    def _calcular_win_rate_rolling(self, estrategia: str, ventana: int = 40) -> float:
        """Calcula win rate con ventana flotante (rolling window) sobre últimos N trades"""
        historial = self.historial_estrategias.get(estrategia, [])
        if len(historial) < 5:
            return None  # muestra insuficiente
        
        # Últimos N trades de la ventana
        ventana_trades = historial[-ventana:]
        ganadores = sum(1 for t in ventana_trades if t.get("profit", 0) > 0)
        total = len(ventana_trades)
        return ganadores / total if total > 0 else None
    
    def _win_rate_historico(self, estrategia: str) -> float:
        """Win rate histórico total (para comparación con rolling window)"""
        rend = self.rendimiento_estrategias.get(estrategia, {})
        if rend.get("trades", 0) == 0:
            return None
        return rend.get("win_rate", 0.0)
    
    def _comprobar_cooldown(self, simbolo: str, estrategia: str) -> Tuple[bool, int]:
        """
        Candle Lock: evita que una estrategia opere más de una vez por vela.
        Retorna (puede_operar, segundos_restantes)
        """
        clave = f"{simbolo}_{estrategia}"
        ultimo = self.ultimo_trade_por_par_estrategia.get(clave)
        if ultimo is None:
            return True, 0
        
        cooldown_minutos = self.cooldown_config.get(estrategia, 15)
        cooldown_segundos = cooldown_minutos * 60
        ahora = datetime.now()
        transcurrido = (ahora - ultimo).total_seconds()
        
        if transcurrido < cooldown_segundos:
            restante = int(cooldown_segundos - transcurrido)
            return False, restante
        return True, 0
    
    def _registrar_cooldown(self, simbolo: str, estrategia: str):
        """Registra el timestamp de un trade para el sistema de cooldown"""
        clave = f"{simbolo}_{estrategia}"
        self.ultimo_trade_por_par_estrategia[clave] = datetime.now()
    
    def decidir_operacion(self, balance: float, equity: float) -> Optional[dict]:
        """Decide si abrir alguna operación y cuál"""
        
        # Verificar reglas de riesgo (incluye spread filter si hay tick disponible)
        # Para scalping, verificamos spread antes de decidir
        puede = True
        razon = "OK"
        
        # Primero chequeamos las reglas base
        puede_base, razon_base = self.risk_manager.puede_operar(balance, equity)
        if not puede_base:
            return {"accion": "esperar", "razon": razon_base}
        
        # Si hay oportunidades de scalping, pre-verificar spread
        # para no perder tiempo analizando si el spread es malo
        # (esto se verifica de nuevo en ejecutar_operacion con tick real)
        
        # Verificar si ya hay posiciones abiertas - no abrir más si ya tenemos 3+
        ordenes_abiertas = len(self.connector.ordenes_abiertas)
        if ordenes_abiertas >= 3:
            return {"accion": "esperar", "razon": f"máximo 3 posiciones simultáneas ({ordenes_abiertas} activas)"}
        
        # Símbolos que ya tienen posición abierta
        simbolos_ocupados = set(o.simbolo for o in self.connector.ordenes_abiertas.values())
        
        # Analizar todos los símbolos
        todos_simbolos = []
        for categoria in self.config.get("simbolos", {}).values():
            todos_simbolos.extend(categoria)
        
        mejores_ops = []
        
        for simbolo in todos_simbolos:
            if simbolo in simbolos_ocupados:
                continue  # ya tenemos posición en este símbolo
            resultados = self.analizar_simbolo(simbolo)
            
            for r in resultados:
                if r["senal"] in ["buy", "sell"] and r["confianza"] >= 50:
                    mejores_ops.append({
                        "simbolo": simbolo,
                        "senal": r["senal"],
                        "confianza": r["confianza"],
                        "estrategia": r["estrategia"],
                        "sl_pips": r.get("sl_pips", 10),
                        "tp_pips": r.get("tp_pips", 20),
                        "trailing_stop": r.get("trailing_stop", False)
                    })
        
        if not mejores_ops:
            return {"accion": "esperar", "razon": "sin oportunidades"}
        
        # Ordenar por confianza
        mejores_ops.sort(key=lambda x: x["confianza"], reverse=True)
        
        # Escoger la mejor operación
        if not mejores_ops:
            return {"accion": "esperar", "razon": "sin oportunidades"}
        mejor_op = mejores_ops[0]
        
        # Pre-verificar spread para scalping antes de confirmar la operación
        if mejor_op["estrategia"] == "scalping_rsi":
            try:
                tick = self.connector.obtener_tick(mejor_op["simbolo"])
                puede_spread, razon_spread = self.risk_manager.puede_operar(
                    balance, equity,
                    simbolo=mejor_op["simbolo"],
                    estrategia="scalping_rsi",
                    tick={"ask": tick.ask, "bid": tick.bid}
                )
                if not puede_spread:
                    # Intentar segunda mejor opción si spread es malo para scalping
                    if len(mejores_ops) > 1:
                        mejor_op = mejores_ops[1]
                        # logging del cambio se hace fuera
                    else:
                        return {"accion": "esperar", "razon": razon_spread}
            except Exception:
                pass  # Si no podemos obtener tick, continuar de todas formas
        
        # CANDLE LOCK: cooldown por vela de la estrategia
        puede_cooldown, segundos_restantes = self._comprobar_cooldown(
            mejor_op["simbolo"], mejor_op["estrategia"]
        )
        if not puede_cooldown:
            # Intentar segunda opción si la primera está en cooldown
            if len(mejores_ops) > 1:
                # Buscar la primera opción que NO esté en cooldown
                for opcion in mejores_ops[1:]:
                    puede_cd, _ = self._comprobar_cooldown(opcion["simbolo"], opcion["estrategia"])
                    if puede_cd:
                        mejor_op = opcion
                        break
                else:
                    return {"accion": "esperar", "razon": f"cooldown {mejor_op['estrategia']} {mejor_op['simbolo']} ({segundos_restantes}s)"}
            else:
                return {"accion": "esperar", "razon": f"cooldown {mejor_op['estrategia']} {mejor_op['simbolo']} ({segundos_restantes}s)"}
        
        # Aplicar aprendizaje con ventana flotante (rolling window 40 trades)
        # En lugar de win_rate histórico total, evaluamos últimos 40 trades
        if self.aprendizaje_config.get("mejora_estrategica", True):
            est = mejor_op["estrategia"]
            
            # Win rate con ventana flotante (últimos 40 trades)
            wr_rolling = self._calcular_win_rate_rolling(est, ventana=40)
            
            if wr_rolling is not None:
                if wr_rolling < 0.35:
                    # Penalizar pero no bloquear permanentemente
                    mejor_op["confianza"] = max(40, int(mejor_op["confianza"] * 0.7))
                elif wr_rolling > 0.65:
                    # Estrategias ganadoras: bonus de confianza
                    mejor_op["confianza"] = min(100, int(mejor_op["confianza"] * 1.2))
            # Si muestra < 5 trades, no penalizar (período de calentamiento)
        
        # Si hay más de una estrategia disponible, intentar alternar
        if len(mejores_ops) > 1:
            # 20% de probabilidad de probar la segunda mejor opción (exploración)
            import random
            if random.random() < 0.2:
                mejor_op = mejores_ops[1]
        
        # Registrar cooldown ANTES de ejecutar (para evitar reintentos infinitos aunque falle la orden)
        self._registrar_cooldown(mejor_op["simbolo"], mejor_op["estrategia"])
        
        return {
            "accion": "operar",
            "simbolo": mejor_op["simbolo"],
            "tipo": mejor_op["senal"],
            "confianza": mejor_op["confianza"],
            "estrategia": mejor_op["estrategia"],
            "sl_pips": mejor_op["sl_pips"],
            "tp_pips": mejor_op["tp_pips"],
            "trailing_stop": mejor_op.get("trailing_stop", False)
        }
    
    def ejecutar_operacion(self, decision: dict) -> dict:
        """Ejecuta una operación basada en la decisión del agente"""
        
        # Obtener precio actual
        tick = self.connector.obtener_tick(decision["simbolo"])
        
        # Filtro de spread en tiempo de ejecución (para todas las estrategias)
        # Solo activo en modo real/ctrader — en demo_real los spreads son irreales
        modo = self.config.get("bot", {}).get("modo", "simulado")
        if modo in ("real", "ctrader"):
            pip_size = 0.0001 if tick.ask < 100 else 0.01
            spread_pips = abs(tick.ask - tick.bid) / pip_size if pip_size > 0 else 0
            if spread_pips > self.risk_manager.spread_max_pips * 2:
                return {"exito": False, "razon": f"spread excesivo en ejecución: {spread_pips:.1f} pips"}
        
        precio = tick.ask if decision["tipo"] == "buy" else tick.bid
        
        # Calcular tamaño de posición
        balance = self.connector.account.balance  # Usar el balance real del connector
        lotes = self.risk_manager.calcular_tamano_posicion(
            balance, precio, decision["sl_pips"] * 0.0001 if precio < 100 else decision["sl_pips"] * 0.01
        )
        
        # Calcular SL y TP
        pip_size = 0.0001 if precio < 100 else 0.01
        if decision["tipo"] == "buy":
            sl = precio - (decision["sl_pips"] * pip_size)
            tp = precio + (decision["tp_pips"] * pip_size)
        else:
            sl = precio + (decision["sl_pips"] * pip_size)
            tp = precio - (decision["tp_pips"] * pip_size)
        
        sl = round(sl, 5)
        tp = round(tp, 5)
        
        # Abrir orden con slippage + magic number
        magic = getattr(self.estrategias.get(decision.get("estrategia", "")), 'magic_number', 1000)
        order = self.connector.abrir_orden(
            simbolo=decision["simbolo"],
            tipo=decision["tipo"],
            lotes=lotes,
            sl=sl,
            tp=tp,
            slippage=self.risk_manager.slippage_pips,
            magic_number=magic,
            estrategia=decision["estrategia"]
        )
        
        if order:
            # Registrar cooldown para Candle Lock
            self._registrar_cooldown(decision["simbolo"], decision["estrategia"])
            return {
                "exito": True,
                "ticket": order.ticket,
                "simbolo": order.simbolo,
                "tipo": order.tipo,
                "lotes": order.volumen,
                "precio": order.precio_apertura,
                "sl": order.sl,
                "tp": order.tp,
                "estrategia": order.estrategia
            }
        else:
            return {"exito": False, "razon": "margen insuficiente o error"}
    
    def verificar_ordenes_abiertas(self):
        """Verifica SL/TP de órdenes abiertas y cierra si es necesario"""
        cerradas = self.connector.verificar_sl_tp()
        for order in cerradas:
            self._registrar_resultado_trade(order)
        return cerradas
    
    def aplicar_trailing_stop(self):
        """Aplica trailing stop a órdenes con esa configuración"""
        for ticket, order in list(self.connector.ordenes_abiertas.items()):
            est_config = None
            for ec in self.config.get("estrategias", []):
                if ec.get("nombre") == order.estrategia:
                    est_config = ec
                    break
            
            if est_config and est_config.get("params", {}).get("trailing_stop", False):
                tick = self.connector.obtener_tick(order.simbolo)
                distancia_pips = est_config.get("params", {}).get("stop_loss_pips", 15) / 2
                pip_size = 0.0001 if order.precio_apertura < 100 else 0.01
                distancia = distancia_pips * pip_size
                
                if order.tipo == "buy":
                    new_sl = tick.bid - distancia
                    if new_sl > order.sl:
                        order.sl = round(new_sl, 5)
                else:
                    new_sl = tick.ask + distancia
                    if new_sl < order.sl or order.sl == 0:
                        order.sl = round(new_sl, 5)
    
    def _registrar_resultado_trade(self, order):
        """Registra el resultado de un trade para el aprendizaje"""
        est = order.estrategia
        if est not in self.rendimiento_estrategias:
            return
        
        rend = self.rendimiento_estrategias[est]
        rend["trades"] += 1
        rend["total_pnl"] += order.profit_neto
        
        if order.profit_neto > 0:
            rend["ganadoras"] += 1
            if order.profit_neto > rend["mejor_trade"]:
                rend["mejor_trade"] = order.profit_neto
        else:
            rend["perdedoras"] += 1
            if order.profit_neto < rend["peor_trade"]:
                rend["peor_trade"] = order.profit_neto
        
        rend["win_rate"] = rend["ganadoras"] / rend["trades"] if rend["trades"] > 0 else 0
        rend["promedio_pnl"] = rend["total_pnl"] / rend["trades"] if rend["trades"] > 0 else 0
        
        # Guardar en historial
        self.historial_estrategias[est].append({
            "ticket": order.ticket,
            "profit": order.profit_neto,
            "timestamp": datetime.now().isoformat()
        })
    
    def obtener_rendimiento(self) -> dict:
        """Devuelve el rendimiento de todas las estrategias"""
        return self.rendimiento_estrategias
    
    def get_cooldown_status(self) -> dict:
        """Devuelve el estado actual de cooldown para el dashboard"""
        status = {}
        ahora = datetime.now()
        for clave, ultimo in self.ultimo_trade_por_par_estrategia.items():
            # clave formato: "EURUSD_trend_following_ema"
            partes = clave.split("_", 1)
            if len(partes) != 2:
                continue
            simbolo, estrategia = partes
            cooldown_min = self.cooldown_config.get(estrategia, 15)
            transcurrido = (ahora - ultimo).total_seconds()
            restante = max(0, (cooldown_min * 60) - transcurrido)
            status[clave] = {
                "simbolo": simbolo,
                "estrategia": estrategia,
                "cooldown_minutos": cooldown_min,
                "segundos_restantes": int(restante),
                "en_cooldown": restante > 0
            }
        return status
    
    def get_analisis_completo(self, simbolo: str) -> dict:
        """Análisis completo de un símbolo para el dashboard"""
        resultados = self.analizar_simbolo(simbolo)
        velas = self.connector.obtener_velas(simbolo, 50)
        tick = self.connector.obtener_tick(simbolo)
        
        return {
            "simbolo": simbolo,
            "precio": {"bid": tick.bid, "ask": tick.ask, "mid": tick.mid},
            "senales": resultados,
            "ultimas_velas": [
                {
                    "open": v.open, "high": v.high, "low": v.low, 
                    "close": v.close, "volume": v.volume,
                    "timestamp": v.timestamp.isoformat()
                }
                for v in velas[-20:]
            ]
        }
