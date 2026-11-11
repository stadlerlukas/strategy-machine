from pathlib import Path
from copy import deepcopy

from .store import Store
from .examples import create_examples,example_config,example_policy
from .research import initialize,run,commit_plan,sign_spec,reproduce,walk_forward
from .operations import shadow_propose,shadow_decide,reconcile,record_decision
from .reporting import report,daily_report
from .data import load_csv
from .common import require,write_json


def build_demo(root,kind="momentum",sessions=18,progress=None):
    root=Path(root).resolve()
    require(not (root/"ledger.sqlite").exists(),"Demo target already exists; use a new folder to preserve the audit trail")
    say=progress or (lambda message:None)
    paths=create_examples(root/"fixtures")
    store=Store(root)
    config=example_config(kind)
    from .intake import create_intake,answer,accept_intake,QUESTIONS
    create_intake(store,config["hypothesis"])
    answer(store,{key:"Synthetic software fixture: see explicit fixture config, costs, policy and provenance. No human investment intention is represented." for key in QUESTIONS})
    accept_intake(store,config,example_policy(),"Synthetic fixture owner","Exercise the translation gate using fully declared fixture settings")
    say("Registering synthetic prices and explicit assumed costs")
    initialize(store,config,{k:paths[k] for k in ("training","validation","holdout")},example_policy())
    commit_plan(store,"Synthetic fixture owner","Software acceptance demonstration only",synthetic=True)
    say("Running a baseline and two single-change experiments")
    baseline=run(store)
    for lookback in (8,20):
        candidate=deepcopy(config)
        candidate["strategy"]["params"]["lookback"]=lookback
        run(store,candidate,baseline=baseline["run_id"])
    run(store,period="validation",purpose="validation")
    walk_forward(store,baseline["run_id"],3)
    say("Testing continuation and recording a clearly synthetic sign-off")
    sign_spec(store,baseline["run_id"],"Synthetic fixture owner","Demonstrate gates, not approve an investment",synthetic=True)
    run(store,period="holdout",purpose="holdout")
    say("Replaying shadow sessions with labelled fixture decisions")
    rows=load_csv(paths["shadow"],config["universe"])
    for i in range(sessions):
        proposal=shadow_propose(store,rows)
        result=shadow_decide(store,proposal["proposal_id"],i!=sessions-2,"Synthetic fixture owner","Fixture approval" if i!=sessions-2 else "Exercise rejection path",synthetic=True)
        # Daily factual report generated from that session's newly calculated output.
        row=result["daily"][-1]
        daily_report(store,result,proposal["proposal_id"],"synthetic_replay")
    final=result["daily"][-1]
    reconcile(store,{"date":final["date"],"cash":final["cash"],"units":final["units"],"provenance":"synthetic_fixture"})
    say("Regenerating evidence and building the report")
    report(store)
    record_decision(store,"pause","Synthetic acceptance fixture; not a candidate for investment","Synthetic fixture owner")
    result=report(store)
    result["workspace"]=str(root)
    result["synthetic_replay_sessions"]=sessions
    result["observed_forward_sessions"]=0
    write_json(root/"demo-completion.json",result)
    return result
