# Segfault investigation notes

Notes for a future-you. Highly condensed.

## Symptom

`./cpython.py -c "print('hello')"` (or any program) eventually segfaults
in the host Python's gc machinery -- usually visible as

    Fatal Python error: Segmentation fault
    Current thread ... :
      Garbage-collecting
      <no Python frame>

at process shutdown. With `--no-better-exchook`, the path is shorter
(stdlib `traceback.print_exc` instead of `better_exchook.get_func_from_code_object`
which calls `gc.get_referrers`), but the underlying gc heap is still broken.

Concretely: by the end of `runFunc`, the host `gc.get_objects(generation=2)`
crashes -- `gc.get_objects(generation=0)` and `generation=1)` work; only
gen2 walking dies.

## What we ruled OUT (don't go back here)

Most of these were rejected by extensive instrumentation; details under
`git log` and `/tmp/probe_*.py` from the session.

1. **Stale gen2 weakref `_gc_next` from improper `_PyObject_GC_UnTrack`.**
   We snapshotted every gen2 weakref's `_gc_next` pre-run and diffed
   post-run. ~1268 weakrefs at startup; 3 of them appear to have
   their `_gc_next` "changed". Looked like the bug.

   **It was a false positive.** Inspecting the destination addresses:
   - All 1/1 verified destinations land at a SANE `PyGC_Head` of a
     real Python object (refcnt in normal range, `ob_type` aligned in
     Python heap range, valid `tp_name`). Concretely we found one
     destination is the `PyGC_Head` of a `_ctypes.PyCPointerType`
     instance -- a normal `LP_X` pointer type that Python's gen1->gen2
     promotion (during a normal `gc.collect`) moved into gen2.
   - Python's `gc.collect()` legitimately runs many times during
     `runFunc` (auto-triggered by allocation pressure), and each
     promotes objects between generations. Our snapshot-then-diff
     approach sees these legitimate updates as "corruption."

2. **Our `pointerStorage`'s `WeakValueDictionary` KeyedRefs dying without untrack.**
   We monkey-patched `weakref.KeyedRef` to track creation+death of every
   one of our pointerStorage entries (91728 KeyedRefs created, 19426
   saw `__del__`). The 3 "victim" PyGC_Heads from `--gc-list-diff` did
   NOT correspond to ANY tracked KeyedRef. The `[interp.pointerStorage value]`
   tag in the diff was a slot-collision artifact (an old ctype value's
   id() got reused by Python for unrelated objects, so our `_reg_info`
   lookup keyed by id matched the wrong record).

