"""Shared application service used by the local UI and automation-friendly CLI."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path

from .common import require,read_json,write_json
from .store import Store
from . import intake,research,operations,forward
from .reporting import report,daily_report
from .examples import example_config,example_policy


def blank_setup():
    config=example_config()
    config.update(name="",hypothesis="",universe=[],costs={},initial_nav=None,risk_free_annual=None,periods_per_year=None,currency="",provenance="historical")
    config["strategy"]={"kind":"expression","expression":"","params":{}}
    policy=example_policy()
    for k,v in list(policy.items()):
        if isinstance(v,(int,float)) and not isinstance(v,bool):
            policy[k]=None
    policy["groups"]={}
    policy["kpis"]=[]
    policy["warmup_mode"]=None
    return {"config":config,"policy":policy}


SETUP_SCHEMA={"type":"object","additionalProperties":False,"properties":{
    "configuration_json":{"type":"string"},"risk_policy_json":{"type":"string"},"explanation":{"type":"string"},
    "remaining_questions":{"type":"array","items":{"type":"string"}}},"required":["configuration_json","risk_policy_json","explanation","remaining_questions"]}


def prepare_setup(store,model=None):
    from .agents import ask_openai
    current=intake.status(store)
    require(current["ready"],"Complete the intake questions first")
    require(current["implementation"] and current["implementation"]["capability"]=="expression","First obtain a supported, reviewed implementation proposal")
    evidence={"intake":current,"empty_structure":blank_setup(),"cost_fields":["spread_bps","commission_bps","slippage_bps","fixed_fee","long_financing_annual","short_financing_annual","borrow_annual","source","as_of","instrument_type","shortable"]}
    prompt="Prepare JSON configuration and risk policy from the owner's answers and expression proposal. Preserve exactly the empty structure's keys. Use expression kind only. All rates and weights are fractions; spread/commission/slippage are basis points. For each universe instrument provide all cost fields. shortable is boolean, instrument_type cash or cfd. Every KPI is {metric,range:[lower,upper],why}. Permitted KPI names include net_sharpe,max_drawdown,annual_volatility,turnover,net_return,trades_per_session. NEVER invent numeric risk limits, fees, capital, annualization frequency, benchmark or data provenance. Put null where not explicitly established and ask the missing question. Do not use synthetic provenance for real research. JSON output is a proposal and will be validated and reviewed by the owner. No Python or executable source."
    response=ask_openai(prompt,evidence,SETUP_SCHEMA,model)
    config=json.loads(response["configuration_json"])
    policy=json.loads(response["risk_policy_json"])
    require(config.get("strategy",{}).get("kind")=="expression","AI setup can only propose the restricted expression adapter")
    response["config"],response["policy"]=config,policy
    store.append("setup_proposed","main",{"artifact":store.put(response)})
    return response


class Application:
    def __init__(self,root):
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)

    def case_path(self,name,create=False):
        require(isinstance(name,str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}",name),"Case name must contain only letters, digits, hyphens or underscores")
        path=(self.root/name).resolve()
        require(path.parent==self.root,"Invalid case path")
        require(create or path.is_dir(),"Unknown case")
        return path

    def store(self,name):
        return Store(self.case_path(name))

    def cases(self):
        out=[]
        for path in sorted(self.root.iterdir()):
            if path.is_dir() and (path/"ledger.sqlite").is_file():
                store=Store(path)
                p=store.latest("project","main")
                c=store.get(p["payload"]["config"]) if p else None
                out.append({"id":path.name,"title":c["name"] if c else path.name,"provenance":c["provenance"] if c else "intake"})
        return out

    def state(self,name):
        store=self.store(name)
        p=store.latest("project","main")
        config=store.get(p["payload"]["config"]) if p else None
        policy=store.get(p["payload"]["policy"]) if p else None
        runs=[]
        for e in store.events("run_started"):
            complete=store.latest("run_completed",e["entity"])
            failed=store.latest("run_failed",e["entity"])
            runs.append({"id":e["entity"],"period":e["payload"]["period"],"status":"completed" if complete else ("failed" if failed else "interrupted"),
                         "purpose":e["payload"]["purpose"],"fold":e["payload"].get("fold"),
                         "metrics":complete["payload"]["metrics"] if complete else None,"changes":complete["payload"].get("changes",[]) if complete else [],"error":failed["payload"]["error"] if failed else None})
        proposals=[]
        for e in store.events("shadow_proposed"):
            prop=store.get(e["payload"]["proposal"])
            decision=store.latest("shadow_decided",e["entity"])
            proposals.append({"id":e["entity"],"date":prop["date"],"orders":prop["orders"],"cost":prop["expected_cost"],"decision":decision["payload"] if decision else None})
        result,head=operations.committed(store)
        advice=store.latest("intake_advice","main")
        setup=store.latest("setup_proposed","main")
        reviews=store.events("history_reviewed")
        signatures=store.latest("spec_signed","main")
        kill=store.latest("kill_switch","book")
        return {"case":name,"path":str(store.root),"intake":intake.status(store),"config":config,"policy":policy,
                "advice":store.get(advice["payload"]["advice"]) if advice else None,
                "setup_proposal":store.get(setup["payload"]["artifact"]) if setup else None,
                "runs":runs,"risk_committed":bool(store.latest("risk_plan_committed","main")),
                "signed":store.get(signatures["payload"]["spec"]) if signatures else None,"proposals":proposals,
                "portfolio":result["daily"][-1] if result else None,"review":store.get(reviews[-1]["payload"]["review"]) if reviews else None,
                "reconciliations":[e["payload"] for e in store.events("reconciliation")],"incidents":[e["payload"] for e in store.events("incident")],
                "decisions":[e["payload"] for e in store.events("human_decision")],"forward":forward.progress(store),
                "forward_proposals":[{"id":e["entity"],"proposal":store.get(e["payload"]["proposal"]),"decided":bool(store.latest("forward_decided",e["entity"])),"closed":bool(store.latest("forward_closed",e["entity"]))} for e in store.events("forward_open_proposed")],
                "kill_active":bool(kill and kill["payload"]["active"]),"report_exists":(store.root/"report.html").exists(),
                "ai_configured":bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")),"model":os.getenv("OPENAI_MODEL"),
                "datasets":p["payload"]["data"] if p else {},"event_count":len(store.events())}

    def action(self,name,action,args):
        if action=="create":
            path=self.case_path(name,create=True)
            require(not path.exists(),"Case already exists")
            return intake.create_intake(Store(path),args["description"])
        if action=="demo":
            from .demo import build_demo
            return build_demo(self.case_path(name,create=True),args.get("kind","momentum"),sessions=18)
        store=self.store(name)
        if action=="answer":
            return intake.answer(store,args["answers"])
        if action=="advise":
            return intake.advise(store)
        if action=="implementation":
            return intake.propose_implementation(store)
        if action=="prepare_setup":
            return prepare_setup(store)
        if action=="packet":
            return intake.export_packet(store)
        if action=="accept":
            require(args["config"]["strategy"]["kind"]!="python" or args.get("trusted_code_reviewed") is True,"Trusted Python adapters require explicit source review")
            return intake.accept_intake(store,args["config"],args["policy"],args["actor"],args["reason"])
        if action=="initialize":
            accepted=store.latest("intake_accepted","main")
            require(accepted,"Accept the written-strategy translation first")
            return research.initialize(store,store.get(accepted["payload"]["config"]),args["paths"],store.get(accepted["payload"]["policy"]),int(args.get("prior_trials",0)))
        if action=="upload":
            label=args["label"]
            require(re.fullmatch(r"[A-Za-z0-9_-]{1,60}\.(csv|json)",label),"Use a simple .csv or .json filename")
            text=args["text"]
            require(isinstance(text,str) and len(text.encode())<=25_000_000,"File exceeds 25 MB")
            target=store.root/"imports"/label
            target.parent.mkdir(exist_ok=True)
            require(not target.exists(),"Import name exists; give each data version a new name")
            target.write_text(text,encoding="utf-8")
            from .common import file_hash
            store.append("local_import",label,{"sha256":file_hash(target),"bytes":target.stat().st_size,"status":"not yet validated"})
            return {"path":str(target)}
        if action=="acquire":
            return intake.acquire_public_csv(store,args["url"],args["label"])
        if action=="plan":
            return research.commit_plan(store,args["actor"],args["reason"],args.get("synthetic",False))
        if action=="run":
            period=args.get("period","training")
            c=deepcopy(research.result_for(store,args["config_from"])["config"] if args.get("config_from") else research.base_config(store))
            if period=="holdout":
                signed=store.latest("spec_signed","main")
                require(signed,"Sign the chosen strategy before opening holdout")
                c=store.get(store.get(signed["payload"]["spec"])["config_hash"])
            if args.get("parameter"):
                require(args["parameter"] in c["strategy"]["params"],"Choose an existing parameter")
                value=args["value"]
                if isinstance(c["strategy"]["params"][args["parameter"]],int):
                    require(float(value).is_integer(),"This parameter requires an integer")
                    value=int(value)
                c["strategy"]["params"][args["parameter"]]=value
            purpose={"training":"research","validation":"validation","holdout":"holdout"}[period]
            r=research.run(store,c,period,args.get("baseline"),purpose)
            return {"run_id":r["run_id"],"metrics":r["metrics"]}
        if action=="continuation":
            return research.continuation(store,args["run_id"])
        if action=="walk_forward":
            return research.walk_forward(store,args["run_id"],args.get("folds",3))
        if action=="draft_spec":
            return research.draft_spec(store,args["run_id"])
        if action=="sign":
            return research.sign_spec(store,args["run_id"],args["actor"],args["reason"],args.get("synthetic",False))
        if action=="shadow":
            from .data import load_csv
            rows=load_csv(args["path"],research.base_config(store)["universe"])
            return operations.shadow_propose(store,rows)
        if action=="decide":
            r=operations.shadow_decide(store,args["proposal_id"],args["approve"],args["actor"],args["reason"],args.get("synthetic",False))
            daily_report(store,r,args["proposal_id"],"synthetic_replay" if research.base_config(store)["provenance"]=="synthetic" else "historical_replay")
            return {"portfolio":r["daily"][-1],"metrics":r["metrics"]}
        if action=="recover":
            r=operations.recover_shadow_commit(store,args["proposal_id"])
            daily_report(store,r,args["proposal_id"],"recovered_shadow_replay")
            return {"portfolio":r["daily"][-1]}
        if action=="reconcile":
            return operations.reconcile(store,args["snapshot"])
        if action=="review":
            if args.get("history_path"):
                require(store.latest("risk_plan_committed","main"),"Commit a risk plan before reading the selected history")
                history=read_json(args["history_path"])
                return operations.review_history(store,history,"imported normalized account history")
            current,_=operations.committed(store)
            require(current,"No shadow history yet; provide a normalized history file")
            return operations.review_history(store,current,"shadow book")
        if action=="human_decision":
            return operations.record_decision(store,args["decision"],args["reason"],args["actor"])
        if action=="kill":
            require(args.get("actor") and args.get("reason"),"Record who changed the kill switch and why")
            return store.append("kill_switch","book",{"active":bool(args["active"]),"by":args["actor"],"reason":args["reason"]})
        if action=="report":
            return report(store)
        if action=="audit":
            return store.verify()
        if action=="ai_review":
            from .agents import ai_review
            reviews=store.events("history_reviewed")
            require(reviews,"Generate a factual review first")
            return ai_review(store,store.get(reviews[-1]["payload"]["review"]))
        if action=="ai_research":
            from .agents import research_loop
            return research_loop(store,args["baseline"],args["bounds"],int(args["max_trials"]))
        if action=="etoro":
            from .etoro import EToroReader
            if args.get("resource","portfolio")=="history":
                require(store.latest("risk_plan_committed","main"),"Commit the risk plan before retrieving history")
            r=EToroReader(args.get("mode","demo")).get(args.get("resource","portfolio"),args.get("params"))
            path=store.root/"etoro"/(r["resource"]+"-"+r["fetched_at"].replace(":","-")+".json")
            write_json(path,r)
            store.append("broker_snapshot",r["resource"],{"artifact":store.put(r)})
            return {"path":str(path),"status":"Read-only raw snapshot. Normalization must be verified."}
        if action=="forward_open":
            return forward.propose_open(store,args["snapshot"])
        if action=="forward_seed":
            from .data import load_csv
            return forward.seed_history(store,load_csv(args["path"],research.base_config(store)["universe"]))
        if action=="forward_recover":
            r=forward.recover_close(store,args["proposal_id"])
            daily_report(store,r,args["proposal_id"],"forward_observed")
            return {"portfolio":r["daily"][-1],"progress":forward.progress(store)}
        if action=="forward_decide":
            return forward.decide_open(store,args["proposal_id"],args["approve"],args["actor"],args["reason"])
        if action=="forward_close":
            r=forward.close_session(store,args["proposal_id"],args["snapshot"])
            daily_report(store,r,args["proposal_id"],"forward_observed")
            return {"portfolio":r["daily"][-1],"progress":forward.progress(store)}
        raise ValueError("Unknown action")
