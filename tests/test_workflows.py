import copy
import unittest
from pathlib import Path

from support import temporary_workspace
from machine.common import MachineError,digest
from machine.store import Store
from machine.examples import create_examples,example_config,example_policy
from machine.research import initialize,run,dataset,commit_plan,sign_spec,reproduce,trial_statistics
from machine.operations import shadow_propose,shadow_decide,reconcile,review_history
from machine.reporting import report
from machine.data import load_csv
from machine.intake import create_intake,answer,status,accept_intake,QUESTIONS
from machine.expressions import evaluate,parse


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=temporary_workspace()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.paths=create_examples(self.root/"fixtures")
        self.store=Store(self.root/"case")
        initialize(self.store,example_config(),{k:self.paths[k] for k in ("training","validation","holdout")},example_policy())

    def test_holdout_cannot_be_read_before_signature(self):
        with self.assertRaisesRegex(MachineError,"permit"):
            dataset(self.store,"holdout",["ALPHA","BETA"])
        with self.assertRaisesRegex(MachineError,"locked"):
            run(self.store,period="holdout",purpose="holdout")
        self.assertEqual(len(self.store.events("run_failed")),1)

    def test_two_changes_and_cost_changes_rejected_and_logged(self):
        baseline=run(self.store)
        c=example_config()
        c["strategy"]["params"]["lookback"]=8
        c["strategy"]["params"]["allocation"]=.3
        with self.assertRaisesRegex(MachineError,"exactly one"):
            run(self.store,c,baseline=baseline["run_id"])
        c=example_config()
        c["costs"]["ALPHA"]["spread_bps"]=0
        with self.assertRaisesRegex(MachineError,"stay locked"):
            run(self.store,c,baseline=baseline["run_id"])
        self.assertEqual(len(self.store.events("run_started")),3)
        self.assertEqual(len(self.store.events("run_failed")),2)

    def test_full_sign_holdout_shadow_and_reproduction(self):
        commit_plan(self.store,"Fixture","Test mandate",synthetic=True)
        baseline=run(self.store)
        for n in (8,20):
            c=example_config()
            c["strategy"]["params"]["lookback"]=n
            run(self.store,c,baseline=baseline["run_id"])
        run(self.store,period="validation",purpose="validation")
        spec=sign_spec(self.store,baseline["run_id"],"Fixture","Verify sign-off workflow",synthetic=True)
        self.assertGreaterEqual(spec["continuation"]["new_sessions"],250)
        self.assertEqual(spec["trials"]["count"],4)
        h=run(self.store,period="holdout",purpose="holdout")
        with self.assertRaisesRegex(ValueError,"Already consumed"):
            run(self.store,period="holdout",purpose="holdout")
        self.assertTrue(reproduce(self.store,h["run_id"])["matched"])
        rows=load_csv(self.paths["shadow"],["ALPHA","BETA"])
        proposal=shadow_propose(self.store,rows)
        result=shadow_decide(self.store,proposal["proposal_id"],True,"Fixture","Accept fixture",synthetic=True)
        with self.assertRaisesRegex(MachineError,"already decided"):
            shadow_decide(self.store,proposal["proposal_id"],True,"Fixture","Duplicate",synthetic=True)
        row=result["daily"][-1]
        bad={"date":row["date"],"cash":row["cash"]-1,"units":row["units"],"provenance":"synthetic_fixture"}
        self.assertFalse(reconcile(self.store,bad)["matched"])
        self.assertEqual(len(self.store.events("incident")),1)
        report_path=report(self.store)["report"]
        self.assertIn("SYNTHETIC DEMONSTRATION",Path(report_path).read_text(encoding="utf-8"))

    def test_history_locked_until_risk_plan(self):
        with self.assertRaisesRegex(MachineError,"dated risk plan"):
            review_history(self.store,{},"external")

    def test_modified_data_stops_run(self):
        path=self.store.root/"data"/"training.csv"
        path.write_text(path.read_text()+"\n",encoding="utf-8")
        with self.assertRaisesRegex(MachineError,"data changed"):
            run(self.store)


class IntakeExpressionTests(unittest.TestCase):
    def test_natural_language_requires_agreement(self):
        with temporary_workspace() as root:
            s=Store(root)
            create_intake(s,"Buy a diversified portfolio when a sufficiently strong trend develops.")
            self.assertFalse(status(s)["ready"])
            with self.assertRaisesRegex(MachineError,"outstanding"):
                accept_intake(s,example_config(),example_policy(),"Owner","Reviewed")
            answer(s,{k:"Explicit fixture answer: "+q for k,q in QUESTIONS.items()})
            accept_intake(s,example_config(),example_policy(),"Fixture","Fixture translation")
            self.assertTrue(status(s)["accepted"])

    def test_expression_rejects_code_and_lookahead(self):
        for expression in ("__import__('os').system('anything')","price(symbol).__class__","[x for x in []]"):
            with self.assertRaises((MachineError,SyntaxError)):
                parse(expression)
        with self.assertRaisesRegex(MachineError,"nonnegative"):
            evaluate("price(symbol, -1)",[],{},"ALPHA",["ALPHA"])

    def test_expression_uses_completed_history(self):
        from machine.data import frames_from_rows
        from machine.examples import synthetic_rows
        history=frames_from_rows(synthetic_rows(25))
        result=evaluate("param('weight') if price(symbol) > sma(symbol, 10) else 0",history,{"weight":.2},"ALPHA",["ALPHA","BETA"])
        self.assertIn(result,(0,.2))


if __name__=="__main__":
    unittest.main()
