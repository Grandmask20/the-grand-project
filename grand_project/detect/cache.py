"""detect.cache"""

from __future__ import annotations

import numpy as np

_PER_IMAGE: dict = {}  # (function, id(image)) -> (weak ref to the image, result)


def _per_image(fn):
    """Decorator: remember fn(img) for the last few images (up to 12 entries).

    One detection asks for the same dashes / walls up to 3x (v1.03). Results are made read-only so no caller can
    change the shared copy. The cache key is the image's id, checked through a weak reference so a new image at a
    reused id is not mistaken for the old one.

    Args:
        fn: Function taking one screenshot array and returning an array or a tuple of arrays.

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

    @functools.wraps(fn)
    def wrapper(img):
        """Return the cached fn(img), computing and storing it on a miss.

        Args:
            img: Screenshot array passed to fn.

        Returns:
            fn(img), read-only.
        """
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
