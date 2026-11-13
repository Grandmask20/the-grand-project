"""The detector models live in the database as pickles: only the classes a trained model is made of may be
loaded, so a tampered database cannot run code (needs no test data)."""
import os
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "program"))
import atlas_detect as ad  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(name)


class _System:
    def __reduce__(self):
        return (os.system, ("echo this must never run",))


class _Eval:
    def __reduce__(self):
        return (eval, ("print('this must never run')",))


for k in ("maps", "badges", "towers", "fortress"):
    try:
        m = ad.load_model(k)
        check(f"shipped model '{k}' loads", m is not None, type(m).__name__)
    except ad.UnsafeModel as e:
        check(f"shipped model '{k}' loads", False, str(e))

for evil in (_System(), _Eval()):
    try:
        ad.safe_model_loads(pickle.dumps(evil))
        check(f"{type(evil).__name__} payload refused", False, "it was loaded")
    except ad.UnsafeModel as e:
        check(f"{type(evil).__name__} payload refused", True, str(e).split(",")[0])

print("PASS: model loading is restricted" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
