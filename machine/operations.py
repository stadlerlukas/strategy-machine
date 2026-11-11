from __future__ import annotations

import uuid
from collections import defaultdict

from .common import require, digest, now
from .research import project, base_config
from .engine import simulate
from .data import validate_rows, frames_from_rows
from .risk import correlated_groups, breaches
from .metrics import summarize


def committed(store):
    e=store.latest("shadow_committed","book")
    return (store.get(e["payload"]["result"]),e["hash"]) if e else (None,None)


def pending(store):
    return [e for e in store.events("shadow_proposed") if not store.latest("shadow_decided",e["entity"])]


def shadow_propose(store,rows):
    require(not store.events("forward_open_proposed"),"Use a separate case for replay; forward observations cannot be mixed with replay")
    require(store.latest("spec_signed","main"),"Sign the strategy specification before shadow operation")
    require(store.latest("risk_plan_committed","main"),"Commit a dated risk plan before operation")
    require(not pending(store),"Decide the pending proposal before advancing")
    require(all(store.latest("shadow_commit_for",e["entity"]) for e in store.events("shadow_decided")),"Recover the interrupted shadow commit before advancing")
    require(not store.latest("kill_switch","book") or not store.latest("kill_switch","book")["payload"]["active"],"Kill switch active; proposals are disabled")
    p=project(store)
    spec=store.get(store.latest("spec_signed","main")["payload"]["spec"])
    config=store.get(spec["config_hash"])
    policy=store.get(p["policy"])
    validate_rows(rows,config["universe"])
    old,head=committed(store)
    last=old["daily"][-1]["date"] if old else None
    # Only one new session enters a proposal. Larger files can be appended daily.
    selected=next((f for f in frames_from_rows(rows) if last is None or f[0]>last),None)
    require(selected,"No new session available")
    new_rows=[selected[1][s] for s in sorted(config["universe"])]
    state=old["state"] if old else None
    planned=simulate(config,new_rows,policy,state)
    abstain=simulate(config,new_rows,policy,state,allow_trades=False)
    old_orders=len(old["orders"]) if old else 0
    plan_orders=planned["orders"][old_orders:]
    proposal={"date":selected[0],"prior_head":head,"policy_hash":p["policy"],"config_hash":spec["config_hash"],"rows":store.put(new_rows),"planned":store.put(planned),"abstain":store.put(abstain),"orders":plan_orders,
              "expected_cost":sum(o.get("cost",0) for o in plan_orders),"mode":"shadow","provenance":config["provenance"],"created_at":now(),
              "interpretation":"Retrospective daily-bar shadow proposal; close is used for end-session accounting, never signal generation. Not a market-order instruction or fill guarantee."}
    key=uuid.uuid4().hex[:12]
    latest_proposal=store.events("shadow_proposed")
    store.append("shadow_proposed",key,{"proposal":store.put(proposal),"date":selected[0]},claim="proposal-for:"+(head or "initial"))
    return {"proposal_id":key,**proposal}


def shadow_decide(store,proposal_id,approve,actor,reason,synthetic=False):
    require(actor.strip() and reason.strip(),"Record who decided and why")
    e=store.latest("shadow_proposed",proposal_id)
    require(e,"Unknown proposal")
    require(not store.latest("shadow_decided",proposal_id),"Proposal already decided")
    proposal=store.get(e["payload"]["proposal"])
    require(synthetic==(proposal["provenance"]=="synthetic"),"Synthetic approvals must be clearly labelled")
    _,head=committed(store)
    require(proposal["prior_head"]==head,"Stale proposal; account state changed")
    require(project(store)["policy"]==proposal["policy_hash"],"Risk policy changed after proposal")
    kill=store.latest("kill_switch","book")
    require(not approve or not kill or not kill["payload"]["active"],"Kill switch active; cannot approve")
    # Claim is atomic: repeated/concurrent approval cannot apply the same proposal twice.
    chosen=proposal["planned"] if approve else proposal["abstain"]
    store.append("shadow_decided",proposal_id,{"approved":approve,"by":actor,"reason":reason,"synthetic":synthetic,"result":chosen,"prior_head":head},claim="shadow-decision:"+proposal_id,
                 expected=[("shadow_committed","book",head),("kill_switch","book",kill["hash"] if kill else None)])
    return recover_shadow_commit(store,proposal_id)


def recover_shadow_commit(store,proposal_id):
    """Recover an interruption after the decision but before portfolio commit."""
    decision=store.latest("shadow_decided",proposal_id)
    require(decision,"No durable decision to recover")
    prior=store.latest("shadow_commit_for",proposal_id)
    if prior:
        return store.get(decision["payload"]["result"])
    p=decision["payload"]
    existing=store.events("shadow_committed","book")
    matching=[e for e in existing if e["payload"]["proposal_id"]==proposal_id]
    if not matching:
        _,head=committed(store)
        require(head==p["prior_head"],"Cannot recover against a different portfolio head")
        store.append("shadow_committed","book",{"proposal_id":proposal_id,"decision_hash":decision["hash"],"result":p["result"]},claim="shadow-commit:"+proposal_id,expected=[("shadow_committed","book",p["prior_head"])])
    store.append("shadow_commit_for",proposal_id,{"result":p["result"]},claim="shadow-marker:"+proposal_id)
    return store.get(p["result"])


