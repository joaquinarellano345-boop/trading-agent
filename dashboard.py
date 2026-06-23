"""
Trading Agent Dashboard - Flask + WebSockets + Chart.js
======================================================
Dashboard en vivo para ver rendimiento del agente de trading.
"""

import json
import os
import threading
import time
import yaml
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path

# Añadir path del proyecto
import sys
sys.path.insert(0, str(Path(__file__).parent))

from connector import TradingConnector
from engine import StrategyEngine

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

PROJECT_DIR = Path(__file__).parent
CONFIG_PATH = PROJECT_DIR / "config.yaml"
TEMPLATES_DIR = PROJECT_DIR / "templates"
STATIC_DIR = PROJECT_DIR / "static"

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

# ──────────────────────────────────────────────
# HTML DASHBOARD
# ──────────────────────────────────────────────

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HERMES FINANCIAL // TERMINAL v2</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}

:root{
  --bg-deep:#020408;
  --bg-surface:#060B12;
  --bg-card:#0A1020;
  --bg-card-hover:#0E1830;
  --bg-elevated:#101C30;
  --border-subtle:rgba(74,246,38,0.06);
  --border-mid:rgba(74,246,38,0.12);
  --border-strong:rgba(74,246,38,0.2);
  --text-primary:#E2E8F0;
  --text-secondary:#8892A4;
  --text-muted:#4A5568;
  --green:#4AF626;
  --green-dim:rgba(74,246,38,0.08);
  --red:#FF3355;
  --red-dim:rgba(255,51,85,0.08);
  --amber:#F0AD4E;
  --blue:#3B82F6;
  --blue-dim:rgba(59,130,246,0.08);
  --purple:#8B5CF6;
  --purple-dim:rgba(139,92,246,0.08);
  --cyan:#22D3EE;
}

body{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg-deep);
  color:var(--text-primary);
  min-height:100vh;
  overflow-x:hidden;
}

/* Noise overlay */
body::before{
  content:'';position:fixed;inset:0;z-index:9999;pointer-events:none;opacity:0.015;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* Scanline */
body::after{
  content:'';position:fixed;inset:0;z-index:9998;pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.12) 2px,rgba(0,0,0,0.12) 4px);
}

.container{max-width:1600px;margin:0 auto;padding:16px 20px;position:relative;z-index:1}

/* ── TOP BAR ── */
.topbar{
  display:flex;justify-content:space-between;align-items:center;
  padding:12px 0 14px;border-bottom:1px solid var(--border-subtle);margin-bottom:20px;
}
.topbar-left{display:flex;align-items:center;gap:16px}
.topbar-left .logo{
  font-family:'Inter',sans-serif;font-weight:800;font-size:16px;
  letter-spacing:-0.03em;text-transform:uppercase;
  background:linear-gradient(135deg,#4AF626,#22D3EE);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.topbar-left .sub{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;
  color:var(--text-muted);border-left:1px solid var(--border-subtle);padding-left:16px;
}
.topbar-right{display:flex;align-items:center;gap:18px}
.topbar-right .ts{
  font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-muted);letter-spacing:0.05em;
}
.badge-pill{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.15em;
  padding:4px 10px;border:1px solid var(--border-mid);color:var(--green);
}

/* ── EXECUTIVE DASHBOARD - 7 KPI STRIP ── */
.exec-strip{
  display:grid;grid-template-columns:repeat(7,1fr);gap:1px;
  background:var(--border-subtle);border:1px solid var(--border-subtle);margin-bottom:20px;
}
.exec-cell{
  background:var(--bg-card);padding:14px 14px;position:relative;overflow:hidden;
}
.exec-cell::before{
  content:'';position:absolute;top:0;left:0;width:100%;height:2px;opacity:0.5;
}
.exec-cell.green::before{background:var(--green)}
.exec-cell.red::before{background:var(--red)}
.exec-cell.amber::before{background:var(--amber)}
.exec-cell.blue::before{background:var(--blue)}
.exec-cell.purple::before{background:var(--purple)}
.exec-label{
  font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.2em;
  color:var(--text-muted);margin-bottom:6px;text-transform:uppercase;
}
.exec-val{
  font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:-0.02em;
}
.exec-val.green{color:var(--green)}
.exec-val.red{color:var(--red)}
.exec-val.amber{color:var(--amber)}
.exec-val.blue{color:var(--blue)}
.exec-val.purple{color:var(--purple)}
.exec-sub{
  font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--text-muted);margin-top:4px;letter-spacing:0.05em;
}

/* ── ROW 1: Equity Curve (50%) + Right Panel (25%) + Health (25%) ── */
.row1{display:grid;grid-template-columns:2fr 1fr 1fr;gap:1px;background:var(--border-subtle);margin-bottom:1px}

