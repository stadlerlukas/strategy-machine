from __future__ import annotations

import csv
import json
import shutil
import uuid
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from .common import require, digest, file_hash, read_json, source_manifest, differences, write_json
from .config import validate_config, validate_policy, validate_spec
from .data import load_csv, save_csv, frames_from_rows
from .engine import simulate
from .metrics import deflated_sharpe, effective_trials
from .risk import red_team


def initialize(store, config, paths, policy, prior_trials=0):
    require(not store.latest("project", "main"), "Workspace already initialized; use a new workspace for a new mandate")
    validate_config(config)
    validate_policy(policy)
    config=deepcopy(config)
    if config["strategy"]["kind"]=="python" and "source" not in config["strategy"]:
        import hashlib
        source=Path(config["strategy"]["path"]).read_text(encoding="utf-8")
        require(hashlib.sha256(source.encode()).hexdigest()==config["strategy"]["sha256"],"Plugin source changed before registration")
        config["strategy"]["source"]=source
        del config["strategy"]["path"]
    require(set(paths)=={"training","validation","holdout"},"Provide separate training, validation and holdout CSV files")
    require(isinstance(prior_trials,int) and prior_trials>=0,"Prior trial count must be a nonnegative integer")
    data={}
    folder=store.root/"data"
    folder.mkdir(exist_ok=True)
    for label,path in paths.items():
        # Holdout is copied and fingerprinted as bytes, not parsed or evaluated here.
        target=folder/f"{label}.csv"
        shutil.copyfile(path,target)
        data[label]={"path":str(target.relative_to(store.root)),"sha256":file_hash(target)}
    train=load_csv(store.root/data["training"]["path"],config["universe"])
    valid=load_csv(store.root/data["validation"]["path"],config["universe"])
    require(train[-1]["date"]<valid[0]["date"],"Training and validation must be non-overlapping chronological files")
    data["training"]["first"],data["training"]["last"]=train[0]["date"],train[-1]["date"]
    data["validation"]["first"],data["validation"]["last"]=valid[0]["date"],valid[-1]["date"]
    payload={"config":store.put(config),"policy":store.put(policy),"data":data,"prior_trials":prior_trials,"source":source_manifest()}
    store.append("project","main",payload)
    store.append("risk_plan_registered","main",{"policy":payload["policy"],"status":"draft; needs human commitment before history review"})
    return payload


def project(store):
    e=store.latest("project","main")
    require(e,"Initialize a workspace first")
    return e["payload"]


def base_config(store):
    return store.get(project(store)["config"])


def dataset(store,period,universe,permit=None):
    p=project(store)
    require(period in p["data"],"Unknown period")
    if period=="holdout":
        require(permit and store.latest("holdout_opened",permit),"Held-out data access requires a consumed evaluation permit")
    item=p["data"][period]
    path=store.root/item["path"]
    require(file_hash(path)==item["sha256"],f"Frozen {period} data changed")
    rows=load_csv(path,universe)
    if period=="holdout":
        require(rows[0]["date"]>p["data"]["validation"]["last"],"Holdout overlaps previously exposed data")
    return rows


def result_for(store,run_id):
    e=store.latest("run_completed",run_id)
    require(e,f"No completed run {run_id}")
    return store.get(e["payload"]["result"])


