"""Read-only eToro transport. Raw responses require a validated normalization map.

No order URLs, write verbs, or guessed fee fallbacks exist in this adapter.
Real account access is opt-in via the CLI. Live credentials were not available
during development; transport is tested with fixtures, not a connected account.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .common import require, now
from .transport import open_authenticated
from datetime import date,datetime,timezone


class EToroReader:
    BASE="https://public-api.etoro.com/api/v1"

    def __init__(self,mode="demo",transport=None):
        require(mode in ("demo","real"),"Unknown eToro environment")
        self.mode=mode
        self.transport=transport

    def get(self,resource,params=None):
        paths={"portfolio":"/trading/info/"+("demo/" if self.mode=="demo" else "")+"portfolio",
               "history":"/trading/info/trade/"+("demo/" if self.mode=="demo" else "")+"history",
               "quotes":"/market-data/instruments/rates"}
        require(resource in paths,"Only documented read-only portfolio, history and quotes resources are enabled")
        params=dict(params or {})
        if resource=="history":
            require(set(params)<={"minDate","page","pageSize"} and "minDate" in params,"History requires minDate; only page and pageSize are optional")
            start=date.fromisoformat(params["minDate"])
            age=(datetime.now(timezone.utc).date()-start).days
            require(0<=age<=364,"History endpoint supports a recent period shorter than one year; use an exported statement for older history")
            for key in ("page","pageSize"):
                if key in params:
                    require(isinstance(params[key],int) and params[key]>=1,f"{key} must be a positive integer")
        app=os.getenv("ETORO_API_KEY")
        user=os.getenv("ETORO_USER_KEY")
        require(app and user,"Set ETORO_API_KEY and ETORO_USER_KEY; use an environment-specific read-only key")
        url=self.BASE+paths[resource]+("?"+urlencode(params,doseq=True) if params else "")
        for attempt in range(3):
            req=Request(url,headers={"x-api-key":app,"x-user-key":user,"x-request-id":str(uuid.uuid4()),"Accept":"application/json"},method="GET")
            try:
                if self.transport:
                    data=self.transport(req)
                else:
                    with open_authenticated(req,timeout=20) as f:
                        data=json.load(f)
                return {"fetched_at":now(),"environment":self.mode,"resource":resource,"source_url":url,"raw":data,"normalization":"not inferred; validate against account schema before using"}
            except HTTPError as e:
                if e.code not in (429,502,503,504) or attempt==2:
                    raise ValueError(f"eToro read failed with HTTP {e.code}; credentials and response bodies are not logged") from None
                delay=min(float(e.headers.get("Retry-After",2**attempt)),10)
                time.sleep(max(0,delay))


def extract_path(obj,path):
    for segment in path.split("."):
        require(isinstance(obj,dict) and segment in obj,f"Mapping path missing: {path}")
        obj=obj[segment]
    return obj


def normalize_snapshot(raw,mapping):
    """User-reviewed field mapping avoids silently guessing API wrappers and units."""
    from .common import number
    data=raw["raw"]
    cash=number(extract_path(data,mapping["cash"]),"cash")
    positions=extract_path(data,mapping["positions"])
    require(isinstance(positions,list),"Positions mapping must select an array")
    units={}
    for pos in positions:
        instrument=str(extract_path(pos,mapping["instrument_id"]))
        require(instrument in mapping["symbols"],f"Unmapped instrument {instrument}")
        symbol=mapping["symbols"][instrument]
        q=number(extract_path(pos,mapping["signed_units"]),"signed_units")
        require(mapping.get("units_are_signed") is True,"Explicitly verify signed unit semantics; invested/margin amounts are not units")
        units[symbol]=units.get(symbol,0)+q
    return {"date":mapping["as_of_date"],"cash":cash,"units":units,"provenance":"broker_snapshot","source_fetched_at":raw["fetched_at"]}
