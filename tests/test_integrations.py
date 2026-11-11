import copy
import json
import os
import threading
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from support import temporary_workspace
from machine.common import MachineError,digest
from machine.examples import create_examples,example_config,example_policy,synthetic_rows
from machine.store import Store
from machine.research import initialize,commit_plan,run,walk_forward,reproduce
from machine.forward import propose_open,decide_open,close_session,recover_close,progress,seed_history
from machine.operations import shadow_propose
from machine.risk import check_order
from machine.normalization import normalize_csv
from machine.data import load_csv
from machine.etoro import EToroReader,normalize_snapshot
from machine.agents import ask_openai,research_loop,ai_review
from machine.intake import create_intake,advise,status,answer,QUESTIONS,propose_implementation
from machine.server import create_server


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=temporary_workspace(); self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name); self.store=Store(root/'case')
        paths=create_examples(root/'fixtures'); c=example_config();c['provenance']='historical';c['strategy']={'kind':'constant','params':{'weight':.15}}
        initialize(self.store,c,{k:paths[k] for k in ('training','validation','holdout')},example_policy())
        commit_plan(self.store,'Test owner','Test fixture',False)
        # Deliberate test fixture: sign-off gates themselves are exercised in WorkflowTests.
        self.store.append('spec_signed','main',{'spec':self.store.put({'config_hash':self.store.put(c)})})
        self.open_time=datetime(2026,11,3,9,tzinfo=timezone.utc)
        seed_history(self.store,synthetic_rows(40,start='2026-08-03'),self.open_time)
        self.snapshot={'stage':'open','observed_at':self.open_time.isoformat(),'session_date':'2026-11-03','source':'unit-test observed feed fixture','provenance':'forward_observed','rows':[{'date':'2026-11-03','symbol':s,'open':100.,'close':100.,'status':'active','split':1.,'dividend':0.,'settlement':None} for s in ('ALPHA','BETA')]}

    def test_open_decision_close_and_idempotent_recovery(self):
        p=propose_open(self.store,self.snapshot,self.open_time)
        self.assertTrue(any(o['status']=='filled_shadow' for o in p['orders']))
        decide_open(self.store,p['proposal_id'],True,'Fixture','Test',self.open_time+timedelta(seconds=2))
        closing=copy.deepcopy(self.snapshot);closing['stage']='close';closing['observed_at']=(self.open_time+timedelta(hours=7)).isoformat()
        for r in closing['rows']:r['close']=101.
        append=self.store.append
        def interrupted(kind,*args,**kwargs):
            if kind=='shadow_committed':raise OSError('simulated interruption')
            return append(kind,*args,**kwargs)
        with patch.object(self.store,'append',side_effect=interrupted):
            with self.assertRaises(OSError):close_session(self.store,p['proposal_id'],closing,self.open_time+timedelta(hours=7))
        self.assertEqual(progress(self.store)['observed_forward_sessions'],0)
        out=recover_close(self.store,p['proposal_id'])
        self.assertEqual(digest(out),digest(recover_close(self.store,p['proposal_id'])))
        self.assertEqual(len(out['daily']),1)
        self.assertEqual(progress(self.store)['observed_forward_sessions'],1)
        self.assertEqual(len(self.store.events('shadow_committed')),1)
        with self.assertRaisesRegex(MachineError,'separate case'):shadow_propose(self.store,self.snapshot['rows'])

    def test_stale_snapshot_and_expired_approval(self):
        with self.assertRaisesRegex(MachineError,'stale'):propose_open(self.store,self.snapshot,self.open_time+timedelta(hours=1))
        p=propose_open(self.store,self.snapshot,self.open_time)
        with self.assertRaisesRegex(MachineError,'expired'):decide_open(self.store,p['proposal_id'],True,'Fixture','Test',self.open_time+timedelta(minutes=11))
        decide_open(self.store,p['proposal_id'],False,'Fixture','Expired',self.open_time+timedelta(minutes=11))

    def test_future_close_cannot_enter_open_proposal(self):
        self.snapshot['rows'][0]['close']=105.
        with self.assertRaisesRegex(MachineError,'future closes'):propose_open(self.store,self.snapshot,self.open_time)


