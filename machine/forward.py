"""Forward daily shadow sessions with an open-time proposal and later close mark.

No network orders are sent. A genuine timestamped feed is supplied by an adapter
or imported snapshot. Session dates must match the actual UTC date on the host;
this intentionally excludes exchanges whose session dates need another adapter.
"""
from __future__ import annotations

import uuid
from datetime import datetime,timezone

from .common import require,digest,now,number
from .research import project
from .engine import simulate
from .data import validate_rows,frames_from_rows
from .operations import committed


def seed_history(store,rows,clock=None):
    require(store.latest("spec_signed","main"),"Sign the strategy before supplying signal history")
    require(not store.events("forward_open_proposed") and not store.events("shadow_proposed"),"Seed history before operation starts")
    spec=store.get(store.latest("spec_signed","main")["payload"]["spec"])
    config=store.get(spec["config_hash"])
    validate_rows(rows,config["universe"])
    current=clock or datetime.now(timezone.utc)
    require(rows[-1]["date"]<current.date().isoformat(),"Signal history must end before today's session")
    frames=frames_from_rows(rows)
    require(all(r["status"]=="active" for r in rows[-len(config["universe"]):]),"Terminated or halted universe needs an adapter before forward operation")
    state={"cash":config["initial_nav"],"prev_nav":config["initial_nav"],"peak":config["initial_nav"],"units":{s:0.0 for s in config["universe"]},"daily":[],"orders":[],"events":[],"history":frames,"dead":[],"prev_close":{s:frames[-1][1][s]["close"] for s in config["universe"]}}
    return store.append("forward_history_seeded","book",{"state":store.put(state),"last_date":rows[-1]["date"],"note":"Signal warmup only; no prior performance or positions carried into the forward book"},claim="forward-history-seed")


def _fresh(snapshot,stage,clock=None):
    current=clock or datetime.now(timezone.utc)
    require(snapshot.get("stage")==stage,"Wrong snapshot stage")
    require(snapshot.get("source") and snapshot.get("provenance")=="forward_observed","Use a named observed forward source")
    stamp=datetime.fromisoformat(snapshot["observed_at"])
    require(stamp.tzinfo is not None,"Observation timestamp needs a timezone")
    require(-30<=(current-stamp).total_seconds()<=600,"Snapshot is stale or future-dated")
    require(snapshot["session_date"]==current.date().isoformat(),"Forward session must be observed on its actual UTC date")
    return current


def propose_open(store,snapshot,clock=None):
    _fresh(snapshot,"open",clock)
    require(store.latest("spec_signed","main"),"Sign the strategy before forward shadow operation")
    require(store.latest("risk_plan_committed","main"),"Commit the risk mandate first")
    kill=store.latest("kill_switch","book")
    require(not kill or not kill["payload"]["active"],"Kill switch is active")
    require(not store.events("shadow_proposed"),"Use a separate case for forward observation; replay cannot count as forward history")
    opens=store.events("forward_open_proposed")
    require(all(any(c["payload"].get("proposal_id")==e["entity"] for c in store.events("shadow_committed","book")) for e in opens),"Close or recover the pending forward session first")
    spec=store.get(store.latest("spec_signed","main")["payload"]["spec"])
    config=store.get(spec["config_hash"])
    require(config["provenance"]!="synthetic","Synthetic data cannot become forward evidence")
    policy=store.get(project(store)["policy"])
    prior,head=committed(store)
    seed=store.latest("forward_history_seeded","book")
    if prior is None and seed:
        prior={"state":store.get(seed["payload"]["state"]),"orders":[],"daily":[]}
    rows=snapshot["rows"]
    validate_rows(rows,config["universe"])
    require(len(frames_from_rows(rows))==1 and rows[0]["date"]==snapshot["session_date"],"Open snapshot must contain exactly one session")
    require(all(r["close"]==r["open"] for r in rows),"Open proposals use open marks only; future closes cannot be supplied")
    state=prior["state"] if prior else None
    planned=simulate(config,rows,policy,state)
    abstain=simulate(config,rows,policy,state,allow_trades=False)
    key=uuid.uuid4().hex[:12]
    old_orders=len(prior["orders"]) if prior else 0
    proposal={"session_date":snapshot["session_date"],"observed_at":snapshot["observed_at"],"source":snapshot["source"],"provenance":"forward_observed","prior_head":head,
              "prior_result":store.put(prior) if prior else None,"config":spec["config_hash"],"policy":project(store)["policy"],"open_rows":store.put(rows),"planned":store.put(planned),"abstain":store.put(abstain),"orders":planned["orders"][old_orders:],"mode":"shadow"}
    store.append("forward_open_proposed",key,{"proposal":store.put(proposal)},claim="forward-session:"+snapshot["session_date"],expected=[("shadow_committed","book",head)])
    return {"proposal_id":key,**proposal}