def run(store,config=None,period="training",baseline=None,purpose="research",policy=None):
    config=deepcopy(config or base_config(store))
    run_id=uuid.uuid4().hex[:12]
    start={"config":store.put(config),"period":period,"baseline":baseline,"purpose":purpose,"source":source_manifest(),"policy":store.put(policy) if policy else None}
    store.append("run_started",run_id,start)
    try:
        require(purpose in ("research","validation","holdout"),"Unknown run purpose")
        validate_config(config)
        p=project(store)
        require((period,purpose) in (("training","research"),("validation","validation"),("holdout","holdout")),"Run purpose must match its data period")
        require(not store.latest("spec_signed","main") or period=="holdout","Research is frozen after sign-off; start a documented successor case to revise it")
        policy=policy if policy is not None else store.get(p["policy"])
        require(digest(policy)==p["policy"],"The registered risk policy stays locked across research and operation")
        require(source_manifest()==p["source"],"Engine changed since workspace creation; explicitly migrate to a new workspace with prior-trial disclosure")
        changes=[]
        if baseline:
            b=result_for(store,baseline)
            require(b["period"]==period,"Ablation baseline must use the same data period")
            changes=differences(b["config"],config)
            require(len(changes)==1,"Ablation must change exactly one leaf setting")
            require(changes[0].startswith("strategy.params."),"Costs, universe, dates and accounting stay locked; only strategy.params can change within an ablation table")
        else:
            known=any(e["payload"]["config"]==digest(config) and store.latest("run_completed",e["entity"]) for e in store.events("run_started"))
            require(digest(config)==p["config"] or period=="holdout" or (period=="validation" and known),"New research variants need a named baseline")
        if period=="holdout":
            require(baseline is None,"Held-out period cannot be used for ablations")
            signed=store.latest("spec_signed","main")
            require(signed,"Holdout is locked until human sign-off and a passing continuation test")
            spec=store.get(signed["payload"]["spec"])
            require(spec["config_hash"]==digest(config),"Only the signed configuration can access holdout")
            store.append("holdout_opened",run_id,{"signature":signed["hash"],"data_hash":p["data"][period]["sha256"]},claim="holdout:"+p["data"][period]["sha256"])
        rows=dataset(store,period,config["universe"],run_id if period=="holdout" else None)
        output=simulate(config,rows,policy)
        result={"run_id":run_id,"period":period,"purpose":purpose,"config":config,"input":store.put(rows),"policy":policy,"changes":changes,"baseline":baseline,"source":source_manifest(),**output}
        ref=store.put(result)
        store.append("run_completed",run_id,{"result":ref,"metrics":result["metrics"],"changes":changes})
        export_trials(store)
        return result
    except Exception as exc:
        store.append("run_failed",run_id,{"error":str(exc),"type":type(exc).__name__})
        export_trials(store)
        raise


def reproduce(store,run_id):
    r=result_for(store,run_id)
    require(r["source"]==source_manifest(),"Reproduction requires the recorded source version")
    output=simulate(r["config"],store.get(r["input"]),r["policy"],r.get("initial_state"))
    expected={k:r[k] for k in output}
    require(digest(output)==digest(expected),"Reproduction mismatch; do not patch reported output")
    store.append("reproduced",run_id,{"result_hash":digest(output),"matched":True})
    return {"run_id":run_id,"matched":True,"metrics":output["metrics"]}


def walk_forward(store,chosen_id,folds=3):
    """Fixed-rule chronological validation. Fitting learned models needs an adapter."""
    chosen=result_for(store,chosen_id)
    require(chosen["period"]=="training","Select a training configuration")
    require(not store.latest("spec_signed","main"),"Research is frozen after sign-off")
    require(isinstance(folds,int) and 2<=folds<=10,"Choose between two and ten chronological folds")
    p=project(store)
    require(source_manifest()==p["source"],"Engine changed since registration")
    config=chosen["config"]
    store.append("walk_forward_started",uuid.uuid4().hex[:12],{"chosen_run":chosen_id,"folds":folds,"method":"Fixed configuration; chronological validation blocks; expanding completed history for signals; flat capital reset per fold; no parameter selection inside validation"})
    train=dataset(store,"training",config["universe"])
    valid=dataset(store,"validation",config["universe"])
    frames=frames_from_rows(valid)
    require(len(frames)>=20*folds,"Each fold requires at least twenty observed sessions")
    results=[]
    for i in range(folds):
        run_id=uuid.uuid4().hex[:12]
        start={"config":store.put(config),"period":"validation","baseline":chosen_id,"purpose":"walk_forward","source":source_manifest(),"policy":p["policy"],"fold":i+1}
        store.append("run_started",run_id,start)
        try:
            first,last=len(frames)*i//folds,len(frames)*(i+1)//folds
            history=frames_from_rows(train)+frames[:first]
            rows=[frame[s] for _,frame in frames[first:last] for s in sorted(config["universe"])]
            state={"history":history,"prev_close":{s:history[-1][1][s]["close"] for s in config["universe"]}}
            output=simulate(config,rows,chosen["policy"],state)
            result={"run_id":run_id,"period":"validation","purpose":"walk_forward","config":config,"input":store.put(rows),"initial_state":state,"policy":chosen["policy"],"changes":[],"baseline":chosen_id,"source":source_manifest(),"fold":i+1,**output}
            store.append("run_completed",run_id,{"result":store.put(result),"metrics":result["metrics"],"changes":[]})
            results.append({"run_id":run_id,"fold":i+1,"start":rows[0]["date"],"end":rows[-1]["date"],"metrics":result["metrics"]})
        except Exception as exc:
            store.append("run_failed",run_id,{"error":str(exc),"type":type(exc).__name__})
            export_trials(store)
            raise
    export_trials(store)
    return results


