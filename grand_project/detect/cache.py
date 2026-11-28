"""detect.cache"""

from __future__ import annotations

import copy
import threading
from concurrent.futures import Future

import numpy as np

from .constants import DETECT_PER_IMAGE_KEEP

_PER_IMAGE: dict = {}  # (function, id(image)) -> (weak ref to the image, Future of the result)
# taken only to look up, add or drop entries, never while a result is worked out: the detection's own thread and its
# helpers (pipeline._prefetch) ask for the same results at once
_LOCK = threading.Lock()


def _per_image(fn):
    """Decorator: remember fn(img) for the last few images (DETECT_PER_IMAGE_KEEP entries).

    One detection asks for the same dashes / walls up to 3x (v1.03). Arrays are made read-only so no caller can
    change the shared copy; lists and dicts (of dicts) are handed out as copies. The cache key is the image's id,
    checked through a weak reference so a new image at a reused id is not mistaken for the old one. Thread-safe: a
    caller asking while another thread works it out waits for that result instead of working it out again.

    Args:
        fn: Function taking one screenshot array and returning an array, a tuple of arrays, or a list / dict.

    Returns:
        The wrapped function with the same signature.
    """
    import functools
    import weakref

    def _freeze(r):
        """Make an array, or every array in a (nested) tuple, read-only.

        Args:
            r: Result of fn.

        Returns:
            The same object `r`.
        """
        if isinstance(r, np.ndarray):
            r.flags.writeable = False
        elif isinstance(r, tuple):
            for x in r:
                _freeze(x)
        return r

    def _out(r):
        """The caller's copy of a shared result: lists and dicts copied, frozen arrays as they are."""
        return copy.deepcopy(r) if isinstance(r, (list, dict)) else r

    @functools.wraps(fn)
    def wrapper(img):
        """Return the cached fn(img), working it out on a miss (or waiting for the thread working it out).

        Args:
            img: Screenshot array passed to fn.

        Returns:
            fn(img), read-only (arrays) or a copy (lists, dicts).
        """
        key = (fn.__name__, id(img))
        try:
            ref = weakref.ref(img)
        except TypeError:
            return _out(_freeze(fn(img)))
        with _LOCK:
            hit = _PER_IMAGE.get(key)
            if hit is not None and hit[0]() is img:
                pending = hit[1]
            else:
                pending = None
                mine: Future = Future()
                _PER_IMAGE[key] = (ref, mine)
                while len(_PER_IMAGE) > DETECT_PER_IMAGE_KEEP:
                    _PER_IMAGE.pop(next(iter(_PER_IMAGE)))
        if pending is not None:
            return _out(pending.result())
        try:
            r = _freeze(fn(img))
        except BaseException as e:
            mine.set_exception(e)  # (a thread waiting for it gets the error too)
            with _LOCK:
                if _PER_IMAGE.get(key, (None, None))[1] is mine:
                    del _PER_IMAGE[key]  # not kept: the next ask tries again
            raise
        mine.set_result(r)
        return _out(r)

    return wrapper