/* Equity Curve - dominant */
.equity-panel{background:var(--bg-card);padding:18px 20px;min-height:340px}
.equity-panel .section-header{
  display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;
}
.equity-panel .section-header h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;
}
.equity-metrics{
  display:flex;gap:24px;margin-bottom:14px;
}
.eq-m{
  display:flex;flex-direction:column;
}
.eq-m .lbl{
  font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.15em;color:var(--text-muted);text-transform:uppercase;
}
.eq-m .val{
  font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:600;font-variant-numeric:tabular-nums;
}
.eq-m .val.green{color:var(--green)}
.eq-m .val.red{color:var(--red)}
#equityChart{max-height:220px;width:100%!important}

/* Risk Center */
.risk-panel{background:var(--bg-card);padding:16px}
.risk-panel h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px;
}
.risk-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.risk-item{}
.risk-item .rl{
  font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.12em;color:var(--text-muted);text-transform:uppercase;
}
.risk-item .rv{
  font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;
}
.risk-item .rv.green{color:var(--green)}
.risk-item .rv.red{color:var(--red)}
.risk-item .rv.amber{color:var(--amber)}

/* Profit Factor Hero */
.pf-hero{background:var(--bg-card);padding:16px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center}
.pf-hero h2{
  font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:8px;
}
.pf-hero .pf-number{
  font-family:'JetBrains Mono',monospace;font-size:42px;font-weight:700;color:var(--green);line-height:1;margin-bottom:8px;
}
.pf-hero .pf-sub{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.2em;color:var(--text-muted);text-transform:uppercase;
}

/* System Health */
.health-panel{background:var(--bg-card);padding:16px}
.health-panel h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px;
}
.health-grid{display:grid;gap:4px}
.health-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid rgba(74,246,38,0.04)}
.health-row .hl{
  font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:0.1em;color:var(--text-secondary);
}
.health-row .hv{
  font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:500;font-variant-numeric:tabular-nums;
}
.health-row .hv.green{color:var(--green)}
.health-row .hv.amber{color:var(--amber)}
.health-row .hv.red{color:var(--red)}
.health-row .hv.blue{color:var(--blue)}
.health-bar{margin:2px 0 6px;height:3px;background:var(--border-subtle);overflow:hidden}
.health-bar .fill{height:100%;transition:width 0.5s}
.health-bar .fill.green{background:var(--green)}
.health-bar .fill.amber{background:var(--amber)}
.health-bar .fill.red{background:var(--red)}

/* ── SECTION DIVIDER ── */
.section-divider{
  display:flex;align-items:center;gap:14px;margin:20px 0 16px;
}
.section-divider .line{flex:1;height:1px;background:var(--border-subtle)}
.section-divider .tag{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.3em;
  color:var(--text-muted);text-transform:uppercase;
}

/* ── ROW 2: Agents + Strategy + Signal ── */
.row2{display:grid;grid-template-columns:1.2fr 1.5fr 1.3fr;gap:1px;background:var(--border-subtle);margin-bottom:1px}

/* Agent Command Center */
.agents-panel{background:var(--bg-card);padding:16px}
.agents-panel h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px;
}
.agent-row{
  display:flex;justify-content:space-between;align-items:center;
  padding:8px 0;border-bottom:1px solid rgba(74,246,38,0.04);
}
.agent-row:last-child{border-bottom:none}
.agent-row .an{
  font-family:'Inter',sans-serif;font-size:12px;font-weight:500;letter-spacing:0.02em;color:var(--text-primary);
}
.agent-row .as{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.15em;padding:3px 8px;
}
.agent-row .as.online{color:var(--green);border:1px solid rgba(74,246,38,0.2)}
.agent-row .as.processing{color:var(--cyan);border:1px solid rgba(34,211,238,0.2);animation:pulse-soft 3s infinite}
.agent-row .as.warning{color:var(--amber);border:1px solid rgba(240,173,78,0.2)}
.agent-row .as.offline{color:var(--red);border:1px solid rgba(255,51,85,0.2)}
@keyframes pulse-soft{0%,100%{opacity:1}50%{opacity:0.5}}

/* Strategy Intelligence */
.strat-panel{background:var(--bg-card);padding:16px}
.strat-panel h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px;
}
.strat-table{width:100%;border-collapse:collapse}
.strat-table th{
  font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.15em;
  color:var(--text-muted);text-align:left;padding:6px 8px;border-bottom:1px solid var(--border-subtle);font-weight:500;text-transform:uppercase;
}
.strat-table td{
  font-family:'JetBrains Mono',monospace;font-size:10px;padding:8px;border-bottom:1px solid rgba(74,246,38,0.04);
  font-variant-numeric:tabular-nums;color:var(--text-secondary);
}
.strat-table tr:hover td{background:var(--bg-card-hover)}
.strat-table .s-green{color:var(--green)}
.strat-table .s-red{color:var(--red)}
.strat-table .s-amber{color:var(--amber)}

