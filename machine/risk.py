from __future__ import annotations

from .common import number, require
from .metrics import correlation


def correlated_groups(history, universe, threshold, lookback=30):
    if len(history) < lookback+1:
        return [], "insufficient history for correlation check"
    returns = {}
    for s in universe:
        frames = history[-lookback-1:]
        # Avoid spurious split/delisting correlations. Explicit shared groups still apply.
        if any(f[s]["split"] != 1 or f[s]["status"] != "active" for _, f in frames):
            continue
        prices = [f[s]["close"] for _,f in frames]
        returns[s] = [b/a-1 for a,b in zip(prices,prices[1:])]
    adjacency = {s:{s} for s in returns}
    for a in returns:
        for b in returns:
            c = correlation(returns[a],returns[b])
            if a != b and c is not None and abs(c)>=threshold:
                adjacency[a].add(b)
    groups, visited = [], set()
    for a in adjacency:
        if a in visited:
            continue
        group, pending = set(), [a]
        while pending:
            s = pending.pop()
            if s not in group:
                group.add(s)
                pending.extend(adjacency[s]-group)
        visited |= group
        if len(group)>1:
            groups.append(sorted(group))
    return groups, "correlations are descriptive; shared economic drivers need human tags"


def breaches(weights, policy, drawdown=0, volatility=None, groups=()):
    for s,w in weights.items():
        number(w, s)
    out=[]
    gross, net = sum(abs(w) for w in weights.values()), abs(sum(weights.values()))
    if gross>policy["max_gross"]+1e-10:
        out.append("gross_exposure")
    if net>policy["max_abs_net"]+1e-10:
        out.append("net_exposure")
    if any(abs(w)>policy["max_position"]+1e-10 for w in weights.values()):
        out.append("position_concentration")
    for name, symbols in list(policy["groups"].items())+[("correlation_"+str(i),g) for i,g in enumerate(groups)]:
        if sum(abs(weights.get(s,0)) for s in symbols)>policy["max_group"]+1e-10:
            out.append("group:"+name)
    if drawdown>policy["max_drawdown"]:
        out.append("drawdown")
    if volatility is not None and volatility>policy["max_volatility"]:
        out.append("volatility")
    return out


def check_order(current, proposed, policy, *, drawdown=0, volatility=None, groups=(), turnover=0, order_value=0, valid_data=True, shortable=True, symbol="", quantity_reduction=None, statistics_available=True):
    if not valid_data:
        return {"allowed":False,"rules":["invalid_or_missing_data"]}
    reducing = quantity_reduction if quantity_reduction is not None else all(abs(proposed.get(s,0))<=abs(current.get(s,0))+1e-10 and proposed.get(s,0)*current.get(s,0)>=-1e-12 for s in set(current)|set(proposed))
    rules = breaches(proposed,policy,drawdown,volatility,groups)
    if reducing:
        # Exposure reduction remains possible while limits bind, except crossing sign.
        rules=[]
    if not statistics_available and policy["warmup_mode"]=="block_increases" and not reducing:
        rules.append("statistical_risk_history_unavailable")
    if not shortable and proposed.get(symbol,0)<min(current.get(symbol,0),0)-1e-10:
        rules.append("short_unavailable")
    if turnover>policy["max_turnover_per_day"]+1e-10 and not reducing:
        rules.append("turnover_budget")
    if abs(order_value)<policy["min_order_value"] and abs(proposed.get(symbol,0))>1e-10:
        rules.append("minimum_order_value")
    return {"allowed":not rules,"rules":rules,"reducing":reducing}


def red_team(policy):
    cases = [
        ("oversized position",{}, {"TEST":policy["max_position"]+1}, {}),
        ("drawdown blocks new exposure",{}, {"TEST":.01}, {"drawdown":policy["max_drawdown"]+.01}),
        ("missing data",{}, {"TEST":.01}, {"valid_data":False}),
        ("short unavailable",{}, {"TEST":-.01}, {"shortable":False}),
        ("reduction during drawdown",{"TEST":.1},{"TEST":0},{"drawdown":policy["max_drawdown"]+.01}),
    ]
    rows=[]
    for name,current,target,kwargs in cases:
        result=check_order(current,target,policy,symbol="TEST",order_value=10000,**kwargs)
        expected = name=="reduction during drawdown"
        require(result["allowed"]==expected,f"Risk red-team failed: {name}")
        rows.append({"scenario":name,"expected_allowed":expected,**result})
    return {"provenance":"synthetic policy stress; not probabilities or financial validation","cases":rows,"passed":True}
