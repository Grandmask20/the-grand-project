"""The detector models use skops: only the classes a trained model is made of may be loaded."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "program"))
import atlas_detect as ad  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(name)


for k in ("maps", "badges", "towers", "fortress"):
    try:
        m = ad.load_model(k)
        check(f"shipped model '{k}' loads", m is not None, type(m).__name__)
    except ad.UnsafeModel as e:
        check(f"shipped model '{k}' loads", False, str(e))

import os  # noqa: E402
import pickle  # noqa: E402

import skops.io as sio  # noqa: E402


class _PickleSystem:                       # an old-style pickle that would run a command when loaded
    def __reduce__(self):
        return (os.system, ("echo this must never run",))


attacks = [("invalid model archive", b"not a skops model"),
           ("old pickle with os.system", pickle.dumps(_PickleSystem())),
           ("skops archive with os.system", sio.dumps(os.system)),
           ("skops archive with eval inside a model dict", sio.dumps({"clf": eval, "names": ["x"]}))]
for label, blob in attacks:
    try:
        ad.safe_model_loads(blob)
        check(f"{label} refused", False, "it was loaded")
    except ad.UnsafeModel as e:
        check(f"{label} refused", True, str(e).split(",")[0][:80])

print("PASS: model loading is restricted" if not fails else f"FAILED: {fails}")
if "pytest" in sys.modules:                # under pytest: a failure, not an exit
    assert not fails, "see the FAIL lines above"
else:
    sys.exit(1 if fails else 0)
