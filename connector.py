"""
IC Markets Connector - Trading Agent Project
==============================================
Soporta 3 modos:
  1. SIMULADO - Funciona 100% sin conexión, datos sintéticos (ideal para desarrollo)
  2. MT5 - Conexión real con MetaTrader 5 (via Wine o VPS Windows)
  3. cTrader - API REST/WebSocket de cTrader

El modo simulado permite probar todo el sistema ahora mismo.
Cuando tengas la cuenta de IC Markets, activás modo MT5 o cTrader.
"""

import json
import os
import random
import time
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# ──────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────

@dataclass
class Tick:
    """Un tick de precio"""
    simbolo: str
    bid: float
    ask: float
    timestamp: datetime
    spread: float = 0.0
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

@dataclass
class Bar:
    """Una vela OHLCV"""
    simbolo: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime

@dataclass
class Order:
    """Una orden de trading"""
    ticket: int
    simbolo: str
    tipo: str  # buy | sell
    volumen: float  # lotes
    precio_apertura: float
    sl: float  # stop loss
    tp: float  # take profit
    timestamp_apertura: datetime
    timestamp_cierre: Optional[datetime] = None
    precio_cierre: Optional[float] = None
    profit: float = 0.0
    comision: float = 0.0
    swap: float = 0.0
    estado: str = "abierta"  # abierta | cerrada | cancelada
    estrategia: str = ""
    
    @property
    def profit_neto(self) -> float:
        return self.profit - self.comision - self.swap

@dataclass
class AccountInfo:
    """Información de la cuenta"""
    balance: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    leverage: int
    currency: str = "USD"
    

# ──────────────────────────────────────────────
# DATA GENERATOR (Modo Simulado)
# ──────────────────────────────────────────────

class SimulatedDataGenerator:
    """Genera datos sintéticos de mercado para pruebas"""
    
    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)
        self.precos_base = {
            "EURUSD": 1.0850,
            "GBPUSD": 1.2650,
            "USDJPY": 151.50,
            "AUDUSD": 0.6520,
            "USDCAD": 1.3620,
            "NZDUSD": 0.5950,
            "XAUUSD": 2020.0,
            "XAGUSD": 23.50,
            "US30": 38900.0,
            "NAS100": 19800.0,
            "SPX500": 5300.0,
            "GER40": 18000.0,
            "UKOIL": 82.0,
            "USOIL": 78.0,
        }
        self.tendencias = {s: 0.0 for s in self.precos_base}
        self.velas_por_simbolo = {s: [] for s in self.precos_base}
        self.tick_actual = {s: p for s, p in self.precos_base.items()}
        
    def generar_tick(self, simbolo: str) -> Tick:
        """Genera un tick sintético con micro-movimiento"""
        base = self.tick_actual.get(simbolo, self.precos_base.get(simbolo, 1.0))
        
        # Tendencia aleatoria con reversión a la media
        self.tendencias[simbolo] += self.random.gauss(0, 0.00005)
        self.tendencias[simbolo] *= 0.98  # decaimiento más lento = tendencias más largas
        
        # Movimiento browniano más suave
        precio = base * (1 + self.tendencias[simbolo] + self.random.gauss(0, 0.00015))
        
        # Reversión a la media más fuerte
        precio_objetivo = self.precos_base[simbolo]
        precio += (precio_objetivo - precio) * 0.002
        
        # Cada ~30 ticks, cambiar dirección de tendencia
        if self.random.random() < 0.03:
            self.tendencias[simbolo] *= -0.5  # reversión parcial
        
        spread = base * 0.00008 * (0.5 + self.random.random())
        bid = precio
        ask = precio + spread
        
        self.tick_actual[simbolo] = precio
        
        return Tick(
            simbolo=simbolo,
            bid=round(bid, 5),
            ask=round(ask, 5),
            timestamp=datetime.now(),
            spread=round(spread, 5)
        )
    
    def generar_vela(self, simbolo: str, timeframe: str = "M5") -> Bar:
        """Genera una vela sintética basada en ticks"""
        precio_actual = self.tick_actual.get(simbolo, self.precos_base.get(simbolo, 1.0))
        open_price = precio_actual
        
        # Movimiento para la vela
        cambio = self.random.gauss(0, 0.001)
        close_price = open_price * (1 + cambio)
        
        high_price = max(open_price, close_price) * (1 + abs(self.random.gauss(0, 0.0005)))
        low_price = min(open_price, close_price) * (1 - abs(self.random.gauss(0, 0.0005)))
        
        volume = self.random.randint(100, 5000)
        
        bar = Bar(
            simbolo=simbolo,
            timeframe=timeframe,
            open=round(open_price, 5),
            high=round(high_price, 5),
            low=round(low_price, 5),
            close=round(close_price, 5),
            volume=volume,
            timestamp=datetime.now()
        )
        
        self.velas_por_simbolo[simbolo].append(bar)
        # Mantener solo últimas 1000 velas
        if len(self.velas_por_simbolo[simbolo]) > 1000:
            self.velas_por_simbolo[simbolo] = self.velas_por_simbolo[simbolo][-1000:]
        
        self.tick_actual[simbolo] = close_price
        return bar
    
    def obtener_velas_recientes(self, simbolo: str, n: int = 100) -> List[Bar]:
        """Obtiene las últimas N velas generadas"""
        velas = self.velas_por_simbolo.get(simbolo, [])
        if len(velas) < n:
            # Generar velas faltantes
            for _ in range(n - len(velas)):
                self.generar_vela(simbolo)
            velas = self.velas_por_simbolo.get(simbolo, [])
        return velas[-n:]


