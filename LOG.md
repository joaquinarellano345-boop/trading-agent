# Trading Agent — IC Markets

## Objetivo
$100 → $1,000 en <3 meses operando 24/7 en IC Markets (forex, futuros, índices).

## Arquitectura

```
agent.py          ← Punto de entrada, bucle principal 24/7
connector.py      ← Conector a IC Markets (MT5 / cTrader / Simulado)
engine.py         ← Estrategias + Risk Manager + Análisis Técnico
dashboard.py      ← Dashboard en vivo vía Flask + HTTP
config.yaml       ← Configuración del agente
```

## Estrategias implementadas

1. **Scalping RSI** - M1, opera en sobrecompra/sobreventa con divergencias
2. **Trend Following EMA** - M15, cruce de EMAs 9/21 + confirmación MACD
3. **Breakout BB** - M15, ruptura de Bandas de Bollinger
4. **Grid Scalper** - M5, para mercado lateral (desactivado por defecto)

## Indicadores técnicos
- RSI (14)
- MACD (12, 26, 9)
- Bollinger Bands (20, 2)
- EMA (9, 21, 50, 200)
- ATR (14)

## Gestión de riesgo
- 2% de riesgo por operación
- 10% drawdown diario máximo
- 30% drawdown total máximo
- 10 operaciones máximas por día
- Trailing stop automático
- Position sizing basado en riesgo

## Dashboard en vivo
- Puerto: 8765
- Métricas: balance, equity, P&L, win rate
- Curva de capital (Chart.js)
- Señales en vivo por símbolo
- Órdenes abiertas en tiempo real
- Historial de trades
- Rendimiento por estrategia

## Cómo usar

### Modo simulado (sin cuenta real)
```bash
cd ~/.hermes/projects/trading-agent
python3 agent.py
```
Abrir navegador en: http://localhost:8765

### Modo real (con cuenta IC Markets)
1. Editar config.yaml → poner credenciales IC Markets
2. Instalar MetaTrader5 (en VPS Windows) o configurar cTrader API
3. Cambiar modo a "mt5" o "ctrader"
4. Ejecutar: python3 agent.py

### Dashboard standalone
```bash
# Solo el dashboard, sin agente
python3 -c "from dashboard import DashboardServer; s=DashboardServer({}); s.start()"
```

## Meta
- Capital inicial: $100
- Capital objetivo: $1,000 (10x)
- Timeframe objetivo: < 3 meses
- Estrategia: gestión de riesgo conservadora + múltiples estrategias
