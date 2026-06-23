"""
cTrader Connector - Conexión WebSocket real para trading
=========================================================
Usa la biblioteca ctrader_open_api (OpenApiPy) con:
  1. App Auth (Client ID + Secret) → Refresh Token
  2. Refresh Token → Access Token
  3. Access Token → Listar cuentas → Auth cuenta → Trading

Si la app está en "Submitted", este módulo primero intenta obtener
un Refresh Token via OAuth, o usa uno ya guardado.
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Dict, List, Optional, Callable, Any

import ctrader_open_api
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from twisted.internet import reactor, error as reactor_error


class cTraderConnector:
    """
    Conector cTrader que maneja:
    - App Auth (Client ID + Secret)
    - Refresh/Access Token lifecycle
    - Account auth (demo/live)
    - Subscribe spots (ticks)
    - Subscribe trendbars (velas)
    - Place/cancel orders
    """

    # Payload types
    PAYLOAD_APP_AUTH_REQ = 1
    PAYLOAD_APP_AUTH_RES = 2
    PAYLOAD_ACCOUNT_AUTH_REQ = 3
    PAYLOAD_ACCOUNT_AUTH_RES = 4
    PAYLOAD_GET_ACCOUNTS_REQ = 5
    PAYLOAD_GET_ACCOUNTS_RES = 6
    PAYLOAD_SPOT_EVENT = 7
    PAYLOAD_SUBSCRIBE_SPOTS_REQ = 8
    PAYLOAD_SUBSCRIBE_SPOTS_RES = 9
    PAYLOAD_TRENDBAR_EVENT = 10
    PAYLOAD_SUBSCRIBE_TRENDBAR_REQ = 11
    PAYLOAD_SUBSCRIBE_TRENDBAR_RES = 12
    PAYLOAD_NEW_ORDER_REQ = 13
    PAYLOAD_NEW_ORDER_RES = 14
    PAYLOAD_SYMBOLS_LIST_REQ = 15
    PAYLOAD_SYMBOLS_LIST_RES = 16
    PAYLOAD_TRADER_REQ = 17
    PAYLOAD_TRADER_RES = 18
    PAYLOAD_EXECUTION_EVENT = 19
    PAYLOAD_RECONCILE_REQ = 20
    PAYLOAD_RECONCILE_RES = 21
    PAYLOAD_ERROR_RES = 22
    PAYLOAD_CLOSE_POSITION_REQ = 23
    PAYLOAD_AMEND_POSITION_SLTP_REQ = 24

    def __init__(self, client_id: str, client_secret: str,
                 account_id: int = None, demo: bool = True,
                 token_store: str = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_id = account_id
        self.demo = demo
        self.host = EndPoints.PROTOBUF_DEMO_HOST if demo else EndPoints.PROTOBUF_LIVE_HOST
        self.port = EndPoints.PROTOBUF_PORT
        self.token_store = token_store or "/root/.hermes/projects/trading-agent/.ctrader_tokens.json"

        # Estado de conexión
        self.connected = False
        self.app_authed = False
        self.account_authed = False
        self.client: Optional[Client] = None

        # Tokens
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_type: Optional[str] = None
        self.expires_in: int = 0
        self._load_tokens()

        # Queues para comunicación sync->async
        self.tick_queue: Queue = Queue()
        self.response_queue: Queue = Queue()

        # Callbacks
        self.on_tick: Optional[Callable] = None
        self.on_execution: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        # Threading
        self._reactor_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # Mapeo symbol_name -> symbol_id
        self.symbol_map: Dict[str, int] = {}
        self.symbol_name_by_id: Dict[int, str] = {}

        # Cuentas disponibles
        self.accounts: List[dict] = []

    # ─────────── TOKEN MANAGEMENT ───────────────

    def _token_path(self) -> Path:
        return Path(self.token_store)

    def _load_tokens(self):
        p = self._token_path()
        if p.exists():
            try:
                data = json.loads(p.read_text())
                self.refresh_token = data.get("refresh_token")
                self.access_token = data.get("access_token")
                self.token_type = data.get("token_type")
                self.expires_in = data.get("expires_in", 0)
                print(f"[cTrader] Tokens cargados desde {p}")
            except Exception as e:
                print(f"[cTrader] Error cargando tokens: {e}")

    def save_tokens(self):
        p = self._token_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "saved_at": datetime.now().isoformat()
        }
        p.write_text(json.dumps(data, indent=2))
        print(f"[cTrader] Tokens guardados en {p}")

    # ─────────── TWISTED REACTOR ───────────────

    _reactor_started = False
    _reactor_lock = threading.Lock()

    def _start_reactor(self):
        """Inicia el reactor Twisted en un thread daemon (solo una vez)"""
        with self._reactor_lock:
            if self._reactor_started:
                return
            self._reactor_started = True
            self._running = True
        self._reactor_thread = threading.Thread(target=self._run_reactor, daemon=True)
        self._reactor_thread.start()
        # Esperar que el reactor arranque
        for _ in range(20):
            if reactor.running:
                break
            time.sleep(0.1)

    def _run_reactor(self):
        try:
            reactor.run(installSignalHandlers=False)
        except reactor_error.ReactorNotRunning:
            pass

    def _stop_reactor(self):
        self._running = False
        try:
            if reactor.running:
                reactor.stop()
        except Exception:
            pass

    # ─────────── CONNECTION ───────────────

    def connect(self) -> bool:
        """Conecta al WebSocket de cTrader y autentica"""
        print(f"[cTrader] Conectando a {self.host}:{self.port}...")

        self._start_reactor()

        self.client = Client(self.host, self.port, TcpProtocol)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)
        self.client.startService()

        # Esperar conexión
        timeout = 10
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.connected:
                break
            time.sleep(0.2)

        if not self.connected:
            print("[cTrader] ❌ Timeout conectando")
            return False

        print("[cTrader] ✅ Conectado, autenticando app...")

        # Autenticar app
        auth_req = ProtoOAApplicationAuthReq()
        auth_req.clientId = self.client_id
        auth_req.clientSecret = self.client_secret

        d = self.client.send(auth_req)
        d.addErrback(self._on_error)

        # Esperar auth app
        t0 = time.time()
        while time.time() - t0 < 10:
            if self.app_authed:
                break
            time.sleep(0.2)

        if not self.app_authed:
            print("[cTrader] ❌ Error autenticando app (Submitted?)")
            return False

        print("[cTrader] ✅ App autenticada")

        # Obtener lista de cuentas
        if not self._list_accounts():
            print("[cTrader] ❌ No se pudieron obtener cuentas")
            return False

        return True

    def auth_account(self, account_id: int = None) -> bool:
        """Autentica una cuenta específica para trading"""
        account_id = account_id or self.account_id
        if not account_id:
            print("[cTrader] No account_id especificado")
            return False

        if not self.access_token:
            print("[cTrader] No hay access_token — no se puede autenticar cuenta")
            return False

        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = account_id
        req.accessToken = self.access_token

        d = self.client.send(req)
        d.addErrback(self._on_error)

        t0 = time.time()
        while time.time() - t0 < 10:
            if self.account_authed:
                break
            time.sleep(0.2)

        return self.account_authed

    def _list_accounts(self) -> bool:
        """Obtiene lista de cuentas asociadas al access token"""
        if not self.access_token:
            print("[cTrader] No hay access token para listar cuentas")
            return False

        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = self.access_token

        d = self.client.send(req)
        d.addErrback(self._on_error)

        t0 = time.time()
        while time.time() - t0 < 10:
            if self.accounts:
                break
            time.sleep(0.2)

        return len(self.accounts) > 0

    # ─────────── CALLBACKS ───────────────

    def _on_connected(self, client):
        print(f"[cTrader] 📡 Conectado a {self.host}")
        self.connected = True

    def _on_disconnected(self, client, reason):
        print(f"[cTrader] 📡 Desconectado: {reason}")
        self.connected = False
        self.app_authed = False
        self.account_authed = False

    def _on_error(self, failure):
        error_str = str(failure)
        print(f"[cTrader] ⚠️ Error: {error_str}")
        if self.on_error:
            self.on_error(error_str)

    def _on_message(self, client, raw_message):
        """Procesa mensajes protobuf entrantes"""
        try:
            msg = Protobuf.extract(raw_message)
            payload_type = msg.payloadType

            if payload_type == self.PAYLOAD_APP_AUTH_RES:
                self._handle_app_auth_res(msg)
            elif payload_type == self.PAYLOAD_GET_ACCOUNTS_RES:
                self._handle_account_list(msg)
            elif payload_type == self.PAYLOAD_ACCOUNT_AUTH_RES:
                self._handle_account_auth_res(msg)
            elif payload_type == self.PAYLOAD_SPOT_EVENT:
                self._handle_spot_event(msg)
            elif payload_type == self.PAYLOAD_EXECUTION_EVENT:
                self._handle_execution_event(msg)
            elif payload_type == self.PAYLOAD_SYMBOLS_LIST_RES:
                self._handle_symbols_list(msg)
            elif payload_type == self.PAYLOAD_ERROR_RES:
                self._handle_error(msg)
            elif payload_type == self.PAYLOAD_TRADER_RES:
                self._handle_trader_res(msg)
            else:
                print(f"[cTrader] Msg tipo {payload_type} ignorado")
        except Exception as e:
            print(f"[cTrader] Error procesando mensaje: {e}")

    def _handle_app_auth_res(self, msg):
        """ProtoOAApplicationAuthRes — app autenticada"""
        self.app_authed = True
        print("[cTrader] ✅ App autenticada correctamente")

    def _handle_account_list(self, msg):
        """ProtoOAGetAccountListByAccessTokenRes — lista de cuentas"""
        self.access_token = msg.accessToken
        accounts = []
        for acc in msg.ctidTraderAccount:
            info = {
                "id": acc.ctidTraderAccountId,
                "type": "demo" if acc.isDemo else "live",
                "currency": acc.currencyName,
                "leverage": acc.leverage,
                "balance": acc.depositAsset.balance if acc.HasField("depositAsset") else 0,
            }
            accounts.append(info)
            print(f"[cTrader] 📋 Cuenta: {info['id']} | {info['type']} | {info['currency']} | Balance: {info['balance']}")

        self.accounts = accounts
        if accounts and not self.account_id:
            self.account_id = accounts[0]["id"]

    def _handle_account_auth_res(self, msg):
        """ProtoOAAccountAuthRes — cuenta autenticada para trading"""
        if msg.ctidTraderAccountId:
            self.account_authed = True
            self.account_id = msg.ctidTraderAccountId
            print(f"[cTrader] ✅ Cuenta {self.account_id} autenticada para trading")

    def _handle_spot_event(self, msg):
        """ProtoOASpotEvent — tick de precio en tiempo real"""
        symbol_name = self.symbol_name_by_id.get(msg.symbolId, str(msg.symbolId))
        tick = {
            "symbol_id": msg.symbolId,
            "symbol": symbol_name,
            "bid": msg.bid / 1e5 if msg.bid > 1e6 else msg.bid,
            "ask": msg.ask / 1e5 if msg.ask > 1e6 else msg.ask,
            "timestamp": datetime.fromtimestamp(msg.timestamp / 1000).isoformat() if msg.timestamp else None,
        }
        # Ajustar decimales: cTrader manda precios como int64 (1.0850 = 108500)
        # Depende del símbolo — para forex 5 decimales, para indices 2 decimales
        self.tick_queue.put(tick)
        if self.on_tick:
            self.on_tick(tick)

    def _handle_execution_event(self, msg):
        """ProtoOAExecutionEvent — orden ejecutada/modificada/cerrada"""
        event = {
            "execution_type": msg.executionType,
            "position_id": msg.position.positionId if msg.HasField("position") else None,
            "order_id": msg.order.orderId if msg.HasField("order") else None,
            "error_code": msg.errorCode if msg.errorCode else None,
        }
        print(f"[cTrader] ⚡ ExecutionEvent: tipo={msg.executionType}")
        if self.on_execution:
            self.on_execution(event)

    def _handle_symbols_list(self, msg):
        """ProtoOASymbolsListRes — lista de símbolos disponibles"""
        for sym in msg.symbol:
            self.symbol_map[sym.symbolName] = sym.symbolId
            self.symbol_name_by_id[sym.symbolId] = sym.symbolName
        print(f"[cTrader] 📋 {len(self.symbol_map)} símbolos cargados")

    def _handle_error(self, msg):
        """ProtoOAErrorRes — error del servidor"""
        error_text = f"[{msg.errorCode}] {msg.description}"
        if msg.maintenanceEndTimestamp:
            from datetime import datetime as dt
            maint_end = dt.fromtimestamp(msg.maintenanceEndTimestamp / 1000)
            error_text += f" (mantenimiento hasta {maint_end})"
        print(f"[cTrader] ❌ Error: {error_text}")
        if self.on_error:
            self.on_error(error_text)

    def _handle_trader_res(self, msg):
        """ProtoOATraderRes — info de la cuenta de trading"""
        if msg.HasField("trader"):
            trader = msg.trader
            print(f"[cTrader] 👤 Trader: balance={trader.balance}, equity={trader.equity}, margin={trader.margin}")

    # ─────────── SUBSCRIPTIONS ───────────────

    def subscribe_spots(self, symbol_id: int):
        """Subscribe a ticks en tiempo real para un símbolo"""
        if not self.account_authed:
            print("[cTrader] ❌ Account not authed for subscribe_spots")
            return

        req = ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = self.account_id
        req.symbolId = symbol_id
        req.subscribeToSpotTimestamp = True

        d = self.client.send(req)
        d.addErrback(self._on_error)
        print(f"[cTrader] 📡 Subscribe spots para symbolId={symbol_id}")

    def subscribe_trendbars(self, symbol_id: int, period: str = "M1"):
        """Subscribe a velas en tiempo real"""
        if not self.account_authed:
            return

        # Mapear periodos
        period_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        period_sec = period_map.get(period, 60)

        req = ProtoOASubscribeLiveTrendbarReq()
        req.ctidTraderAccountId = self.account_id
        req.symbolId = symbol_id
        req.period = period_sec

        d = self.client.send(req)
        d.addErrback(self._on_error)
        print(f"[cTrader] 📡 Subscribe trendbars {period} para symbolId={symbol_id}")

    def get_symbols_list(self):
        """Obtener lista de todos los símbolos disponibles"""
        if not self.account_authed:
            return

        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = self.account_id
        req.includeArchivedSymbols = False

        d = self.client.send(req)
        d.addErrback(self._on_error)

    def get_trader_info(self):
        """Obtener info de la cuenta de trading"""
        if not self.account_authed:
            return

        req = ProtoOATraderReq()
        req.ctidTraderAccountId = self.account_id

        d = self.client.send(req)
        d.addErrback(self._on_error)

    # ─────────── ORDER MANAGEMENT ───────────────

    def place_order(self, symbol_id: int, order_type: str, trade_side: str,
                    volume: int, stop_loss: float = None, take_profit: float = None,
                    comment: str = "", label: str = "") -> dict:
        """
        Coloca una orden de mercado.
        - order_type: "market", "limit", "stop"
        - trade_side: "buy", "sell"
        - volume: en cents (1 lote = 100000 cents)
        """
        if not self.account_authed:
            return {"error": "Account not authenticated"}

        # Mapear tipos
        order_type_map = {"market": 1, "limit": 2, "stop": 3}
        trade_side_map = {"buy": 1, "sell": 2}
        time_in_force_map = {"gtc": 1, "ioc": 3, "fok": 4}

        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.account_id
        req.symbolId = symbol_id
        req.orderType = order_type_map.get(order_type, 1)  # market por defecto
        req.tradeSide = trade_side_map.get(trade_side, 1)
        req.volume = int(volume)  # en cents (100000 = 1 lote)
        req.timeInForce = time_in_force_map["ioc"]  # Immediate or Cancel
        req.comment = comment
        req.label = label

        if stop_loss is not None:
            req.stopLoss = stop_loss
        if take_profit is not None:
            req.takeProfit = take_profit

        d = self.client.send(req)
        d.addErrback(self._on_error)
        print(f"[cTrader] 🎯 Orden enviada: {trade_side} {volume} symbolId={symbol_id}")
        return {"status": "sent"}

    def close_position(self, position_id: int, volume: int):
        """Cierra una posición (parcial o total)"""
        if not self.account_authed:
            return {"error": "Account not authenticated"}

        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self.account_id
        req.positionId = position_id
        req.volume = volume  # en cents

        d = self.client.send(req)
        d.addErrback(self._on_error)
        print(f"[cTrader] 🔒 Cerrando posición {position_id}")
        return {"status": "sent"}

    def amend_position_sltp(self, position_id: int, stop_loss: float = None, take_profit: float = None):
        """Modifica SL/TP de una posición"""
        if not self.account_authed:
            return {"error": "Account not authenticated"}

        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = self.account_id
        req.positionId = position_id
        if stop_loss is not None:
            req.stopLoss = stop_loss
        if take_profit is not None:
            req.takeProfit = take_profit

        d = self.client.send(req)
        d.addErrback(self._on_error)
        return {"status": "sent"}

    def reconcile(self):
        """Sincroniza estado (órdenes/posiciones abiertas)"""
        if not self.account_authed:
            return

        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.account_id
        d = self.client.send(req)
        d.addErrback(self._on_error)

    # ─────────── HELPERS ───────────────

    def get_symbol_id(self, symbol_name: str) -> Optional[int]:
        """Obtiene symbol_id por nombre (EURUSD, BTCUSD, etc.)"""
        return self.symbol_map.get(symbol_name)

    def get_lots_to_volume(self, lots: float) -> int:
        """Convierte lotes a volumen cTrader (cents): 1 lote = 100000"""
        return int(lots * 100000)

    def get_volume_to_lots(self, volume: int) -> float:
        """Convierte volumen cTrader (cents) a lotes"""
        return volume / 100000.0

    def get_tick(self, timeout: float = 1.0) -> Optional[dict]:
        """Obtiene el próximo tick de la cola (non-blocking con timeout)"""
        try:
            return self.tick_queue.get(timeout=timeout)
        except Empty:
            return None

    def disconnect(self):
        """Desconecta limpiamente"""
        self._stop_reactor()
        self.connected = False
        self.app_authed = False
        self.account_authed = False
        print("[cTrader] Desconectado")
