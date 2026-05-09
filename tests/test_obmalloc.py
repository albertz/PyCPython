"""
Tests for CPython's obmalloc.c interpreted via cparser.

These tests exercise the PyMem_Raw* family and _PyMem_RawWcsdup *without*
the manual interpreter._func_cache overrides that cpython.py currently
injects.  If all tests here pass we can remove those overrides and let the
C code run as-is through the interpreter.

Each runFunc call is guarded with a timeout so a hung interpreter surfaces
as a TimeoutError rather than an infinite wait.
"""

import sys
import os
import pytest

# Make the PyCPython root importable (conftest.py does this too, but be safe).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cparser
import cparser.interpreter
from cpython import CPythonState  # re-use the CPython include-path setup

TIMEOUT = 10  # seconds per runFunc call


# ---------------------------------------------------------------------------
# Shared fixture: parse just obmalloc.c (enough to get PyMem_Raw* symbols)
# ---------------------------------------------------------------------------

CPYTHON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CPython")


@pytest.fixture(scope="module")
def obmalloc_state():
    state = CPythonState()
    state.macros["Py_BUILD_CORE"] = cparser.Macro(rightside="1")
    state.macros["Py_BUILD_CORE_BUILTIN"] = cparser.Macro(rightside="1")
    cparser.parse(os.path.join(CPYTHON_DIR, "Objects", "obmalloc.c"), state)
    if state._errors:
        # Non-fatal parse errors can occur in the debug-malloc portions of
        # obmalloc.c (e.g. SST, snprintf) that we don't test here.  Report
        # them but don't fail the fixture — instead each test checks that
        # the specific symbol it needs actually got parsed.
        print("\nparse warnings in obmalloc.c:")
        for e in state._errors:
            print(" ", e)
    return state


@pytest.fixture(scope="module")
def interp(obmalloc_state):
    interp = cparser.interpreter.Interpreter()
    interp.register(obmalloc_state)
    return interp


# ---------------------------------------------------------------------------
# PyMem_RawMalloc: goes through _PyMem_Raw.malloc struct function pointer
# ---------------------------------------------------------------------------

def test_pymem_raw_malloc_returns_nonzero(interp, obmalloc_state):
    """PyMem_RawMalloc(8) must return a non-NULL pointer."""
    if "PyMem_RawMalloc" not in obmalloc_state.funcs:
        pytest.skip("PyMem_RawMalloc not parsed (parse error in obmalloc.c)")
    r = interp.runFunc("PyMem_RawMalloc", 8, timeout=TIMEOUT)
    assert r.value != 0, "PyMem_RawMalloc returned NULL"


def test_pymem_raw_malloc_zero_size(interp, obmalloc_state):
    """PyMem_RawMalloc(0) must also return non-NULL (CPython adds 1)."""
    if "PyMem_RawMalloc" not in obmalloc_state.funcs:
        pytest.skip("PyMem_RawMalloc not parsed")
    r = interp.runFunc("PyMem_RawMalloc", 0, timeout=TIMEOUT)
    assert r.value != 0, "PyMem_RawMalloc(0) returned NULL"


def test_pymem_raw_calloc_returns_nonzero(interp, obmalloc_state):
    """PyMem_RawCalloc(4, 4) must return a non-NULL pointer."""
    if "PyMem_RawCalloc" not in obmalloc_state.funcs:
        pytest.skip("PyMem_RawCalloc not parsed")
    r = interp.runFunc("PyMem_RawCalloc", 4, 4, timeout=TIMEOUT)
    assert r.value != 0, "PyMem_RawCalloc returned NULL"


# ---------------------------------------------------------------------------
# _PyMem_RawWcsdup: uses wcslen + PyMem_RawMalloc + memcpy
# ---------------------------------------------------------------------------

def test_pymem_raw_wcsdup_returns_nonzero(interp, obmalloc_state):
    """_PyMem_RawWcsdup of a short string must return a non-NULL pointer."""
    if "_PyMem_RawWcsdup" not in obmalloc_state.funcs:
        pytest.skip("_PyMem_RawWcsdup not parsed")
    import ctypes
    # _castArgToCType converts a Python str to a wchar_t* automatically.
    r = interp.runFunc("_PyMem_RawWcsdup", "hello", timeout=TIMEOUT)
    # The return type is wchar_t* — cast to c_void_p to get the address.
    addr = ctypes.cast(r, ctypes.c_void_p).value
    assert addr, "_PyMem_RawWcsdup returned NULL"
