"""Written idea -> questions -> agreed description and data plan -> reviewed config.

Intake never signs a strategy, sets risk appetite, or opens market data itself.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit

from .common import require,digest,now,write_json,file_hash
from .config import validate_config,validate_policy
from .agents import ask_openai

QUESTIONS={
    "hypothesis":"What exactly do you expect to happen, and what result would falsify it?",
    "economic_reason":"Why should this opportunity exist after other traders and costs?",
    "universe":"Which instruments may be traded, and how is membership determined over time?",
    "signal":"How is the signal calculated, with numerical thresholds and lookback periods?",
    "entry":"When is information available, and at what later time may a position be opened?",
    "exit":"What causes a position to close, and is there a maximum holding period?",
    "sizing":"How are signed position sizes and overlapping signals converted into portfolio exposure?",
    "frequency":"What data frequency, decision schedule and market calendar does this need?",
    "data_features":"Besides prices, what signals, instrument facts and corporate actions are needed?",
    "costs":"Which spread, commission, slippage, financing and borrow costs apply to each instrument?",
    "capital_benchmark":"What initial portfolio value, currency and performance benchmark will be used?",
    "risk_limits":"Which losses, exposures and shared drivers should trigger blocking or intervention?",
    "data_sources":"Which sources are available, what access do they require and how will their data be obtained?",
    "prior_exposure":"Which periods and variants have already been inspected or tested, including outside this machine?"
}


def create_intake(store,description):
    require(isinstance(description,str) and len(description.strip())>=20,"Describe the strategy in at least twenty characters")
    require(not store.latest("intake_created","main"),"This case already has a written idea")
    store.append("intake_created","main",{"description":description.strip(),"created_at":now()})
    return status(store)


def status(store):
    original=store.latest("intake_created","main")
    if not original:
        return {"description":"","answers":{},"questions":QUESTIONS,"ready":False,"accepted":False}
    answers={}
    for e in store.events("intake_answered","main"):
        answers.update(e["payload"]["answers"])
    questions={k:q for k,q in QUESTIONS.items() if not str(answers.get(k,"")).strip()}
    acceptance=store.latest("intake_accepted","main")
    proposal=store.latest("intake_implementation","main")
    return {"description":original["payload"]["description"],"answers":answers,"questions":questions,"ready":not questions,
            "accepted":bool(acceptance),"acceptance":acceptance["payload"] if acceptance else None,
            "implementation":store.get(proposal["payload"]["artifact"]) if proposal else None}


def answer(store,answers,actor="owner"):
    require(store.latest("intake_created","main"),"Create an intake first")
    require(not store.latest("intake_accepted","main"),"Accepted intake is frozen; start a new case for material changes")
    require(isinstance(answers,dict) and answers and set(answers)<=set(QUESTIONS),"Unknown or empty intake fields")
    require(all(isinstance(v,str) and len(v)<=10000 for v in answers.values()),"Answers must be text")
    store.append("intake_answered","main",{"answers":answers,"by":actor})
    return status(store)


ADVISOR_SCHEMA={"type":"object","additionalProperties":False,"properties":{
    "understanding":{"type":"string"},
    "suggested_answers":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"field":{"type":"string"},"answer":{"type":"string"},"assumption":{"type":"boolean"}},"required":["field","answer","assumption"]}},
    "questions":{"type":"array","items":{"type":"string"}},
    "data_requirements":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"reason":{"type":"string"},"possible_source":{"type":"string"}},"required":["name","reason","possible_source"]}},
    "capability":{"type":"string","enum":["daily_bar_candidate","needs_additional_adapter","unclear"]},
    "capability_reason":{"type":"string"}},"required":["understanding","suggested_answers","questions","data_requirements","capability","capability_reason"]}


def advise(store,model=None,advisor=None):
    current=status(store)
    require(current["description"],"Write the strategy first")
    prompt="You are the strategy intake agent. Clarify the owner's idea, do not replace it with a different strategy. Extract answers only from supplied text; mark every proposed assumption. Ask focused questions for missing definitions. Suggest required data and possible sources, explicitly noting that availability and current fees must be verified. Do not invent historical results. The current reference engine handles synchronized unadjusted daily bars in one currency, next-open target weights, cash/CFD positions, splits/dividends/halts/delistings and optional numeric feature columns. Options, futures margin, intraday/order books and ticket-level execution require an additional adapter. Available questionnaire field names: "+", ".join(QUESTIONS)
    evidence={"description":current["description"],"answers":current["answers"],"missing_fields":current["questions"]}
    store.append("ai_request","intake",{"evidence":store.put(evidence),"model":model,"external":advisor is None})
    response=advisor(evidence) if advisor else ask_openai(prompt,evidence,ADVISOR_SCHEMA,model)
    require(set(response)==set(ADVISOR_SCHEMA["required"]),"Malformed intake advice")
    for item in response["suggested_answers"]:
        require(item["field"] in QUESTIONS,"AI suggested an unknown intake field")
    store.append("intake_advice","main",{"advice":store.put(response),"status":"proposal; no answers accepted automatically"})
    return response


IMPLEMENT_SCHEMA={"type":"object","additionalProperties":False,"properties":{
    "capability":{"type":"string","enum":["expression","needs_additional_adapter"]},
    "expression":{"type":"string"},"parameters":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"value":{"type":"number"}},"required":["name","value"]}},
    "explanation":{"type":"string"},"assumptions":{"type":"array","items":{"type":"string"}},
    "additional_adapter_work":{"type":"string"}},"required":["capability","expression","parameters","explanation","assumptions","additional_adapter_work"]}


def propose_implementation(store,model=None,designer=None):
    current=status(store)
    require(current["ready"],"Complete the strategy definitions before proposing an implementation")
    grammar="One expression returns the signed NAV fraction for each symbol. Names: symbol, n_assets. Calls: price(symbol, lag=0), sma(symbol, window), std(symbol, window), momentum(symbol, lag), zscore(symbol, window), feature(name, symbol, lag=0), param(name), abs, min, max. Use positional arguments only. Arithmetic, comparisons, boolean and/or and Python conditional expression are allowed. Only completed bars are visible. Params must be finite numbers. No imports, attributes, indexing or statements. Insufficient lookback returns zero exposure. This DSL cannot hold per-ticket state or enforce time-since-entry exits. Never substitute a simpler exit or sizing rule silently. If the agreed idea cannot be represented exactly, return needs_additional_adapter. No risk thresholds or fee assumptions may be invented."
    evidence={"description":current["description"],"answers":current["answers"]}
    response=designer(evidence) if designer else ask_openai("Translate the agreed written strategy into a reviewable implementation proposal. "+grammar,evidence,IMPLEMENT_SCHEMA,model)
    require(set(response)==set(IMPLEMENT_SCHEMA["required"]),"Malformed implementation proposal")
    if response["capability"]=="expression":
        from .expressions import parse
        parse(response["expression"])
        require(len({p["name"] for p in response["parameters"]})==len(response["parameters"]),"Duplicate parameters")
    store.append("intake_implementation","main",{"artifact":store.put(response),"status":"requires human review"})
    return response


def accept_intake(store,config,policy,actor,reason):
    current=status(store)
    require(current["ready"],"Answer the outstanding intake questions first")
    require(actor.strip() and reason.strip(),"Record who accepted the translation and why")
    validate_config(config)
    validate_policy(policy)
    if config["strategy"]["kind"]=="expression":
        from .expressions import parse
        parse(config["strategy"]["expression"])
    accepted={"config":store.put(config),"policy":store.put(policy),"description":current["description"],"answers":current["answers"],"by":actor,"reason":reason,
              "attestation":"The owner reviewed that the implementation, inputs and assumptions represent the intended written strategy; performance is not approved."}
    store.append("intake_accepted","main",accepted,claim="intake-acceptance")
    return accepted


def export_packet(store):
    current=status(store)
    folder=store.root/"intake-packet"
    folder.mkdir(exist_ok=True)
    write_json(folder/"intake.json",current)
    prompt="Work with the owner to formalise this written strategy. Read intake.json. Identify unresolved definitions and propose required data sources with explicit availability checks. Do not inspect holdout data, acquire paid data, set risk appetite, sign specifications, or trade. Produce a proposed config and risk-policy file for the owner to review, preserving their choices. Use the machine's docs/STRATEGY_ADAPTERS.md and docs/DATA.md. Clearly distinguish suggestions from facts. If implementation requires a new adapter, explain the required capability before coding.\n"
    (folder/"agent-instructions.txt").write_text(prompt,encoding="utf-8")
    return {"folder":str(folder),"status":"Open this packet with Codex or another coding agent; no model invocation has occurred"}


def acquire_public_csv(store,url,label):
    parts=urlsplit(url)
    require(parts.scheme=="https" and parts.hostname and not parts.username and not parts.password,"Use a public HTTPS data URL without embedded credentials")
    require(not re.search(r"(?i)(api.?key|token|secret|password)=",parts.query),"Do not put credentials in a recorded URL; import an authorized local export instead")
    require(re.fullmatch(r"[a-zA-Z0-9_-]{1,60}",label),"Use a simple dataset label")
    target=store.root/"acquired"/(label+".csv")
    require(not target.exists(),"Dataset label already exists; use a new version label")
    store.append("data_acquisition_requested",label,{"url":url,"kind":"public_https_csv"})
    try:
        with urlopen(Request(url,headers={"User-Agent":"StrategyMachine/1.0"}),timeout=30) as response:
            require(urlsplit(response.url).scheme=="https","Data source redirected to an insecure URL")
            content=response.read(25_000_001)
            require(len(content)<=25_000_000,"Dataset exceeds 25 MB; use a local adapter")
            text=content.decode("utf-8-sig")
            require(not text.lstrip().startswith(("<","{")),"Source did not return a CSV; inspect it before importing")
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(content)
            record={"url":url,"final_url":response.url,"fetched_at":now(),"sha256":file_hash(target),"path":str(target),"bytes":len(content),"status":"downloaded, not yet normalized or validated"}
        store.append("data_acquired",label,record)
        return record
    except Exception as exc:
        store.append("data_acquisition_failed",label,{"error_type":type(exc).__name__})
        raise
