"""Daily unadjusted-price, cash/position accounting; no broker order transport."""
from __future__ import annotations

import math
from copy import deepcopy
from datetime import date
from statistics import stdev

from .common import require
from .config import validate_config, validate_policy
from .data import validate_rows, frames_from_rows
from .strategies import targets
from .risk import check_order, breaches, correlated_groups
from .metrics import summarize


def simulate(config, rows, policy=None, initial_state=None, allow_trades=True):
    validate_config(config)
    if policy:
        validate_policy(policy)
    universe=config["universe"]
    validate_rows(rows,universe)
    frames=frames_from_rows(rows)
    state=deepcopy(initial_state or {})
    cash=state.get("cash",config["initial_nav"])
    prev_nav=state.get("prev_nav",config["initial_nav"])
    peak=state.get("peak",config["initial_nav"])
    units=state.get("units",{s:0.0 for s in universe})
    daily,orders,events,history=state.get("daily",[]),state.get("orders",[]),state.get("events",[]),state.get("history",[])
    dead=set(state.get("dead",[]))
    prev_close=state.get("prev_close",{})
    for day,frame in frames:
        i=len(history)
        require(not history or day>history[-1][0],"New observations must follow the last committed session")
        starting_units=dict(units)
        transaction=financing=turnover=0.0
        trades=0
        by_symbol={s:0.0 for s in universe}
        days=(date.fromisoformat(day)-date.fromisoformat(history[-1][0])).days if i else 0
        # Charge held notional over calendar time, including weekends, with documented annual assumptions.
        for s in universe:
            cost=config["costs"][s]
            q=units[s]
            if q and days:
                rate=cost["long_financing_annual"] if q>0 else cost["short_financing_annual"]+cost["borrow_annual"]
                fee=abs(q*prev_close[s])*rate*days/365
                cash-=fee
                financing+=fee
            bar=frame[s]
            require(s not in dead or bar["status"]=="delisted","A terminated instrument cannot reactivate between shadow updates")
            units[s]*=bar["split"]
            dividend=units[s]*bar["dividend"]
            cash+=dividend
            if i:
                by_symbol[s]=units[s]*bar["close"]-starting_units[s]*prev_close[s]+dividend
            if bar["status"]=="delisted" and s not in dead:
                cash+=units[s]*bar["settlement"]
                events.append({"date":day,"kind":"delisting_settlement","symbol":s,"units":units[s],"price":bar["settlement"]})
                units[s]=0
                dead.add(s)
            if bar["split"]!=1:
                events.append({"date":day,"kind":"split","symbol":s,"ratio":bar["split"]})
        nav_open=cash+sum(units[s]*frame[s]["open"] for s in universe)
        require(nav_open>0,"Account insolvent at open; run stopped and logged")
        dd=max(0,1-nav_open/peak)
        returns=[r["net_return"] for r in daily[-30:]]
        vol=stdev(returns)*math.sqrt(config["periods_per_year"]) if len(returns)>=20 else None
        groups,_=correlated_groups(history,universe,policy["correlation_threshold"]) if policy else ([],"")
        correlation_ready=len(history)>=31 and all(f[t]["status"]=="active" and f[t]["split"]==1 for _,f in history[-31:] for t in universe)
        if allow_trades and i>0 and (i-1)%config["holding"]["rebalance_every"]==0:
            # Only history through previous close is passed into strategy code.
            weights=targets(deepcopy(history),config["strategy"],universe)
            desired={s:(weights[s]*nav_open/frame[s]["open"] if frame[s]["open"]>0 else 0) for s in universe}
            # Reductions/sales first reduce transient gross exposure.
            ordering=sorted(universe,key=lambda s:(abs(desired[s])>=abs(units[s]),desired[s]-units[s],s))
            for s in ordering:
                bar,cost=frame[s],config["costs"][s]
                delta=desired[s]-units[s]
                if abs(delta*bar["open"])<1e-8:
                    continue
                order={"date":day,"symbol":s,"units":delta,"reference_price":bar["open"],"target_weight":weights[s]}
                if bar["status"]!="active" or s in dead:
                    orders.append({**order,"status":"blocked","rules":["market_"+bar["status"]]})
                    continue
                notional=abs(delta*bar["open"])
                fee=notional*(cost["spread_bps"]/2+cost["commission_bps"]+cost["slippage_bps"])/10000+cost["fixed_fee"]
                equity=cash+sum(units[t]*frame[t]["open"] for t in universe)
                require(equity-fee>0,"Fees exhaust account equity")
                before={t:units[t]*frame[t]["open"]/equity for t in universe}
                after={t:units[t]*frame[t]["open"]/(equity-fee) for t in universe}
                after[s]=desired[s]*bar["open"]/(equity-fee)
                decision=check_order(before,after,policy,drawdown=dd,volatility=vol,groups=groups,
                    statistics_available=vol is not None and correlation_ready,
                    turnover=turnover+notional/prev_nav,order_value=notional,shortable=cost["shortable"],symbol=s,
                    quantity_reduction=abs(desired[s])<=abs(units[s])+1e-12 and desired[s]*units[s]>=0) if policy else {"allowed":True,"rules":[]}
                if desired[s]<min(units[s],0) and not cost["shortable"]:
                    decision={"allowed":False,"rules":["short_unavailable"]}
                require(desired[s]>=0 or cost["instrument_type"]=="cfd","Short positions require an explicit CFD cost model")
                require(sum(abs(w) for w in weights.values())<=1 or cost["instrument_type"]=="cfd","Leveraged targets require an explicit CFD cost model")
                if not decision["allowed"]:
                    orders.append({**order,"status":"blocked","rules":decision["rules"]})
                    continue
                cash-=delta*bar["open"]+fee
                units[s]+=delta
                by_symbol[s]+=delta*(bar["close"]-bar["open"])
                turnover+=notional/prev_nav
                transaction+=fee
                trades+=1
                orders.append({**order,"status":"filled_shadow","notional":notional,"cost":fee,"rules":[]})
        nav=cash+sum(units[s]*frame[s]["close"] for s in universe)
        require(nav>0,"Account insolvent at close; run stopped and logged")
        net_return=nav/prev_nav-1
        gross_return=(nav-prev_nav+transaction+financing)/prev_nav
        # Independent dollar attribution reconciles accounting before any reporting.
        require(abs(sum(by_symbol.values())-(nav-prev_nav+transaction+financing))<max(1e-6,abs(nav)*1e-9),"Accounting attribution does not reconcile")
        benchmark=[]
        if i:
            for s in universe:
                if prev_close[s]>0 and s not in {x for x in dead if history[-1][1][x]["status"]=="delisted"}:
                    benchmark.append((frame[s]["close"]*frame[s]["split"]+frame[s]["dividend"]*frame[s]["split"])/prev_close[s]-1)
        peak=max(peak,nav)
        current_weights={s:units[s]*frame[s]["close"]/nav for s in universe}
        close_returns=(returns+[net_return])[-30:]
        close_vol=stdev(close_returns)*math.sqrt(config["periods_per_year"]) if len(close_returns)>=20 else None
        row={"date":day,"nav":nav,"cash":cash,"units":dict(units),"weights":current_weights,
             "net_return":net_return,"gross_return":gross_return,"turnover":turnover,
             "transaction_cost":transaction,"financing":financing,"financing_return":financing/prev_nav,
             "trades":trades,"drawdown":1-nav/peak,"instrument_gross_pnl":by_symbol,
             "benchmark_return":sum(benchmark)/len(benchmark) if benchmark else 0,
             "risk_breaches":breaches(current_weights,policy,1-nav/peak,close_vol,groups) if policy else [],
             "risk_data_gaps":(["rolling_volatility_warmup"] if policy and close_vol is None else [])+(["correlation_warmup_or_missing"] if policy and not correlation_ready else [])}
        daily.append(row)
        prev_nav=nav
        prev_close={s:frame[s]["close"] for s in universe}
        history.append((day,frame))
    return {"metrics":summarize(daily,config["periods_per_year"],config["risk_free_annual"],config["initial_nav"]),
            "daily":daily,"orders":orders,"events":events,"provenance":config["provenance"],
            "engine":"daily-next-open-v1","closed_at_end":False,
            "state":{"cash":cash,"prev_nav":prev_nav,"peak":peak,"units":units,"daily":daily,"orders":orders,"events":events,"history":history,"dead":sorted(dead),"prev_close":prev_close},
            "limitations":["End positions are marked, not forcibly liquidated.","No margin liquidation, order-book liquidity, partial fills, FX conversion, or broker ticket semantics.","Explicit shortability and assumed fees are inputs, not verified broker availability."]}