class AdapterTests(unittest.TestCase):
    def test_broker_reads_only_fixed_hosts_and_routes(self):
        calls=[]
        def send(req):calls.append(req);return []
        with patch.dict(os.environ,{'ETORO_API_KEY':'fixture-app','ETORO_USER_KEY':'fixture-user'}):
            reader=EToroReader('demo',send)
            reader.get('portfolio')
            reader.get('history',{'minDate':datetime.now(timezone.utc).date().isoformat(),'page':1,'pageSize':100})
            with self.assertRaises(MachineError):reader.get('orders')
            with self.assertRaises(MachineError):reader.get('history',{'minDate':'2000-01-01'})
        self.assertTrue(all(r.method=='GET' for r in calls))
        self.assertTrue(calls[0].full_url.endswith('/trading/info/demo/portfolio'))
        self.assertIn('/trading/info/trade/demo/history?',calls[1].full_url)
        self.assertEqual(calls[0].get_header('X-api-key'),'fixture-app')

    def test_broker_mapping_requires_signed_units(self):
        raw={'raw':{'cash':100,'positions':[{'id':1,'q':-2}]},'fetched_at':'fixture'}
        mapping={'cash':'cash','positions':'positions','instrument_id':'id','signed_units':'q','symbols':{'1':'ALPHA'},'as_of_date':'2026-11-03'}
        with self.assertRaisesRegex(MachineError,'signed unit'):normalize_snapshot(raw,mapping)
        mapping['units_are_signed']=True
        self.assertEqual(normalize_snapshot(raw,mapping)['units']['ALPHA'],-2)

    def test_authenticated_redirect_refused(self):
        from machine.transport import NoRedirect
        with self.assertRaises(HTTPError):NoRedirect().redirect_request(Request('https://api.openai.com/v1/responses'),None,302,'Moved',{},'https://example.com')

    def test_normalizer_requires_explicit_actions_and_preserves_provenance(self):
        with temporary_workspace() as root:
            root=Path(root);p=root/'vendor.csv';p.write_text('Day,Ticker,Open,Close\n2026-01-02,ALPHA,100,101\n')
            m={'currency':'USD','price_adjustment':'unadjusted','columns':{'date':'Day','symbol':'Ticker','open':'Open','close':'Close'},'constants':{'status':'active','split':1,'dividend':0,'settlement':None}}
            result=normalize_csv(p,m,root/'mapped.csv')
            self.assertEqual(result['rows'],1)
            self.assertEqual(load_csv(root/'mapped.csv',['ALPHA'])[0]['close'],101)
            del m['constants']['dividend']
            with self.assertRaisesRegex(MachineError,'dividend'):normalize_csv(p,m,root/'bad.csv')

    def test_warmup_is_explicit_and_reductions_remain_possible(self):
        p=example_policy();p['warmup_mode']='block_increases'
        result=check_order({}, {'ALPHA':.1},p,statistics_available=False,order_value=100)
        self.assertIn('statistical_risk_history_unavailable',result['rules'])
        self.assertTrue(check_order({'ALPHA':.1},{'ALPHA':0},p,statistics_available=False,order_value=100)['allowed'])


class FinalControlTests(unittest.TestCase):
    def test_pause_enables_kill_and_keep_does_not_silently_release(self):
        from machine.operations import record_decision
        with temporary_workspace() as root:
            s=Store(root)
            s.append("history_reviewed","fixture",{"review":s.put({"provenance":"test fixture"})})
            record_decision(s,"pause","Stop the test book","Fixture owner")
            self.assertTrue(s.latest("kill_switch","book")["payload"]["active"])
            record_decision(s,"keep","Keep thesis while stopped","Fixture owner")
            self.assertTrue(s.latest("kill_switch","book")["payload"]["active"])

    def test_inactive_history_is_reported_as_correlation_gap(self):
        from machine.engine import simulate
        rows=synthetic_rows(40)
        rows[70]["status"]="halted"
        result=simulate(example_config(),rows,example_policy())
        self.assertIn("correlation_warmup_or_missing",result["daily"][-1]["risk_data_gaps"])


