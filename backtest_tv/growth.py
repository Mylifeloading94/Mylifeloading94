"""What does it take to grow $500->$3,000 and $1,000->$10,000 with a measured edge?

Bootstrap the strategy's own per-trade R results (honest backtest), compound at a fixed % risk,
and report the odds of hitting the target vs. suffering a large drawdown, over several horizons.
"""
import json, random, statistics as st, sys


def sim(rs, trades_per_day, risk, start, target, days, sims=4000, ruin=0.5, seed=11):
    rnd = random.Random(seed); hit = ruined = 0; ends = []; dd_big = 0
    n_tr = int(round(trades_per_day * days))
    for _ in range(sims):
        eq = start; pk = start; mdd = 0; reached = False
        for _ in range(n_tr):
            eq *= 1 + risk * rnd.choice(rs)
            pk = max(pk, eq); mdd = max(mdd, 1 - eq / pk)
            if eq >= target and not reached: reached = True
            if eq <= start * (1 - ruin): break
        hit += reached; ruined += eq <= start * (1 - ruin); ends.append(eq); dd_big += mdd >= 0.3
    ends.sort()
    return dict(p_target=hit / sims, p_ruin=ruined / sims, p_dd30=dd_big / sims,
                median_end=ends[len(ends) // 2], p10_end=ends[len(ends) // 10], p90_end=ends[9 * len(ends) // 10])


def report(rs, tpd, label):
    print(f"\n### {label}: {len(rs)} trades, avg {st.mean(rs):+.3f}R/trade, {tpd:.2f} trades/day")
    for start, target in ((500, 3000), (1000, 10000)):
        print(f"  ${start} -> ${target}")
        for days in (90, 180, 365):
            for risk in (0.01, 0.02, 0.03, 0.05):
                r = sim(rs, tpd, risk, start, target, days)
                print(f"    {days:3d}d @{risk*100:.0f}%: P(target)={r['p_target']:.0%}  P(-50%)={r['p_ruin']:.0%}  "
                      f"P(DD>=30%)={r['p_dd30']:.0%}  median end=${r['median_end']:,.0f}  (10th ${r['p10_end']:,.0f} / 90th ${r['p90_end']:,.0f})")


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    report(d["rs"], d["tpd"], d.get("label", "strategy"))
