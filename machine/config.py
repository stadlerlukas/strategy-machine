from __future__ import annotations

from .common import require, number

COST_FIELDS = ("spread_bps", "commission_bps", "slippage_bps", "fixed_fee", "long_financing_annual", "short_financing_annual", "borrow_annual")


def validate_config(c):
    required = {"name", "hypothesis", "universe", "strategy", "holding", "costs", "periods_per_year", "risk_free_annual", "initial_nav", "provenance", "currency", "price_adjustment"}
    require(required <= c.keys(), f"Config missing: {sorted(required-c.keys())}")
    require(isinstance(c["hypothesis"], str) and len(c["hypothesis"].strip()) >= 15, "Write a falsifiable hypothesis with economic reasoning")
    require(c["universe"] and len(set(c["universe"])) == len(c["universe"]), "Universe must be nonempty and unique")
    require(all(isinstance(s,str) and s.strip() for s in c["universe"]),"Instrument identifiers must be nonempty text")
    require(isinstance(c["currency"],str) and len(c["currency"])==3,"Declare the common three-letter valuation currency")
    require(c["price_adjustment"]=="unadjusted","Reference engine requires unadjusted prices with explicit corporate actions")
    require(c["holding"].get("execution") == "next_open", "Reference engine supports next_open execution")
    require(c["holding"].get("rebalance_every", 0) >= 1, "rebalance_every must be positive")
    require(isinstance(c["holding"]["rebalance_every"], int), "rebalance_every must be integral")
    require(c["strategy"].get("kind") and isinstance(c["strategy"].get("params"), dict), "strategy needs kind and params")
    require(c["provenance"] in ("synthetic", "historical", "forward"), "Label data provenance")
    number(c["initial_nav"], "initial_nav", 1)
    number(c["periods_per_year"], "periods_per_year", 1)
    number(c["risk_free_annual"], "risk_free_annual", -0.99)
    for s in c["universe"]:
        require(s in c["costs"], f"Missing fee model for {s}; no default is allowed")
        cost = c["costs"][s]
        for f in COST_FIELDS:
            require(f in cost, f"Missing fee: {s}.{f}")
            number(cost[f], f"{s}.{f}", 0)
        require(cost.get("source") and cost.get("as_of"), f"{s}: document fee source and as_of")
        require(cost.get("instrument_type") in ("cash", "cfd"), f"{s}: choose cash or cfd")
        require(isinstance(cost.get("shortable"), bool), f"{s}: short availability must be explicit")
    return c


def validate_policy(p):
    for key in ("max_gross", "max_abs_net", "max_position", "max_group", "max_drawdown", "max_turnover_per_day", "min_order_value", "max_volatility", "correlation_threshold"):
        require(key in p, f"Risk policy missing {key}")
        number(p[key], key, 0)
    number(p["max_drawdown"], "max_drawdown", 0, 1)
    number(p["correlation_threshold"], "correlation_threshold", 0, 1)
    require(isinstance(p.get("groups"), dict), "Provide explicit shared-driver groups (possibly empty)")
    require(p.get("mode") == "shadow", "Only shadow operation is enabled")
    require(p.get("require_approval") is True, "Shadow proposals require an explicit approval record")
    require(p.get("warmup_mode") in ("static_limits", "block_increases"), "Choose warmup_mode: static_limits or block_increases when statistical risk history is unavailable")
    require(p.get("kpis") and all(k.get("why") and k.get("metric") for k in p["kpis"]), "Each KPI needs metric and why")
    for k in p["kpis"]:
        require(isinstance(k.get("range"), list) and len(k["range"]) == 2, "KPI range needs two numbers")
        number(k["range"][0], "KPI lower")
        number(k["range"][1], "KPI upper")
        require(k["range"][0] <= k["range"][1], "KPI bounds reversed")
    return p


def validate_spec(s):
    fields = {"hypothesis", "universe", "signal", "holding", "costs", "expected", "kill", "trials", "signed"}
    require(fields <= s.keys(), f"Spec missing {fields-s.keys()}")
    for metric in ("net_sharpe", "turnover", "break_even_cost_bps"):
        v = s["expected"].get(metric)
        require(isinstance(v, list) and len(v) == 2, f"{metric} must be a range")
        for x in v:
            number(x, metric)
        require(v[0] <= v[1], "Expected bounds reversed")
    require(isinstance(s["kill"], list) and s["kill"], "Supply at least one explicit kill criterion")
    require("count" in s["trials"] and "effective_count" in s["trials"] and "deflated_sharpe" in s["trials"], "Trial provenance missing")
    return s
