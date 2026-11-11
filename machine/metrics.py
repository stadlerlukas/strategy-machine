from __future__ import annotations

import math
import random
from statistics import NormalDist, mean, stdev, pstdev


def quantile(values, q):
    values = sorted(x for x in values if x is not None and math.isfinite(x))
    if not values:
        return None
    i = (len(values) - 1) * q
    a = int(i)
    return values[a] + (values[min(a + 1, len(values)-1)] - values[a]) * (i-a)


def sharpe(values, ppy=252, rf=0):
    if len(values) < 2 or stdev(values) < 1e-14:
        return None
    excess = mean(values) - ((1 + rf) ** (1/ppy) - 1)
    return excess / stdev(values) * math.sqrt(ppy)


def correlation(a, b):
    if len(a) != len(b) or len(a) < 3:
        return None
    ma, mb = mean(a), mean(b)
    va, vb = sum((x-ma)**2 for x in a), sum((x-mb)**2 for x in b)
    if va * vb < 1e-24:
        return None
    return max(-1.0, min(1.0, sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(va*vb)))


def bootstrap_sharpe(values, ppy, rf, draws=160, block=5):
    if len(values) < 20:
        return None
    rng, scores = random.Random(93217), []
    n = len(values)
    for _ in range(draws):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start+j) % n] for j in range(block))
        scores.append(sharpe(sample[:n], ppy, rf))
    return [quantile(scores, .025), quantile(scores, .975)]


def summarize(daily, ppy=252, rf=0, initial_nav=100000):
    net = [r["net_return"] for r in daily]
    gross = [r["gross_return"] for r in daily]
    peak, dd = initial_nav, 0.0
    for r in daily:
        peak = max(peak, r["nav"])
        dd = max(dd, 1-r["nav"]/peak)
    n = len(daily)
    turn = sum(r["turnover"] for r in daily)
    pnl = sum(r["gross_return"] - r["financing_return"] for r in daily)
    final = daily[-1]["nav"] if daily else initial_nav
    benchmark = [r["benchmark_return"] for r in daily]
    cov = correlation(net, benchmark)
    beta = cov * stdev(net)/stdev(benchmark) if cov is not None and stdev(benchmark)>1e-14 else None
    rfbar = (1+rf)**(1/ppy)-1
    alpha = (mean(net)-rfbar-beta*(mean(benchmark)-rfbar))*ppy if beta is not None else None
    return {
        "observations": n, "net_sharpe": sharpe(net, ppy, rf), "gross_sharpe": sharpe(gross, ppy, rf),
        "net_return": final/initial_nav-1,
        "annual_return": (final/initial_nav)**(ppy/n)-1 if n and final>0 else None,
        "annual_volatility": stdev(net)*math.sqrt(ppy) if n>1 else None,
        "max_drawdown": dd, "turnover": turn*ppy/n if n else None,
        "break_even_cost_bps": pnl/turn*10000 if turn else None,
        "transaction_cost": sum(r["transaction_cost"] for r in daily),
        "financing_cost": sum(r["financing"] for r in daily),
        "trade_count": sum(r["trades"] for r in daily),
        "trades_per_session": sum(r["trades"] for r in daily)/n if n else None,
        "beta_to_equal_weight_universe": beta,
        "annual_arithmetic_residual": alpha,
        "sharpe_95pct_block_bootstrap": bootstrap_sharpe(net, ppy, rf),
        "conventions": "Sharpe uses portfolio returns and configured risk-free benchmark. Gross is same-path before fees. Turnover sums absolute notional/NAV (not halved). Break-even is a fixed-path estimate after financing, not a rerun. Benchmark is equal-weight universe, not a factor model. Bootstrap is descriptive and not a guarantee."
    }


def deflated_sharpe(returns, trial_sharpes, trial_count, ppy=252, rf=0):
    """Bailey/Lopez de Prado DSR; probability, not an annualized Sharpe.

Trial Sharpe dispersion must be estimated from comparable experiments.
IID moment approximation does not correct serial correlation; report caveat.
"""
    if len(returns)<20 or len(trial_sharpes)<2 or trial_count<2 or pstdev(returns)<1e-14:
        return None
    dispersion = stdev(trial_sharpes)/math.sqrt(ppy)
    if dispersion < 1e-14:
        return None
    normal = NormalDist()
    gamma = .5772156649015329
    threshold = dispersion*((1-gamma)*normal.inv_cdf(1-1/trial_count)+gamma*normal.inv_cdf(1-1/(trial_count*math.e)))
    mu, sd = mean(returns), pstdev(returns)
    skew = mean(((x-mu)/sd)**3 for x in returns)
    kurt = mean(((x-mu)/sd)**4 for x in returns)
    sr = sharpe(returns, ppy, rf)/math.sqrt(ppy)
    variance = 1-skew*sr+(kurt-1)/4*sr*sr
    if variance <= 0:
        return None
    return normal.cdf((sr-threshold)*math.sqrt(len(returns)-1)/math.sqrt(variance))


def effective_trials(series):
    """Participation-ratio heuristic from correlations; not a known true N."""
    n = len(series)
    if not n:
        return None
    squared = float(n)
    for i in range(n):
        for j in range(i):
            c = correlation(series[i], series[j])
            # Unknown dependence treated as independent, not silently identical.
            squared += 2*(c or 0)**2
    return n*n/squared
