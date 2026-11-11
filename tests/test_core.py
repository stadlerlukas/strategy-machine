import copy
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from machine.common import MachineError, digest
from machine.config import validate_config, validate_policy
from machine.data import validate_rows
from machine.engine import simulate
from machine.examples import example_config, example_policy, synthetic_rows
from machine.metrics import correlation, deflated_sharpe, effective_trials, sharpe
from machine.risk import check_order, red_team
from machine.store import Store
from support import temporary_workspace


def one_asset_config(weight=0.5):
    c=example_config()
    c["universe"]=["ALPHA"]
    c["costs"]={"ALPHA":c["costs"]["ALPHA"]}
    c["strategy"]={"kind":"constant","params":{"weight":weight}}
    c["initial_nav"]=1000.0
    for f in ("spread_bps","commission_bps","slippage_bps","fixed_fee","long_financing_annual","short_financing_annual","borrow_annual"):
        c["costs"]["ALPHA"][f]=0.0
    return c


def bar(day,opening,closing,**kwargs):
    return {"date":day,"symbol":"ALPHA","open":opening,"close":closing,"split":1.0,"dividend":0.0,"settlement":None,"status":"active",**kwargs}


class AccountingTests(unittest.TestCase):
    def test_next_open_and_fee_by_hand(self):
        c=one_asset_config()
        c["costs"]["ALPHA"]["commission_bps"]=10
        result=simulate(c,[bar("2025-01-02",100,100),bar("2025-01-03",100,110)])
        self.assertEqual(len(result["orders"]),1)
        self.assertAlmostEqual(result["daily"][-1]["nav"],1049.5)
        self.assertAlmostEqual(result["metrics"]["transaction_cost"],.5)
        self.assertEqual(result["orders"][0]["date"],"2025-01-03")

    def test_split_and_dividend_do_not_create_phantom_loss(self):
        c=one_asset_config()
        c["holding"]["rebalance_every"]=99
        r=simulate(c,[bar("2025-01-02",100,100),bar("2025-01-03",100,100),bar("2025-01-06",50,50,split=2,dividend=1)])
        self.assertAlmostEqual(r["daily"][-1]["nav"],1010)
        self.assertEqual(r["daily"][-1]["units"]["ALPHA"],10)

    def test_weekend_financing(self):
        c=one_asset_config()
        c["holding"]["rebalance_every"]=99
        c["costs"]["ALPHA"]["long_financing_annual"]=.365
        r=simulate(c,[bar("2025-01-02",100,100),bar("2025-01-03",100,100),bar("2025-01-06",100,100)])
        self.assertAlmostEqual(r["metrics"]["financing_cost"],1.5)

    def test_zero_settlement_delisting(self):
        c=one_asset_config()
        r=simulate(c,[bar("2025-01-02",100,100),bar("2025-01-03",100,100),bar("2025-01-06",0,0,status="delisted",settlement=0)])
        self.assertEqual(r["daily"][-1]["nav"],500)
        self.assertEqual(r["daily"][-1]["units"]["ALPHA"],0)

    def test_halt_prevents_fill(self):
        c=one_asset_config()
        r=simulate(c,[bar("2025-01-02",100,100),bar("2025-01-03",100,100,status="halted")])
        self.assertEqual(r["orders"][0]["status"],"blocked")
        self.assertEqual(r["daily"][-1]["cash"],1000)

    def test_short_pnl(self):
        c=one_asset_config(-.5)
        r=simulate(c,[bar("2025-01-02",100,100),bar("2025-01-03",100,90)])
        self.assertEqual(r["daily"][-1]["nav"],1050)

    def test_incremental_equals_whole(self):
        c=example_config()
        rows=synthetic_rows(45)
        whole=simulate(c,rows)
        state=None
        for i in range(0,len(rows),2):
            part=simulate(c,rows[i:i+2],initial_state=state)
            state=part["state"]
        self.assertEqual(digest(whole),digest(part))

    def test_future_close_cannot_change_same_open_order(self):
        c=example_config()
        rows=synthetic_rows(40)
        a=simulate(c,rows)
        changed=copy.deepcopy(rows)
        changed[-1]["close"]*=2
        b=simulate(c,changed)
        self.assertEqual(a["orders"],b["orders"])


class RiskAndDataTests(unittest.TestCase):
    def test_missing_fee_is_error(self):
        c=example_config()
        del c["costs"]["ALPHA"]["borrow_annual"]
        with self.assertRaisesRegex(MachineError,"Missing fee"):
            validate_config(c)

    def test_nan_rejected(self):
        rows=synthetic_rows(3)
        rows[0]["close"]=float("nan")
        with self.assertRaises(MachineError):
            validate_rows(rows,["ALPHA","BETA"])

    def test_missing_session_instrument_rejected(self):
        rows=synthetic_rows(3)
        del rows[2]
        with self.assertRaisesRegex(MachineError,"Incomplete session"):
            validate_rows(rows,["ALPHA","BETA"])

    def test_risk_red_team(self):
        self.assertTrue(red_team(example_policy())["passed"])

    def test_drawdown_blocks_entry_but_allows_exit(self):
        p=example_policy()
        self.assertFalse(check_order({}, {"ALPHA":.1},p,drawdown=.3,order_value=1000,symbol="ALPHA")["allowed"])
        self.assertTrue(check_order({"ALPHA":.1},{"ALPHA":0},p,drawdown=.3,order_value=1000,symbol="ALPHA")["allowed"])


class StoreAndStatsTests(unittest.TestCase):
    def test_append_only_and_hash_verification(self):
        with temporary_workspace() as d:
            store=Store(d)
            store.put({"value":3})
            store.append("sample","a",{"answer":4},claim="one")
            self.assertTrue(store.verify()["valid"])
            with self.assertRaises(ValueError):
                store.append("sample","a",{},claim="one")
            with self.assertRaises(sqlite3.IntegrityError):
                with store.connect() as db:
                    db.execute("DELETE FROM events")

    def test_undefined_sharpe_is_not_zero(self):
        self.assertIsNone(sharpe([0,0,0]))
        self.assertIsNone(deflated_sharpe([0]*40,[1,2],2))

    def test_effective_count_identical_series(self):
        a=[.01,-.01,.02,-.02,.03]
        self.assertAlmostEqual(effective_trials([a,a,a]),1)

    def test_multiple_testing_reduces_probability(self):
        a=[.012,-.008,.02,-.01,.002]*30
        self.assertGreater(deflated_sharpe(a,[.2,1,2],3),deflated_sharpe(a,[.2,1,2],50))


if __name__=="__main__":
    unittest.main()