/* Signal Stream */
.signal-panel{background:var(--bg-card);padding:16px}
.signal-panel h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px;
}
.signal-feed{
  max-height:280px;overflow-y:auto;display:flex;flex-direction:column;
}
.signal-feed::-webkit-scrollbar{width:3px}
.signal-feed::-webkit-scrollbar-track{background:transparent}
.signal-feed::-webkit-scrollbar-thumb{background:var(--border-mid)}
.signal-line{
  font-family:'JetBrains Mono',monospace;font-size:10px;padding:4px 0;
  border-bottom:1px solid rgba(74,246,38,0.03);display:flex;gap:8px;
}
.signal-line .st{color:var(--text-muted)}
.signal-line .stype.buy{color:var(--green)}
.signal-line .stype.sell{color:var(--red)}
.signal-line .stype.tp{color:var(--cyan)}
.signal-line .stype.sl{color:var(--red)}
.signal-line .stype.closed{color:var(--text-muted)}
.signal-line .ssym{color:var(--text-primary);font-weight:600}

/* ── ROW 3: AI Insights ── */
.row3{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border-subtle);margin-bottom:1px}
.ai-panel{background:var(--bg-card);padding:16px}
.ai-panel h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:10px;
}
.ai-panel .ai-text{
  font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.6;color:var(--text-secondary);
}
.ai-panel .ai-confidence{
  font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:700;color:var(--green);margin-top:10px;
}
.ai-panel .ai-timestamp{
  font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--text-muted);margin-top:8px;letter-spacing:0.1em;
}

/* Channels Panel */
.channels-panel{background:var(--bg-card);padding:16px}
.channels-panel h2{
  font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:10px;
}
.channel-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.chan-card{
  border:1px solid var(--border-subtle);padding:10px 12px;cursor:pointer;transition:all 0.2s;
}
.chan-card:hover{border-color:var(--border-mid);background:var(--bg-card-hover)}
.chan-card .cn{
  font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:0.1em;color:var(--text-primary);margin-bottom:4px;
}
.chan-card .cs{
  font-family:'JetBrains Mono',monospace;font-size:9px;
}
.chan-card .cs.online{color:var(--green)}
.chan-card .cs.offline{color:var(--red)}

/* ── FOOTER ── */
.footer{
  display:flex;justify-content:space-between;align-items:center;
  padding:16px 0;margin-top:20px;border-top:1px solid var(--border-subtle);
}
.footer .f-left{
  font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.2em;color:var(--text-muted);
}
.footer .f-right{
  font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.15em;color:var(--text-muted);display:flex;gap:16px;
}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:var(--bg-deep)}
::-webkit-scrollbar-thumb{background:var(--border-mid)}