def decide_open(store,proposal_id,approve,actor,reason,clock=None):
    require(actor.strip() and reason.strip(),"Record the decision-maker and rationale")
    e=store.latest("forward_open_proposed",proposal_id)
    require(e,"Unknown forward proposal")
    prop=store.get(e["payload"]["proposal"])
    current=clock or datetime.now(timezone.utc)
    age=(current-datetime.fromisoformat(prop["observed_at"])).total_seconds()
    require(not approve or 0<=age<=600,"Approval window expired; reject the proposal and mark the untraded session")
    kill=store.latest("kill_switch","book")
    require(not approve or not kill or not kill["payload"]["active"],"Kill switch is active")
    event=store.append("forward_decided",proposal_id,{"approved":approve,"by":actor,"reason":reason,"session_date":prop["session_date"],"paper_fill_convention":"Original observed opening marks plus configured costs; no real order"},claim="forward-decision:"+proposal_id,
                       expected=[("shadow_committed","book",prop["prior_head"]),("kill_switch","book",kill["hash"] if kill else None)])
    return event


def close_session(store,proposal_id,snapshot,clock=None):
    _fresh(snapshot,"close",clock)
    e=store.latest("forward_open_proposed",proposal_id)
    decision=store.latest("forward_decided",proposal_id)
    require(e and decision,"A recorded open-time decision is required")
    prop=store.get(e["payload"]["proposal"])
    require(snapshot["session_date"]==prop["session_date"],"Close belongs to another session")
    require(datetime.fromisoformat(snapshot["observed_at"])>datetime.fromisoformat(prop["observed_at"]),"Close must follow the open observation")
    require(not store.latest("forward_closed",proposal_id),"Session already closed; use forward recovery if its portfolio commit was interrupted")
    opening=store.get(prop["open_rows"])
    rows=snapshot["rows"]
    config=store.get(prop["config"])
    validate_rows(rows,config["universe"])
    require(len(rows)==len(opening),"Close snapshot universe differs")
    for original,closing in zip(opening,rows):
        for key in ("date","symbol","open","split","dividend"):
            require(original[key]==closing[key],"Open facts changed; reconcile as an incident before closing")
    prior=store.get(prop["prior_result"]) if prop["prior_result"] else None
    output=simulate(config,rows,store.get(prop["policy"]),prior["state"] if prior else None,decision["payload"]["approved"])
    original=store.get(prop["planned"] if decision["payload"]["approved"] else prop["abstain"])
    require(output["orders"]==original["orders"],"Close information changed an order; incident requires review")
    ref=store.put(output)
    close_event=store.append("forward_closed",proposal_id,{"result":ref,"close_snapshot":store.put(snapshot),"session_date":prop["session_date"],"open_event":e["hash"],"decision":decision["hash"],"provenance":"forward_observed"},claim="forward-close:"+proposal_id)
    return recover_close(store,proposal_id)


def recover_close(store,proposal_id):
    event=store.latest("forward_closed",proposal_id)
    require(event,"No saved close observation to recover")
    prop=store.get(store.latest("forward_open_proposed",proposal_id)["payload"]["proposal"])
    existing=next((c for c in store.events("shadow_committed","book") if c["payload"].get("proposal_id")==proposal_id),None)
    if not existing:
        store.append("shadow_committed","book",{"proposal_id":proposal_id,"result":event["payload"]["result"],"forward":True,"decision_hash":event["payload"]["decision"],"close_hash":event["hash"]},claim="forward-commit:"+proposal_id,expected=[("shadow_committed","book",prop["prior_head"])])
    return store.get(event["payload"]["result"])


def progress(store):
    sessions=store.events("forward_closed")
    commits={e["payload"].get("proposal_id") for e in store.events("shadow_committed","book") if e["payload"].get("forward")}
    dates=sorted({e["payload"]["session_date"] for e in sessions if e["entity"] in commits})
    return {"observed_forward_sessions":len(dates),"dates":dates,"five_session_requirement_met":len(dates)>=5,
            "note":"Counted from separately timestamped open decisions and later close observations. Feed authenticity and exchange calendar need independent verification."}
