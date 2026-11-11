from __future__ import annotations

import csv
import html
from pathlib import Path

from .common import now, write_json
from .research import base_config, project, result_for, reproduce, trial_statistics, export_trials
from .operations import committed, review_history


def fmt(value):
    if value is None:
        return "Not available"
    if isinstance(value,float):
        return f"{value:,.4f}"
    return str(value)


def table(headers,rows):
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(fmt(c))+'</td>' for c in r)+'</tr>' for r in rows)+'</tbody></table></div>'


def chart(daily):
    if not daily:
        return '<p>No observations yet.</p>'
    vals=[r["nav"] for r in daily]
    low,high=min(vals),max(vals)
    spread=high-low or max(high*.01,1)
    points=' '.join(f'{32+i*836/max(1,len(vals)-1):.1f},{180-(v-low)*140/spread:.1f}' for i,v in enumerate(vals))
    return f'<svg viewBox="0 0 900 215" role="img" aria-label="Portfolio net asset value over the observed sessions"><line x1="32" y1="180" x2="868" y2="180" stroke="#d8e3dc"/><polyline points="{points}" fill="none" stroke="#137855" stroke-width="2.5"/><text x="32" y="205">{html.escape(daily[0]["date"])}</text><text x="770" y="205">{html.escape(daily[-1]["date"])}</text><text x="32" y="23">NAV {low:,.2f} – {high:,.2f}</text></svg>'


STYLE='''body{margin:0;background:#f4f5f1;color:#20332c;font:15px/1.55 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:38px 24px 70px}header{border-bottom:1px solid #cad7ce;padding-bottom:25px;margin-bottom:25px}.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:11px;font-weight:750;color:#507467}h1{font-size:38px;margin:8px 0;letter-spacing:-1.4px}h2{font-size:21px;margin-top:0}h3{font-size:16px}.subtle{color:#61736b}.badge{display:inline-block;padding:5px 10px;border-radius:6px;background:#f8e7c5;color:#624609;font-size:12px;font-weight:700}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card,section{background:white;border:1px solid #d9e1d9;border-radius:12px;padding:22px;margin-bottom:20px}.big{font-size:29px;font-weight:700;letter-spacing:-.8px}.label{font-size:12px;color:#53675d}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}td,th{text-align:left;padding:11px 9px;border-bottom:1px solid #edf0eb;vertical-align:top}th{color:#4c6557;font-size:11px;text-transform:uppercase;letter-spacing:.05em}svg{width:100%;background:#fbfcf9;border-radius:8px}svg text{font:11px system-ui;fill:#66796c}code{font-size:12px;overflow-wrap:anywhere}a{color:#12684d}details{margin:10px 0}summary{cursor:pointer;font-weight:650}footer{font-size:12px;color:#61736b}li{margin:7px 0}@media(max-width:720px){.grid{grid-template-columns:repeat(2,1fr)}h1{font-size:29px}main{padding:20px 12px}section{padding:15px}}'''


