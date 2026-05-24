# Progress notes: making `cpython.py -c "print('hello')"` work

## Current state (2026-05-24)

🎉 **`./cpython.py -c "print('hello')"` now prints "hello" and
exits with status 0** -- via the real interpreted CPython chain:

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
