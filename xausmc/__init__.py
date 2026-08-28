"""
XAUUSD SMC Sniper Engine — a high-selectivity Smart Money Concepts analysis and
signal bot for gold.

Design commitments (they are the point of the package, not decoration):
  * Prices are never invented. If no provider returns fresh data the engine
    reports LIVE DATA UNAVAILABLE and produces no setup.
  * Live data and historical/backtest data are labelled everywhere and never
    mixed.
  * A displayed win probability is the measured frequency of that exact
    configuration in the backtest, shown with its sample size — or the words
    INSUFFICIENT SAMPLE.
  * The live scanner and the backtest run the same detection and grading code,
    which is what makes those numbers describe this engine.
  * Every published setup is re-derived from scratch every 60 seconds and
    marked VALID or INVALID, with a reason.

Entry point: `xau_bot.py` at the repository root.
"""
__version__ = "1.0.0"
__all__ = ["candles", "feed", "smc", "sessions", "regime", "config", "setups", "grading",
           "stats", "invalidation", "journal", "performance", "news", "engine", "render",
           "chart", "web", "backtest"]
