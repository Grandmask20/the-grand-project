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

try:
    ad.safe_model_loads(b"not a skops model")
    check("invalid model archive refused", False, "it was loaded")
except ad.UnsafeModel as e:
    check("invalid model archive refused", True, str(e))

print("PASS: model loading is restricted" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
