import argparse
import json
import sys
from pathlib import Path

from .common import read_json


def main(argv=None):
    parser=argparse.ArgumentParser(description="Strategy Machine — written ideas, reproducible research and controlled shadow operation")
    sub=parser.add_subparsers(dest="command",required=True)
    s=sub.add_parser("serve",help="Open the local application")
    s.add_argument("--root",default="workspaces")
    s.add_argument("--port",type=int,default=8877)
    s.add_argument("--no-open",action="store_true")
    d=sub.add_parser("demo",help="Build a complete synthetic demonstration")
    d.add_argument("--output",default="workspaces/demo-trend")
    d.add_argument("--kind",choices=["momentum","mean_reversion"],default="momentum")
    d.add_argument("--sessions",type=int,default=18)
    e=sub.add_parser("examples",help="Generate labelled synthetic fixtures")
    e.add_argument("--output",default="examples/generated")
    r=sub.add_parser("reproduce",help="Regenerate results and reports from a case in a clean source copy")
    r.add_argument("--workspace",required=True)
    a=sub.add_parser("action",help="Execute one documented application action")
    a.add_argument("--root",default="workspaces")
    a.add_argument("--case",required=True)
    a.add_argument("action")
    a.add_argument("--args",help="JSON file containing action arguments")
    st=sub.add_parser("status",help="Inspect a case")
    st.add_argument("--root",default="workspaces")
    st.add_argument("--case",required=True)
    t=sub.add_parser("test",help="Run the acceptance tests")
    n=sub.add_parser("normalize",help="Normalize an explicitly mapped vendor CSV")
    n.add_argument("--input",required=True)
    n.add_argument("--mapping",required=True)
    n.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=="serve":
            from .server import serve
            serve(args.root,args.port,not args.no_open)
            return 0
        if args.command=="demo":
            from .demo import build_demo
            result=build_demo(args.output,args.kind,args.sessions,lambda s:print(s,flush=True))
        elif args.command=="examples":
            from .examples import create_examples
            result=create_examples(args.output)
        elif args.command=="reproduce":
            from .reporting import report
            from .store import Store
            result=report(Store(args.workspace))
        elif args.command=="action":
            from .application import Application
            result=Application(args.root).action(args.case,args.action,read_json(args.args) if args.args else {})
        elif args.command=="status":
            from .application import Application
            result=Application(args.root).state(args.case)
        elif args.command=="normalize":
            from .normalization import normalize_csv
            result=normalize_csv(args.input,read_json(args.mapping),args.output)
        elif args.command=="test":
            import unittest
            folder=Path(__file__).resolve().parents[1]/"tests"
            sys.path.insert(0,str(folder))
            suite=unittest.defaultTestLoader.discover(str(folder))
            passed=unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
            return 0 if passed else 1
        print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
        return 0
    except (ValueError,KeyError,OSError,TypeError) as exc:
        print(f"Action stopped: {exc}",file=sys.stderr)
        return 2


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