def report(store):
    config=base_config(store)
    completed=store.events("run_completed")
    # Report-last: regenerate the engine outputs in this invocation before prose.
    runs=[]
    for e in completed:
        reproduce(store,e["entity"])
        runs.append(result_for(store,e["entity"]))
    shadow,_=committed(store)
    if shadow:
        # Replay all approvals and rejections from immutable observations, not cached state.
        from .engine import simulate
        state=None
        for event in store.events("shadow_committed","book"):
            if event["payload"].get("forward"):
                proposal_id=event["payload"]["proposal_id"]
                decision=store.latest("forward_decided",proposal_id)
                prop_event=store.latest("forward_open_proposed",proposal_id)
                prop=store.get(prop_event["payload"]["proposal"])
                close_event=store.latest("forward_closed",proposal_id)
                snapshot=store.get(close_event["payload"]["close_snapshot"])
                if state is None and prop.get("prior_result"):
                    state=store.get(prop["prior_result"])["state"]
                replay=simulate(store.get(prop["config"]),snapshot["rows"],store.get(prop["policy"]),state,decision["payload"]["approved"])
            else:
                decision=store.latest("shadow_decided",event["payload"]["proposal_id"])
                prop_event=store.latest("shadow_proposed",event["payload"]["proposal_id"])
                prop=store.get(prop_event["payload"]["proposal"])
                replay=simulate(store.get(prop["config_hash"]),store.get(prop["rows"]),store.get(prop["policy_hash"]),state,decision["payload"]["approved"])
            from .common import digest,require
            require(digest(replay)==digest(store.get(event["payload"]["result"])),"Shadow replay mismatch")
            state=replay["state"]
        shadow=replay
        store.append("shadow_reproduced","book",{"result_hash":digest(shadow)})
    selected=shadow or (runs[-1] if runs else None)
    review=review_history(store,selected,"shadow" if shadow else "research") if selected and store.latest("risk_plan_committed","main") else None
    signed=store.latest("spec_signed","main")
    spec=store.get(signed["payload"]["spec"]) if signed else None
    chosen_id=spec["chosen_run"] if spec else next((r["run_id"] for r in runs if r["period"]=="training"),None)
    stats=trial_statistics(store,chosen_id,spec["ledger_through"] if spec else None) if chosen_id else {}
    if spec:
        from .common import require,digest
        require(digest(stats)==digest(spec["trials"]),"Signed trial statistics do not reproduce")
    audit=store.verify()
    metrics=selected["metrics"] if selected else {}
    from .forward import progress
    forward_status=progress(store)
    daily=selected["daily"] if selected else []
    badge="SYNTHETIC DEMONSTRATION · NO ACCOUNT CONNECTED" if config["provenance"]=="synthetic" else "RESEARCH / SHADOW · NO REAL ORDERS"
    cards=''.join(f'<div class="card"><div class="label">{label}</div><div class="big">{html.escape(fmt(metrics.get(key)))}</div></div>' for label,key in [("Net Sharpe","net_sharpe"),("Max drawdown (fraction)","max_drawdown"),("Turnover / year","turnover"),("Break-even bps / side","break_even_cost_bps")])
    run_table=table(["Run","Period","Change","Gross SR","Net SR","Turnover/y","Break-even bps"],[[r["run_id"],r["period"]+' ('+r['daily'][0]['date']+' to '+r['daily'][-1]['date']+')',('chronological fold '+str(r['fold'])) if r.get('fold') else (', '.join(r["changes"]) or 'full-period baseline'),r["metrics"]["gross_sharpe"],r["metrics"]["net_sharpe"],r["metrics"]["turnover"],r["metrics"]["break_even_cost_bps"]] for r in runs])
    risk_table=table(["Measure","Observed","Planned range","Assessment","Why it matters"],[[f["metric"],f["value"],f["range"],f["status"],f["why"]] for f in review["findings"]]) if review else '<p>Commit the dated risk plan before inspecting a history.</p>'
    ops=store.events("shadow_proposed")
    ops_rows=[]
    for e in ops:
        prop=store.get(e["payload"]["proposal"])
        dec=store.latest("shadow_decided",e["entity"])
        ops_rows.append([prop["date"],e["entity"],len(prop["orders"]),prop["expected_cost"],('approved' if dec["payload"]["approved"] else 'rejected') if dec else 'pending',dec["payload"]["by"] if dec else '—'])
    for e in store.events("forward_open_proposed"):
        prop=store.get(e["payload"]["proposal"])
        dec=store.latest("forward_decided",e["entity"])
        ops_rows.append([prop["session_date"],e["entity"],len(prop["orders"]),sum(o.get("cost",0) for o in prop["orders"]),("approved" if dec["payload"]["approved"] else "rejected") if dec else "pending",dec["payload"]["by"] if dec else "—"])
    ranges=table(["Metric","Signed range","Observed","Assessment"],[[k,bounds,metrics.get(k),"unavailable" if metrics.get(k) is None else ("within" if bounds[0]<=metrics[k]<=bounds[1] else "outside")] for k,bounds in spec["expected"].items()]) if spec else "<p>No signed expectations yet.</p>"
    rec=store.events("reconciliation")
    reconciliations=table(["Date","Matched","Source","Differences"],[[e["payload"]["date"],e["payload"]["matched"],e["payload"]["provenance"],e["payload"]["differences"]] for e in rec])
    attribution={s:sum(d["instrument_gross_pnl"].get(s,0) for d in daily) for s in config["universe"]} if daily else {}
    attr=table(["Contribution","Amount"],[[s+" gross P&L",v] for s,v in attribution.items()]+[["Transaction costs",-metrics.get("transaction_cost",0)],["Financing / borrow",-metrics.get("financing_cost",0)]])
    body=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Strategy Machine · {html.escape(config['name'])}</title><style>{STYLE}</style></head><body><main>
