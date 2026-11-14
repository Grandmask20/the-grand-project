"""detect.cache (from atlas_detect.py)"""

from __future__ import annotations

import numpy as np

_PER_IMAGE: dict = {}  # (function, id(image)) -> (weak ref to the image, result)


def _per_image(fn):
    """remember fn(img) for the last few images: one detection asks for the same dashes / walls up to 3x
    (v1.03; results are made read-only so no caller can change the shared copy)"""
    import functools
    import weakref

    def _freeze(r):
        if isinstance(r, np.ndarray):
            r.flags.writeable = False
        elif isinstance(r, tuple):
            for x in r:
                _freeze(x)
        return r

    @functools.wraps(fn)
    def wrapper(img):
        key = (fn.__name__, id(img))
        hit = _PER_IMAGE.get(key)
        if hit is not None and hit[0]() is img:
            return hit[1]
        r = _freeze(fn(img))
        try:
            _PER_IMAGE[key] = (weakref.ref(img), r)
        except TypeError:
            return r
        while len(_PER_IMAGE) > 12:
            _PER_IMAGE.pop(next(iter(_PER_IMAGE)))
        return r

    return wrapper
