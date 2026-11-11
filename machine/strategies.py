"""Strategies receive only completed sessions; target weights are signed NAV fractions.

Custom plugin: {"kind":"python", "path":"/path/plugin.py", "sha256":"...", "params":{...}}
Plugin exposes targets(history, params) -> dict[symbol, weight].
Plugins are trusted Python code, not sandboxed. Never run unreviewed model-generated code.
"""
from __future__ import annotations

import importlib.util
from statistics import mean, pstdev

from .common import require, number, file_hash


def targets(history, strategy, universe):
    kind, p = strategy["kind"], strategy["params"]
    if kind == "expression":
        from .expressions import evaluate
        result={s:evaluate(strategy["expression"],history,p,s,universe) for s in universe}
    elif kind == "python":
        import hashlib
        import types
        from pathlib import Path
        source=strategy.get("source") or Path(strategy["path"]).read_text(encoding="utf-8")
        require(hashlib.sha256(source.encode()).hexdigest()==strategy["sha256"],"Strategy plugin hash changed")
        module=types.ModuleType("trusted_strategy")
        exec(compile(source,"<reviewed-strategy>","exec"),module.__dict__)
        result = module.targets(history, p)
    elif kind == "constant":
        result = {s: p.get("weight", 0) for s in universe}
    elif kind in ("momentum", "mean_reversion"):
        lookback = p["lookback"]
        require(isinstance(lookback, int) and lookback >= 2, "lookback must be an integer >= 2")
        number(p["allocation"], "allocation", 0, 1)
        result = {s: 0.0 for s in universe}
        if len(history) >= lookback:
            for s in universe:
                series = [frame[s]["close"] for _, frame in history[-lookback:]]
                # Built-ins reset after corporate actions instead of treating a split as alpha.
                if any(f[s]["split"] != 1 or f[s]["status"] != "active" for _, f in history[-lookback:]):
                    continue
                if kind == "momentum":
                    score = series[-1] / series[0] - 1
                    direction = 1 if score > p.get("threshold", 0) else 0
                else:
                    sd = pstdev(series)
                    z = (series[-1] - mean(series)) / sd if sd else 0
                    direction = 1 if z < -p.get("entry_z", 1) else (-1 if z > p.get("entry_z", 1) else 0)
                result[s] = direction * p["allocation"] / len(universe)
    else:
        raise ValueError(f"Unknown strategy kind: {kind}")
    require(isinstance(result, dict) and set(result) <= set(universe), "Strategy returned unknown instruments")
    for k, v in result.items():
        number(v, f"target {k}")
    return {s: float(result.get(s, 0)) for s in universe}
