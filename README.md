PyCPython
=========

Use [PyCParser](https://github.com/albertz/PyCParser) to parse and interpret CPython.
The C source of CPython itself becomes the runtime:
every call into
`builtin_print`, `PyDict_New`, `PyEval_EvalFrameDefault`, `PyOS_Readline`, etc.
is dispatched to the corresponding C function
that was parsed from the CPython tree
and interpreted by PyCParser's interpreter.

## Status

Targeting CPython 3.7 (vendored in `CPython/`).
The interactive REPL and `-c` invocations
both work end-to-end through real interpreted C code:

```
$ ./cpython.py
PyCPython - Emulate CPython by interpreting its C code via PyCParser.
(use --pycpython-help for help)
Parsing CPython...finished
Python 3.7.4 (default, xx/xx/xx, xx:xx:xx) [GCC GCC] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> print("hello world")
hello world
>>> 1 + 2 * 3
7
>>> 42 ** 8
9682651996416
>>> import sys
>>> sys.version
'3.7.4 (default, xx/xx/xx, xx:xx:xx) [GCC GCC]'
>>> sys.stderr.write("this goes to stderr\n")
this goes to stderr
20
>>> x = "PyCPython"
>>> print(f"running on {x}")
running on PyCPython
>>> sum(range(1, 11))
55
>>> [i*i for i in range(6)]
[0, 1, 4, 9, 16, 25]
>>>
$
```

What's running underneath, in interpreted C:

1. **Tokenizer** -- `Parser/tokenizer.c` lexes each line.
2. **Parser** -- `Parser/parser.c` + `parsetok.c` build a CST against
   `Python/graminit.c`'s grammar tables.
3. **AST builder** -- `Python/ast.c` lowers CST to AST.
4. **Compiler** -- `Python/compile.c` + `symtable.c` + `peephole.c` emit a
   `PyCodeObject` with real bytecode.
5. **Evaluator** -- `Python/ceval.c` executes the bytecode through
   `_PyEval_EvalFrameDefault`.
6. **REPL input** -- `Parser/myreadline.c::PyOS_Readline` reads from stdin via
   `fgets`/`PyOS_StdioReadline`.
7. **Output** -- `print` → `PyFile_WriteObject` → `sys.stdout.write` →
   CPython's own `stdprinter` writing to `fd=1` via libc `write(2)`.

The only Python-level wrappers that remain in `cpython.py` are unavoidable for
this stripped-down build:

- `_static_pylifecycle_init_sys_streams` -- installs a `stdprinter` for
  `sys.stdout` (the real version would import the `io` module and
  `encodings.utf_8` / `encodings.latin_1`, which need a working filesystem
  importer).
- `_static_pylifecycle_initsite` -- no-op (we run without `site.py`,
  equivalent to `python -S`).
- `_static_pylifecycle_get_locale_encoding` -- bypasses
  `_PyCodec_Lookup`/`encodings` machinery.
- `_static_pylifecycle_initexternalimport` -- fast stub that skips the
  filesystem-importer bootstrap (importlib bytecode translation is minutes per
  run; not needed for builtins-only programs).
- `PyGILState_Check` -- returns 1 (we don't run a real GIL state machine).
- `PyInit_posix` -- wrapped to backfill numeric constants whose macro names
  expanded before the `#` stringification.

Everything else is the original C code, parsed and interpreted.

## Compatibility

- Host: CPython 3 (developed on 3.12 / 3.13).
- Target: CPython 3.7 (vendored in this repo).
- The C data structures are layout-compatible with stock CPython, 
  so loading real C extensions would in principle work.

## Running

```sh
./cpython.py                              # interactive REPL
./cpython.py -c "print('hello')"          # -c style one-shot
./cpython.py -i < script.py               # run a script, then drop to REPL
./cpython.py --pycpython-help             # PyCPython-specific options
```

Startup is slow (~18 s of parsing CPython source).
Once it reaches the prompt,
individual statements take a moment to evaluate
because each new C function in the call path is translated to Python AST on demand.

## Why

For fun, originally.
The first version was a 2012 toy
([pypy-dev post](https://mail.python.org/pipermail/pypy-dev/2012-January/009048.html))
that printed `Python 2.7.1` and called it a day.
The Python 3.7 path is a more serious bring-up
-- see `PROGRESS.md` for the round-by-round history.

## See also

- [PyCParser](https://github.com/albertz/PyCParser) -- the C parser /
  interpreter this builds on.
- `PROGRESS.md` -- round-by-round history of getting a real Python program to
  run end-to-end.
- `ONBOARDING.md` -- orientation guide for the codebase.
- `SEGFAULT_INVESTIGATION.md` -- deep-dive on a specific class of bug
  (file-scope-static type confusion) and the fix it motivated.