3. **Aliasing between our `_malloc`'d c_byte buffers and Python heap.**
   `_malloc` returns addresses in 0x12c..-0x12d.. (small system malloc)
   or 0xa9..-0xb.. (mmap'd large allocations). Python heap is 0x100..-0x110..
   No overlap. Also: `addressof(c_byte_buf)` is ~90 KB BEFORE `id(buf)` --
   the data area and Python object header live in completely different
   memory regions, so interp writes to the buf data can't clobber the
   buf's own PyGC_Head.

4. **`_PyObject_GC_TRACK`/`_UNTRACK` in our interp writing to Python heap.**
   We dumped our interp's `_PyRuntime.gc.generations[].head._gc_next/_prev`
   at iters 1340 and 1344. All fields stay in our interp's
   `mallocs`/`_PyRuntime` ranges. No Python-heap pointer ever leaked
   into our interp's gc list state.

5. **A minimal standalone repro of obmalloc + gen-list manipulation.**
   We built a subprocess-based test
   (`test_obmalloc_minimal_pool_alloc_does_not_corrupt_python_heap`)
   that replicates: `usedpools[]` PTA-trick init, full `pymalloc_alloc`
   init_pool writes, fn-ptr dispatch through `checkedFuncPtrCall`-shape
   struct, real `interp._malloc`'d pool buffers, `arena_object`
   linked-list bind, `_PyObject_GC_TRACK`-style gen list manipulation,
   5000 iters across 32 size classes, interleaved host `gc.collect()`.
   **All of that combined does NOT reproduce.** Whatever the real bug
   is, none of these mechanisms in isolation cause it.

6. **The writes hooked by `Helpers.assign` / `assignPtr` / `_ctype_ptr_set_value`.**
   `--watch-write` and `--watch-write-gen2-weakrefs` armed tripwires on
   thousands of addresses and never fired for the supposed bad write.
   So the corruption -- whatever it is -- doesn't go through those
   Python-level interp helpers. If it's a real interp-driven write, it's
   via ctypes C-level paths (struct field setattr, `memmove`, etc.).

7. **`mprotect`-based watchpoint on Python's heap pages.**
   macOS rejects `mprotect`/`mach_vm_protect` on pymalloc-arena pages
   (immediate `SIGBUS` from the call itself). Linux might allow it.

## What we KNOW (positive findings)

1. **Host gen0 / gen1 are intact** after `runFunc`. Only `gc.get_objects(generation=2)`
   crashes. Likely a single object in gen2 has a corrupt internal field
   that `tp_traverse` (or list walking) deref's.

2. **The crash site in host Python** is consistently inside
   `deduce_unreachable + 56` (called from `gc_collect_main`). That's
   the gen-list walk where each obj's tp_traverse runs. So either:
   - a gen2 obj's `_gc_next/_gc_prev` is bad, or
   - a gen2 obj's `tp_traverse` walks into freed memory.

3. **`_PyObject.malloc` is being dispatched via `checkedFuncPtrCall`**
   in our interp. Our `_malloc` allocations are well-behaved (verified
   against the host weakref/KeyedRef tracking).

4. **lldb hardware watchpoints work** with `PYTHONHASHSEED=0` + `disable-aslr`.
   Addresses are *partially* deterministic across runs -- the relative
   deltas between PyGC_Heads of consecutive heap allocations stay
   stable, but the absolute base address can shift by a few pages
   between runs.

5. **`PYCPYTHON_LLDB_TRAP=1` env var** raises SIGTRAP after the
   gc-list-diff baseline is captured but before `runFunc`, suitable
   for attaching lldb and setting watchpoints.

## Likely real bug class

Since (1)-(4) are ruled out, the real corruption is most likely
**a ctype object's internal field (`_b_base_`, `_objects` dict, or
similar) pointing into freed memory**. When Python's gc.collect()
walks gen2 and visits this ctype, `tp_traverse` follows the bad
pointer and crashes.

