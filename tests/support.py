import os
import tempfile
from pathlib import Path


def temporary_workspace():
    root=Path(os.environ.get("STRATEGY_MACHINE_TEST_ROOT",Path(__file__).resolve().parents[1]/".test-work")).resolve()
    root.mkdir(parents=True,exist_ok=True)
    # TemporaryDirectory only cleans its own generated child of this checked root.
    return tempfile.TemporaryDirectory(dir=root,prefix="case-")
