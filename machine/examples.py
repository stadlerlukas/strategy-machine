"""Deterministic synthetic fixtures. These are software tests, not investment ideas."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from pathlib import Path

from .common import write_json
from .data import save_csv


def example_config(kind="momentum"):
    params = {"lookback":12,"allocation":0.6,"threshold":0.005} if kind=="momentum" else {"lookback":12,"allocation":0.4,"entry_z":0.8}
    return {
        "name": "Synthetic trend demonstration" if kind=="momentum" else "Synthetic reversal demonstration",
        "hypothesis": "For software demonstration only: test whether recent price trends persist over the next daily session." if kind=="momentum" else "For software demonstration only: test whether deviations from a recent average reverse over the next daily session.",
        "universe":["ALPHA","BETA"],"strategy":{"kind":kind,"params":params},
        "holding":{"execution":"next_open","rebalance_every":1},
        "costs":{s:{"spread_bps":6.0,"commission_bps":2.0,"slippage_bps":1.0,"fixed_fee":0.0,
                      "long_financing_annual":0.02,"short_financing_annual":0.03,"borrow_annual":0.01,
                      "source":"Explicit synthetic fee assumption; not an eToro quote","as_of":"2025-01-01","instrument_type":"cfd","shortable":True} for s in ("ALPHA","BETA")},
        "periods_per_year":252,"risk_free_annual":0.02,"initial_nav":100000.0,"provenance":"synthetic","currency":"USD","price_adjustment":"unadjusted"
    }


def example_policy():
    return {"mode":"shadow","require_approval":True,"warmup_mode":"static_limits","max_gross":0.9,"max_abs_net":0.9,"max_position":0.45,
            "max_group":0.8,"max_drawdown":0.12,"max_turnover_per_day":1.5,"min_order_value":5.0,
            "max_volatility":0.25,"correlation_threshold":0.8,"groups":{"shared_demo_driver":["ALPHA","BETA"]},
            "kpis":[{"metric":"net_sharpe","range":[-1,3],"why":"Illustrative risk-adjusted performance range, not a promised outcome."},
                    {"metric":"max_drawdown","range":[0,0.12],"why":"Illustrative loss limit for the fixture."},
                    {"metric":"annual_volatility","range":[0,0.25],"why":"Illustrative volatility tolerance."},
                    {"metric":"turnover","range":[0,120],"why":"Monitor the trading activity that generates costs."}]}


def synthetic_rows(sessions=650, start="2021-01-04", seed=713):
    rng=random.Random(seed)
    day=date.fromisoformat(start)
    prices={"ALPHA":100.0,"BETA":85.0}
    rows=[]
    i=0
    while i<sessions:
        if day.weekday()<5:
            common=rng.gauss(0,0.005)
            for j,s in enumerate(sorted(prices)):
                opening=prices[s]*math.exp(rng.gauss(0,0.002))
                ret=0.0001+common+rng.gauss(0,0.007)+0.0025*math.sin(i/17+j)
                closing=opening*math.exp(ret)
                rows.append({"date":day.isoformat(),"symbol":s,"open":opening,"close":closing,
                             "status":"active","split":1.0,"dividend":0.0,"settlement":None})
                prices[s]=closing
            i+=1
        day+=timedelta(days=1)
    return rows


def create_examples(folder):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    rows=synthetic_rows()
    paths={}
    for name,a,b in (("training",0,380),("validation",380,520),("holdout",520,600),("shadow",600,650)):
        path=folder/f"{name}.csv"
        save_csv(path,rows[a*2:b*2])
        paths[name]=str(path.resolve())
    for kind in ("momentum","mean_reversion"):
        write_json(folder/f"{kind}.json",example_config(kind))
    write_json(folder/"risk-policy.json",example_policy())
    write_json(folder/"provenance.json",{"kind":"synthetic","seed":713,"purpose":"Software verification only","prices":"Invented daily bars; weekdays are not an exchange calendar","fees":"Invented per-instrument assumptions"})
    return paths