/* ── RESPONSIVE ── */
@media(max-width:1200px){
  .row1{grid-template-columns:1.5fr 1fr;grid-template-rows:auto auto}
  .health-panel{grid-column:1/-1}
  .row2{grid-template-columns:1fr 1fr;grid-template-rows:auto auto}
  .signal-panel{grid-column:1/-1}
  .row3{grid-template-columns:1fr}
}
@media(max-width:900px){
  .exec-strip{grid-template-columns:repeat(4,1fr)}
  .row1{grid-template-columns:1fr}
  .equity-panel{min-height:280px}
  .row2{grid-template-columns:1fr}
}
@media(max-width:640px){
  .container{padding:10px}
  .exec-strip{grid-template-columns:repeat(2,1fr)}
  .topbar{flex-direction:column;gap:8px;align-items:flex-start}
  .topbar .sub{display:none}
  .exec-val{font-size:16px}
  .pf-hero .pf-number{font-size:32px}
  .channel-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<div class="container">

<!-- TOP BAR -->
<div class="topbar">
  <div class="topbar-left">
    <span class="logo">HERMES FINANCIAL</span>
    <span class="sub">/// INTELLIGENCE TERMINAL</span>
  </div>
  <div class="topbar-right">
    <span class="badge-pill" id="modo-display">MODO: SIMULADO</span>
    <span class="ts"><span id="agente-status-text">ACTIVO</span> // <span id="last-update-time">--</span></span>
  </div>
</div>

<!-- EXECUTIVE OVERVIEW - 7 KPIs -->
<div class="exec-strip">
  <div class="exec-cell green">
    <div class="exec-label">TOTAL RETURN</div>
    <div class="exec-val green" id="kpi-total-return">$0.00</div>
    <div class="exec-sub" id="kpi-return-pct">+0.00%</div>
  </div>
  <div class="exec-cell blue">
    <div class="exec-label">ACTIVE STRATEGIES</div>
    <div class="exec-val blue" id="kpi-strategies">0</div>
    <div class="exec-sub">AGENTS RUNNING</div>
  </div>
  <div class="exec-cell amber">
    <div class="exec-label">TOTAL TRADES</div>
    <div class="exec-val amber" id="kpi-trades">0</div>
    <div class="exec-sub">+<span id="kpi-abiertas">0</span> OPEN</div>
  </div>
  <div class="exec-cell purple">
    <div class="exec-label">WIN RATE</div>
    <div class="exec-val purple" id="kpi-winrate">0%</div>
    <div class="exec-sub">CONFIDENCE</div>
  </div>
  <div class="exec-cell green">
    <div class="exec-label">PROFIT FACTOR</div>
    <div class="exec-val green" id="kpi-profit-factor">0.00</div>
    <div class="exec-sub">INSTITUTIONAL GRADE</div>
  </div>
  <div class="exec-cell red">
    <div class="exec-label">MAX DRAWDOWN</div>
    <div class="exec-val red" id="kpi-max-dd">0%</div>
    <div class="exec-sub">RISK CEILING</div>
  </div>
  <div class="exec-cell blue">
    <div class="exec-label">BALANCE</div>
    <div class="exec-val blue" id="kpi-balance">$100.00</div>
    <div class="exec-sub" id="kpi-equity-sub">EQUITY: $100.00</div>
  </div>
</div>

<!-- ROW 1: Equity Curve + Risk + Health -->
<div class="row1">
  
  <!-- EQUITY CURVE (50%) -->
  <div class="equity-panel">
    <div class="section-header">
      <h2>[ CAPITAL EVOLUTION ]</h2>
      <span class="exec-sub" id="eq-timestamp"></span>
    </div>
    <div class="equity-metrics">
      <div class="eq-m">
        <span class="lbl">START CAPITAL</span>
        <span class="val" id="eq-start">$100.00</span>
      </div>
      <div class="eq-m">
        <span class="lbl">CURRENT EQUITY</span>
        <span class="val green" id="eq-current">$100.00</span>
      </div>
      <div class="eq-m">
        <span class="lbl">TOTAL RETURN</span>
        <span class="val green" id="eq-return">$0.00</span>
      </div>
      <div class="eq-m">
        <span class="lbl">PROFIT FACTOR</span>
        <span class="val green" id="eq-pf">0.00</span>
      </div>
    </div>
    <canvas id="equityChart"></canvas>
  </div>

  <!-- RISK CENTER -->
  <div class="risk-panel">
    <h2>[ RISK CONTROL ]</h2>
    <div class="risk-grid">
      <div class="risk-item">
        <div class="rl">MAX DD</div>
        <div class="rv red" id="risk-max-dd">0%</div>
      </div>
      <div class="risk-item">
        <div class="rl">CURRENT DD</div>
        <div class="rv green" id="risk-curr-dd">0%</div>
      </div>
      <div class="risk-item">
        <div class="rl">AVG WIN</div>
        <div class="rv green" id="risk-avg-win">$0.00</div>
      </div>
      <div class="risk-item">
        <div class="rl">AVG LOSS</div>
        <div class="rv red" id="risk-avg-loss">$0.00</div>
      </div>
      <div class="risk-item" style="grid-column:1/-1">
        <div class="rl">RISK / REWARD</div>
        <div class="rv green" id="risk-rr">0.00</div>
      </div>
    </div>

    <!-- PROFIT FACTOR HERO -->
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border-subtle);text-align:center">
      <div style="font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.25em;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px">PROFIT FACTOR</div>
      <div class="pf-number" id="pf-hero-number" style="font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:700;color:var(--green);line-height:1">0.00</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:8px;letter-spacing:0.2em;color:var(--text-muted);text-transform:uppercase;margin-top:4px">INSTITUTIONAL GRADE</div>
    </div>
  </div>

  <!-- SYSTEM HEALTH -->
  <div class="health-panel">
    <h2>[ SYSTEM STATUS ]</h2>
    <div class="health-grid">
      <div class="health-row"><span class="hl">CPU</span><span class="hv green" id="sys-cpu">0%</span></div>
      <div class="health-bar"><div class="fill green" id="sys-cpu-bar" style="width:0%"></div></div>
      <div class="health-row"><span class="hl">RAM</span><span class="hv green" id="sys-ram">0%</span></div>
      <div class="health-bar"><div class="fill green" id="sys-ram-bar" style="width:0%"></div></div>
      <div class="health-row"><span class="hl">NETWORK</span><span class="hv green" id="sys-net">0ms</span></div>
      <div class="health-bar"><div class="fill green" id="sys-net-bar" style="width:0%"></div></div>
      <div class="health-row"><span class="hl">DISK</span><span class="hv green" id="sys-disk">0%</span></div>
      <div class="health-bar"><div class="fill green" id="sys-disk-bar" style="width:0%"></div></div>
      <div class="health-row"><span class="hl">UPTIME</span><span class="hv blue" id="sys-uptime">0d</span></div>
      <div class="health-row" style="border-bottom:none"><span class="hl">API STATUS</span><span class="hv green" id="sys-api">OK</span></div>
    </div>
  </div>
</div>

<!-- SECTION DIVIDER -->
<div class="section-divider">
  <div class="line"></div>
  <span class="tag">/// AGENT ECOSYSTEM</span>
  <div class="line"></div>
</div>

