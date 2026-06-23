"""
ADAPTIVE RISK MANAGER v7
=======================
- Martingale inverso: aumenta 0.5% por racha ganadora, reduce en perdedora
- Stop diario duro: si pierde $X en un día, no opera más hasta el próximo
- Time session filter: solo opera en London/NY overlap
- Risk ajustable por estrategia
"""

from datetime import datetime, time
from typing import Tuple, Optional


# Sesiones de trading (UTC)
TRADING_SESSIONS = {
    "london": {"start": time(7, 0), "end": time(16, 0)},    # 7am-4pm UTC
    "new_york": {"start": time(13, 0), "end": time(22, 0)},  # 1pm-10pm UTC
    "london_ny_overlap": {"start": time(13, 0), "end": time(16, 0)},  # 1pm-4pm UTC — LA MEJOR
    "asia": {"start": time(23, 0), "end": time(8, 0)},       # 11pm-8am UTC
}


class AdaptiveRiskManager:
    """Risk Manager v7 con martingale inverso y stops inteligentes"""

    def __init__(self, config: dict):
        self.config = config
        bot_config = config.get("bot", {})
        self.capital_inicial = bot_config.get("capital_inicial", 200.0)
        self.capital_objetivo = bot_config.get("capital_objetivo", 1000.0)

        # Riesgo base
        self.base_risk_pct = 0.02  # 2% del capital

        # Martingale inverso
        self.current_risk_pct = self.base_risk_pct
        self.current_streak = 0  # positivo = racha ganadora, negativo = perdedora
        self.streak_type = None  # "win" o "loss"
        self.max_risk_pct = 0.04  # máximo 4% (después de 4 wins seguidos)
        self.min_risk_pct = 0.01  # mínimo 1% (después de 3 losses seguidos)

        # Stop diario
        self.daily_max_loss = self.capital_inicial * 0.10  # $20/día
        self.daily_pnl = 0.0
        self.current_day = datetime.now().date()
        self.daily_trades = 0
        self.daily_max_trades = 12
        self.daily_halted = False

        # Time filter
        self.sessions_activas = {"london_ny_overlap"}  # solo overlap por defecto
        self.session_enabled = True

        # Estado de la cuenta
        self.peak_balance = self.capital_inicial
        self.current_balance = self.capital_inicial
        self.max_drawdown = 0.0
        self.max_drawdown_hard_limit = 0.30  # 30% stop total

        # Estadísticas
        self.total_trades = 0
        self.win_streak = 0
        self.loss_streak = 0
        self.best_streak = 0

    def reset_daily(self):
        """Resetear contadores diarios"""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_halted = False
        self.current_day = datetime.now().date()

    def is_valid_session(self) -> Tuple[bool, str]:
        """Verifica si estamos en una sesión de trading válida"""
        if not self.session_enabled:
            return True, "sessions disabled"

        now = datetime.now().time()

        # London-NY overlap es la prioridad máxima
        if TRADING_SESSIONS["london_ny_overlap"]["start"] <= now <= TRADING_SESSIONS["london_ny_overlap"]["end"]:
            return True, "london_ny_overlap"

        # London
        if TRADING_SESSIONS["london"]["start"] <= now <= TRADING_SESSIONS["london"]["end"]:
            return True, "london"

        # NY
        if TRADING_SESSIONS["new_york"]["start"] <= now <= TRADING_SESSIONS["new_york"]["end"]:
            return True, "new_york"

        return False, f"fuera de sesión ({now.strftime('%H:%M')} UTC) — solo opera London/NY (7:00-22:00 UTC)"

    def puede_operar(self, balance: float, equity: float) -> Tuple[bool, str]:
        """Verifica todas las reglas antes de operar"""
        now = datetime.now().date()

        # Reset diario
        if now != self.current_day:
            self.reset_daily()

        # 1. Stop total (30% drawdown)
        dd = (self.peak_balance - balance) / self.peak_balance if self.peak_balance > 0 else 0
        if dd > self.max_drawdown_hard_limit:
            return False, f"🛑 STOP TOTAL: drawdown {dd:.1%} > {self.max_drawdown_hard_limit:.0%}"

        # 2. Stop diario
        if self.daily_halted:
            return False, f"⏸️ STOP DIARIO ACTIVO: pérdida de ${abs(self.daily_pnl):.2f} hoy (límite ${self.daily_max_loss:.2f})"

        if self.daily_pnl <= -self.daily_max_loss:
            self.daily_halted = True
            return False, f"⏸️ STOP DIARIO: perdiste ${abs(self.daily_pnl):.2f} hoy. Mañana volvemos."

        # 3. Máximo de trades diarios
        if self.daily_trades >= self.daily_max_trades:
            return False, f"⏸️ MÁXIMO DE {self.daily_max_trades} TRADES HOY ALCANZADO"

        # 4. Balance mínimo
        if balance < 1.0:
            return False, "BALANCE INSUFICIENTE"

        # 5. Sesión de trading
        session_ok, session_msg = self.is_valid_session()
        if not session_ok:
            return False, session_msg

        return True, "OK"

    def calcular_tamano_posicion(self, balance: float, precio: float,
                                 sl_distancia_pips: float) -> float:
        """Calcula lotes usando el riesgo adaptativo actual"""
        riesgo_usd = balance * self.current_risk_pct

        pip_size = 0.0001 if precio < 100 else 0.01
        sl_en_pips = sl_distancia_pips / pip_size if pip_size > 0 else sl_distancia_pips

        if sl_en_pips <= 0:
            return 0.01

        # $10 por pip por lote estándar (aproximado)
        valor_por_pip_por_lote = 10.0
        lotes = riesgo_usd / (sl_en_pips * valor_por_pip_por_lote)
        lotes = max(0.01, min(lotes, balance / 1000))
        lotes = round(lotes * 100) / 100
        return max(0.01, lotes)

    def actualizar_streak(self, profit: float):
        """Actualiza racha y ajusta riesgo (martingale inverso)"""
        if profit > 0:
            if self.streak_type == "win":
                self.current_streak += 1
            else:
                self.current_streak = 1
                self.streak_type = "win"
            self.win_streak = max(self.win_streak, self.current_streak)
        else:
            if self.streak_type == "loss":
                self.current_streak -= 1
            else:
                self.current_streak = -1
                self.streak_type = "loss"
            self.loss_streak = max(self.loss_streak, abs(self.current_streak))

        # Martingale inverso
        if self.streak_type == "win":
            # Subir riesgo: 2% base + 0.5% por cada win consecutivo
            self.current_risk_pct = min(
                self.max_risk_pct,
                self.base_risk_pct + (self.current_streak * 0.005)
            )
        else:
            # Bajar riesgo: 2% base - 0.5% por cada loss consecutivo
            self.current_risk_pct = max(
                self.min_risk_pct,
                self.base_risk_pct - (abs(self.current_streak) * 0.005)
            )

    def registrar_trade(self, profit: float):
        """Registra un trade finalizado"""
        self.daily_pnl += profit
        self.daily_trades += 1
        self.total_trades += 1
        self.current_balance += profit

        # Actualizar peak y drawdown
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        dd = (self.peak_balance - self.current_balance) / self.peak_balance
        self.max_drawdown = max(self.max_drawdown, dd)

        # Martingale inverso
        self.actualizar_streak(profit)

    def get_summary(self) -> dict:
        return {
            "balance": round(self.current_balance, 2),
            "peak_balance": round(self.peak_balance, 2),
            "drawdown": round(self.max_drawdown * 100, 1),
            "risk_pct": round(self.current_risk_pct * 100, 2),
            "streak": self.current_streak,
            "streak_type": self.streak_type,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "daily_halted": self.daily_halted,
            "session": self.is_valid_session()[1],
            "total_trades": self.total_trades,
        }

    def to_dict(self) -> dict:
        return {
            "current_risk_pct": self.current_risk_pct,
            "current_streak": self.current_streak,
            "streak_type": self.streak_type,
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
            "daily_halted": self.daily_halted,
            "current_day": self.current_day.isoformat(),
            "peak_balance": self.peak_balance,
            "current_balance": self.current_balance,
            "max_drawdown": self.max_drawdown,
            "total_trades": self.total_trades,
            "win_streak": self.win_streak,
            "loss_streak": self.loss_streak,
        }

    @classmethod
    def from_dict(cls, config: dict, data: dict):
        """Restaurar desde estado guardado"""
        rm = cls(config)
        if data:
            rm.current_risk_pct = data.get("current_risk_pct", 0.02)
            rm.current_streak = data.get("current_streak", 0)
            rm.streak_type = data.get("streak_type")
            rm.daily_pnl = data.get("daily_pnl", 0.0)
            rm.daily_trades = data.get("daily_trades", 0)
            rm.daily_halted = data.get("daily_halted", False)
            try:
                rm.current_day = datetime.fromisoformat(data.get("current_day", datetime.now().date().isoformat())).date()
            except Exception:
                rm.current_day = datetime.now().date()
            rm.peak_balance = data.get("peak_balance", rm.capital_inicial)
            rm.current_balance = data.get("current_balance", rm.capital_inicial)
            rm.max_drawdown = data.get("max_drawdown", 0.0)
            rm.total_trades = data.get("total_trades", 0)
            rm.win_streak = data.get("win_streak", 0)
            rm.loss_streak = data.get("loss_streak", 0)
        return rm