<header><div class="eyebrow">Strategy Machine / Evidence & operations</div><h1>{html.escape(config['name'])}</h1><p class="subtle">{html.escape(config['hypothesis'])}</p><span class="badge">{badge}</span><p class="subtle">Generated {now()} · {'Shadow account' if shadow else 'Latest research run'} · {len(daily)} observed sessions</p></header>
<div class="grid">{cards}</div>
<section><h2>Portfolio path</h2>{chart(daily)}<p class="subtle">{html.escape(metrics.get('conventions','No results yet.'))}</p><p>Sharpe descriptive block-bootstrap interval: {html.escape(fmt(metrics.get('sharpe_95pct_block_bootstrap')))}. A short replay does not establish forward performance.</p></section>
<section><h2>Research evidence</h2>{run_table}<p>Declared research attempts: {stats.get('count','—')}. Effective-trial heuristic: {fmt(stats.get('effective_count'))}. Deflated Sharpe probability: {fmt(stats.get('deflated_sharpe'))}.</p><p class="subtle">{html.escape(stats.get('scope',''))} {html.escape(stats.get('dsr_method',''))}</p><p><a href="trials.csv">Complete trial log, including failures</a> · <a href="evidence.json">Machine-readable evidence</a></p></section>
<section><h2>Comparison with signed expectations</h2>{ranges}<p>These are descriptive sensitivity ranges, not predictive confidence intervals.</p></section><section><h2>Risk review</h2>{risk_table}<p>Current rules triggered: {html.escape(fmt(review['current_rule_breaches'] if review else []))}.</p><p>Shared drivers: {html.escape(fmt(review['shared_driver_groups'] if review else {}))}.</p><p class="subtle">This is the deterministic review. AI interpretation is optional and never enforces limits. Official eToro risk score is unavailable unless supplied from the platform.</p></section>
<section><h2>Shadow operations</h2>{table(['Session','Proposal','Order proposals','Expected cost','Decision','Actor'],ops_rows)}<p>Observed forward sessions: {forward_status['observed_forward_sessions']}. Five-session requirement met: {forward_status['five_session_requirement_met']}.</p><h3>Reconciliation</h3>{reconciliations}<p>Historical/synthetic replay sessions are not elapsed forward trading days. Approval records identify fixture approvals explicitly.</p></section>
<section><h2>Attribution and costs</h2>{attr}<p>Beta to equal-weight universe: {fmt(metrics.get('beta_to_equal_weight_universe'))}. Annual arithmetic residual: {fmt(metrics.get('annual_arithmetic_residual'))}. This is descriptive attribution, not proof of alpha.</p></section>
<section><h2>Audit and next decision</h2><p>Verified {audit['events']} append-only events and {audit['objects']} content-addressed artifacts.</p><p>Ledger head: <code>{audit['head']}</code></p><p>Owner decision: {html.escape(fmt(store.events('human_decision')[-1]['payload'] if store.events('human_decision') else 'Pending. Choose keep, adjust, pause or manual after checking evidence.'))}</p><details><summary>Operating limitations</summary><ul>{''.join('<li>'+html.escape(s)+'</li>' for s in (selected or {}).get('limitations',[]))}</ul></details></section>
<footer>All numerical tables are regenerated before this report is written. Hash chaining detects accidental or partial edits; a machine owner can rewrite local storage. Retain independent backups. Demo evidence is not investment performance.</footer></main></body></html>'''
    dest=store.root/"report.html"
    dest.write_text(body,encoding="utf-8")
    export_trials(store)
    evidence={"generated_at":now(),"provenance":config["provenance"],"metrics":metrics,"trials":stats,"review":review,"audit":audit}
    evidence["forward_observation"]=forward_status
    if spec:
        evidence["comparison_to_signed_ranges"]={k:{"observed":metrics.get(k),"expected":bounds,"status":"missing" if metrics.get(k) is None else ("within" if bounds[0]<=metrics[k]<=bounds[1] else "outside")} for k,bounds in spec["expected"].items()}
    write_json(store.root/"evidence.json",evidence)
    monthly=f"Performance review generated {now()}\nEvidence type: {config['provenance']}.\nObserved sessions: {len(daily)}.\nNet return: {fmt(metrics.get('net_return'))}. Net Sharpe: {fmt(metrics.get('net_sharpe'))}.\nMaximum drawdown: {fmt(metrics.get('max_drawdown'))}.\nTransaction costs: {fmt(metrics.get('transaction_cost'))}; financing: {fmt(metrics.get('financing_cost'))}.\n\nThese are computed observations. The owner must verify explanations and decide whether to keep, adjust, pause or trade manually. No claim of skill follows from this summary.\n"
    (store.root/"performance-note.txt").write_text(monthly,encoding="utf-8")
    if daily:
        (store.root/f"daily-report-{daily[-1]['date']}.html").write_text(body,encoding="utf-8")
    return {"report":str(dest),"evidence":str(store.root/"evidence.json"),"metrics":metrics}


def daily_report(store,result,proposal_id,provenance):
    """Write a factual session report immediately after a calculated book commit."""
    row=result["daily"][-1]
    today=[o for o in result["orders"] if o["date"]==row["date"]]
    facts={"generated_at":now(),"provenance":provenance,"proposal_id":proposal_id,"portfolio":row}
    write_json(store.root/f"daily-{row['date']}.json",facts)
    body=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Daily evidence {row['date']}</title><style>{STYLE}</style><main><header><div class="eyebrow">Strategy Machine / Daily evidence</div><h1>{row['date']}</h1><span class="badge">{html.escape(provenance)}</span></header><section><h2>Account observation</h2>{table(['Measure','Value'],[[k,row[k]] for k in ('nav','cash','net_return','gross_return','transaction_cost','financing','turnover','trades')])}<p>Proposal: {html.escape(proposal_id)}. This is paper accounting; no brokerage order was sent.</p></section><section><h2>Order decisions</h2>{table(['Instrument','Units','Status','Blocking rules'],[[o['symbol'],o['units'],o['status'],o['rules']] for o in today])}</section><section><h2>Risk and missing information</h2><p>{html.escape(str(row['risk_breaches']))}</p><p>{html.escape(str(row['risk_data_gaps']))}</p><p>Independent reconciliation and the owner's next decision are recorded separately in the case ledger.</p></section></main></html>'''
    (store.root/f"daily-report-{row['date']}.html").write_text(body,encoding="utf-8")
    store.append("daily_report_written",row["date"],{"proposal_id":proposal_id,"facts":store.put(facts),"provenance":provenance})