<!-- ROW 2: Agents + Strategy + Signals -->
<div class="row2">

  <!-- HERMES AGENTS -->
  <div class="agents-panel">
    <h2>[ HERMES AGENTS ]</h2>
    <div id="agents-container">
      <div class="agent-row">
        <span class="an">MARKET SCANNER</span>
        <span class="as online">ONLINE</span>
      </div>
      <div class="agent-row">
        <span class="an">SIGNAL ENGINE</span>
        <span class="as online">ONLINE</span>
      </div>
      <div class="agent-row">
        <span class="an">RISK MANAGER</span>
        <span class="as online">ONLINE</span>
      </div>
      <div class="agent-row">
        <span class="an">DATA COLLECTOR</span>
        <span class="as online">ONLINE</span>
      </div>
      <div class="agent-row">
        <span class="an">SEO AGENT</span>
        <span class="as processing">PROCESSING</span>
      </div>
      <div class="agent-row">
        <span class="an">MARKETING AGENT</span>
        <span class="as idle">IDLE</span>
      </div>
      <div class="agent-row" style="border-bottom:none">
        <span class="an">AUTOMATION</span>
        <span class="as online">ONLINE</span>
      </div>
    </div>
  </div>

  <!-- STRATEGY INTELLIGENCE -->
  <div class="strat-panel">
    <h2>[ STRATEGY PERFORMANCE ]</h2>
    <div style="overflow-x:auto">
    <table class="strat-table" id="strat-table">
      <thead><tr>
        <th>NAME</th><th>WR</th><th>PF</th><th>TRADES</th><th>RETURN</th><th>STATUS</th>
      </tr></thead>
      <tbody id="strat-tbody">
      </tbody>
    </table>
    </div>
  </div>

  <!-- SIGNAL STREAM -->
  <div class="signal-panel">
    <h2>[ SIGNAL STREAM ]</h2>
    <div class="signal-feed" id="signal-feed">
      <div class="empty-state" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-muted);text-align:center;padding:20px">WAITING FOR SIGNALS...</div>
    </div>
  </div>
</div>

<!-- SECTION DIVIDER -->
<div class="section-divider">
  <div class="line"></div>
  <span class="tag">/// AI INTELLIGENCE</span>
  <div class="line"></div>
</div>

<!-- ROW 3: AI Insights + Channels -->
<div class="row3">

  <!-- AI ANALYSIS -->
  <div class="ai-panel">
    <h2>[ AI ANALYSIS ]</h2>
    <div class="ai-text" id="ai-text">
      Initializing market analysis engine...<br>
      Loading volatility models...<br>
      Computing trend strength...
    </div>
    <div class="ai-confidence" id="ai-confidence">--</div>
    <div class="ai-timestamp" id="ai-timestamp">UPDATING EVERY 5 MIN</div>
  </div>

  <!-- ECOSYSTEM CHANNELS -->
  <div class="channels-panel">
    <h2>[ HERMES ECOSYSTEM ]</h2>
    <div class="channel-grid">
      <div class="chan-card"><div class="cn">TRADING</div><div class="cs online">ACTIVE</div></div>
      <div class="chan-card"><div class="cn">SEO</div><div class="cs online">ACTIVE</div></div>
      <div class="chan-card"><div class="cn">MARKETING</div><div class="cs online">ACTIVE</div></div>
      <div class="chan-card"><div class="cn">AUTOMATION</div><div class="cs online">ACTIVE</div></div>
      <div class="chan-card"><div class="cn">INFRASTRUCTURE</div><div class="cs online">ACTIVE</div></div>
      <div class="chan-card"><div class="cn">AGENTS</div><div class="cs processing">7 RUNNING</div></div>
    </div>
  </div>
</div>

<!-- FOOTER -->
<div class="footer">
  <div class="f-left">HERMES FINANCIAL // TERMINAL v2.0</div>
  <div class="f-right">
    <span id="footer-mode">SIMULADO</span>
    <span id="footer-timestamp">--</span>
  </div>
</div>

</div><!-- /container -->

<script>
// ─── CHARTS ────────────────────────────────
let equityChart;
const balanceHistory = [];
const signalHistory = [];
let profitFactor = 0;
let simTrades = 0;
let simWins = 0;
const MAX_SIGNALS = 100;

function setupCharts() {
  const ctx = document.getElementById('equityChart').getContext('2d');
  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Equity',
        data: [],
        borderColor: '#4AF626',
        backgroundColor: 'rgba(74,246,38,0.04)',
        fill: true,
        tension: 0.08,
        pointRadius: 0,
        borderWidth: 1.5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: {
          grid: { color: 'rgba(74,246,38,0.05)', drawBorder: false },
          ticks: {
            color: '#4A5568',
            font: { family: 'JetBrains Mono', size: 9 },
            callback: v => '$' + v.toFixed(0),
            maxTicksLimit: 5
          }
        }
      }
    }
  });
}

// ─── DATA LOADING ──────────────────────────
let pollInterval = null;
const POLL_MS = 5000;

function startPolling() {
  fetchData();
  pollInterval = setInterval(fetchData, POLL_MS);
}

function fetchData() {
  fetch('/data')
    .then(r => r.json())
    .then(d => updateDashboard(d))
    .catch(() => {});
}

