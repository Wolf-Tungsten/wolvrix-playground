"""ctypes bridge to the C segment-DP kernel (kernel.c).

Compiles ``kernel.c`` on demand (cc -O3 -shared -fPIC, cached next to the
source and rebuilt when the source is newer) and falls back to the pure
Python ``searcher.segment_dp`` when no C compiler is available, so the
harness stays runnable everywhere — just slower (D6 sanctions the C bridge
for the hot loop; Phase 0 measured ~12-48 ms per Python DP call at n≈2k,
which rules out 10k-100k SA iterations per region).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

_KERNEL_PATH = Path(__file__).resolve().parent

_lib = None
_tried = False


def _compile() -> Path | None:
    source = _KERNEL_PATH / "kernel.c"
    # Name must not shadow the harness.kernel module itself (extension
    # modules take import precedence over .py in the same directory).
    target = _KERNEL_PATH / "_segdp_kernel.so"
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    import shutil

    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        return None
    result = subprocess.run(
        [cc, "-O3", "-shared", "-fPIC", "-o", str(target), str(source)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kernel.c compilation failed:\n{result.stderr}")
    return target


def available() -> bool:
    """True when the C kernel can be loaded (compiling it if needed)."""
    global _lib, _tried
    if _tried:
        return _lib is not None
    _tried = True
    try:
        import ctypes

        path = _compile()
        if path is not None:
            _lib = ctypes.CDLL(str(path))
            _lib.segdp_cost.restype = ctypes.c_double
            _lib.segdp_cost.argtypes = [
                ctypes.c_int32, ctypes.c_int32, ctypes.c_int32,
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_uint32,
                ctypes.c_double,
            ]
    except Exception:
        _lib = None
    return _lib is not None


def _csr(lists: list[list[int]]) -> tuple[np.ndarray, np.ndarray]:
    offsets = np.zeros(len(lists) + 1, dtype=np.int32)
    counts = np.array([len(entry) for entry in lists], dtype=np.int32)
    np.cumsum(counts, out=offsets[1:])
    values = np.array([v for entry in lists for v in entry], dtype=np.int32)
    return offsets, values


class KernelDP:
    """Per-problem kernel handle: owns CSR + scratch, evaluates orders."""

    def __init__(
        self,
        uses: list[list[int]],
        defs: list[list[int]],
        weight: np.ndarray,
        capacity: int,
    ):
        use_off, use_var = _csr(uses)
        def_off, def_var = _csr(defs)
        self._init_arrays(use_off, use_var, def_off, def_var, weight, capacity)

    @classmethod
    def from_csr(
        cls,
        use_off: np.ndarray,
        use_var: np.ndarray,
        def_off: np.ndarray,
        def_var: np.ndarray,
        weight: np.ndarray,
        capacity: int,
        n: int | None = None,
    ) -> "KernelDP":
        """CSR-direct constructor (full-graph scale; skips list building).

        ``n`` = number of positions in evaluated orders; defaults to the CSR
        node count. Pass explicitly when the CSR is keyed by global node ids
        that are denser than the evaluated order (state-write nodes carry
        empty rows).
        """
        self = cls.__new__(cls)
        self._init_arrays(use_off, use_var, def_off, def_var, weight, capacity)
        if n is not None:
            self.n = int(n)
            self.dp = np.empty(self.n + 1, dtype=np.float64)
            self.prev = np.empty(self.n + 1, dtype=np.int32)
        return self

    def _init_arrays(self, use_off, use_var, def_off, def_var, weight, capacity):
        if not available():
            raise RuntimeError("C kernel unavailable")
        import ctypes

        self._ctypes = ctypes
        self.n = int(use_off.size) - 1
        self.nvar = int(weight.size)
        self.capacity = int(capacity)
        self.use_off = np.ascontiguousarray(use_off, dtype=np.int32)
        self.use_var = np.ascontiguousarray(use_var, dtype=np.int32)
        self.def_off = np.ascontiguousarray(def_off, dtype=np.int32)
        self.def_var = np.ascontiguousarray(def_var, dtype=np.int32)
        self.weight = np.ascontiguousarray(weight, dtype=np.int64)
        # Scratch.
        self.src_pos = np.empty(self.nvar, dtype=np.int32)
        self.seen = np.zeros(self.nvar, dtype=np.uint32)
        self.counted = np.zeros(self.nvar, dtype=np.uint32)
        self.dp = np.empty(self.n + 1, dtype=np.float64)
        self.prev = np.empty(self.n + 1, dtype=np.int32)
        # Stamps must strictly increase across calls sharing the scratch.
        self._stamp_base = 0
        # Per-segment penalty inside the DP objective (0 = pure copy cost).
        self.penalty = 0.0

    def _ptr(self, array: np.ndarray):
        return array.ctypes.data_as(self._ctypes.c_void_p)

    def cost_with_prev(self, order: np.ndarray) -> float:
        """DP cost of the order; leaves prev[] filled for cut replay."""
        order = np.ascontiguousarray(order, dtype=np.int32)
        if order.size != self.n:
            raise ValueError("order length != node count")
        if self._stamp_base + self.n + 1 >= 0xFFFFFFFF:
            self.seen[:] = 0
            self.counted[:] = 0
            self._stamp_base = 0
        base = self._stamp_base
        self._stamp_base += self.n + 1
        return float(
            _lib.segdp_cost(
                self.n, self.nvar, self.capacity,
                self._ptr(self.use_off), self._ptr(self.use_var),
                self._ptr(self.def_off), self._ptr(self.def_var),
                self._ptr(self.weight),
                self._ptr(self.src_pos), self._ptr(self.seen),
                self._ptr(self.counted), self._ptr(self.dp), self._ptr(self.prev),
                self._ptr(order), base, self.penalty,
            )
        )

    def cost(self, order: np.ndarray) -> float:
        return self.cost_with_prev(order)

    def cuts(self) -> list[int]:
        """Segment starts replayed from the prev[] of the last evaluation."""
        starts = []
        end = self.n
        while end > 0:
            starts.append(int(self.prev[end]))
            end = int(self.prev[end])
        starts.reverse()
        return starts
