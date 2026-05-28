# Progress notes: making `cpython.py -c "print('hello')"` work

## Current state (2026-05-28)

🎉 **Interactive REPL works.** Running `./cpython.py` drops into a `>>>`
prompt; `print(...)`, expression evaluation, `sys.stderr.write`,
f-strings, list comprehensions, etc. all work end-to-end through the real
interpreted C chain (tokenizer → parser → AST → compile → ceval). EOF /
Ctrl-D closes cleanly. See `README.md` for a screencast and `demo.cast`
for an asciinema recording.

`-c "..."` invocations also work; `cpython.py -c "print('hello')"`
exits with rc=0 after printing `hello`.

## Round 13 -- REPL works via Parser/myreadline.c (2026-05-28)

Running `./cpython.py` (no args) ought to give an interactive REPL but
was failing with ``TODO (missing C source code file): PyOS_Readline is
not loaded yet``.  Root cause: ``Parser/myreadline.c`` was never parsed,
so ``PyOS_Readline`` had only the header forward decl (no body).

### Fix
Add one line in ``cpython.py``'s ``parse_cpython``:

```python
cparser.parse(CPythonDir + "/Parser/myreadline.c", self)
```

myreadline.c parses cleanly -- no missing wrappers needed -- and
``PyOS_Readline`` immediately gets a real body that calls
``PyOS_StdioReadline`` → ``fgets``.

### Verification
```
$ printf 'print("hi")\n1+2*3\n[i*i for i in range(6)]\n' | \
    ./cpython.py -i
>>> hi
>>> 7
>>> [0, 1, 4, 9, 16, 25]
>>>
```

## Round 12 -- Replace stream-stub wrapper with stdprinter (2026-05-28)