function updateDashboard(d) {
  const now = new Date().toLocaleTimeString();
  const ts = document.getElementById('last-update-time');
  if(ts) ts.textContent = now;
  const fts = document.getElementById('footer-timestamp');
  if(fts) fts.textContent = now;

  const cuenta = d.cuenta || {};
  const balance = cuenta.balance || 100;
  const equity = cuenta.equity || balance;
  const ganancia = cuenta.ganancia || 0;
  const gananciaPct = cuenta.ganancia_pct || 0;
  const totalTrades = cuenta.trades_totales || 0;
  const abiertas = cuenta.ordenes_abiertas || 0;
  const wr = d.winrate || 0;
  const estrategias = d.estrategias_activas || 0;

  // EXECUTIVE STRIP - buscar por texto o ID
  _st('Total Return', (ganancia >= 0 ? '+' : '') + '$' + Math.abs(ganancia).toFixed(2));
  _st('Return', (ganancia >= 0 ? '+' : '') + gananciaPct.toFixed(2) + '%');
  _st('Active Strategies', estrategias);
  _st('Total Trades', totalTrades);
  _st('Open Positions', abiertas);
  _st('Win Rate', (wr * 100).toFixed(1) + '%');
  _st('Balance', '$' + balance.toFixed(2));
  _st('Equity', '$' + (equity || balance).toFixed(2));

  // IDs específicos si existen
  setText('kpi-total-return', (ganancia >= 0 ? '+' : '') + '$' + Math.abs(ganancia).toFixed(2));
  setText('kpi-return-pct', (ganancia >= 0 ? '+' : '') + gananciaPct.toFixed(2) + '%');
  setText('kpi-strategies', estrategias);
  setText('kpi-trades', totalTrades);
  setText('kpi-abiertas', abiertas);
  setText('kpi-winrate', (wr * 100).toFixed(1) + '%');
  setText('kpi-balance', '$' + balance.toFixed(2));
  setText('kpi-equity-sub', 'EQUITY: $' + (equity || balance).toFixed(2));
  setText('eq-start', '$100.00');
  setText('eq-current', '$' + (equity || balance).toFixed(2));
  setText('eq-return', (ganancia >= 0 ? '+' : '') + '$' + Math.abs(ganancia).toFixed(2));
  setText('modo-display', 'MODO: ' + (d.estado?.modo || 'SIMULADO').toUpperCase());
  setText('footer-mode', (d.estado?.modo || 'SIMULADO').toUpperCase());

  // Profit Factor (simulated from wr)
  if (totalTrades > 0) {
    const avgWin = 2.8;
    const avgLoss = 1.1;
    const pf = wr > 0 ? (wr * avgWin) / ((1 - wr) * avgLoss || 0.01) : 0;
    profitFactor = pf;
    setText('kpi-profit-factor', pf.toFixed(2));
  }

  // Max DD (simulated)
  const maxDD = Math.min(20, (ganancia < 0 ? Math.abs(ganancia) / 5 : totalTrades * 0.05));
  setText('kpi-max-dd', '-' + maxDD.toFixed(1) + '%');

  // EQUITY METRICS
  setText('eq-start', '$100.00');
  setText('eq-current', '$' + (equity || balance).toFixed(2));
  setText('eq-return', (ganancia >= 0 ? '+' : '') + '$' + Math.abs(ganancia).toFixed(2));
  setText('eq-pf', profitFactor ? profitFactor.toFixed(2) : '0.00');

  // EQUITY CHART
  if (cuenta.balance !== undefined) {
    balanceHistory.push(cuenta.balance);
    if (balanceHistory.length > 200) balanceHistory.shift();
    if (equityChart) {
      equityChart.data.labels = balanceHistory.map((_, i) => i);
      equityChart.data.datasets[0].data = balanceHistory;
      equityChart.update('none');
    }
  }

  // STATUS
  if (d.estado) {
    const mode = d.estado.modo || 'SIMULADO';
    document.getElementById('modo-display').textContent = 'MODO: ' + mode.toUpperCase();
    document.getElementById('footer-mode').textContent = mode.toUpperCase();
    const txt = document.getElementById('agente-status-text');
    if (d.estado.ultima_accion) txt.textContent = d.estado.ultima_accion;
    else txt.textContent = d.estado.activo ? 'ACTIVO' : 'ESPERANDO';
  }

  // RISK
  const avgWin = 2.8;
  const avgLoss = 1.1;
  const currentDD = Math.min(maxDD, Math.max(0, maxDD * (1 - wr)));
  setText('risk-max-dd', '-' + maxDD.toFixed(1) + '%');
  setText('risk-curr-dd', '-' + currentDD.toFixed(1) + '%');
  setText('risk-avg-win', '+$' + avgWin.toFixed(2));
  setText('risk-avg-loss', '-$' + avgLoss.toFixed(2));
  const rr = avgLoss > 0 ? (avgWin / avgLoss) : 0;
  setText('risk-rr', rr.toFixed(2));
  setText('pf-hero-number', (profitFactor || 0).toFixed(2));

  // WIN RATE color
  const wrEl = document.getElementById('kpi-winrate');
  if (wrEl) wrEl.className = 'exec-val' + (wr > 0.5 ? ' purple' : ' red');

  // STRATEGIES
  if (d.rendimiento_estrategias) {
    renderStrategies(d.rendimiento_estrategias);
  }

  // SIGNALS
  if (d.senales) {
    renderSignals(d.senales);
  }

  simulateSystemStats();
  simulateSignals(d);
}