class AITests(unittest.TestCase):
    def test_provider_payload_and_incomplete_response(self):
        captured=[]
        def send(req):
            captured.append(json.loads(req.data));return {'status':'completed','output':[{'content':[{'type':'output_text','text':'{"answer":"fixture"}'}]}]}
        schema={'type':'object','additionalProperties':False,'properties':{'answer':{'type':'string'}},'required':['answer']}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-key'}):
            self.assertEqual(ask_openai('Explain',{'fact':1},schema,'fixture-model',send),{'answer':'fixture'})
            with self.assertRaisesRegex(MachineError,'incomplete'):ask_openai('Explain',{},schema,'fixture-model',lambda r:{'status':'incomplete'})
        self.assertFalse(captured[0]['store'])
        self.assertNotIn('tools',captured[0])
        self.assertTrue(captured[0]['text']['format']['strict'])

    def test_advice_does_not_accept_answers(self):
        with temporary_workspace() as root:
            s=Store(root);create_intake(s,'Buy only after a clearly defined momentum signal appears.')
            advice={'understanding':'fixture','suggested_answers':[{'field':'universe','answer':'ALPHA','assumption':True}],'questions':['Which universe?'],'data_requirements':[],'capability':'unclear','capability_reason':'Owner input needed'}
            advise(s,advisor=lambda e:advice)
            self.assertEqual(status(s)['answers'],{})
            answer(s,{k:'Explicit fixture answer' for k in QUESTIONS})
            response={'capability':'needs_additional_adapter','expression':'','parameters':[],'explanation':'Ticket state required','assumptions':[],'additional_adapter_work':'Implement ticket-specific holding period'}
            self.assertEqual(propose_implementation(s,designer=lambda e:response)['capability'],'needs_additional_adapter')

    def test_bounded_search_and_walk_forward_reproduce(self):
        with temporary_workspace() as root:
            root=Path(root);paths=create_examples(root/'fixtures');s=Store(root/'case')
            initialize(s,example_config(),{k:paths[k] for k in ('training','validation','holdout')},example_policy())
            baseline=run(s)
            with self.assertRaisesRegex(MachineError,'budget'):research_loop(s,baseline['run_id'],{'lookback':[5,20]},1,planner=lambda e:{'candidates':[{'parameter':'lookback','value':8,'reason':'fixture'},{'parameter':'lookback','value':9,'reason':'fixture'}]})
            results=research_loop(s,baseline['run_id'],{'lookback':[5,20]},1,planner=lambda e:{'candidates':[{'parameter':'lookback','value':8,'reason':'fixture'}]})
            self.assertEqual(len(results),1)
            folds=walk_forward(s,baseline['run_id'],2)
            self.assertLess(folds[0]['end'],folds[1]['start'])
            for fold in folds:self.assertTrue(reproduce(s,fold['run_id'])['matched'])
            self.assertEqual(len(s.events('holdout_opened')),0)


class ServerTests(unittest.TestCase):
    def test_local_csrf_origin_and_path_guards(self):
        with temporary_workspace() as root:
            server=create_server(root,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with urlopen(base) as f:self.assertIn(b'Strategy Machine',f.read())
                body=json.dumps({'case':'new-idea','action':'create','args':{'description':'A sufficiently detailed written strategy idea.'}}).encode()
                with self.assertRaises(HTTPError) as cm:urlopen(Request(base+'/api/action',body,{'Content-Type':'application/json'},method='POST'))
                self.assertEqual(cm.exception.code,403)
                headers={'Content-Type':'application/json','X-CSRF-Token':server.csrf_token,'Origin':base}
                with urlopen(Request(base+'/api/action',body,headers,method='POST')) as f:self.assertEqual(f.status,200)
                headers['Origin']='https://attacker.example'
                with self.assertRaises(HTTPError) as cm:urlopen(Request(base+'/api/action',body,headers,method='POST'))
                self.assertEqual(cm.exception.code,403)
                with self.assertRaises(MachineError):server.app.case_path('../outside')
            finally:
                server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
