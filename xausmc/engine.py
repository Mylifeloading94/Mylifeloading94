"""
The scanner (spec §3 / §11): one pass = one complete, self-contained re-derivation.

Every 60 seconds the engine performs the full spec sequence:
  1. pull the newest market data (never a cached price for the fastest TF)
  2. analyse every timeframe of every enabled mode
  3. classify the market regime
  4. detect SMC setups
  5. validate them against the confluence model
  6. compute entry / stop / targets
  7. compute risk-to-reward
  8. assign a grade
  9. attach the measured historical probability (or say there isn't one)
 10. re-validate everything already published, invalidating what no longer holds

Nothing is carried over between scans except the journal. If the data is not
live, no setup is produced at all.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .candles import tf_seconds
from .config import MODES, EngineConfig
from .feed import DataFeed, FeedStatus, Snapshot
from .grading import apply_history_veto, grade
from .invalidation import revalidate
from .journal import Journal, Record
from .news import NewsVerdict, check as news_check
from .sessions import SessionInfo, session_at
from .setups import Context, Setup, build_context, detect
from .stats import StatsStore, apply_probability

GRADE_RANK = {"A+": 4, "A": 3, "B": 2, "C": 1, "INVALID": 0}


@dataclass
class Guard:
    """Risk gate state for the day (spec §17). Blocks NEW setups only."""
    setups_today: int = 0
    max_setups: int = 3
    open_trades: int = 0
    max_open: int = 2
    consecutive_losses: int = 0
    max_consecutive: int = 3
    realised_r_today: float = 0.0
    daily_loss_limit_r: float = 4.0
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)

    def evaluate(self):
        self.reasons = []
        if self.setups_today >= self.max_setups:
            self.reasons.append(f"daily setup ceiling reached ({self.setups_today}/{self.max_setups})")
        if self.open_trades >= self.max_open:
            self.reasons.append(f"maximum simultaneous trades open ({self.open_trades}/{self.max_open})")
        if self.consecutive_losses >= self.max_consecutive:
            self.reasons.append(f"{self.consecutive_losses} consecutive losses — standing down")
        if self.realised_r_today <= -self.daily_loss_limit_r:
            self.reasons.append(f"daily loss limit hit ({self.realised_r_today:+.2f}R of "
                                f"-{self.daily_loss_limit_r:.1f}R)")
        self.blocked = bool(self.reasons)
        return self


@dataclass
class ModeView:
    mode: str = ""
    htf_bias: str = ""
    htf_trend: str = ""
    mtf_trend: str = ""
    ltf_trend: str = ""
    regime: str = ""
    volatility: str = ""
    pd_zone: str = ""
    pd_position: float = 0.0
    range_high: float = 0.0
    range_low: float = 0.0
    equilibrium: float = 0.0
    unswept_pools: int = 0
    open_fvgs: int = 0
    fresh_obs: int = 0
    candidates: int = 0
    note: str = ""


@dataclass
class ScanResult:
    ts: float = 0.0
    feed: FeedStatus = field(default_factory=FeedStatus)
    price: float | None = None
    session: str = ""
    killzone: str | None = None
    bias: str = "UNKNOWN"
    regime: str = "UNKNOWN"
    modes: dict[str, ModeView] = field(default_factory=dict)
    setups: list[Setup] = field(default_factory=list)        # published, VALID
    rejected: list[Setup] = field(default_factory=list)      # detected but INVALID
    invalidated: list[tuple[Record, str]] = field(default_factory=list)
    active: list[Record] = field(default_factory=list)
    guard: Guard = field(default_factory=Guard)
    news: NewsVerdict | None = None
    notes: list[str] = field(default_factory=list)
    scan_ms: int = 0
    stats_meta: dict = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return self.feed.state == "LIVE"

    @property
    def best(self) -> Setup | None:
        return self.setups[0] if self.setups else None

    @property
    def headline(self) -> str:
        if not self.live:
            return self.feed.banner
        if self.setups:
            s = self.setups[0]
            return f"{s.grade} {s.direction} {s.mode} — {s.pattern.replace('_', ' ').title()}"
        return "NO VALID SETUP"


class Engine:
    def __init__(self, cfg: EngineConfig | None = None):
        self.cfg = cfg or EngineConfig()
        self.feed = DataFeed(prefer=self.cfg.provider)
        self.journal = Journal(self.cfg.path("signals.jsonl"))
        self.stats = StatsStore.load(self.cfg.path("stats.json"))
        self._contexts: dict[str, Context] = {}

    # -- helpers -----------------------------------------------------------
    def position_size(self, setup: Setup) -> tuple[float, float]:
        """Lots and dollars at risk for this setup under the configured risk model."""
        r = self.cfg.risk
        dollars = r.risk_dollars()
        per_pip = r.xau_pip_value_per_lot
        lots = dollars / (setup.sl_pips * per_pip) if setup.sl_pips > 0 else 0.0
        return round(max(0.01, lots), 2), round(dollars, 2)

    def _guard(self) -> Guard:
        r = self.cfg.risk
        limit_r = (r.max_daily_loss_pct / r.risk_per_trade_pct) if r.risk_per_trade_pct else 4.0
        return Guard(setups_today=self.journal.count_today(), max_setups=r.max_setups_per_day,
                     open_trades=len(self.journal.open_records()), max_open=r.max_open_trades,
                     consecutive_losses=self.journal.consecutive_losses(),
                     max_consecutive=r.max_consecutive_losses,
                     realised_r_today=self.journal.realised_r_today(),
                     daily_loss_limit_r=round(limit_r, 2)).evaluate()

    # -- the scan ----------------------------------------------------------
    def scan(self) -> ScanResult:
        t0 = time.time()
        res = ScanResult(ts=t0, stats_meta=dict(self.stats.meta))

        # 1. newest data, forced fresh on the fastest timeframe
        snap: Snapshot = self.feed.snapshot(self.cfg.timeframes, force=True)
        res.feed = snap.status
        res.price = snap.price
        sess: SessionInfo = session_at()
        res.session, res.killzone = sess.name, sess.killzone

        if snap.status.state != "LIVE":
            res.notes.append(snap.status.banner)
            res.notes.append("No setup is generated without live data (spec §18).")
            for e in snap.status.errors:
                res.notes.append(f"provider error — {e}")
            res.active = self.journal.open_records()
            res.guard = self._guard()
            res.scan_ms = int((time.time() - t0) * 1000)
            return res

        # 2. advance the paper record against the newest completed price action
        fast = min(snap.series, key=tf_seconds)
        recent = snap.tf(fast).bars[-3:]
        if recent:
            self.journal.track(price=snap.price, high=max(b.h for b in recent),
                               low=min(b.l for b in recent), ts=recent[-1].ts)

        # 3. build one context per mode
        self._contexts = {}
        for m in self.cfg.modes:
            mode = MODES[m]
            view = {tf: snap.tf(tf).closed for tf in mode.timeframes}
            ctx = build_context(mode, view, self.cfg.strategy, price=snap.price)
            if ctx is None:
                res.modes[m] = ModeView(mode=m, note="insufficient history for this mode")
                continue
            self._contexts[m] = ctx
            res.modes[m] = _mode_view(m, ctx)

        primary = self._contexts.get("INTRADAY") or next(iter(self._contexts.values()), None)
        if primary is not None:
            res.bias = primary.htf_bias.upper()
            res.regime = primary.ltf.regime.state

        # 4. re-validate everything already published (spec §11/§12)
        for rec in self.journal.open_records():
            ctx = self._contexts.get(rec.mode)
            if ctx is None:
                continue
            stub = _record_to_setup(rec)
            verdict = revalidate(stub, ctx, self.cfg.strategy, snap.price,
                                 rec.high_since, rec.low_since)
            if not verdict.valid:
                self.journal.invalidate(rec.id, verdict.reason)
                res.invalidated.append((rec, verdict.reason))

        # 5. risk + news gates
        res.guard = self._guard()
        res.news = news_check(self.cfg.path("news.json"), self.cfg.risk.news_blackout_minutes) \
            if self.cfg.risk.news_filter else None

        # 6. detect, grade, price the probability
        for m, ctx in self._contexts.items():
            for s in detect(ctx, snap.status.quality, f"{snap.status.source}:{snap.status.symbol}"):
                grade(s, self.cfg.strategy)
                apply_probability(s, self.stats, self.cfg.min_probability_sample)
                apply_history_veto(s, self.cfg.min_probability_sample, self.cfg.history_veto_pf)
                if s.status == "VALID" and ctx.session.name not in self.cfg.risk.allowed_sessions:
                    s.status, s.grade = "INVALID", "INVALID"
                    s.invalid_reason = f"{ctx.session.name} is outside the configured trading sessions"
                if s.status == "VALID" and res.news is not None and res.news.blocked:
                    s.status, s.grade = "INVALID", "INVALID"
                    s.invalid_reason = f"news blackout — {res.news.reason}"
                if s.status == "VALID" and GRADE_RANK[s.grade] < GRADE_RANK[self.cfg.min_publish_grade]:
                    s.status, s.invalid_reason = "INVALID", (
                        f"grade {s.grade} is below the configured publish minimum "
                        f"of {self.cfg.min_publish_grade}")
                (res.setups if s.status == "VALID" else res.rejected).append(s)

        res.setups.sort(key=lambda s: (-GRADE_RANK[s.grade], -s.score))
        res.rejected.sort(key=lambda s: -s.score)

        # 7. publish to the journal, unless the risk gate says stand down
        for s in res.setups:
            if res.guard.blocked:
                res.notes.append(f"setup {s.id} shown but NOT recorded — {res.guard.reasons[0]}")
                continue
            rec, is_new = self.journal.record(s)
            if is_new:
                res.guard.setups_today += 1
                res.guard.open_trades = len(self.journal.open_records())
                res.guard.evaluate()          # the ceiling binds inside a scan too
                res.notes.append(f"new setup recorded: {s.grade} {s.direction} {s.mode} [{s.id}]")

        if not res.setups:
            res.notes.append("NO VALID SETUP — conditions do not meet the minimum confluence "
                             "requirements. Quality over quantity (spec §10).")
        self.journal.flush()
        res.active = self.journal.open_records()
        res.scan_ms = int((time.time() - t0) * 1000)
        return res


def _mode_view(m: str, ctx: Context) -> ModeView:
    ltf, htf = ctx.ltf, ctx.htf
    return ModeView(
        mode=m, htf_bias=ctx.htf_bias.upper(), htf_trend=htf.structure.trend.upper(),
        mtf_trend=ctx.mtf.structure.trend.upper(), ltf_trend=ltf.structure.trend.upper(),
        regime=ltf.regime.state, volatility=ltf.regime.volatility,
        pd_zone=htf.pd.zone, pd_position=round(htf.pd.position, 3),
        range_high=round(htf.pd.high, 2), range_low=round(htf.pd.low, 2),
        equilibrium=round(htf.pd.equilibrium, 2),
        unswept_pools=sum(1 for p in ltf.pools if not p.swept),
        open_fvgs=sum(1 for g in ltf.fvgs if not g.mitigated),
        fresh_obs=sum(1 for o in ltf.obs if not o.mitigated))


def _record_to_setup(rec: Record) -> Setup:
    """Rehydrate just enough of a Setup for the invalidation checks."""
    s = Setup(id=rec.id, signal_ts=rec.signal_ts, mode=rec.mode, pattern=rec.pattern,
              direction=rec.direction, entry=rec.entry, entry_low=rec.entry_low,
              entry_high=rec.entry_high, entry_type=rec.entry_type,
              entry_state="ARMED" if rec.state == "ACTIVE" else "PENDING",
              sl=rec.sl, tp1=rec.tp1, tp2=rec.tp2, tp3=rec.tp3, grade=rec.grade)
    s.anchors = {"poi": {"kind": "FVG", "top": rec.entry_high, "bottom": rec.entry_low},
                 "sweep": {}, "mss": {"kind": "MSS"}}
    return s