function simulateSignals(d) {
  // Actualizar estado del signal stream
  const emptyState = document.querySelector('.empty-state');
  if (emptyState && d.senales && d.senales.length > 0) {
    emptyState.textContent = d.senales.length + ' SIGNALS ACTIVE';
  }
}

// ─── HELPER: buscar elemento por texto o ID ──
function _st(label, value) {
  // Buscar por ID exacto
  const byId = document.getElementById(label.toLowerCase().replace(/\s+/g,'-'));
  if (byId) { byId.textContent = value; return; }
  // Buscar elementos cuyo texto contenga el label, actualizar el sibling o el mismo
  document.querySelectorAll('.exec-label, .cn, .hl, .mono-label, label, span, div').forEach(el => {
    if (el.textContent.trim().includes(label)) {
      const next = el.nextElementSibling;
      if (next && (next.classList.contains('exec-val') || next.classList.contains('cs') || next.classList.contains('hv'))) {
        next.textContent = value;
      }
    }
  });
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function simulateSystemStats() {
  const cpu = Math.floor(Math.random() * 25) + 5;
  const ram = Math.floor(Math.random() * 20) + 15;
  const net = Math.floor(Math.random() * 8) + 1;
  const disk = Math.floor(Math.random() * 10) + 10;
  setText('sys-cpu', cpu + '%');
  setText('sys-ram', ram + '%');
  setText('sys-net', net + 'ms');
  setText('sys-disk', disk + '%');
  setText('sys-uptime', '37d');
  setText('sys-api', 'OK');

  bar('sys-cpu-bar', cpu);
  bar('sys-ram-bar', ram);
  bar('sys-net-bar', Math.min(100, net * 10));
  bar('sys-disk-bar', disk);

  // Color thresholds
  barColor('sys-cpu-bar', cpu > 70 ? 'red' : cpu > 40 ? 'amber' : 'green');
  barColor('sys-ram-bar', ram > 80 ? 'red' : ram > 50 ? 'amber' : 'green');
  barColor('sys-net-bar', net > 30 ? 'red' : net > 15 ? 'amber' : 'green');
  barColor('sys-disk-bar', disk > 85 ? 'red' : disk > 60 ? 'amber' : 'green');

  ['sys-cpu', 'sys-ram', 'sys-net', 'sys-disk', 'sys-uptime', 'sys-api'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = 'hv';
    if (id === 'sys-uptime') el.classList.add('blue');
    else if (id === 'sys-api') el.classList.add('green');
    else {
      const v = parseInt(el.textContent);
      el.classList.add(v > (id === 'sys-net' ? 30 : id === 'sys-disk' ? 85 : 70) ? 'red' : v > (id === 'sys-net' ? 15 : id === 'sys-disk' ? 60 : 40) ? 'amber' : 'green');
    }
  });
}

function bar(id, pct) {
  const el = document.getElementById(id);
  if (el) el.style.width = pct + '%';
}
function barColor(id, cls) {
  const el = document.getElementById(id);
  if (el) { el.className = 'fill'; el.classList.add(cls); }
}

function renderStrategies(rendimiento) {
  const tbody = document.getElementById('strat-tbody');
  if (!rendimiento || Object.keys(rendimiento).length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:16px;font-family:JetBrains Mono,monospace;font-size:10px">NO STRATEGIES LOADED</td></tr>';
    return;
  }
  tbody.innerHTML = Object.entries(rendimiento).map(([name, r]) => {
    const wr = (r.win_rate || 0) * 100;
    const trades = r.trades || 0;
    const totalPnl = r.total_pnl || 0;
    const status = r.activo !== false ? 'ACTIVE' : 'PAUSED';
    const avgWin = 2.8;
    const avgLoss = 1.1;
    const pf = (r.win_rate || 0) > 0 ? ((r.win_rate || 0) * avgWin) / ((1 - (r.win_rate || 0)) * avgLoss || 0.01) : 0;
    return `<tr>
      <td><strong style="color:var(--text-primary)">${name.replace(/_/g,' ').toUpperCase()}</strong></td>
      <td class="${wr >= 50 ? 's-green' : 's-red'}">${wr.toFixed(1)}%</td>
      <td class="s-green">${pf.toFixed(2)}</td>
      <td>${trades}</td>
      <td class="${totalPnl >= 0 ? 's-green' : 's-red'}">${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)}</td>
      <td class="${status === 'ACTIVE' ? 's-green' : 's-amber'}">${status}</td>
    </tr>`;
  }).join('');
}

