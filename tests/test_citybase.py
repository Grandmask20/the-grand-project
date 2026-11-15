"""City barrel detection (grand_project/detect/citybase.py).

    python -m tests.test_citybase

Offline checks of the model file and the feature window, then the shipped model on the hand-labelled screenshots
with known cities (screenshots/random_samples/cities_truth.json, map nodes cached there): it must find nearly
all of them and call almost no other map node a city. (Those screenshots are part of its training: this guards
against a broken model or feature change, the fair score is `python -m grand_project.detect train_cities`.)
"""

from __future__ import annotations

import json
import sys

import numpy as np

from grand_project import core
from grand_project import paths as rc_paths
from grand_project.detect import citybase, citytrain
from grand_project.detect.constants import CITY_BARREL_FILE, CITY_BARREL_WIN, CITY_P, SHOTS

MIN_FOUND = 0.85  # share of the labelled cities found
MAX_FALSE = 2  # other map nodes called a city

failures = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("ok   " if ok else "FAIL ") + name + (f"  ({extra})" if extra else ""))
    if not ok:
        failures.append(name)


def test_model_file() -> None:
    with np.load(CITY_BARREL_FILE, allow_pickle=False) as z:  # plain numbers only, no pickled code
        keys = set(z.files)
        n = len(z["coef"])
        ok = all(len(z[k]) == n for k in ("mean", "scale")) and np.all(z["scale"] > 0)
    check("model file holds plain arrays", keys >= {"mean", "scale", "coef", "intercept"} and ok, f"{n} features")
    img = np.zeros((1080, 1920, 3), np.uint8)
    f = citybase.features(img, 960, 540)
    check("feature length matches the model", f is not None and len(f) == n)


def test_window_edges() -> None:
    img = np.zeros((1080, 1920, 3), np.uint8)
    y0, y1, x0, x1 = CITY_BARREL_WIN
    check("window off the left edge: no features", citybase.features(img, -x0 - 1, 540) is None)
    check("window off the bottom: no features", citybase.features(img, 960, 1080 - y1 + 1) is None)
    check("window just inside: features", citybase.features(img, -x0, -y0) is not None)


def test_snapping() -> None:
    img = np.zeros((1080, 1920, 3), np.uint8)
    check("no map node nearby: probability 0", citybase.barrel_p(img, 500, 500, nodes=[(900, 900)]) == 0.0)
    check("no map nodes at all: probability 0", citybase.barrel_p(img, 500, 500, nodes=[]) == 0.0)
    p = citybase.barrel_p(img, 500, 500, nodes=[{"x": 505, "y": 498}])
    check("black screen is not a city", p < CITY_P, f"p {p:.2f}")


def test_nearest_nodes() -> None:
    nodes = [(100, 100), (300, 100)]
    got = citytrain.nearest_nodes(nodes, [(110, 95), (300, 180), (600, 600)])
    check("truth points go to the nearest map node within reach", got == {0}, str(got))


def test_labelled_cities() -> None:
    truth_file = SHOTS / "cities_truth.json"
    if not truth_file.exists():
        print(f"skip labelled cities ({truth_file} not in the test data)")
        return
    truth = json.loads(truth_file.read_text(encoding="utf-8"))
    found = cities = false = 0
    for name, entry in truth.items():
        img = core.read_screenshot(SHOTS / name)
        nodes = entry.get("nodes")
        if img is None or not nodes:
            continue
        city_nodes = citytrain.nearest_nodes(nodes, entry["cities"])
        unsure = citytrain.nearest_nodes(nodes, entry.get("unsure", []))
        for k, (x, y) in enumerate(nodes):
            if k in unsure:
                continue
            called = citybase.barrel_p(img, x, y) >= CITY_P
            if k in city_nodes:
                cities += 1
                found += called
            else:
                false += called
    check(
        "labelled cities found",
        cities > 0 and found >= MIN_FOUND * cities and false <= MAX_FALSE,
        f"{found} of {cities} found, {false} false",
    )


def main() -> int:
    rc_paths.need_test_data()
    for t in (test_model_file, test_window_edges, test_snapping, test_nearest_nodes, test_labelled_cities):
        t()
    print("FAIL: " + ", ".join(failures) if failures else "PASS: city barrel detection")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
