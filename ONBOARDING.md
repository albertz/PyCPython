# PyCPython Onboarding

PyCPython interprets CPython's own C source via PyCParser (a pure-Python
C parser + AST-translating interpreter under `cparser/`). The user-facing
entry point is `cpython.py`; running `cpython.py -c "..."` parses CPython,
translates relevant C functions to Python AST on demand, and executes
them to evaluate the given Python snippet.

Also see [`PROGRESS.md`](PROGRESS.md) and [`README.md`](README.md).

## Current focus

Removing Python-level overrides/stubs in `cpython.py` one by one and
replacing them with the real interpreted C code paths, fixing
underlying `cparser`/`interpreter` bugs as they surface. **Several
overrides have been removed already; the remaining ones are listed
below.**

Read the most recent commits with `git log --oneline -20` — the commit
messages describe each removed override and the bug fixes that
unblocked it.

## Remaining overrides (in `cpython.py`)

Look for `_func_cache[...]`:

- **`pymain_init_sys_path`** — real impl calls `pymain_update_sys_path`
  which does `PySys_GetObject("path")` and fails with "can't get
  sys.path" because importlib bootstrap is skipped. Probably needs
  one of: (a) populating `sys.path` directly before `pymain_init_sys_path`
  runs, (b) overriding `pymain_update_sys_path` instead at a deeper
  layer, (c) fixing whatever blocks the importlib bootstrap.
- **`pymain_init_python_main`** — the real
  `_Py_InitializeMainInterpreter` imports the `encodings` module via
  importlib bootstrap. That path no longer infinite-loops but
  translates a huge amount of importlib bytecode on demand and takes
  minutes per run. Blocked on either translation-result caching or
  selectively skipping the encodings import. **Also currently doubles
  as the place where `sys.stdout`/`sys.stderr` stubs are installed
  (see commit history)** — those need a home if this override goes.
- **`_make_pyinit_stub`** loop — fills in `PyInit_<modname>` for
  modules whose C source isn't parsed (`itertools`, `_struct`, etc.;
  `_io` is now parsed). Strictly correct (turns silent-NULL into
  proper `ImportError`); to actually remove for a given module,
  the corresponding C source must be added to the parse list in
  `CPythonState.parse_cpython`. Many of these modules pull in
  `Python-ast.h`-style macro/grammar hazards or other parser edge
  cases — expect to fix `cparser` bugs along the way.
- `--instrument` wrapper (line ~977) — debug instrumentation, not an
  override. Leave alone.

## Workflow

1. Pick an override; read its comment for the stated blocker.
2. **Verify the blocker is real.** Several comments are stale —
   parser/interpreter has been improved since they were written.
   Quick check: query the parsed state for the function and its
   transitive callees, see if all have bodies, then try removing the
   override and run `cpython.py -c "print('hello')"`.
3. If the real C path fails, capture the traceback and decide:
   *fix the underlying parser/interpreter issue* (preferred), or
   *re-narrow the override* (e.g. populate one global instead of
   intercepting five getters — see the `_Py_path_config` commit for
   an example).
4. Write a focused regression test in `cparser/tests/test_interpret_stmnt.py`
   that reproduces the bug pattern in isolation (small C snippet,
   not the full CPython parse). Match existing style.
5. Run the test suite (see below). Smoke-test end-to-end with
   `cpython.py -c "..."`. Commit.

## Test infrastructure

- Pytest config: `cparser/conftest.py`. Run from either the project
  root or the `cparser/` repo root — both work. **Always pass a
  timeout** (`timeout 120 python -m pytest ...`); some C tests can
  hit infinite loops.
- The symlink `cparser/tests/cparser -> ..` exists so test modules
  can do `import cparser.X`; **without the conftest** pytest follows
  the link and recurses infinitely. The conftest ignores the loop
  and prepends `cparser/tests` to `sys.path` so plain
  `import helpers_test` works.
- Excluded by convention from "quick" runs:
  `test_ctestsuite.py` (slow C-testsuite), `test_sdl_header.py`
  (needs SDL). `test_interpreter_helloworld.py` does a `fork()` —
  pytest's stdout capture used to break it; fixed by restoring
  `sys.stdout = sys.__stdout__` in the forked child.
- Standard quick run:
  ```
  timeout 120 python -m pytest cparser/tests \
      --ignore=cparser/tests/test_ctestsuite.py \
      --ignore=cparser/tests/test_sdl_header.py -q
  ```
  Expect ~423 passing.

## Gotchas / lessons learned

- **Stale comments.** Multiple "this can't work because X" comments
  in `cpython.py` were no longer accurate when re-checked. Don't
  trust them; verify with a quick experiment.
- **Allocation domain matters.** Strings passed to C structs the C
  code frees (e.g. `_Py_path_config.prefix` cleared by
  `_PyPathConfig_Clear`) must be allocated in the matching heap.
  `interpreter._make_wchar_string` uses the *interpreter*'s tracked
  pool — its `_free` raises "address was not allocated by us" when
  the C side runs `PyMem_RawFree`. Use the C-side allocator instead
  (e.g. `_PyMem_RawWcsdup`) for anything the C runtime owns.
