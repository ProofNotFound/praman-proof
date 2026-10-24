"""Give memory back to the system after heavy work (page fetches decode many large photos).

Python frees objects but glibc often keeps the pages; on a small server (512 MB) that adds up
across checks. malloc_trim hands the free pages back. A no-op where it isn't available.
"""

from __future__ import annotations

import contextlib
import ctypes
import gc


def release() -> None:
    gc.collect()
    with contextlib.suppress(OSError, AttributeError):  # not glibc (macOS, Windows, musl): no-op
        ctypes.CDLL("libc.so.6").malloc_trim(0)
