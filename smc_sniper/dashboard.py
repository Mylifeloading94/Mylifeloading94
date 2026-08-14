"""Phase 10 -- HTML dashboard generated from the logs and backtest results.

Bot status, HTF bias per pair, trades, win rate, profit factor, drawdown, score
distribution, per-pair and per-session performance, recent signals, recent
*rejections*, and errors. Self-contained HTML: no external assets.
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone

import pandas as pd

_CSS = """
:root{--bg:#ffffff;--fg:#16181d;--muted:#5d6470;--line:#e3e6ec;--card:#f7f8fa;
--pos:#0d7a4f;--neg:#b3261e;--accent:#2b5cd9;}
@media (prefers-color-scheme:dark){:root{--bg:#12141a;--fg:#e8eaf0;--muted:#9aa3b2;
--line:#272b35;--card:#1a1d25;--pos:#3ddc97;--neg:#ff6b6b;--accent:#7aa2ff;}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}
h1{font-size:22px;margin:0 0 4px} h2{font-size:15px;margin:28px 0 10px;
text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.v{font-size:22px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)} .neg{color:var(--neg)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:520px}
th,td{padding:8px 11px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap;font-variant-numeric:tabular-nums}
th{background:var(--card);font-size:11px;text-transform:uppercase;
letter-spacing:.05em;color:var(--muted);position:sticky;top:0}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
.banner{border-left:3px solid var(--accent);background:var(--card);padding:12px 16px;
border-radius:0 8px 8px 0;margin:18px 0}
.warn{border-left-color:var(--neg)}
code{background:var(--card);padding:1px 5px;border-radius:4px;font-size:12px}
"""


def _num(value, digits=2, signed=False):
    try:
        val = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    cls = "pos" if val > 0 else ("neg" if val < 0 else "")
    text = f"{val:+.{digits}f}" if signed else f"{val:.{digits}f}"
    return f'<span class="{cls}">{text}</span>' if cls else text


def _table(frame: pd.DataFrame, limit: int | None = None) -> str:
    if frame is None or frame.empty:
        return '<p class="sub">No rows.</p>'
    view = frame.head(limit) if limit else frame
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in view.columns)
    body = []
    for _, row in view.iterrows():
        cells = []
        for col in view.columns:
            val = row[col]
            if isinstance(val, float):
                signed = col in ("expectancy_r", "total_r", "r_multiple", "pnl")
                cells.append(f"<td>{_num(val, 3 if 'exp' in str(col) else 2, signed)}</td>")
            else:
                cells.append(f"<td>{html.escape(str(val))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _stat(label: str, value, digits=2, signed=False) -> str:
    return (f'<div class="card"><div class="k">{html.escape(label)}</div>'
            f'<div class="v">{_num(value, digits, signed)}</div></div>')


def render(cfg, metrics: dict, tables: dict, caveats: list[str],
           status: str = "BACKTEST / RESEARCH -- not live") -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stack = cfg.stack
    parts = [
        f"<style>{_CSS}</style>",
        "<h1>SMC Sniper -- Status &amp; Performance</h1>",
        f'<div class="sub">Generated {now} &middot; stack <code>{stack.get("name")}</code> '
        f'({stack.get("bias_tf")} bias / {stack.get("structure_tf")} structure / '
        f'{stack.get("setup_tf")} setup / {stack.get("entry_tf")} entry) &middot; '
        f'status: <b>{html.escape(status)}</b></div>',
    ]

    parts.append('<div class="grid">')
    parts.append(_stat("Trades", metrics.get("trades", 0), 0))
    parts.append(_stat("Win rate %", metrics.get("win_rate", 0)))
    parts.append(_stat("Profit factor", metrics.get("profit_factor", 0)))
    parts.append(_stat("Expectancy R", metrics.get("expectancy_r", 0), 3, True))
    parts.append(_stat("Total R", metrics.get("total_r", 0), 2, True))
    parts.append(_stat("Max DD %", metrics.get("max_drawdown_pct", 0)))
    parts.append(_stat("Sharpe", metrics.get("sharpe", 0)))
    parts.append(_stat("Max cons. losses", metrics.get("max_consecutive_losses", 0), 0))
    parts.append("</div>")

    if caveats:
        items = "".join(f"<li>{html.escape(c)}</li>" for c in caveats)
        parts.append(f'<div class="banner warn"><b>Caveats</b><ul>{items}</ul></div>')

    for title, frame in tables.items():
        parts.append(f"<h2>{html.escape(title)}</h2>")
        parts.append(_table(frame, 60))
    return "\n".join(parts)


def write(cfg, metrics: dict, tables: dict, caveats: list[str],
          path: str | None = None, status: str = "BACKTEST / RESEARCH -- not live") -> str:
    path = path or cfg.resolve_path(cfg.get("dashboard.output", "reports/dashboard.html"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = render(cfg, metrics, tables, caveats, status)
    with open(path, "w") as fh:
        fh.write("<!doctype html><html><head><meta charset='utf-8'>"
                 "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                 "<title>SMC Sniper Dashboard</title></head><body>"
                 + body + "</body></html>")
    return path