`sys.__stderr__` was a CPython `stdprinter` (fd-backed file object) even
though our `_install_sys_streams` had replaced `sys.stderr` with a
`<pycpython-stderr>` module.  `_Py_InitializeCore` (pylifecycle.c:791)
already creates a `stdprinter` for stderr early -- exactly the
bootstrap fallback CPython was designed for.  So we don't need our
ctypes-callback-based replacement; we just need to create the
corresponding `stdprinter` for stdout (which CPython doesn't do early).

### Fix
`_py_init_sys_streams` now just calls `PyFile_NewStdPrinter(1)` and
sets `sys.stdout` / `sys.__stdout__`.  The stderr `stdprinter` is left
in place.  Removed ~95 lines of `_make_stream_module` /
`_install_sys_streams` / `_stream_keepalive` plumbing (ctypes
callbacks, `PyMethodDef` arrays, `PyCFunction_NewEx` wiring).

Bonus: output now goes through real `write(2)` instead of being
marshaled back through host Python's `sys.stdout.write()`.

## Round 11 -- Remove `pymain_init_python_main` wrapper (2026-05-27)

The override was a ~40-line Python substitute that bypassed the real
`_Py_InitializeMainInterpreter`.  Documented as "blocked on fixing the
importlib bootstrap" but the four lifecycle sub-overrides
(`init_sys_streams`, `initsite`, `initexternalimport`,
`get_locale_encoding`) now cover everything the real path needs.

Also discovered: the prior `_wrapped_initext` block was dead code --
its `if "initexternalimport" in state.funcs:` check was looking up the
bare name, but auto-scoping had renamed the function to
`_static_pylifecycle_initexternalimport`.  Replaced with a proper fast
stub at the renamed name (returns `_Py_INIT_OK` without invoking the
slow importlib bytecode translation).

With those in place, the real C `pymain_init_python_main` →
`_Py_InitializeMainInterpreter` chain runs end-to-end.  Removed the
override entirely.

## Round 10 -- Remove `_PyLong_FromTime_t` wrapper via real pytime.c (2026-05-27)

`_PyLong_FromTime_t` was Python-wrapped because pytime.c wasn't parsed
(needed `clock_gettime` / `CLOCK_MONOTONIC` / `struct timespec`).  Added
the missing pieces in `cparser/globalincludewrappers.py`:

- `CHAR_BIT = 8` in `handle_limits_h`.
- `clockid_t` typedef, `struct tm`, `CLOCK_REALTIME`/`MONOTONIC`/etc.
  macros, `clock_gettime`/`clock_getres`/`localtime_r`/`gmtime_r` libc
  bindings in `handle_time_h`.
- `HAVE_CLOCK_GETTIME = 1` in `cpython.py`'s pyconfig.h setup.
- Pop the shared `SEC_TO_*` unit macros between pytime.c and
  faulthandler.c parses (both `#define` them identically).

pytime.c now parses; `_PyLong_FromTime_t` gets a real body; wrapper
removed.

## Round 9 -- Fix shutdown crashes (2026-05-27)

Three asks in one round:

1.  **`TypeError: incompatible types` on FAM init.**
    `static PyDictKeysObject empty_keys_struct = { ..., {DKIX_EMPTY,
    ...} }` initializes a trailing C99 flexible array member with 8
    bytes.  Our ctypes baseline laid out the FAM as `c_byte * 0` so
    passing a `c_byte * 8` to the constructor mismatched.  Added
    `Helpers.make_struct_with_fam(base, elem, N)` which builds a
    specialized `ctypes.Structure` subclass with the FAM resized.
    `getAstNode_curlyArrayArgsInit` detects FAM-with-init and uses the
    specialized class.  `GlobalScope.getVar` notices the post-init
    type mismatch with the placeholder and rebinds the dict entry to
    the specialized value.

2.  **Cross-dict `structseq_new` warning.**  A static function
    (`clinic/structseq.c.h`) collides with a same-named static var
    (`posixmodule.c`).  Per-TU local lookup already handles the
    resolution correctly; the warning was a false positive.  Compare
    `defPos` source files in `_addToParent`'s cross-dict check; only
    warn if both decls come from the same TU.

3.  **`SEC_TO_US` already defined.**  pytime.c and faulthandler.c both
    `#define SEC_TO_US` identically.  Pop the eight shared unit-
    conversion macros between parses.

4.  **`_free: address ... not allocated by us`.**  Discovered after
    the FAM fix unblocked more shutdown code.  `Py_FinalizeEx` →
    `PyMem_RawFree(Py_FileSystemDefaultEncoding)` was freeing a buffer
    our `_py_get_locale_encoding` override had set via `_make_string`
    (which doesn't register the buffer in `mallocs`).  Changed the
    override to use `interpreter._malloc()` instead, matching the
    real CPython contract (the encoding is `_PyMem_RawStrdup`'d and
    freed at shutdown).

`cpython.py -c "print('hello')"` now exits cleanly with rc=0.

## Round 8 -- Per-TU local lookup for cross-dict shadowing (2026-05-26)

A header `static int foo(void)` in TU-A and a same-named
`static int foo;` variable in TU-B are SEPARATE C symbols (internal
linkage), but cparser merges all TUs into one `state.funcs` /
`state.vars`.  The auto-scoping rename handles same-dict collisions,
but cross-dict collisions (function in one TU vs. variable in another)
still strand TU-B's body references on the wrong target (the global
`getObjInBody` searched `funcs` before `vars` regardless of which TU
asked).

### Fix
- New `State._tu_local_lookup: dict[name -> obj]` populated by
  `_addToParent` whenever a state-level dict entry is newly bound
  during this parse.
- `cparser.parse(filename, state)` resets `_tu_local_lookup = {}` on
  entry, restores on exit.
- `getObjInBody(state, name)` consults `_tu_local_lookup` FIRST when
  called on the State itself, before falling through to the global
  `funcs > typedefs > vars > ...` chain.

This mimics real-C scoping: within a translation unit, an identifier
resolves to that TU's own decl first.

### Side effect
The clinic/structseq.c.h vs. posixmodule.c collision (which had been
"fixed" by a brittle filename-matching heuristic skipping rename for
clinic headers) is now handled correctly by the principled per-TU
lookup, and the heuristic was removed.

## Round 7 -- (see original notes below for INT_MIN fix, etc.)



1. **Tokenizer** (interpreted `Parser/tokenizer.c`) lexes the input.
2. **Parser** (interpreted `Parser/parser.c` + `parsetok.c`) builds
   a CST using the real grammar tables (`Python/graminit.c`).
3. **AST builder** (interpreted `Python/ast.c`) converts CST to AST.
4. **Compiler** (interpreted `Python/compile.c` + `symtable.c` +
   `peephole.c`) produces a `PyCodeObject` with real bytecode.
5. **Evaluator** (interpreted `Python/ceval.c`) executes the
   bytecode through `PyEval_EvalCode`.
6. ``CALL_FUNCTION print(...)`` dispatches to ``builtin_print``
   (overridden with a Python helper that writes to host stdout
   because we skipped ``init_sys_streams``).

Also works: ``-c "print('a'); print('b')"`` → "a\nb\n";
``-c "print('hello', 'world')"`` → "hello world\n"; ``-c "pass"``
→ silently succeeds.

``-c "print(3)"`` → "3" and ``-c "print(1+2)"`` → "3" also work.

## Round 7 — `INT_MIN` / `LONG_MIN` / `LLONG_MIN` macros

The OverflowError observed in Round 6 turned out to be a real
cparser-side bug:

```c
#define INT_MIN  -2147483648    /* what we had */
```

cparser's literal-typing rule (post-`SIZE_MAX` fix) types
``2147483648`` as ``uint32_t`` because it doesn't fit in
signed ``int32``.  Unary-minus on an unsigned wraps modulo
``2**32``, so the macro silently expanded to ``+2147483648U``.
Every ``x < INT_MIN`` check (e.g. inside ``_PyLong_AsInt``)
then fired for normal small ``x`` -- including ``x = 0`` --
producing a bogus ``OverflowError`` in
``_install_external_importers``.

### Fix (`cparser/globalincludewrappers.py`)
Match real ``<limits.h>``:

```python
state.macros["INT_MIN"]   = Macro(rightside="(-INT_MAX - 1)")
state.macros["LONG_MIN"]  = Macro(rightside="(-LONG_MAX - 1L)")
state.macros["LLONG_MIN"] = Macro(rightside="(-LLONG_MAX - 1LL)")
```

The value stays in signed range throughout.

### Verification
New cparser test:
``tests/test_interpreter_extra.py::test_int_min_comparison_no_false_overflow``
-- ``x < INT_MIN`` returns 0 for ``x = 0``, ``x = INT_MIN``,
and ``x = INT_MAX``.

### Side note on `initexternalimport`
With the ``INT_MIN`` fix, ``_PyLong_AsInt(0)`` no longer
raises -- so when we call the real ``initexternalimport`` from
``pymain_init_python_main``, the path goes *much* further into
``_install_external_importers`` and translates a huge amount
of importlib bytecode on demand (multiple minutes per run).
``MarkupIterator_next`` is no longer infinite-looping; the
remaining cost is translation overhead.  Until we have
translation caching across runs, we keep skipping
``initexternalimport`` -- ``-c "..."`` programs that only use
builtins don't need the filesystem importers anyway.

## Round 6 — removed `initexternalimport` Python stub (partial)

(Re-instated, see Round 7.)  Original concern was the
``MarkupIterator_next`` postfix-`++` infinite loop that
occurred when ``PyErr_Print`` formatted the
``_install_external_importers`` failure traceback.  The
accumulated fixes from earlier rounds removed the loop; the
new blocker (translation cost of the deeper import path) is
a perf issue, not a correctness one.

## Round 5 — removed `PyModule_ExecDef` Python override

The override existed because cparser couldn't translate the
cast-then-call pattern in `Objects/moduleobject.c`:

```c
ret = ((int (*)(PyObject *))cur_slot->value)(module);
```

Root cause: C's grammar requires unbounded lookahead to tell
``int (`` apart as the start of a function call vs. a function-
pointer type-name ``int (*) (args)``.  Our pre-3 statement parser
commits to the call interpretation while consuming tokens.  The
``*`` between ``( )`` is then a prefix-op with no operand and
falls out, leaving the intermediate shape

```
CFuncCall(
    base = CFuncCall(base = ReturnType, args = []),   # T()
    args = [CStatement(P1), CStatement(P2), ...],     # (args)
)
```

### Fix (`cparser/cparser.py`)
Parser normalisation at statement-finalize time -- the buggy
shape never escapes the parser:

- New ``_is_funcptr_typename_misparse(node)`` detector.
- New ``_funcptr_typename_misparse_to_decl(node)`` ->
  ``CFuncPointerDecl`` converter.
- ``CStatement.finalize`` calls the converter on
  ``self._leftexpr`` when the shape matches.  By the time
  ``subStatement.finalize(...)`` returns inside
  ``_cpre3_parse_brackets``, ``subStatement._leftexpr`` is a
  proper ``CFuncPointerDecl`` (or remained a regular value
  if it really was a function call).
- Added ``CFuncPointerDecl`` to ``isType`` (a function-pointer
  type-name *is* a type, used as cast target).

### Verification
- New cparser test
  ``tests/test_funcptrdecl.py::test_cast_to_function_pointer_then_call``
  -- builds a real ``int(*)(int)`` callback on the host, passes
  its address as ``void *``, interpreted ``call_via_cast`` casts
  it back to a function pointer and invokes it.
- All 417 cparser tests pass.
- ``cpython.py`` works without the Python override; the real
  C `PyModule_ExecDef` translates and runs.

## Round 4 — `pymain_init_python_main` removal (partial)

Attempted to remove the `pymain_init_python_main` stub.  Got
genuine fixes for cparser/interpreter but hit a hard wall on
the importlib bootstrap.

### Real fixes this round
- **`&&` / `||` translation** wraps each operand in `bool()` so
  Python's short-circuit eval doesn't yield a float value to
  `c_int(...)` (caused `int expected instead of float`).
- **Parse `Python/mystrtoul.c`** — without it `PyOS_strtol` was
  a stub that didn't update `end`, so `parsenumber_raw` for
  every integer literal fell through to `PyFloat_FromDouble`.
- **`handle_langinfo_h`** in cparser globalincludewrappers:
  installs `nl_langinfo` (delegates to host
  `locale.nl_langinfo`) and exposes `CODESET`.
- **`HAVE_LANGINFO_H = 1`** in pyconfig.h handler.
- **Python-keyword and Python-dunder C identifiers** -- now
  handled by automatic rename in cparser, not per-site workarounds:
  - New ``py_safe_identifier(name)`` in ``cparser_utils.py``
    appends ``_`` for:
    * Python reserved words (``def``, ``class``, ``lambda``,
      ``return``, ...).
    * Soft keywords in 3.10+ (``match``, ``case``, ``type``).
    * Object/type class-level dunders (``__doc__``,
      ``__class__``, ``__annotations__``, ``__dict__``,
      ``__module__``, ``__name__`` ...).
  - Applied consistently:
    * struct ``_fields_`` definition (``_getCTypeStruct``)
    * struct/union curly-init kwargs
    * ``CAttribAccessRef`` translation (``obj.def`` → ``obj.def_``)
    * ``getAstNodeForVarDecl`` for globals (``g.lambda`` →
      ``g.lambda_``, ``g.__doc__`` → ``g.__doc___``)
    * function definition name (``def lambda`` → ``def lambda_``)
  - ``GlobalsWrapper.__getattr__`` translates the renamed name
    back to the C name for ``state.funcs`` / ``state.vars``
    lookup -- no ``__getattribute__`` override needed.
  - Removed the per-file macro renames in ``cpython.py`` for
    ``lambda``, ``__class__``, ``__doc__``, ``__annotations__``.

### Hard wall: importlib bootstrap dependency
Following the chain after removing the stub:

```
pymain_init_python_main
  -> _Py_InitializeMainInterpreter
    -> initfsencoding
      -> get_locale_encoding
        -> get_codec_name("UTF-8")
          -> _PyCodec_Lookup
            -> _PyCodecRegistry_Init
              -> PyImport_ImportModuleNoBlock("encodings")  -- BLOCKED
```

The `encodings` module import needs the full importlib bootstrap
(the same one with the `MarkupIterator_next` postfix-++ infinite
loop that the `initexternalimport` stub was originally introduced
to bypass).  So full removal of `pymain_init_python_main` is
blocked on fixing the bootstrap chain, which is the next big
sub-project.

Restored the partial implementation — it does not call
`_Py_InitializeMainInterpreter` (would fail), but explicitly does
the `add_main_module`-equivalent step (`PyImport_AddModule
("__main__")` + `PyDict_SetItemString(d, "__builtins__",
PyImport_AddModule("builtins"))`) so user code can find `print`
etc.

## Fixes accumulated across this session

### Round 1 (parser bring-up, cparser-side)
1. K&R-style function-typed parameters (cparser).
2. Function-signature collision detection (cparser).
3. Subscript through `CTypedef`-of-pointer (interpreter).
4. Bitwise ops on pointer-typed expressions (interpreter).
5. NULL-pointer robustness in `Helpers` (3 sites).

### Round 2 (parser bring-up, big fixes)
6. **Multi-digit octal escapes** -- ``\NNN`` (1-3 digits) now
   correctly decoded; previously only ``\0``-``\7`` worked, so
   grammar bitsets ``"\004\050\340..."`` were stored as garbage.
7. **Latin-1 not UTF-8** for C string bytes in
   ``Helpers._make_string``; codepoint 0xE0 must stay one byte.
8. **`SIZE_MAX` typed as ``uint64_t``** -- via
   ``minCIntTypeForNums(useUnsignedTypes=True)``; previously
   overflowed into signed ``int64_t = -1``, breaking
   ``X > SIZE_MAX / sizeof(node)`` checks.
9. **`sizeof(*p)` no-deref** -- compile-time type lookup, not
   runtime deref (which would NULL-fault for the common
   ``p = malloc(sizeof(*p))`` pattern).
10. **`graminit.h` dedup exception** -- no include guard, must
    be re-included with macros redefined.
11. graminit-symbol macros (``expr``, ``atom``, ``test``, ...)
    popped before parsing files that use them as identifiers
    (twice: after parsetok+graminit, again after ast.c).
12. File-scope-static renames for collisions: ``tailmatch``,
    ``_common_reduce``, ``pad``, ``do_strip``, ``do_argstrip``,
    ``method_get_doc``, ``method_repr``.

### Round 3 (compile chain + ceval bring-up)
13. **`__doc__` / `__class__` rename** -- collide with Python
    class-level dunders on ``GlobalsWrapper`` so ``g.__doc__``
    returned Python's None instead of the C variable.
14. **`lambda` rename** -- Python reserved word; ``g.lambda``
    is a Python syntax error.
15. **`_PyAST_Optimize` stub** -- skip ast_opt.c which chokes
    on ``node_->v.<UnionTag>.<field>`` AST-macro confusion.
16. Parses added: ``Python/{asdl,Python-ast,ast,symtable,
    compile,future,peephole}.c``.
17. **`pymain_init_python_main` partial impl** -- calls
    ``PyImport_AddModule("__main__")`` + ``PyImport_AddModule
    ("builtins")`` + ``PyDict_SetItemString(d, "__builtins__",
    bimod)`` directly, bypassing the slow
    ``PyImport_ImportModule("builtins")`` path in the real
    ``add_main_module``.  Without this, ``print`` lookup raises
    ``NameError`` (no ``__builtins__`` in user namespace).
18. **`builtin_print` override** -- writes to host stdout
    because we skipped ``init_sys_streams`` (which imports the
    huge ``io`` module).  Reads PyObject* args via ctypes,
    converts via ``PyObject_Str`` + ``PyUnicode_AsUTF8``,
    prints to host stdout.  Returns ``&_Py_NoneStruct``'s
    address with refcount bumped.

## Working tree changes (UNCOMMITTED)

### `cparser/cparser.py`
- K&R function-typed param fix.
- Function-signature collision detection in `_addToParent`.
- Multi-digit octal escape (``_read_octal_escape`` + state 21/26).

### `cparser/interpreter.py`
- ``CArrayIndexRef`` unwraps ``CTypedef`` before pointer check.
- Bitwise BinOp paths don't trigger ``ptrArithmetic`` assert.
- ``Helpers.augAssignPtr`` NULL coerce.
- ``Helpers.getValueGeneric`` NULL coerce.
- ``Interpreter._storePtr`` permissive fallback for external addrs.
- ``CNumber`` uses ``useUnsignedTypes=True`` so ``SIZE_MAX`` types
  correctly.
- ``Helpers._make_string`` uses latin-1.
- ``sizeof(*p)`` no-deref special-case in ``CSizeofSymbol`` handler.

### `cpython.py`
- All the parses + macro renames + overrides listed above.
- ``builtin_print`` Python override (the only "cheaty" bit -- needed
  because ``init_sys_streams`` is huge and imports ``io``).

### Tests
- ``cparser/tests/test_funcptrdecl.py::test_kr_function_typed_parameter``
- ``cparser/tests/test_interpreter_extra.py::test_subscript_through_typedef_pointer``
- ``cparser/tests/test_interpreter_extra.py::test_bitwise_and_on_pointer_typed_expr``
- All 413 cparser tests pass.

## Verification

```
$ ./cpython.py -c "print('hello')"
...
Run ('Py_Main', 3, ['./cpython.py', '-c', "print('hello')", None]) :
hello

$ ./cpython.py -c "print('a'); print('b')"
...
a
b

$ ./cpython.py -c "print('hello', 'world')"
...
hello world

$ ./cpython.py -c "pass"
...  (silent, exit 0)
```

## What's still cheaty

The ``builtin_print`` override writes to host stdout directly
instead of going through ``sys.stdout`` (which we don't set up
because ``init_sys_streams`` imports the ``io`` module).  The
rest of the chain is genuine: tokenizer, parser, AST, compiler,
peephole optimizer, ceval are all running as interpreted C.

Removing this last shortcut requires either:
- Parsing/translating Modules/_io/*.c (huge) and finishing the
  importlib bootstrap to a usable state, OR
- A minimal Python-side ``stdout`` object with a ``write`` method,
  attached to ``sys.stdout`` via ``_PySys_SetObject``.

## Remaining blockers for richer programs

1. ``_Py_HashDouble`` translation fails for integer hashing
   (``int expected instead of float`` when hashing an int).  Hits
   on any code that uses arithmetic constants needing dict-key
   hashing (e.g. literal ``2`` being interned).
2. Slow startup -- adding the parser + AST + compile chain pushes
   first-run translation cost past 5 minutes.  Caching translated
   ASTs across runs would help substantially.
3. ``MarkupIterator_next`` postfix-++ loop (deferred; not on the
   current happy path).
