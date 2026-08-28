"""
Chart rendering (spec §1 / §2).

Two charts, side by side, because they answer different questions:

  * a TradingView Advanced Chart widget — the officially supported, free embed.
    It is TradingView's own live XAUUSD chart, drawn by TradingView. This bot
    does not scrape TradingView and does not read prices from it.

  * an SVG chart this engine draws itself, from the same bars it graded the
    setup on, carrying the SMC annotations TradingView cannot know about:
    market structure, BOS/CHoCH, liquidity pools, order blocks, FVGs,
    premium/discount, and the entry / stop / target levels.

Colour system (identical to the terminal renderer):
    Entry BLUE · Stop Loss RED · Targets GREEN · Invalid GREY, labelled INVALID
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .candles import Series
from .setups import Context, Setup

# -- palette ---------------------------------------------------------------
C_ENTRY = "#2e8fff"
C_STOP = "#ff4d4d"
C_TARGET = "#22c55e"
C_INVALID = "#9aa4b2"
C_UP = "#26a69a"
C_DOWN = "#ef5350"
C_GRID = "#232838"
C_TEXT = "#c9d1d9"
C_DIM = "#7d8590"
C_BG = "#0d1117"
C_PANEL = "#161b22"
C_FVG_BULL = "rgba(38,166,154,0.16)"
C_FVG_BEAR = "rgba(239,83,80,0.16)"
C_OB_BULL = "rgba(46,143,255,0.14)"
C_OB_BEAR = "rgba(255,166,87,0.14)"
C_LIQ = "#f0b429"
C_PREM = "rgba(239,83,80,0.06)"
C_DISC = "rgba(38,166,154,0.06)"


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _ts(ts) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %H:%M") if ts else "—"


# --------------------------------------------------------------------------
# SVG chart
# --------------------------------------------------------------------------
def svg_chart(series: Series, ctx: Context | None = None, setup: Setup | None = None,
              bars: int = 140, width: int = 1180, height: int = 560) -> str:
    win = series.bars[-bars:]
    if len(win) < 5:
        return f'<div class="empty">not enough bars on {series.tf} to draw a chart</div>'

    ml, mr, mt, mb = 8, 96, 16, 26
    plot_w, plot_h = width - ml - mr, height - mt - mb
    invalid = setup is not None and setup.status != "VALID"

    levels: list[tuple[float, str, str]] = []
    if setup is not None:
        ec, sc, tc = (C_INVALID, C_INVALID, C_INVALID) if invalid else (C_ENTRY, C_STOP, C_TARGET)
        levels = [(setup.entry, ec, "ENTRY"), (setup.sl, sc, "STOP"),
                  (setup.tp1, tc, "TP1"), (setup.tp2, tc, "TP2")]
        if setup.tp3:
            levels.append((setup.tp3, tc, "TP3"))

    lo = min([b.l for b in win] + [v for v, _, _ in levels])
    hi = max([b.h for b in win] + [v for v, _, _ in levels])
    pad = (hi - lo) * 0.05 or 1.0
    lo, hi = lo - pad, hi + pad
    span = hi - lo

    def y(p: float) -> float:
        return mt + (hi - p) / span * plot_h

    cw = plot_w / len(win)
    t0 = win[0].ts

    def x_of_ts(ts: int) -> float:
        step = win[1].ts - win[0].ts if len(win) > 1 else 1
        return ml + max(0.0, min(float(len(win)), (ts - t0) / step)) * cw

    p: list[str] = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
                    f'preserveAspectRatio="xMidYMid meet" class="smcchart">',
                    f'<rect width="{width}" height="{height}" fill="{C_BG}"/>']

    # premium / discount shading + equilibrium
    if ctx is not None:
        pd = ctx.htf.pd
        if lo < pd.high and hi > pd.low:
            eq = pd.equilibrium
            p.append(f'<rect x="{ml}" y="{y(pd.high):.1f}" width="{plot_w}" '
                     f'height="{max(0, y(eq) - y(pd.high)):.1f}" fill="{C_PREM}"/>')
            p.append(f'<rect x="{ml}" y="{y(eq):.1f}" width="{plot_w}" '
                     f'height="{max(0, y(pd.low) - y(eq)):.1f}" fill="{C_DISC}"/>')
            p.append(f'<line x1="{ml}" y1="{y(eq):.1f}" x2="{ml + plot_w}" y2="{y(eq):.1f}" '
                     f'stroke="{C_DIM}" stroke-width="1" stroke-dasharray="2 6"/>')
            p.append(f'<text x="{ml + 6}" y="{y(eq) - 4:.1f}" fill="{C_DIM}" font-size="10">'
                     f'EQUILIBRIUM {eq:,.2f} · PREMIUM above / DISCOUNT below</text>')

        # FVGs and order blocks from the execution timeframe
        for g in ctx.ltf.fvgs[-14:]:
            if g.mitigated or g.ts < t0:
                continue
            fill = C_FVG_BULL if g.direction == "bullish" else C_FVG_BEAR
            gy, gh = y(g.top), max(1.0, y(g.bottom) - y(g.top))
            gx = x_of_ts(g.ts)
            p.append(f'<rect x="{gx:.1f}" y="{gy:.1f}" width="{max(6.0, ml + plot_w - gx):.1f}" '
                     f'height="{gh:.1f}" fill="{fill}"/>')
            p.append(f'<text x="{ml + plot_w - 4:.1f}" y="{gy + gh / 2 + 3:.1f}" fill="{C_DIM}" '
                     f'font-size="9" text-anchor="end">FVG</text>')
        for o in ctx.ltf.obs[-10:]:
            if o.mitigated or o.ts < t0:
                continue
            fill = C_OB_BULL if o.direction == "bullish" else C_OB_BEAR
            oy, oh = y(o.top), max(1.0, y(o.bottom) - y(o.top))
            ox = x_of_ts(o.ts)
            p.append(f'<rect x="{ox:.1f}" y="{oy:.1f}" width="{max(6.0, ml + plot_w - ox):.1f}" '
                     f'height="{oh:.1f}" fill="{fill}" stroke="{C_DIM}" stroke-width="0.5" '
                     f'stroke-dasharray="2 3"/>')
            p.append(f'<text x="{ox + 3:.1f}" y="{oy - 2:.1f}" fill="{C_DIM}" font-size="9">OB</text>')

        # unswept liquidity pools
        for pool in [q for q in ctx.ltf.pools if not q.swept][:8]:
            if not (lo < pool.price < hi):
                continue
            py = y(pool.price)
            p.append(f'<line x1="{ml}" y1="{py:.1f}" x2="{ml + plot_w}" y2="{py:.1f}" '
                     f'stroke="{C_LIQ}" stroke-width="0.8" stroke-dasharray="1 5" opacity="0.7"/>')
            p.append(f'<text x="{ml + 4}" y="{py - 3:.1f}" fill="{C_LIQ}" font-size="9" '
                     f'opacity="0.9">{_esc(pool.kind.upper())} {pool.price:,.2f}</text>')

    # grid
    for i in range(5):
        gy = mt + plot_h * i / 4
        p.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + plot_w}" y2="{gy:.1f}" '
                 f'stroke="{C_GRID}" stroke-width="1"/>')
        p.append(f'<text x="{ml + plot_w + 6}" y="{gy + 4:.1f}" fill="{C_DIM}" font-size="10">'
                 f'{hi - span * i / 4:,.2f}</text>')

    # candles
    body_w = max(1.0, cw * 0.62)
    for i, b in enumerate(win):
        cx = ml + i * cw + cw / 2
        col = C_UP if b.c >= b.o else C_DOWN
        p.append(f'<line x1="{cx:.1f}" y1="{y(b.h):.1f}" x2="{cx:.1f}" y2="{y(b.l):.1f}" '
                 f'stroke="{col}" stroke-width="1"/>')
        top, bot = y(max(b.o, b.c)), y(min(b.o, b.c))
        p.append(f'<rect x="{cx - body_w / 2:.1f}" y="{top:.1f}" width="{body_w:.1f}" '
                 f'height="{max(1.0, bot - top):.1f}" fill="{col}"/>')

    # structure events (BOS / CHoCH) on the execution timeframe
    if ctx is not None:
        for ev in ctx.ltf.structure.events[-6:]:
            if ev.ts < t0:
                continue
            ex, ey = x_of_ts(ev.ts), y(ev.level)
            col = C_UP if ev.direction == "bullish" else C_DOWN
            p.append(f'<line x1="{max(ml, ex - 60):.1f}" y1="{ey:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                     f'stroke="{col}" stroke-width="1" stroke-dasharray="4 3" opacity="0.85"/>')
            p.append(f'<text x="{ex + 3:.1f}" y="{ey - 3:.1f}" fill="{col}" font-size="9" '
                     f'font-weight="600">{"MSS/CHoCH" if ev.kind == "CHOCH" else "BOS"}</text>')

    # setup anchors
    if setup is not None:
        sw = setup.anchors.get("sweep", {})
        if sw.get("ts") and sw["ts"] >= t0:
            sx, sy = x_of_ts(sw["ts"]), y(sw["price"])
            p.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4" fill="none" stroke="{C_LIQ}" '
                     f'stroke-width="1.5"/>')
            p.append(f'<text x="{sx + 6:.1f}" y="{sy + 3:.1f}" fill="{C_LIQ}" font-size="9">'
                     f'SWEEP {_esc(sw.get("pool", ""))}</text>')
        zt, zb = setup.entry_high, setup.entry_low
        zc = C_INVALID if invalid else C_ENTRY
        p.append(f'<rect x="{ml}" y="{y(zt):.1f}" width="{plot_w}" '
                 f'height="{max(2.0, y(zb) - y(zt)):.1f}" fill="{zc}" opacity="0.12"/>')

    # entry / stop / target lines — the spec's colour layout
    dash = ' stroke-dasharray="6 4"' if invalid else ''
    for lv, col, name in levels:
        ly = y(lv)
        p.append(f'<line x1="{ml}" y1="{ly:.1f}" x2="{ml + plot_w}" y2="{ly:.1f}" '
                 f'stroke="{col}" stroke-width="1.6"{dash}/>')
        p.append(f'<rect x="{ml + plot_w + 2}" y="{ly - 8:.1f}" width="90" height="16" '
                 f'fill="{col}" rx="2"/>')
        p.append(f'<text x="{ml + plot_w + 6}" y="{ly + 4:.1f}" fill="#0d1117" font-size="10" '
                 f'font-weight="700">{name} {lv:,.2f}</text>')

    # live price
    last = win[-1].c
    p.append(f'<line x1="{ml}" y1="{y(last):.1f}" x2="{ml + plot_w}" y2="{y(last):.1f}" '
             f'stroke="{C_TEXT}" stroke-width="1" stroke-dasharray="3 3" opacity="0.6"/>')
    p.append(f'<rect x="{ml + plot_w + 2}" y="{y(last) - 8:.1f}" width="90" height="16" '
             f'fill="{C_TEXT}" rx="2"/>')
    p.append(f'<text x="{ml + plot_w + 6}" y="{y(last) + 4:.1f}" fill="#0d1117" font-size="10" '
             f'font-weight="700">PRICE {last:,.2f}</text>')

    p.append(f'<text x="{ml + 4}" y="{height - 8}" fill="{C_DIM}" font-size="10">'
             f'{_esc(series.symbol or "XAUUSD")} · {series.tf} · {len(win)} bars · '
             f'{_ts(win[0].ts)} → {_ts(win[-1].ts)} UTC · source {_esc(series.source)}</text>')
    if invalid:
        p.append(f'<text x="{ml + plot_w / 2:.0f}" y="{mt + plot_h / 2:.0f}" fill="{C_INVALID}" '
                 f'font-size="46" font-weight="800" text-anchor="middle" opacity="0.30">'
                 f'INVALID</text>')
    p.append("</svg>")
    return "".join(p)


# --------------------------------------------------------------------------
# TradingView embed (the supported, free widget)
# --------------------------------------------------------------------------
def tradingview_widget(symbol: str = "OANDA:XAUUSD", interval: str = "15",
                       height: int = 560) -> str:
    return f"""
<div class="tvwrap" style="height:{height}px">
  <div class="tradingview-widget-container" style="height:100%">
    <div id="tv_chart" style="height:100%"></div>
  </div>
  <script src="https://s3.tradingview.com/tv.js"></script>
  <script>
  (function () {{
    function boot() {{
      if (!window.TradingView) {{
        document.getElementById('tv_chart').innerHTML =
          '<div class="empty">TradingView widget could not load '
          + '(no network access to s3.tradingview.com from this browser).</div>';
        return;
      }}
      new TradingView.widget({{
        container_id: "tv_chart", autosize: true,
        symbol: {symbol!r}, interval: {interval!r}, timezone: "Etc/UTC",
        theme: "dark", style: "1", locale: "en",
        hide_side_toolbar: false, allow_symbol_change: true, withdateranges: true,
        studies: ["STD;Sessions"], backgroundColor: "{C_BG}", gridColor: "{C_GRID}"
      }});
    }}
    if (document.readyState === 'complete') boot();
    else window.addEventListener('load', boot);
  }})();
  </script>
</div>"""
