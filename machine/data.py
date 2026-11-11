"""Strict long-format daily bars. Corporate actions use unadjusted prices.

Columns: date,symbol,open,close,status,split,dividend,settlement
status is active/halted/delisted; dividend is per post-split share.
Every observed session has a row for every symbol, including halted names.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .common import require, number


def load_csv(path, universe):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        needed = {"date", "symbol", "open", "close", "status", "split", "dividend", "settlement"}
        require(needed <= set(reader.fieldnames or []), f"CSV requires {sorted(needed)}")
        rows = []
        for r in reader:
            row = {k: r[k] for k in needed}
            for key in ("open", "close", "split", "dividend"):
                row[key] = float(row[key])
            row["settlement"] = float(row["settlement"]) if row["settlement"].strip() else None
            for key,value in r.items():
                if key.startswith("feature_"):
                    row[key]=float(value) if value.strip() else None
            rows.append(row)
    return validate_rows(rows, universe)


def validate_rows(rows, universe):
    require(rows, "Empty price panel")
    frames = {}
    last_key = None
    terminated = set()
    for r in rows:
        date.fromisoformat(r["date"])
        key = (r["date"], r["symbol"])
        require(last_key is None or key > last_key, "Rows must be sorted by date,symbol without duplicates")
        last_key = key
        require(r["symbol"] in universe, f"Unexpected symbol {r['symbol']}")
        require(r["status"] in ("active", "halted", "delisted"), "Unknown instrument status")
        for f in ("open", "close", "dividend"):
            number(r[f], f, 0)
        number(r["split"], "split", 1e-12)
        for f,v in r.items():
            if f.startswith("feature_") and v is not None:
                number(v,f)
        if r["status"] != "delisted":
            require(r["open"] > 0 and r["close"] > 0, "Nonpositive active/halted price")
        else:
            number(r["settlement"], "delisting settlement", 0)
            require(r["close"] == r["settlement"], "Delisted close must equal explicit cash settlement")
            terminated.add(r["symbol"])
        require(r["symbol"] not in terminated or r["status"] == "delisted", "A delisted instrument cannot silently reactivate")
        frames.setdefault(r["date"], {})[r["symbol"]] = r
    for d, frame in frames.items():
        require(set(frame) == set(universe), f"Incomplete session {d}; gaps must be explicit, never forward-filled")
    return rows


def frames_from_rows(rows):
    out = {}
    for r in rows:
        out.setdefault(r["date"], {})[r["symbol"]] = dict(r)
    return list(out.items())


def save_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        extras=sorted({k for r in rows for k in r if k.startswith("feature_")})
        writer = csv.DictWriter(f, fieldnames=["date", "symbol", "open", "close", "status", "split", "dividend", "settlement"]+extras)
        writer.writeheader()
        writer.writerows(rows)