# ──────────────────────────────────────────────
# TRADING CONNECTOR (interfaz unificada)
# ──────────────────────────────────────────────

class TradingConnector:
    """Conector unificado para MT5 / cTrader / Simulado"""
    
    def __init__(self, config: dict):
        self.config = config
        self.modo = config.get("bot", {}).get("modo", "simulado")
        self.simbolos_config = config.get("simbolos", {})
        self.todos_los_simbolos = []
        for categoria in self.simbolos_config.values():
            self.todos_los_simbolos.extend(categoria)
        
        # Modo simulado
        self.data_gen = SimulatedDataGenerator()
        
        # Estado de la cuenta
        self.account = AccountInfo(
            balance=config.get("bot", {}).get("capital_inicial", 100.0),
            equity=config.get("bot", {}).get("capital_inicial", 100.0),
            margin=0.0,
            margin_free=config.get("bot", {}).get("capital_inicial", 100.0),
            margin_level=0.0,
            leverage=config.get("broker", config.get("ic_markets", {})).get("leverage", 500),
        )
        
        # Flag de conexión MT5 (para dashboard)
        self.mt5_conectado = None  # None = no aplica (simulado), True/False = MT5
        
        # Cache de velas para demo_real
        self.velas_cache: Dict[str, List[Bar]] = {}
        
        # Órdenes abiertas
        self.ordenes_abiertas: Dict[int, Order] = {}
        self.ordenes_cerradas: List[Order] = {}
        self.siguiente_ticket = 1
        
        # Historial de trades para el dashboard
        self.trades_history: List[dict] = []
        
        # Conectar
        self._conectar()
        
    def _conectar(self):
        """Inicializa la conexión según el modo"""
        if self.modo == "mt5":
            self._conectar_mt5()
        elif self.modo == "ctrader":
            self._conectar_ctrader()
        elif self.modo == "demo_real":
            self._conectar_demo_real()
        else:  # simulado
            print(f"[SIMULADO] Conector iniciado - Capital: ${self.account.balance:.2f}")
    
    def _conectar_mt5(self):
        """Conectar a MetaTrader 5 con IOC y códigos de retorno"""
        try:
            import MetaTrader5 as mt5
            broker_cfg = self.config.get("broker", {})
            
            path = broker_cfg.get("path_terminal", "")
            cuenta = broker_cfg.get("cuenta", 0)
            password = broker_cfg.get("password", "")
            servidor = broker_cfg.get("servidor", "ICMarketsSC-Demo")
            
            print(f"[MT5] Inicializando terminal: {path}")
            
            # Inicializar con path explícito (requiere MT5 instalado)
            if path and os.path.exists(path):
                initialized = mt5.initialize(path=path)
            else:
                print(f"[MT5] Path no encontrado: {path} — intentando initialize() sin path")
                initialized = mt5.initialize()
            
            if not initialized:
                error = mt5.last_error()
                print(f"[!] CRÍTICO /// Falló mt5.initialize(): {error}")
                self.mt5_conectado = False
                self.modo = "simulado"
                return
            
            # Login
            print(f"[MT5] Logueando cuenta {cuenta} en {servidor}...")
            login_result = mt5.login(
                login=int(cuenta),
                password=password,
                server=servidor
            )
            
            if not login_result:
                error = mt5.last_error()
                print(f"[!] CRÍTICO /// Login rechazado por IC Markets: {error}")
                print(f"[!] Códigos: 10014=Volumen inválido, 10018=Mercado cerrado")
                mt5.shutdown()
                self.mt5_conectado = False
                self.modo = "simulado"
                return
            
            # Login exitoso — obtener info de cuenta
            account_info = mt5.account_info()
            if account_info:
                self.account.balance = account_info.balance
                self.account.equity = account_info.equity
                self.account.leverage = account_info.leverage
                print(f"[✅] CONEXIÓN EXITOSA /// IC Markets Live Data Feed")
                print(f"[MT5] Cuenta: {cuenta} | Balance: ${account_info.balance:.2f} | Leverage: 1:{account_info.leverage}")
            
            self.mt5_conectado = True
            
        except ImportError:
            print("[!] MetaTrader5 no instalado — pip install MetaTrader5 (solo Windows/Wine)")
            self.mt5_conectado = False
            self.modo = "simulado"
        except Exception as e:
            print(f"[!] MT5 Error: {e}")
            self.mt5_conectado = False
            self.modo = "simulado"
    
    def _conectar_ctrader(self):
        """Conectar a cTrader API usando OpenApiPy (WebSocket)"""
        try:
            from ctrader_connector import cTraderConnector
            
            broker_cfg = self.config.get("broker", {})
            client_id = broker_cfg.get("client_id", "")
            client_secret = broker_cfg.get("client_secret", "")
            account_id = broker_cfg.get("cuenta", 0)
            demo = broker_cfg.get("account_type", "demo") == "demo"
            app_status = broker_cfg.get("app_status", "submitted")
            
            print(f"[cTrader] Inicializando conector (app status: {app_status})...")
            
            if app_status != "approved" or not client_id:
                print(f"[cTrader] ⏳ App no aprobada aún (status: {app_status})")
                print(f"[cTrader] El agente funcionará en modo simulado hasta aprobación")
                print(f"[cTrader] Cuenta demo configurada: {account_id}")
                print(f"[cTrader] Balance demo: $200 USD | Leverage: 1:{broker_cfg.get('leverage', 1000)}")
                self.modo = "simulado"
                
                # Configurar balance con datos reales de la demo
                self.account.balance = 200.0
                self.account.equity = 200.0
                self.account.margin_free = 200.0
                self.account.leverage = broker_cfg.get("leverage", 1000)
                return
            
            # Intentar conexión real
            self.ctrader = cTraderConnector(
                client_id=client_id,
                client_secret=client_secret,
                account_id=account_id,
                demo=demo,
                token_store="/root/.hermes/projects/trading-agent/.ctrader_tokens.json"
            )
            
            if self.ctrader.connect():
                print(f"[cTrader] ✅ Conectado a cTrader {'demo' if demo else 'live'}")
                
                if self.ctrader.auth_account(account_id):
                    print(f"[cTrader] ✅ Cuenta {account_id} autenticada para trading")
                    self.ctrader.get_symbols_list()
                    self.ctrader.get_trader_info()
                    self.modo = "ctrader"
                else:
                    print(f"[cTrader] ❌ No se pudo autenticar cuenta {account_id}")
                    self.modo = "simulado"
            else:
                print(f"[cTrader] ❌ No se pudo conectar a cTrader")
                self.modo = "simulado"
                
        except ImportError as e:
            print(f"[cTrader] ⚠️ ctrader_connector no disponible: {e}")
            print(f"[cTrader] Usando modo simulado hasta que la app sea aprobada")
            self.modo = "simulado"
        except Exception as e:
            print(f"[cTrader] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            self.modo = "simulado"
    
    # ────────────────────────────────────────
    # YAHOO FINANCE REAL DATA
    # ────────────────────────────────────────
    
    SIMBOLO_MAP = {
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
        "GER40": "DAX=F",
        "UKOIL": "BZ=F",
        "USOIL": "CL=F",
    }
    
    def _conectar_demo_real(self):
        """Conecta a Yahoo Finance para datos reales, ejecuta en simulado"""
        try:
            import yfinance as yf
            print(f"[DEMO_REAL] Conectado a Yahoo Finance para datos de mercado reales")
            print(f"[DEMO_REAL] Cuenta MT4 de referencia: {self.config.get('broker',{}).get('mt4',{}).get('cuenta','N/A')}")
            print(f"[DEMO_REAL] Balance simulado: ${self.account.balance:.2f}")
            print(f"[DEMO_REAL] ⚠️ NO se ejecutan órdenes reales - modo prueba")
            self.modo = "demo_real"
        except ImportError:
            print("[DEMO_REAL] yfinance no instalado - cayendo a simulado")
            self.modo = "simulado"
    
    def _get_yahoo_velas(self, simbolo: str, n: int = 100, intervalo: str = "5m") -> List[Bar]:
        """Obtiene velas reales de Yahoo Finance"""
        import yfinance as yf
        yahoo_sym = self.SIMBOLO_MAP.get(simbolo, simbolo)
        yahoo_interval = intervalo if intervalo in ("1m","2m","5m","15m","30m","60m") else "5m"
        
        # Período: calcular cuántos días necesitamos
        period_map = {"1m": "1d", "2m": "1d", "5m": "5d", "15m": "5d", "30m": "1mo", "60m": "1mo"}
        period = period_map.get(yahoo_interval, "5d")
        
        ticker = yf.Ticker(yahoo_sym)
        df = ticker.history(period=period, interval=yahoo_interval)
        
        if df.empty:
            return self.data_gen.obtener_velas_recientes(simbolo, n)
        
        velas = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
            bar = Bar(
                simbolo=simbolo,
                timeframe=intervalo,
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=int(row['Volume']) if 'Volume' in row else 0,
                timestamp=ts
            )
            velas.append(bar)
        
        self.velas_cache[simbolo] = velas
        return velas[-n:]
    
    # ────────────────────────────────────────
    # PRECIOS
    # ────────────────────────────────────────
    
    def obtener_tick(self, simbolo: str) -> Tick:
        """Obtiene el último tick"""
        if self.modo in ("simulado", "mt5", "ctrader"):
            if self.modo == "simulado":
                return self.data_gen.generar_tick(simbolo)
            return self.data_gen.generar_tick(simbolo)
        
        # Modo demo_real: usar último precio de yahoo
        bars = self.obtener_velas(simbolo, n=3)
        if bars:
            last = bars[-1]
            spread = last.close * 0.0001
            return Tick(
                simbolo=simbolo,
                bid=round(last.close - spread/2, 5),
                ask=round(last.close + spread/2, 5),
                timestamp=datetime.now(),
                spread=round(spread, 5)
            )
        return self.data_gen.generar_tick(simbolo)
    
    def obtener_velas(self, simbolo: str, n: int = 100) -> List[Bar]:
        """Obtiene velas - reales si demo_real, sintéticas si no"""
        if self.modo == "demo_real":
            return self._get_yahoo_velas(simbolo, n)
        if self.modo == "mt5" and self.mt5_conectado:
            # TODO: implementar MT5 real
            pass
        return self.data_gen.obtener_velas_recientes(simbolo, n)
    
    def obtener_precios_varios(self, simbolos: List[str]) -> Dict[str, dict]:
        """Obtiene precios de varios símbolos a la vez"""
        precios = {}
        for s in simbolos:
            tick = self.obtener_tick(s)
            precios[s] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "spread": tick.spread,
                "mid": tick.mid,
                "timestamp": tick.timestamp.isoformat()
            }
        return precios
    
    # ────────────────────────────────────────
    # ÓRDENES
    # ────────────────────────────────────────
    
    def calcular_lotes(self, simbolo: str, riesgo_pct: float) -> float:
        """
        Calcula tamaño de lote basado en riesgo.
        riesgo_pct = porcentaje del capital a arriesgar (ej: 0.02 = 2%)
        
        Para forex: 1 lote estándar = 100,000 unidades
        Para índices/futuros: varía según el broker
        En modo simulado usamos lotes pequeños (micro-lotes)
        """
        riesgo_usd = self.account.balance * riesgo_pct
        
        if "USD" in simbolo or "XAU" in simbolo or "XAG" in simbolo:
            # Forex / metales
            tick_value_per_lot = 10.0  # $10 por pip en 1 lote estándar
        else:
            # Índices
            tick_value_per_lot = 1.0
            
        # Convertir riesgo a lotes
        lotes = riesgo_usd / (tick_value_per_lot * 10)  # estimación
        lotes = max(0.01, min(lotes, 10.0))  # entre 0.01 y 10 lotes
        lotes = round(lotes, 2)
        
        return lotes
    
    def calcular_sl_tp(self, simbolo: str, precio_entrada: float, 
                       tipo: str, pips_sl: int, pips_tp: int) -> Tuple[float, float]:
        """Calcula SL y TP basado en pips"""
        pip_size = 0.0001 if precio_entrada < 100 else 0.01
        if tipo == "buy":
            sl = precio_entrada - (pips_sl * pip_size)
            tp = precio_entrada + (pips_tp * pip_size)
        else:
            sl = precio_entrada + (pips_sl * pip_size)
            tp = precio_entrada - (pips_tp * pip_size)
        return round(sl, 5), round(tp, 5)
    
    def abrir_orden(self, simbolo: str, tipo: str, lotes: float,
                    sl: float = 0, tp: float = 0, estrategia: str = "",
                    slippage: int = 1, magic_number: int = 1000) -> Optional[Order]:
        """Abre una orden de mercado con IOC filling"""
        # MT5 real
        if self.mt5_conectado:
            try:
                import MetaTrader5 as mt5
                # Tipo de orden
                order_type = mt5.ORDER_TYPE_BUY if tipo == "buy" else mt5.ORDER_TYPE_SELL
                
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": simbolo,
                    "volume": lotes,
                    "type": order_type,
                    "price": mt5.symbol_info_tick(simbolo).ask if tipo == "buy" else mt5.symbol_info_tick(simbolo).bid,
                    "sl": sl if sl > 0 else 0,
                    "tp": tp if tp > 0 else 0,
                    "deviation": slippage,
                    "magic": magic_number,
                    "comment": estrategia,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,  # Immediate or Cancel
                }
                
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"[MT5] ORDEN #{result.order}: {tipo.upper()} {lotes} {simbolo} @ {request['price']}")
                    order = Order(
                        ticket=result.order,
                        simbolo=simbolo,
                        tipo=tipo,
                        volumen=lotes,
                        precio_apertura=request['price'],
                        sl=sl,
                        tp=tp,
                        timestamp_apertura=datetime.now(),
                        estado="abierta",
                        estrategia=estrategia
                    )
                    self.ordenes_abiertas[order.ticket] = order
                    return order
                else:
                    retcode = result.retcode if result else "NO_RESULT"
                    error_msg = {
                        10004: "TRADE_RETCODE_NO_MONEY - Margen insuficiente",
                        10006: "TRADE_RETCODE_REJECT - Orden rechazada (mercado cerrado?)",
                        10007: "TRADE_RETCODE_EXPIRED - Orden expiró (IOC sin fill parcial)",
                        10008: "TRADE_RETCODE_INVALID_PRICE - Precio inválido",
                        10014: "TRADE_RETCODE_INVALID_VOLUME - Volumen inválido",
                        10018: "TRADE_RETCODE_MARKET_CLOSED - Mercado cerrado (fin de semana?)",
                        10019: "TRADE_RETCODE_DISABLED - Símbolo deshabilitado",
                    }.get(retcode, f"Código {retcode}")
                    print(f"[MT5] ❌ Orden rechazada: {error_msg}")
                    return None
            except Exception as e:
                print(f"[MT5] Error en orden: {e}")
                return None
        
        # Modo simulado (fallback)
        tick = self.obtener_tick(simbolo)
        precio = tick.ask if tipo == "buy" else tick.bid
        
        # Calcular margen requerido
        margen_requerido = lotes * 100000 * precio / self.account.leverage
        
        # Actualizar estado primero
        estado = self.obtener_estado()
        margin_free = estado["margin_free"]
        balance = estado["balance"]
        
        if margen_requerido > margin_free and len(self.ordenes_abiertas) > 0:
            print(f"[REJECTED] Margen insuficiente: ${margen_requerido:.2f} > ${margin_free:.2f} (balance=${balance}, abiertas={len(self.ordenes_abiertas)})")
            return None
        
        order = Order(
            ticket=self.siguiente_ticket,
            simbolo=simbolo,
            tipo=tipo,
            volumen=lotes,
            precio_apertura=precio,
            sl=sl,
            tp=tp,
            timestamp_apertura=datetime.now(),
            estado="abierta",
            estrategia=estrategia
        )
        
        self.siguiente_ticket += 1
        self.ordenes_abiertas[order.ticket] = order
        
        # Actualizar margen
        self.account.margin += margen_requerido
        self.account.margin_free = self.account.equity - self.account.margin
        self.account.margin_level = (self.account.equity / self.account.margin * 100) if self.account.margin > 0 else 0
        
        print(f"[ORDEN #{order.ticket}] {tipo.upper()} {lotes} {simbolo} @ {precio}")
        return order
    
    def cerrar_orden(self, ticket: int) -> Optional[Order]:
        """Cierra una orden abierta"""
        if ticket not in self.ordenes_abiertas:
            return None
        
        order = self.ordenes_abiertas[ticket]
        tick = self.obtener_tick(order.simbolo)
        precio_cierre = tick.bid if order.tipo == "buy" else tick.ask
        
        # Calcular profit
        if order.tipo == "buy":
            diff = precio_cierre - order.precio_apertura
        else:
            diff = order.precio_apertura - precio_cierre
        
        # Profit en USD (estimación)
        pip_value = 10.0 * order.volumen  # $10 por pip por lote estándar
        pip_size = 0.0001 if order.precio_apertura < 100 else 0.01
        profit = (diff / pip_size) * pip_value
        
        order.precio_cierre = precio_cierre
        order.profit = round(profit, 2)
        order.timestamp_cierre = datetime.now()
        order.comision = round(order.volumen * 3.5, 2)  # ~$3.5 por lote
        order.estado = "cerrada"
        
        # Mover a cerradas
        del self.ordenes_abiertas[ticket]
        self.ordenes_cerradas[ticket] = order
        
        # Actualizar balance
        profit_neto = order.profit_neto
        self.account.balance += profit_neto
        self.account.equity = self.account.balance
        self.account.margin = max(0, self.account.margin - (
            order.volumen * 100000 * order.precio_apertura / self.account.leverage
        ))
        self.account.margin_free = self.account.equity - self.account.margin
        
        # Registrar en historial
        trade_record = {
            "ticket": order.ticket,
            "simbolo": order.simbolo,
            "tipo": order.tipo,
            "volumen": order.volumen,
            "precio_apertura": order.precio_apertura,
            "precio_cierre": order.precio_cierre,
            "profit": round(profit_neto, 2),
            "timestamp_apertura": order.timestamp_apertura.isoformat(),
            "timestamp_cierre": order.timestamp_cierre.isoformat(),
            "estrategia": order.estrategia
        }
        self.trades_history.append(trade_record)
        
        print(f"[CIERRE #{order.ticket}] Profit: ${profit_neto:.2f} | Balance: ${self.account.balance:.2f}")
        return order
    
    def verificar_sl_tp(self) -> List[Order]:
        """Verifica si alguna orden abierta golpeó SL o TP"""
        cerradas = []
        
        for ticket, order in list(self.ordenes_abiertas.items()):
            tick = self.obtener_tick(order.simbolo)
            precio_actual = tick.bid if order.tipo == "buy" else tick.ask
            
            if order.tipo == "buy":
                if order.sl > 0 and precio_actual <= order.sl:
                    cerradas.append(self.cerrar_orden(ticket))
                elif order.tp > 0 and precio_actual >= order.tp:
                    cerradas.append(self.cerrar_orden(ticket))
            else:  # sell
                if order.sl > 0 and precio_actual >= order.sl:
                    cerradas.append(self.cerrar_orden(ticket))
                elif order.tp > 0 and precio_actual <= order.tp:
                    cerradas.append(self.cerrar_orden(ticket))
        
        return cerradas
    
    # ────────────────────────────────────────
    # ESTADO DE LA CUENTA
    # ────────────────────────────────────────
    
    def obtener_estado(self) -> dict:
        """Devuelve el estado completo actual"""
        # Actualizar equity con P&L no realizado
        pnl_no_realizado = 0.0
        for order in self.ordenes_abiertas.values():
            tick = self.obtener_tick(order.simbolo)
            precio_actual = tick.bid if order.tipo == "buy" else tick.ask
            if order.tipo == "buy":
                diff = precio_actual - order.precio_apertura
            else:
                diff = order.precio_apertura - precio_actual
            pip_value = 10.0 * order.volumen
            pip_size = 0.0001 if order.precio_apertura < 100 else 0.01
            pnl_no_realizado += (diff / pip_size) * pip_value
        
        self.account.equity = self.account.balance + pnl_no_realizado
        self.account.margin_free = max(0, self.account.equity - self.account.margin)
        self.account.margin_level = (self.account.equity / self.account.margin * 100) if self.account.margin > 0 else 0
        
        ganancia = self.account.balance - self.config.get("bot", {}).get("capital_inicial", 100.0)
        ganancia_pct = (ganancia / self.config.get("bot", {}).get("capital_inicial", 100.0)) * 100
        
        return {
            "balance": round(self.account.balance, 2),
            "equity": round(self.account.equity, 2),
            "margin": round(self.account.margin, 2),
            "margin_free": round(self.account.margin_free, 2),
            "margin_level": round(self.account.margin_level, 2),
            "pnl_no_realizado": round(pnl_no_realizado, 2),
            "ganancia": round(ganancia, 2),
            "ganancia_pct": round(ganancia_pct, 2),
            "ordenes_abiertas": len(self.ordenes_abiertas),
            "ordenes_cerradas_hoy": len(self.ordenes_cerradas),
            "trades_totales": len(self.trades_history),
            "modo": self.modo
        }
    
    def obtener_ordenes_abiertas(self) -> List[dict]:
        """Lista de órdenes abiertas para el dashboard"""
        resultado = []
        for ticket, order in self.ordenes_abiertas.items():
            tick = self.obtener_tick(order.simbolo)
            precio_actual = tick.bid if order.tipo == "buy" else tick.ask
            
            if order.tipo == "buy":
                diff = precio_actual - order.precio_apertura
            else:
                diff = order.precio_apertura - precio_actual
            
            pip_value = 10.0 * order.volumen
            pip_size = 0.0001 if order.precio_apertura < 100 else 0.01
            pnl = (diff / pip_size) * pip_value
            
            resultado.append({
                "ticket": ticket,
                "simbolo": order.simbolo,
                "tipo": order.tipo,
                "volumen": order.volumen,
                "precio_apertura": order.precio_apertura,
                "precio_actual": round(precio_actual, 5),
                "sl": order.sl,
                "tp": order.tp,
                "pnl": round(pnl, 2),
                "tiempo_abierto": str(datetime.now() - order.timestamp_apertura).split('.')[0],
                "estrategia": order.estrategia
            })
        return resultado
    
    def obtener_trades_recientes(self, n: int = 20) -> List[dict]:
        """Últimos N trades cerrados"""
        return self.trades_history[-n:]