def export_trials(store):
    columns=["run_id","timestamp","status","period","purpose","baseline","config_hash","single_change","gross_sharpe","net_sharpe","turnover","break_even_cost_bps","error"]
    with (store.root/"trials.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=columns)
        w.writeheader()
        for e in store.events("run_started"):
            done=store.latest("run_completed",e["entity"])
            failed=store.latest("run_failed",e["entity"])
            p=e["payload"]
            row={"run_id":e["entity"],"timestamp":e["time"],"status":"completed" if done else ("failed" if failed else "interrupted"),"period":p["period"],"purpose":p["purpose"],"baseline":p["baseline"],"config_hash":p["config"],"single_change":json.dumps(done["payload"].get("changes",[])) if done else "","error":failed["payload"]["error"] if failed else ""}
            if done:
                row.update({k:done["payload"]["metrics"][k] for k in columns if k in done["payload"]["metrics"]})
            w.writerow(row)


def trial_statistics(store,chosen_id,through=None):
    chosen=result_for(store,chosen_id)
    all_attempts=[e for e in store.events("run_started") if (through is None or e["seq"]<=through) and e["payload"]["period"] in ("training","validation")]
    events=[e for e in all_attempts if e["payload"]["period"]==chosen["period"] and e["payload"]["purpose"]=="research"]
    completed=[]
    for e in events:
        if store.latest("run_completed",e["entity"]):
            completed.append(result_for(store,e["entity"]))
    sharpes=[r["metrics"]["net_sharpe"] for r in completed if r["metrics"]["net_sharpe"] is not None]
    series=[[d["net_return"] for d in r["daily"]] for r in completed]
    count=len(all_attempts)+project(store)["prior_trials"]
    effective=effective_trials(series)
    dsr=deflated_sharpe([d["net_return"] for d in chosen["daily"]],sharpes,count,chosen["config"]["periods_per_year"],chosen["config"]["risk_free_annual"])
    return {"count":count,"local_attempts":len(all_attempts),"comparable_training_runs":len(completed),"completed":sum(bool(store.latest("run_completed",e["entity"])) for e in all_attempts),"prior_trials":project(store)["prior_trials"],
            "unique_configurations":len({e["payload"]["config"] for e in all_attempts}),
            "effective_count":effective,"effective_count_method":"Participation-ratio heuristic on aligned local return correlations; prior search dependence unknown. Not a measured true independent trial count.",
            "deflated_sharpe":dsr,"dsr_trials_used":count,"dsr_method":"Bailey-Lopez de Prado probability using all declared attempts as independent; null if dispersion/sample insufficient; IID moment approximation, serial dependence not corrected.",
            "scope":"All development/validation attempts (including failures and repeated runs) plus declared prior attempts. Dispersion and correlation estimates use comparable training runs. Cannot discover undisclosed external searches."}


def continuation(store,chosen_id):
    r=result_for(store,chosen_id)
    require(r["period"]!="holdout","Continuation test must not repurpose held-out data")
    source=store.get(r["input"])
    rows=deepcopy(source)
    latest=frames_from_rows(rows)[-1][1]
    start=date.fromisoformat(rows[-1]["date"])
    stop=start+timedelta(days=365)
    d=start
    n=0
    symbols=r["config"]["universe"]
    prices={s:latest[s]["close"] for s in symbols}
    while d<stop:
        d+=timedelta(days=1)
        if d.weekday()>4:
            continue
        n+=1
        for j,s in enumerate(sorted(symbols)):
            status="halted" if s==symbols[0] and 20<=n<23 else "active"
            if s==symbols[-1] and n>=100:
                status="delisted"
            if status=="active":
                prices[s]*=1+(.001 if n%3 else -.0015)
            rows.append({"date":d.isoformat(),"symbol":s,"open":prices[s],"close":prices[s],"status":status,"split":1.0,"dividend":0.0,"settlement":prices[s] if status=="delisted" else None,**{k:v for k,v in latest[s].items() if k.startswith("feature_")}})
    path=store.root/"continuation.synthetic.csv"
    save_csv(path,rows)
    # The real loader is intentionally used. No mock and no fixed end date.
    loaded=load_csv(path,symbols)
    result=simulate(r["config"],loaded,r["policy"])
    new=[x for x in result["daily"] if x["date"]>start.isoformat()]
    require(len(new)==n and n>=250,"Continuation failed to process the extra year")
    require(any(x["status"]=="halted" for x in loaded),"Missing halt fixture")
    require(any(x["kind"]=="delisting_settlement" for x in result["events"]),"Delisting was not processed")
    test={"passed":True,"provenance":"synthetic operational test, not forward financial evidence","config_hash":digest(r["config"]),"source":source_manifest(),"new_sessions":n,"start":new[0]["date"],"end":new[-1]["date"],"input_hash":file_hash(path),"result":store.put(result)}
    store.append("continuation_passed",chosen_id,test)
    return test


def draft_spec(store,chosen_id):
    r=result_for(store,chosen_id)
    require(r["period"]=="training","Choose a development run, not a holdout winner")
    config=r["config"]
    metrics=[result_for(store,e["entity"])["metrics"] for e in store.events("run_completed") if store.latest("run_started",e["entity"])["payload"]["period"] in ("training","validation")]
    expected={}
    for key in ("net_sharpe","turnover","break_even_cost_bps"):
        values=[m[key] for m in metrics if m[key] is not None]
        require(values,f"Cannot draft a filled range: {key} unavailable; strategy may not trade")
        expected[key]=[min(values),max(values)]
    policy=store.get(project(store)["policy"])
    spec={"hypothesis":config["hypothesis"],"universe":config["universe"],"signal":config["strategy"],"holding":config["holding"],"costs":config["costs"],"expected":expected,
          "expected_method":"Observed min/max across recorded development and validation runs; descriptive sensitivity ranges, NOT predictive confidence intervals. Human must assess suitability before signing.",
          "kill":[{"metric":"drawdown","operator":">","value":policy["max_drawdown"],"action":"block increasing exposure and escalate"}],
          "trials":trial_statistics(store,chosen_id),"signed":None,"config_hash":digest(config),"chosen_run":chosen_id,
          "data_hashes":{k:v["sha256"] for k,v in project(store)["data"].items()},"source":source_manifest(),"ledger_through":store.events()[-1]["seq"],"provenance":config["provenance"]}
    validate_spec(spec)
    write_json(store.root/"strategy.spec.draft.json",spec)
    return spec


def sign_spec(store,chosen_id,signer,reason,synthetic=False):
    require(signer.strip() and reason.strip(),"Sign-off requires a human name and rationale")
    require(not store.latest("spec_signed","main"),"This workspace already has a signed specification")
    require(store.latest("risk_plan_committed","main"),"Commit the chosen risk mandate before strategy sign-off")
    chosen=result_for(store,chosen_id)
    require(any(result_for(store,e["entity"])["period"]=="validation" and digest(result_for(store,e["entity"])["config"])==digest(chosen["config"]) for e in store.events("run_completed")),"Evaluate the chosen configuration on validation data before sign-off")
    for event in store.events("run_completed"):
        reproduce(store,event["entity"])
    c=continuation(store,chosen_id)  # always run immediately before signing
    spec=draft_spec(store,chosen_id)
    require(synthetic== (spec["provenance"]=="synthetic"),"Synthetic evidence must have an explicitly synthetic sign-off")
    require(spec["trials"]["deflated_sharpe"] is not None,"Insufficient trial evidence for DSR; record more comparable experiments or document an explicit external exception outside this signing workflow")
    spec["continuation"]=c
    spec["risk_policy_hash"]=project(store)["policy"]
    from .common import now
    spec["signed"]={"at":now(),"by":signer,"reason":reason,"synthetic_demonstration":synthetic,"method":"local timestamped attestation; not cryptographic identity proof"}
    ref=store.put(spec)
    store.append("spec_signed","main",{"spec":ref},claim="spec-signature")
    write_json(store.root/"strategy.spec.json",spec)
    return spec


def commit_plan(store,signer,reason,synthetic=False):
    p=project(store)
    require(signer.strip() and reason.strip(),"Plan commitment needs a name and rationale")
    require(synthetic==(base_config(store)["provenance"]=="synthetic"),"Label synthetic plan commitments explicitly")
    require(not store.events("history_reviewed"),"Cannot preregister a plan after reviewing history in this workspace")
    test=red_team(store.get(p["policy"]))
    event=store.append("risk_plan_committed","main",{"policy":p["policy"],"by":signer,"reason":reason,"synthetic":synthetic,"test":store.put(test)},claim="risk-plan")
    template=f"Adverse-performance note template prepared at plan commitment {event['time']}.\n\nObserved period: [fill from regenerated evidence]\nWhat happened: [facts and attribution, with costs separate]\nWhich predeclared rules fired: [rule IDs and supporting figures]\nWhat is known and unknown: [separate observations from explanations]\nOwner decision and reason: [keep, adjust, pause or manual]\nFollow-up evidence required: [state before changing strategy]\n\nPolicy hash: {p['policy']}. Do not claim this template was written before the trades themselves.\n"
    (store.root/"adverse-performance-note-template.txt").write_text(template,encoding="utf-8")
    return event