def reconcile(store,observed,tolerance=1e-8):
    from .common import number
    number(tolerance,"reconciliation tolerance",0)
    result,head=committed(store)
    require(result,"No shadow account to reconcile")
    expected=result["daily"][-1]
    require(observed.get("date")==expected["date"],"Snapshot and book dates differ")
    require(observed.get("provenance") in ("synthetic_fixture","broker_snapshot","manual_snapshot"),"Label reconciliation snapshot provenance")
    require(isinstance(observed.get("units"),dict),"Snapshot must explicitly include units; absent positions are not inferred")
    for symbol,value in observed["units"].items():
        number(value,"units."+symbol)
    number(observed.get("cash"),"snapshot cash")
    differences=[]
    for s in set(expected["units"])|set(observed.get("units",{})):
        a,b=expected["units"].get(s,0),observed.get("units",{}).get(s,0)
        if abs(a-b)>tolerance:
            differences.append({"field":"units."+s,"expected":a,"observed":b})
    require("cash" in observed,"Snapshot missing cash")
    if abs(expected["cash"]-observed["cash"])>tolerance:
        differences.append({"field":"cash","expected":expected["cash"],"observed":observed["cash"]})
    out={"date":expected["date"],"matched":not differences,"differences":differences,"provenance":observed["provenance"],"book_head":head,"snapshot":store.put(observed)}
    store.append("reconciliation","book",out)
    if differences:
        store.append("incident",uuid.uuid4().hex[:12],{"kind":"reconciliation_mismatch",**out})
    return out


def review_history(store,result,source):
    require(store.latest("risk_plan_committed","main"),"A dated risk plan must be committed before reviewing history")
    policy=store.get(project(store)["policy"])
    config=base_config(store)
    daily=result.get("daily",[])
    require(daily,"History is empty; missing data is not inferred")
    # Recalculate metrics rather than trusting an imported summary.
    needed={"date","nav","net_return","gross_return","turnover","transaction_cost","financing","financing_return","trades","benchmark_return","weights","units"}
    for row in daily:
        require(needed<=row.keys(),f"History row missing {sorted(needed-row.keys())}")
    from .history import validate_history
    validate_history(daily,config["initial_nav"])
    m=summarize(daily,config["periods_per_year"],config["risk_free_annual"],config["initial_nav"])
    findings=[]
    facts={f"metrics.{k}":v for k,v in m.items() if k!="conventions"}
    for kpi in policy["kpis"]:
        value=m.get(kpi["metric"])
        lower,upper=kpi["range"]
        state="missing" if value is None else ("outside" if value<lower or value>upper else "within")
        findings.append({"metric":kpi["metric"],"value":value,"range":[lower,upper],"status":state,"why":kpi["why"]})
    last=daily[-1]
    groups,note=correlated_groups(result.get("state",{}).get("history",[]),config["universe"],policy["correlation_threshold"])
    from statistics import stdev
    recent=[r["net_return"] for r in daily[-30:]]
    rolling_vol=stdev(recent)*config["periods_per_year"]**.5 if len(recent)>=20 else None
    peak=max([config["initial_nav"]]+[r["nav"] for r in daily])
    rules=breaches(last["weights"],policy,1-last["nav"]/peak,rolling_vol,groups)
    out={"source":source,"metrics":m,"facts":facts,"findings":findings,"current_rule_breaches":rules,"shared_driver_groups":policy["groups"],"observed_correlated_groups":groups,"correlation_note":note,"missing":["eToro official risk score is not computed or inferred", "Historical realised correlations do not identify all common economic drivers"],"mode":"deterministic review; no LLM call","decision":"awaiting human keep/adjust/pause/manual decision"}
    ref=store.put(out)
    store.append("history_reviewed",uuid.uuid4().hex[:12],{"review":ref,"source":source,"policy":project(store)["policy"]})
    return out


def record_decision(store,action,reason,actor):
    require(action in ("keep","adjust","pause","manual"),"Choose keep, adjust, pause or manual")
    require(reason.strip() and actor.strip(),"Provide a reason and decision-maker")
    reviews=store.events("history_reviewed")
    require(reviews,"Review evidence before deciding")
    if action in ("pause","manual"):
        store.append("kill_switch","book",{"active":True,"by":actor,"reason":reason,"cause":"owner_decision_"+action})
    return store.append("human_decision",reviews[-1]["entity"],{"action":action,"reason":reason,"by":actor,"review":reviews[-1]["payload"]["review"]})