Suspects:
- Our interp creates many transient pointer-to-pointer chains via
  `ctypes.cast(p, ...)` and `ctypes.pointer(...)`. These chains hold
  `_b_base_` references. If any reference goes stale (refers to
  memory we've freed via `_free`) and the parent object survives
  into gen2, gc walks crash.
- Our `pointerStorage` is a `WeakValueDictionary` -- the values are
  ctype objects. Some of these are `_typeobject` instances that
  PyType_Ready'd structures register pointers into. If we ever
  manually break a `_objects` chain or `_b_base_` link, those become
  walking traps.

## 2026-05-23 update: gen2-bisect run reveals a SECOND crash site

Adding `--gen2-bisect` (which does `gc.disable()` before `runFunc`)
revealed a previously-masked crash:

    Fatal Python error: Segmentation fault
      File ".../ctypes/__init__.py", line 531 in cast
      File "<PyCParser_PyObject_ClearWeakRefs>", line 11
      File "<PyCParser_meth_dealloc>", line 30
      File "<PyCParser__Py_Dealloc>", line 4
      File "<PyCParser_PyFile_WriteObject>", line 59
      ...
      File "<PyCParser_PyErr_Print>", line 3
      File "<PyCParser_initimport>", line 31

So while printing the `_thread`-missing ImportError traceback
during `initimport`, the deallocation of a C method object trips
`PyObject_ClearWeakRefs`.  This is a **weakref-list walk** crash --
the method object's `tp_weaklistoffset`-rooted list contains a
dangling pointer.

This is consistent with the gen2 gc crash being the same bug
class (gc walks objects whose weakref data points into freed memory).

## 2026-05-23 update #2: --gen2-bisect identifies the bad object

Added `--gen2-bisect` (in `cpython.py`).  Disables host gc before
`runFunc`, walks the gen0 list via raw PyGC_Head pointer-chases after
runFunc (which raises `CAbortException`), forks subsets to
`gc.get_referents()` and binary-searches the offender.

**Result (deterministic across runs):**

- Walk finds ~15 million tracked objects in gen0.
- Exactly **one** has `refcnt=0`: a `set` whose body fields are
  garbage (`fill=15151544`, `mask=0x1ffffff`, `table=0x642000000`).
- Its `_gc_prev = 0x0` (broken gc-list back-pointer).
- It's always at idx=1 of our walk -- the entry immediately after
  our anchor `[]` via `_gc_next`.

**Sentinel theory ruled out.**  The initial "always idx=1" position
was an artifact of the walker's filter `rc > 0` -- it skipped the
refcnt=0 entry until we removed that filter.  Without the filter, the
bad set appears at idx=8 (varies, NOT adjacent to anchor).  So this is
a REAL set object, not the sentinel head.

**The bug, concretely:**

A Python `set` object reaches `refcnt=0` without ever being
deallocated/untracked.  pymalloc later reuses the slot, clobbering the
body data.  The gc-list still has a `PyGC_Head` entry pointing at this
freed-but-not-untracked slot.  Any subsequent gc walk
(`gc.collect`, `gc.get_objects(2)`, `tp_traverse`) dereferences this
stale entry's body and crashes.

In a normal gc-enabled run, the crash surfaces as
`deduce_unreachable + 56` during shutdown gc.  In our `--gen2-bisect`
mode it surfaces as `gc.get_referents()` crashing on this single
specific set.

**The hunt is now well-defined:** find the path in our interp where a
Python `set`'s refcount gets decremented to 0 without invoking
set_dealloc (which would have called `_PyObject_GC_UnTrack`).

Candidates:
- `cparser.sortedcontainers.SortedSet` internals (uses `set` as backing)
- `pointerStorage = WeakValueDictionary()` -- internal weakset?
- `pointerStorageRanges = SortedSet()` -- when entries get evicted
- A raw `ctypes` refcount manipulation in `_storePtr` / `_free`

## 2026-05-23 update #3: neighbor dump & instrumentation results

Walking the gen0 list's idx 3..13 around the bad set (idx 8):

    [3]  addr=...  refcnt=2 type='tuple'                 _gc_prev=...
    [4]  addr=...  refcnt=2 type='getset_descriptor'     _gc_prev=...
    [5]  addr=...  refcnt=2 type='getset_descriptor'     _gc_prev=...
    [6]  addr=...  refcnt=2 type='weakref.ReferenceType' _gc_prev=...
    [7]  addr=...  refcnt=2 type='list'                  _gc_prev=...
    [8]  addr=...  refcnt=2 type='set'                   _gc_prev=0x0  <-- BAD
    [9]  addr=...  refcnt=1 type='py_object'             _gc_prev=...
    [10] addr=...  refcnt=2 type='Attribute'             _gc_prev=...
    [11] addr=...  refcnt=2 type='dict'                  _gc_prev=...
    [12] addr=...  refcnt=2 type='Name'                  _gc_prev=...
    [13] addr=...  refcnt=2 type='dict'                  _gc_prev=...

Key observations:

- ONLY the bad set has `_gc_prev=0x0` (broken doubly-linked invariant).
- bad set `refcnt` varies between runs: sometimes 0, sometimes 2.
- Neighbors are AST nodes (Attribute / Name / dict) -- suggests this
  set was allocated during AST processing or related initialization.
- `--instrument make_new_set,frozenset_new` reports ZERO calls during
  the run, so sets must be created via a different code path
  (probably `PyType_GenericAlloc` + `set_init`, or via internal C
  helpers that bypass `make_new_set`).
- `PyType_GenericAlloc` is called 1500+ times for many distinct types
  -- the leaker is one of these.

## Suggested next investigation steps

In order of probable yield:

## 2026-05-23 update #4: it's a HOST set, found via body-invariant sweep

Two new pieces of evidence:

1. `bad_set.ob_type == id(set)` -- the leaker is a **HOST Python set**,
   not an interp-built set type.  Our interp creates types in
   `0x12X_xxxx_xxx` range; host `set` lives at `0x101024e38` (varies
   per run but always matches `id(set)`).

2. **Body-invariant sweep**: scan all gen0 entries whose ob_type ==
   host set; check `(used <= mask+1) and (mask in {7,15,31,...,65535})`.
   Of 43871 host sets in gen0, exactly **ONE** fails the check -- the
   same one the fork-bisect identifies.

Implications:
- We don't need fork-bisect anymore; the body-invariant sweep is the
  fast detector.  The bisect harness in `--gen2-bisect` can be
  simplified to just call this sweep.
- The leaked set has body fields like `fill=15252840 used=15252840
  mask=0x1ffffff table=0x576000000` -- not zero (so `tp_alloc` with
  `calloc=1` didn't initialize it).  Either:
  (a) `tp_alloc(set_type, ...)` is called with `calloc=0` (or our
      interp's translated calloc doesn't actually zero memory), OR
  (b) Pymalloc gave us a slot whose contents were preserved from a
      prior interp-managed buffer (our `_malloc`'d c_byte data).
      Need to check if `0x376d01fc0` overlaps with `interp.mallocs`.
- The set is somewhere in HOST Python's machinery -- candidates
  include: stdlib `weakref`, `gc`, `_compile_charset`,
  `dict.keys() -> set`, `set comprehension`s, exception cycle
  tracking, `typing` module internals.

## 2026-05-23 update #5: bad set is created DURING runFunc, not pre-existing

Pre-runFunc snapshot: 103 host sets exist (bootstrap state).
Post-runFunc gen0: 43,871 host sets in gen0 (~43,768 new ones).
The leaker is NOT in the pre-snapshot -- created during runFunc.

The leaker is at **idx=8 in the gen0 walk** (LIFO order from anchor),
meaning only ~8 allocations happened between its tracking and the
end of runFunc.  So it was tracked at the very END of runFunc --
likely during exception unwinding when CAbortException propagated.

Its memory address does NOT overlap any `interp.mallocs` buffer --
the garbage body fields come from pymalloc's freelist residue, not
from our interp's data.

Neighbors in the gen0 list (idx 3..13): tuple, getset_descriptor x2,
weakref.ReferenceType, list, **SET (BAD)**, py_object, Attribute,
dict, Name, dict.  AST nodes + ctypes py_object near the leaker --
suggests interp activity involving ctypes objects and ast was running
when the leak happened.

## 2026-05-23 update #6: REVISED diagnosis -- gc linked list corruption

After more testing, the "refcnt=0 set" was a **misleading
intermittent symptom**, not the root cause.  New diagnostic
(`_fork_call_gc_collect`):

    [gen2-bisect] sets with broken body invariants: 0
    [gen2-bisect] objects with refcnt=0 still in gc-list: 0
    [gen2-bisect] objects with _gc_prev=0 still in gc-list: 0
    [gen2-bisect] explicitly calling gc.collect()...
    [gen2-bisect] gc.collect() CRASHES -- bug IS in gen-list walk machinery

So even when gen0 looks structurally clean (no zero-refcnt, no
zero-_gc_prev, no weird set bodies), `gc.collect()` still crashes.
The corruption is in the gen-list's **doubly-linked invariant** --
specifically, somewhere `prev->_gc_next != cur` or
`cur->_gc_prev != prev`, which our forward-only walker tolerates
but `gc_collect_main`'s `validate_list` fails on.

The "refcnt=0 set" we sometimes saw was a SECONDARY artifact:
when `gc.collect()` runs incrementally, it can leave individual
objects in inconsistent state mid-collect; our walker happens to
observe them at a bad moment.

Note: the bug is **heap-timing-sensitive**.  Adding extra
instrumentation (eg. an abort-time gen0 scan) can perturb timing
enough to make the bug NOT reproduce.  Run multiple times to
confirm.

## 2026-05-23 update #7: FOUND IT -- half-untracked dict

Bidirectional walk reveals exactly ONE broken link in 14.9M entries:

    [gen2-bisect] doubly-linked invariant breaks: 1
    [gen2-bisect]   broken-link head=0x371b22ab0 type='dict':
                    nxt invalid 0x0

A **dict** object with `_gc_next == NULL` -- but still reachable
via its predecessor's `_gc_next` pointer.  This is a HALF-UNTRACKED
state: `_PyObject_GC_UnTrack` partially ran:
- `gc->_gc_next = 0` and `_PyGCHead_SET_PREV(gc, NULL)` DID execute
- BUT `_PyGCHead_SET_NEXT(prev, next)` did NOT -- prev's forward
  link still points at this dict

When `gc.collect()` walks the list, it follows prev's `_gc_next`
to this half-untracked dict, then reads `dict->_gc_next == NULL`
and crashes (or for the iter-loop in `validate_list`, fails an
assertion).

**The bug is in our interp's `_PyObject_GC_UnTrack` translation.**
It's supposed to atomically unlink from the doubly-linked list,
but our interp executes the unlinking steps as separate
interpreter operations -- if an exception unwinds between
"clear my pointers" and "fix neighbors' pointers", we leave a
half-untracked obj.

## 2026-05-23 update #8: SMOKING GUN -- buffer overflow into adjacent host obj

Reproducible across runs (the BROKEN obj type varies -- dict, tuple,
etc. -- but the pattern is identical):

    [gen2-bisect]   broken-link head=0x374d855f0 obj=0x374d855f0+16
                    rc=2 type='tuple' HOST tuple: nxt invalid 0x0
    [gen2-bisect]     pointerStorageRanges covers head:
                      range_base=0x374d855b0 size=64 (head offset=64)

The 64-byte buffer in `pointerStorageRanges` ends at byte
`0x374d855f0`, which is EXACTLY where the broken host object's
PyGC_Head starts.  Our 64-byte buffer's *last* offset is byte 63
(= 0x374d855ef); byte 64 onward belongs to a different object's
PyGC_Head.

**The bug: our interp writes past the end of a 64-byte ctypes
buffer.**  Bytes 64+ of the write overflow into the next pymalloc
slot -- the host tuple's `_gc_next` (which gets nulled, since we
typically write zeros past our buffer end).

This matches all earlier observations:
- `_gc_next=NULL`: it's a zero write from buffer overflow.
- Bad obj is always HOST python obj (in pymalloc arena adjacent to
  our buffer).
- Bad obj has normal refcnt (it's perfectly alive -- just its
  gc-list link was clobbered).
- "set/dict/tuple" varies (whatever happens to neighbor our buffer
  in pymalloc).
- The body fields of the bad obj (when it's a set) sometimes look
  garbage -- that's MORE bytes of our overflow going further.

Old "memory aliasing" hypothesis we ruled out (Investigation #3 in
the original "What we ruled OUT" section) was based on
`interp._malloc` ranges -- but the leaker buffer here is in
**pymalloc's arena**, registered via `pointerStorageRanges`, NOT
allocated by our `_malloc`.  So the earlier ruling-out missed this
case.

## 2026-05-23 update #9: overflowing buffer is `c_byte_Array_64`

Identified the ctype:

    range_base 0x374e91070 -> ctype <cparser.cparser.wrapCTypeClass_c_byte_Array_64
                                     object at 0x374ea0dd0>
                              (type=wrapCTypeClass_c_byte_Array_64, size=64)

So the overflowing buffer is a `c_byte[64]` array.  In CPython
source there's `char msgbuf[64]` in `Objects/obmalloc.c`
(`_PyMem_DebugCheckAddress`) but that's only used in
PYMALLOC_DEBUG builds (not active in our runs).

The actual culprit `char[64]` is elsewhere -- needs targeted
instrumentation of `_addPointerStorageRange` to capture the
stack at the moment a `c_byte[64]` buffer is registered.

## Suggested next investigation steps

In order of probable yield:

0. **Identify the C-source site declaring the 64-byte buffer.**
   Hook `_addPointerStorageRange`: when called with `size == 64`
   AND `ctype is wrapCTypeClass_c_byte_Array_64`, log a Python
   stack trace (via `traceback.extract_stack()`).  After runFunc,
   look at the registered range whose end matches the broken
   obj's head -- the stack at registration tells us which
   interpreted C function declares this buffer.

   Once identified: audit that C function's code for an
   off-by-one access (e.g., `buf[64]` instead of `buf[63]`),
   a strcpy/snprintf with wrong size, or a sizeof bug.

1. **Inspect the interp's translation of `_PyObject_GC_UnTrack`.**
   Find where this function is generated; check whether the four
   pointer updates run as a single atomic block or if there's an
   interleaving point.  Possibly add try/finally semantics so the
   neighbor-fixup ALWAYS runs even if a step raises.

   Note: `_PyObject_GC_UnTrack` is typically an inline-macro in
   CPython source (`#define _PyObject_GC_UNTRACK(o) ...`).  Our
   parser may expand the macro at every call site -- those expanded
   sites are individual statement blocks in the interp.  If our
   interp ever throws between the statements (e.g. via a watchdog
   or signal handler), we leak.
   For each obj, verify `obj._gc_prev._gc_next == obj` and
   `obj._gc_next._gc_prev == obj`.  The single broken link is
   what `gc.collect()`'s `validate_list` trips on.  Add this to
   the bisect's post-runFunc forensics.

1. **Hook host-set allocation via gen0-walk-on-each-`checkedFuncPtrCall`.**
   Even though gc.callbacks don't fire when gc is disabled, we can
   manually walk gen0 via PyGC_Head at every K-th interp iter (or
   only during the last M iters) and snapshot host-set IDs.  Compare
   snapshots to find when the leaker's address first appears.  Walk
   only the FIRST ~50 entries from anchor (recently-allocated) -- the
   bad set is always at idx<10, so we don't need to scan all 15M.

1. **Wrap exception-propagation paths in our interp.**
   Since the leaker is created at the very end of runFunc (during
   CAbortException unwind), instrument the path through Python's
   exception/traceback C code.  Specifically: hook
   `PyErr_Print`, `print_exception`, `_PyTraceBack_FromFrame`,
   `_PyObject_GC_New` w/ refcounting -- one of these creates the
   leaker.

2. **Wrap `set_init` (not `make_new_set`) plus `_PyObject_GC_UnTrack`.**
   Pair-track: every set passing through `set_init` should also pass
   through `_PyObject_GC_UnTrack` at its dealloc time.  The leaker is
   a set whose UnTrack never fires.  Caveat: these may be C macros,
   not functions -- check if they exist as wrappable functions in the
   parsed AST.

   Alternative: instrument lower-level `_PyObject_Malloc` /
   `_PyObject_Free` and pair-track ALL allocations.  More expensive
   but catches everything.

1. **Find the bad obj in gen2 by partition.**
   Subprocess-based bisect: after `runFunc` returns (or natural error),
   enumerate `gc.get_objects(generation=0)` + `(generation=1)` (both
   work). Then walk gen2 manually via PyGC_Head links (we have code
   for this). For each gen2 obj, call `gc.get_referents(obj)` in a
   sandboxed subprocess. The subprocess that segfaults identifies
   the bad obj. Binary-search subset is feasible.

2. **Instrument ctype `tp_traverse` calls.**
   Set lldb breakpoint on `gen_traverse` or directly on each
   `tp_traverse` of major types (`_typeobject`, `LP_X` pointers,
   ctypes arrays). With auto-continue + lightweight callback log.
   The traverse call right before the crash is the bad one.

3. **Find when an obj's `_b_base_` chain becomes stale.**
   Instrument `_free` to also poison the freed buffer (memset to
   a marker). When ctype tp_traverse later derefs poisoned memory,
   SIGSEGV with stack identifies the bad obj.

4. **Try mprotect on Linux** -- the implementation already exists,
   just BUS-errors on macOS. Linux is permissive and would let us
   catch ANY write to a target page.

## Useful artifacts still in the tree

- `cpython.py --no-better-exchook` -- skips the better_exchook gc walk
  during exception printing (the original symptom). Keep for diagnostics.
- `cpython.py --gc-check-at N1,N2,... --gc-check-range A:B:STEP` --
  call `gc.get_referrers(co)` on a known-alive code object at named
  iters. Useful for bisection.
- `cpython.py --instrument FUNC[,FUNC...]` -- wraps interp'd C
  functions with entry/exit logging. Useful for finding which call in
  a chain silently returns NULL.
- `PYCPYTHON_LLDB_TRAP=1 env var` -- raises SIGTRAP before runFunc so
  lldb can attach (combine with `target.disable-aslr true` and
  `PYTHONHASHSEED=0`).
- `cparser/tests/test_interpreter_extra.py::test_obmalloc_minimal_pool_alloc_does_not_corrupt_python_heap`
  -- subprocess-based unit-test scaffold for trying to reproduce in
  isolation. Currently passes (negative result kept as a baseline).

## Removed (don't reach for these again)

- `--gc-list-diff` -- baseline-and-diff of gen2 weakrefs. False
  positives (legitimate gc promotions look like corruption).
- `--watch-write`, `--watch-write-gen2-weakrefs` -- never tripped.
- `--track-pointer-storage`, `--watch-pointer-storage-id` -- entry_ids
  matched victims by slot-collision id reuse, not by actual identity.
- `--mprotect-at-iter` -- macOS won't allow protection changes on
  pymalloc arenas. Removed (was always experimental).
