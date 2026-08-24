"""Primary backtest driver: real XAUUSD M1, Jan 2026 -> today, $500 account."""
import sys, time, json
sys.path.insert(0, '.')
import pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute, render, breakdown
from xauusd_bot.news.news_filter import NewsFilter


class Prep:
    def __init__(self, F): self.F = F; self.m1 = None


def main():
    F = pd.read_pickle('data_cache/F_2026.pkl')
    prep = Prep(F)
    news = NewsFilter.load(Config().news)
    for label, ov in [
        ("A) STANDARD CONTRACT  min lot 0.01, risk 0.50%", {}),
        ("B) MICRO CONTRACT     min lot 0.001, risk 0.50%",
         {'instrument.min_lot': 0.001, 'instrument.lot_step': 0.001}),
    ]:
        cfg = Config().with_overrides(**ov) if ov else Config()
        cfg.initial_equity = 500.0
        t = time.time()
        res, art = run(prep, cfg, news)
        m = compute(res.trades, res.equity, 500.0)
        print("\n" + "=" * 78); print(label); print("=" * 78)
        print(f"  [{time.time()-t:.1f}s]  signals evaluated: {res.signals_seen}")
        print("  selector:", res.stats['selector'])
        print("  rejections:", dict(sorted(res.rejections.items(), key=lambda x: -x[1])))
        print(render(m, "RESULT"))
        if len(res.trades):
            for by in ("strategy", "session", "grade", "exit_reason", "regime"):
                b = breakdown(res.trades, by)
                if len(b): print(f"\n  by {by}:\n" + b.to_string(index=False))
            res.trades.to_csv(f"xauusd_bot/reports/trades_{label[0]}.csv", index=False)


if __name__ == "__main__":
    main()