- **C99 integer literal typing matters.** `INT_MIN` etc. are
  represented as `-2147483648` literals, which under C99 §6.4.4.1
  type as `long` (decimal, signed-only candidates). `cparser`
  implements this in `cIntTypeForLiteral`. If you see surprise
  unsigned/overflow behavior on literal-typed expressions, suspect
  this path.
- **Python soft-keyword field rename.** `py_safe_identifier` renames
  C struct fields whose names are Python keywords/soft-keywords
  (`type` → `type_`, `def` → `def_`). Any lookup like
  `getattr(struct_t, field_name)` must pre-process the field name
  through `py_safe_identifier`. Both `offsetof` sites in
  `interpreter.py` were missing this; the fix is in commit history
  along with a regression test.
- **Grammar-symbol macros from `graminit.h`.** `#define test 305`,
  `#define expr 315`, etc. They get re-introduced whenever
  `ast.c` is parsed (it re-includes `graminit.h` with the dedup
  guard off). If a downstream `.c` file uses `test` or `expr` as
  a variable/field name, pop these macros from `state.macros`
  *before* parsing that file. See `_grammar_macros_to_pop` in
  `cpython.py::parse_cpython`.
- **Enum/struct forward-decl resolution.** When a `cpre3_parse_funcargs`
  fresh `CEnum()` placeholder (no body) is used as a parameter
  type, `make_type_from_typetokens` now looks up the same tag in
  the surrounding scope via `findCObjTypeInNamespace` and prefers
  the full-body version. Don't break this — the parser will
  otherwise hit `AttributeError: 'NoneType' has no contentlist` on
  enum range queries.
- **`raise Exception` style.** The user dislikes broad
  `try/except Exception:` and `try/except AttributeError:` —
  prefer `hasattr`/type checks. See `CLAUDE.md` for full style notes.

## Speed work done

- Tokenizer: `_Pre2ParseStream.next_char()` used to slice the buffer
  string by one char per read (quadratic in macro expansion length).
  Replaced with an index pointer + a putback queue for escape
  readers. Fast path for the common no-macro-expansion case.
- `State.Attribs` is a `frozenset` (was a `list`) — O(1) lookup in
  the parser hot loop.
- Interpreter peephole optimizer (`_PeepholeOptimizer` in
  `interpreter.py`): collapses generated patterns like
  `int(c_T(...).value)` → `c_T(...).value`, `c_T(c_T(X).value)` →
  `c_T(X)`. Importantly, **respects ctypes truncation semantics** —
  see the `_CTYPES_INT_RANGES` table. If you extend it, the
  collapse must be provably value-preserving (e.g. literal fits in
  T's range, or same-T idempotent re-wrap).
- `_CtypesWrappedHoister`: per-`FunctionDef` AST pass that binds
  `ctypes_wrapped.<T>` once at function entry so subsequent uses
  become `LOAD_FAST` instead of `LOAD_GLOBAL + LOAD_ATTR`.

User explicitly asked **NOT** to add: disk caches of translated
ASTs (frequent parser changes invalidate them), Cython/native
helpers (defeats the project's purpose), parallel parsing
(GIL-bound).

Still on the table: `_storePtr` round-trip elimination, more
inlining of common patterns, hoisting `intp.<helper>` like we do
for `ctypes_wrapped.<T>`.

## House rules (user preferences)

- Default Python: Something recent. See your current env.
- Don't ask before running tests/demos that you wrote — just run.
- **Always use a timeout** on long commands (max 5 min). Some tests
  can run into infinite loops.
- Follow TDD: failing test first when fixing a bug, in the existing
  test file matching the area, in the existing style. No generic
  filenames like `test_new_fixes.py`.
- Avoid bare `except Exception:` (except in root loops). Avoid
  `try: ... except AttributeError:` — use `hasattr` / type checks
  instead. Same for `except ValueError:` — use logic checks.
- Public functions/classes get type hints and docstrings.
- Match the surrounding code style. Keep changes small and focused.
- Don't add new `.md` files unless asked. Don't add emojis.

## Useful one-liners

```
# End-to-end smoke test
timeout 90 python3 cpython.py -c "print('hello'); print(1+2)"

# Full test run from repo root (cwd: PyCPython/)
timeout 120 python3 -m pytest cparser/tests \
    --ignore=cparser/tests/test_ctestsuite.py \
    --ignore=cparser/tests/test_sdl_header.py -q

# Inspect what a translated function looks like after the peephole/hoister
python3 -c "
import sys; sys.path.insert(0, '.')
import cparser, cparser.interpreter as ip
state = cparser.parse_code('int add(int a, int b) { return a+b; }')
interp = ip.Interpreter(); interp.register(state)
fn = interp.getFunc('add')
print(ip._unparse(fn.C_pyAst))
"

# Profile a parse_cpython run
python3 -c "
import cProfile, pstats, sys; sys.path.insert(0, '.')
import cpython
s = cpython.CPythonState()
pr = cProfile.Profile(); pr.enable()
s.parse_cpython()
pr.disable()
pstats.Stats(pr).sort_stats('cumulative').print_stats(20)
"
```