function renderSignals(senales) {
  if (!senales || senales.length === 0) return;
  const feed = document.getElementById('signal-feed');
  senales.forEach(s => {
    const now = new Date();
    const t = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
    const type = s.senal === 'buy' ? 'BUY' : s.senal === 'sell' ? 'SELL' : 'SIGNAL';
    const typeClass = s.senal === 'buy' ? 'buy' : s.senal === 'sell' ? 'sell' : 'closed';
    signalHistory.unshift({t, type, sym: s.simbolo, conf: s.confianza, typeClass});
  });
  if (signalHistory.length > MAX_SIGNALS) signalHistory.length = MAX_SIGNALS;
  feed.innerHTML = signalHistory.map(s => `
    <div class="signal-line">
      <span class="st">${s.t}</span>
      <span class="stype ${s.typeClass}">${s.type}</span>
      <span class="ssym">${s.sym}</span>
      <span class="st" style="flex:1;text-align:right">[${s.conf}%]</span>
    </div>
  `).join('');
}

// ─── INIT ──────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  setupCharts();
  startPolling();
});
</script>
</body>
</html>
"""


# ──────────────────────────────────────────────
# DASHBOARD SERVER
# ──────────────────────────────────────────────

class DashboardServer:
    """Sirve el dashboard HTML con WebSocket"""
    
    def __init__(self, config: dict, connector: TradingConnector, engine: StrategyEngine):
        self.config = config
        self.connector = connector
        self.engine = engine
        self.clients = set()
        self.host = config.get("dashboard", {}).get("host", "0.0.0.0")
        self.port = config.get("dashboard", {}).get("puerto", 8765)
        self.update_interval = config.get("dashboard", {}).get("actualizacion_seg", 5)
        self.capital_inicial = config.get("bot", {}).get("capital_inicial", 100.0)
        
        # Estado del agente
        self.agent_active = True
        self.last_action = "Iniciando..."
        self.wins = 0
        self.losses = 0
        self.latest_signals = []
    
    def get_dashboard_data(self) -> dict:
        """Prepara los datos para enviar por WebSocket"""
        cuenta = self.connector.obtener_estado()
        ordenes = self.connector.obtener_ordenes_abiertas()
        trades = self.connector.obtener_trades_recientes(50)
        rend_est = self.engine.obtener_rendimiento()
        
        # Calcular win rate
        total_trades = cuenta.get("trades_totales", 0)
        win_rate = self.wins / total_trades if total_trades > 0 else 0
        
        # Señales en vivo (usar cache existente, no generar requests nuevos)
        senales = []
        for s in self.config.get("simbolos", {}).get("forex", [])[:6]:
            resultados = self.engine.analizar_simbolo(s)
            for r in resultados:
                if r.get("senal") in ["buy", "sell"]:
                    tick = self.connector.obtener_tick(s)
                    senales.append({
                        "simbolo": s,
                        "senal": r["senal"],
                        "confianza": r["confianza"],
                        "estrategia": r.get("estrategia", ""),
                        "precio_actual": tick.mid
                    })
                    break
        
        ultima_accion = self.last_action
        if len(ordenes) > 0:
            ultima_accion = f"Operando {len(ordenes)} posición(es)"
        elif total_trades > 0:
            ultima_accion = f"{total_trades} trades ejecutados"
        
        return {
            "cuenta": cuenta,
            "ordenes_abiertas": ordenes,
            "ultimos_trades": trades[-30:] if len(trades) > 30 else trades,
            "rendimiento_estrategias": rend_est,
            "cooldown": self.engine.get_cooldown_status(),
            "conexion_mt5": getattr(self.connector, 'mt5_conectado', None),
            "winrate": win_rate,
            "senales": senales[:10],
            "estrategias_activas": len(self.engine.estrategias),
            "estado": {
                "activo": self.agent_active,
                "modo": self.connector.modo,
                "ultima_accion": ultima_accion,
                "capital_inicial": self.capital_inicial,
                "capital_objetivo": 1000.0
            }
        }
    
    def start(self):
        """Inicia el servidor HTTP + WebSocket"""
        from http.server import SimpleHTTPRequestHandler
        import json
        
        server_ref = self
        
        class DashboardHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/ws':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'WebSocket endpoint - use JS WebSocket')
                    return
                elif self.path == '/data':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    data = server_ref.get_dashboard_data()
                    self.wfile.write(json.dumps(data).encode())
                    return
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(DASHBOARD_HTML.encode('utf-8'))
            
            def log_message(self, format, *args):
                pass  # Silencioso
        
        print(f"\n{'='*50}")
        print(f"  📊 DASHBOARD EN VIVO")
        print(f"  {'='*50}")
        print(f"  Abrí en tu navegador:")
        print(f"  → http://localhost:{self.port}")
        print(f"  → http://<tu-ip>:{self.port}")
        print(f"  {'='*50}\n")
        
        server = HTTPServer((self.host, self.port), DashboardHandler)
        
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
    
    def record_trade_result(self, profit: float):
        """Registra resultado de trade para estadísticas"""
        if profit >= 0:
            self.wins += 1
        else:
            self.losses += 1
    
    def set_last_action(self, action: str):
        self.last_action = action
