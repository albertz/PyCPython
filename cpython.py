#!/usr/bin/env python3
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

from __future__ import print_function

import argparse
import os
import sys
import ctypes

MyDir = os.path.dirname(os.path.abspath(__file__))

CPythonDir = MyDir + "/CPython"

import cparser
import cparser.interpreter


class CPythonState(cparser.State):

    def __init__(self):
        super(CPythonState, self).__init__()
        self.autoSetupSystemMacros()
        self.autoSetupGlobalIncludeWrappers()
        self.included_files = set()  # type: set[str]

    def findIncludeFullFilename(self, filename, local):
        fullfn = CPythonDir + "/Include/" + filename
        if os.path.exists(fullfn): return fullfn
        return super(CPythonState, self).findIncludeFullFilename(filename, local)

    def readLocalInclude(self, filename):
        #print " ", filename, "..."
        if filename == "pyconfig.h":
            if filename in self.included_files: return "", None
            self.included_files.add(filename)
            def reader():
                # see CPython/pyconfig.h.in for reference
                sizeofMacro = lambda t: cparser.Macro(rightside=str(ctypes.sizeof(t)))
                self.macros["SIZEOF_SHORT"] = sizeofMacro(ctypes.c_short)
                self.macros["SIZEOF_INT"] = sizeofMacro(ctypes.c_int)
                self.macros["SIZEOF_LONG"] = sizeofMacro(ctypes.c_long)
                self.macros["SIZEOF_LONG_LONG"] = sizeofMacro(ctypes.c_longlong)
                self.macros["SIZEOF_DOUBLE"] = sizeofMacro(ctypes.c_double)
                self.macros["SIZEOF_FLOAT"] = sizeofMacro(ctypes.c_float)
                self.macros["SIZEOF_VOID_P"] = sizeofMacro(ctypes.c_void_p)
                self.macros["SIZEOF_SIZE_T"] = sizeofMacro(ctypes.c_size_t)
                self.macros["SIZE_MAX"] = cparser.Macro(rightside=str(ctypes.c_size_t(-1).value) + "ULL")
                self.macros["SIZEOF_UINTPTR_T"] = sizeofMacro(ctypes.POINTER(ctypes.c_uint))
                self.macros["SIZEOF_PTHREAD_T"] = self.macros["SIZEOF_LONG"]
                self.macros["SIZEOF_WCHAR_T"] = sizeofMacro(ctypes.c_wchar)
                self.macros["SIZEOF_PID_T"] = self.macros["SIZEOF_INT"]
                self.macros["SIZEOF_TIME_T"] = self.macros["SIZEOF_LONG"]
                # ``off_t`` is typedef'd as ``long`` in our sys/types.h
                # shim (cparser/globalincludewrappers.handle_sys_types_h),
                # so SIZEOF_OFF_T == SIZEOF_LONG.  _iomodule.h needs
                # this to choose between PyLong_AsLong / PyLong_AsLongLong
                # / PyLong_AsSsize_t for Py_off_t conversions.
                self.macros["SIZEOF_OFF_T"] = self.macros["SIZEOF_LONG"]
                self.macros["SIZEOF__BOOL"] = cparser.Macro(rightside="1")
                self.macros["HAVE_ERRNO_H"] = cparser.Macro(rightside="1")
                self.macros["HAVE_FCNTL_H"] = cparser.Macro(rightside="1")
                self.macros["HAVE_SYS_STAT_H"] = cparser.Macro(rightside="1")
                self.macros["HAVE_SYS_TYPES_H"] = cparser.Macro(rightside="1")
                self.macros["HAVE_UNISTD_H"] = cparser.Macro(rightside="1")
                # Force strict ANSI mode so pymacro.h uses the simple Py_ARRAY_LENGTH
                # (without GCC-extension typeof/__builtin_types_compatible_p).
                self.macros["__STRICT_ANSI__"] = cparser.Macro(rightside="1")
                # _PYTHONFRAMEWORK: name of the macOS framework bundle (empty when not bundled)
                self.macros["_PYTHONFRAMEWORK"] = cparser.Macro(rightside='""')
                self.macros["HAVE_SIGNAL_H"] = cparser.Macro(rightside="1")
                self.macros["HAVE_STDARG_PROTOTYPES"] = cparser.Macro(rightside="1")
                self.macros["HAVE_STD_ATOMIC"] = cparser.Macro(rightside="1")
                self.macros["HAVE_WCHAR_H"] = cparser.Macro(rightside="1")
                # ``initfsencoding`` needs ``nl_langinfo(CODESET)`` to
                # discover the filesystem encoding.  Without this, it
                # returns NULL and ``_Py_FatalInitError`` aborts with
                # "Unable to get the locale encoding".
                self.macros["HAVE_LANGINFO_H"] = cparser.Macro(rightside="1")
                # posixmodule.c gates its dirent / utime / sys-wait
                # blocks on these.  We provide stubs for the underlying
                # headers in cparser.globalincludewrappers so the
                # parsed code finds the identifiers.
                self.macros["HAVE_DIRENT_H"] = cparser.Macro(rightside="1")
                self.macros["HAVE_UTIME_H"] = cparser.Macro(rightside="1")
                self.macros["HAVE_SYS_WAIT_H"] = cparser.Macro(rightside="1")
                self.macros["_POSIX_THREADS"] = cparser.Macro(rightside="1")
                # _GNU_SOURCE, _POSIX_C_SOURCE or so?
                return
                yield None # make it a generator
            return reader(), None
        fullfn = self.findIncludeFullFilename(filename, True)
        # Stringlib headers are template headers: they are intentionally included
        # multiple times with different macro definitions (STRINGLIB=ucs1lib_ etc.)
        # and must NOT be deduplicated by filename.
        is_template_header = fullfn and os.path.join(CPythonDir, "Objects", "stringlib") in fullfn
        # ``graminit.h`` has no include guard and is intended to be
        # re-included by ast.c / compile.c / parsetok.c each with the
        # grammar-symbol macros (``expr``, ``atom``, ...) freshly
        # defined for that translation unit.  Don't dedupe it.
        is_graminit = fullfn and fullfn.endswith("/graminit.h")
        if not is_template_header and not is_graminit:
            if fullfn and fullfn in self.included_files: return "", fullfn
            if fullfn: self.included_files.add(fullfn)
        return super(CPythonState, self).readLocalInclude(filename)

    def readGlobalInclude(self, filename):
        """Fall back to CPython/Include/<filename> for any unhandled global include."""
        fullfn = os.path.join(CPythonDir, "Include", filename)
        if os.path.exists(fullfn):
            return self.readLocalInclude(fullfn)
        return super(CPythonState, self).readGlobalInclude(filename)

    # Modules to register in ``_PyImport_Inittab`` beyond the
    # always-built-in ones declared by ``Modules/config.c.in`` itself
    # (marshal, _imp, _ast, builtins, sys, gc, _warnings, _string).
    # Real CPython picks this list from ``Modules/Setup`` via the
    # ``makesetup`` script; we hard-code it.  Windows-only entries
    # (winreg, _winapi, msvcrt, _locale, nt) are intentionally
    # excluded and ``nt`` is replaced by ``posix``.
    _EXTRA_INITTAB_MODULES = [
        "_abc", "array", "audioop", "binascii", "cmath", "errno",
        "faulthandler", "math", "posix", "_operator", "_signal",
        "_md5", "_sha1", "_sha256", "_sha512", "_sha3", "_blake2",
        "time", "_thread", "_tracemalloc", "_codecs", "_weakref",
        "_random", "_bisect", "_heapq", "_lsprof", "itertools",
        "_collections", "_symtable", "mmap", "_csv", "_sre",
        "parser", "_struct", "_datetime", "_functools", "_json",
        "xxsubtype", "zipimport",
        "_multibytecodec", "_codecs_cn", "_codecs_hk",
        "_codecs_iso2022", "_codecs_jp", "_codecs_kr", "_codecs_tw",
        "_io", "_pickle", "atexit", "_stat", "_opcode",
        "_contextvars",
    ]

    def _parse_makesetup_inittab(self):
        """Replicate what CPython's ``Modules/makesetup`` shell script
        does at build time: read ``Modules/config.c.in``, splice the
        per-build module list into the ``ADDMODULE MARKER`` slots,
        parse the result.

        Marker 1 hosts the ``extern PyObject* PyInit_xxx(void);``
        declarations; marker 2 hosts the ``{"xxx", PyInit_xxx},``
        entries inside ``_PyImport_Inittab[]``.
        """
        with open(CPythonDir + "/Modules/config.c.in") as f:
            src = f.read()
        extern_decls = "\n".join(
            "extern PyObject* PyInit_%s(void);" % mod
            for mod in self._EXTRA_INITTAB_MODULES)
        inittab_entries = "\n".join(
            '    {"%s", PyInit_%s},' % (mod, mod)
            for mod in self._EXTRA_INITTAB_MODULES)
        marker1 = "/* -- ADDMODULE MARKER 1 -- */"
        marker2 = "/* -- ADDMODULE MARKER 2 -- */"
        assert marker1 in src and marker2 in src, \
            "config.c.in template missing expected ADDMODULE markers"
        src = src.replace(marker1, marker1 + "\n" + extern_decls, 1)
        src = src.replace(marker2, marker2 + "\n" + inittab_entries, 1)
        cparser.parse_code(src, self)

    def parse_cpython(self):
        # We keep all in the same state, i.e. the same static space.
        # This also means that we don't reset macro definitions. This speeds up header includes.
        # Usually this is not a problem.
        self.macros["Py_BUILD_CORE"] = cparser.Macro(rightside="1")  # Makefile
        self.macros["Py_BUILD_CORE_BUILTIN"] = cparser.Macro(rightside="1")  # Makefile
        cparser.parse(CPythonDir + "/Modules/main.c", self) # Py_Main
        self.macros["FAST_LOOPS"] = cparser.Macro(rightside="0")  # not sure where this would come from
        cparser.parse(CPythonDir + "/Python/ceval.c", self) # PyEval_EvalFrameEx etc
        del self.macros["EMPTY"]  # will be redefined later
        cparser.parse(CPythonDir + "/Python/getopt.c", self) # _PyOS_GetOpt
        cparser.parse(CPythonDir + "/Python/pythonrun.c", self) # Py_Initialize
        cparser.parse(CPythonDir + "/Python/pyarena.c", self) # PyArena_New, struct _arena
        cparser.parse(CPythonDir + "/Parser/bitset.c", self)
        cparser.parse(CPythonDir + "/Parser/grammar1.c", self)
        cparser.parse(CPythonDir + "/Parser/node.c", self) # PyNode_New, etc.
        cparser.parse(CPythonDir + "/Parser/listnode.c", self)
        cparser.parse(CPythonDir + "/Parser/acceler.c", self)
        cparser.parse(CPythonDir + "/Parser/tokenizer.c", self) # PyTokenizer_*
        cparser.parse(CPythonDir + "/Parser/parser.c", self) # PyParser_New, PyParser_AddToken
        cparser.parse(CPythonDir + "/Parser/parsetok.c", self) # PyParser_ParseStringObject
        cparser.parse(CPythonDir + "/Python/graminit.c", self) # _PyParser_Grammar
        # ``graminit.h`` (transitively included via ``parsetok.c``) defines
        # very generic grammar-symbol names like ``test``, ``expr``,
        # ``atom``, ``term``, ``power``, etc. as integer constants.
        # cparser keeps a single global macro namespace, so these would
        # poison every subsequently-parsed file using any of those names
        # as a local variable (e.g. ``bytearray_repr`` has
        # ``char *test, *start;``).  Pop them here -- parser
        # C code that needs them has already been parsed.  We have to
        # do this AGAIN later because ast.c re-includes graminit.h.
        _grammar_macros_to_pop = (
            "single_input", "file_input", "eval_input", "decorator",
            "decorators", "decorated", "async_funcdef", "funcdef",
            "parameters", "typedargslist", "tfpdef", "varargslist",
            "vfpdef", "stmt", "simple_stmt", "small_stmt", "expr_stmt",
            "annassign", "testlist_star_expr", "augassign", "del_stmt",
            "pass_stmt", "flow_stmt", "break_stmt", "continue_stmt",
            "return_stmt", "yield_stmt", "raise_stmt", "import_stmt",
            "import_name", "import_from", "import_as_name",
            "dotted_as_name", "import_as_names", "dotted_as_names",
            "dotted_name", "global_stmt", "nonlocal_stmt", "assert_stmt",
            "compound_stmt", "async_stmt", "if_stmt", "while_stmt",
            "for_stmt", "try_stmt", "with_stmt", "with_item",
            "except_clause", "suite", "test", "test_nocond", "lambdef",
            "lambdef_nocond", "or_test", "and_test", "not_test",
            "comparison", "comp_op", "star_expr", "expr", "xor_expr",
            "and_expr", "shift_expr", "arith_expr", "term", "factor",
            "power", "atom_expr", "atom", "testlist_comp", "trailer",
            "subscriptlist", "subscript", "sliceop", "exprlist",
            "testlist", "dictorsetmaker", "classdef", "arglist",
            "argument", "comp_iter", "sync_comp_for", "comp_for",
            "comp_if", "encoding_decl", "yield_expr", "yield_arg",
        )
        for _m in _grammar_macros_to_pop:
            self.macros.pop(_m, None)
        # Parse the AST + compile chain.  ast.c re-includes graminit.h
        # (no include guard -- we made it non-dedup'd in
        # readLocalInclude) so it sees the grammar-symbol macros
        # freshly defined and can use ``case suite:`` switch labels.
        cparser.parse(CPythonDir + "/Python/asdl.c", self) # _Py_asdl_seq_new
        cparser.parse(CPythonDir + "/Python/Python-ast.c", self) # _PyAST_*
        cparser.parse(CPythonDir + "/Python/ast.c", self) # PyAST_FromNodeObject
        cparser.parse(CPythonDir + "/Python/future.c", self) # PyFuture_FromASTObject
        cparser.parse(CPythonDir + "/Python/peephole.c", self) # PyCode_Optimize
        # ast.c put those macros back.  Pop AGAIN before ast_opt.c /
        # symtable.c / compile.c.  ast_opt.c uses ``node_->v.While.test``
        # where ``test`` is otherwise expanded to ``305``.  compile.c
        # uses ``VISIT(C, expr, V)`` to token-paste
        # ``compiler_visit_expr``; if ``expr`` is still macro = 315,
        # the result is ``compiler_visit_315`` (parse error).
        for _m in _grammar_macros_to_pop:
            self.macros.pop(_m, None)
        cparser.parse(CPythonDir + "/Python/ast_opt.c", self) # _PyAST_Optimize
        self.macros.pop("OFF", None)  # symtable.c re-defines OFF
        # Python-reserved-word / dunder C identifiers (``lambda``,
        # ``__doc__``, ``__class__``, ``__annotations__`` in
        # symtable.c / compile.c) are now handled automatically by
        # cparser's ``py_safe_identifier`` rename + ``GlobalsWrapper.
        # __getattribute__`` override -- no source-level renaming
        # needed here.
        cparser.parse(CPythonDir + "/Python/symtable.c", self) # _PySymtable_Build
        # compile.c re-#defines DEFAULT_BLOCK_SIZE (originally from
        # pyarena.c), VISIT and VISIT_SEQ (both originally from
        # symtable.c).  In real C each #define would have local scope
        # to its translation unit; our single-state parser keeps them
        # alive across files, so pop them here to let compile.c
        # redefine cleanly.
        for _m in ("DEFAULT_BLOCK_SIZE", "VISIT", "VISIT_SEQ"):
            self.macros.pop(_m, None)
        cparser.parse(CPythonDir + "/Python/compile.c", self) # PyAST_CompileObject
        cparser.parse(CPythonDir + "/Python/pystate.c", self) # PyInterpreterState_New
        cparser.parse(CPythonDir + "/Python/errors.c", self) # PyErr_Clear
        cparser.parse(CPythonDir + "/Python/getargs.c", self) # PyArg_ParseTuple, _PyArg_UnpackStack, etc.
        cparser.parse(CPythonDir + "/Python/structmember.c", self) # PyMember_GetOne, PyMember_SetOne
        self.macros.pop("FLAG_SIZE_T", None)
        # Linux-flavored inittab.
        # CPython builds run the ``Modules/makesetup`` shell script over
        # ``Modules/config.c.in`` + ``Modules/Setup`` to produce
        # ``Modules/config.c`` with the per-build module list spliced
        # at the ``ADDMODULE MARKER`` comments.  We don't build, so
        # replicate that splice on the fly here.
        self._parse_makesetup_inittab() # _PyImport_Inittab
        cparser.parse(CPythonDir + "/Python/import.c", self) # _PyImport_Fini2
        cparser.parse(CPythonDir + "/Python/thread.c", self) # PyThread_allocate_lock
        cparser.parse(CPythonDir + "/Python/bootstrap_hash.c", self) # _Py_ReadHashSeed
        cparser.parse(CPythonDir + "/Python/codecs.c", self) # Py_hexdigits
        # Collision: static void fatal_error(...) in pylifecycle.c vs static struct fatal_error in faulthandler.c.
        # We rename them via macros to unique names to avoid shadowing in the global funcs/vars dicts.
        self.macros["fatal_error"] = cparser.Macro(rightside="fatal_error_pylifecycle")
        cparser.parse(CPythonDir + "/Python/pylifecycle.c", self) # _PyRuntime_Initialize, _Py_SetLocaleFromEnv
        self.macros.pop("fatal_error")
        self.macros.pop("NAME", None)  # token.h defines NAME=1; sysmodule.c redefines it as "cpython"
        if os.path.exists(CPythonDir + "/Python/random.c"):
            cparser.parse(CPythonDir + "/Python/random.c", self) # _PyRandom_Init
        cparser.parse(CPythonDir + "/Python/pyhash.c", self) # _Py_HashPointer, _Py_HashDouble, etc.
        cparser.parse(CPythonDir + "/Python/pyctype.c", self) # _Py_ctype_table, _Py_ctype_tolower, _Py_ctype_toupper
        cparser.parse(CPythonDir + "/Objects/object.c", self) # _Py_ReadyTypes etc
        self.macros["free_list"] = cparser.Macro(rightside="free_list_bool")
        cparser.parse(CPythonDir + "/Objects/boolobject.c", self) # PyBool_Type
        self.macros["free_list"] = cparser.Macro(rightside="free_list_float")
        cparser.parse(CPythonDir + "/Objects/floatobject.c", self) # PyFloat_Type
        self.macros.pop("free_list")
        cparser.parse(CPythonDir + "/Objects/unicodeobject.c", self) # PyUnicode_InternFromString etc.
        cparser.parse(CPythonDir + "/Objects/typeobject.c", self) # PyType_Ready
        cparser.parse(CPythonDir + "/Objects/moduleobject.c", self) # _PyModule_CreateInitialized, PyModule_New, etc.
        # provide getversion (Py_GetVersion) before modules that call it
        cparser.parse(CPythonDir + "/Python/getversion.c", self) # Py_GetVersion
        # buildinfo, compiler id and snprintf wrappers used during init
        cparser.parse(CPythonDir + "/Modules/getbuildinfo.c", self) # Py_GetBuildInfo, _Py_gitversion, _Py_gitidentifier
        cparser.parse(CPythonDir + "/Python/getcopyright.c", self) # Py_GetCopyright
        cparser.parse(CPythonDir + "/Python/getplatform.c", self) # Py_GetPlatform
        # __VERSION__ is a compiler-provided macro; define a safe default
        self.macros["__VERSION__"] = cparser.Macro(rightside='"GCC"')
        cparser.parse(CPythonDir + "/Python/getcompiler.c", self) # Py_GetCompiler
        self.macros.pop("__VERSION__", None)
        cparser.parse(CPythonDir + "/Python/mysnprintf.c", self) # PyOS_snprintf, PyOS_vsnprintf
        cparser.parse(CPythonDir + "/Python/mystrtoul.c", self) # PyOS_strtol, PyOS_strtoul
        # formatter_unicode.c provides ``_PyUnicode_FormatAdvancedWriter``
        # / ``_PyLong_FormatAdvancedWriter`` / ``_PyFloat_FormatAdvancedWriter``
        # / ``_PyComplex_FormatAdvancedWriter`` -- without these,
        # ``render_field`` in unicode_format.h dispatches to a body-less
        # stub that silently returns 0 (success) without writing
        # anything.  Symptom: ``'{!r}'.format(x)`` produces just the
        # literal prefix; e.g. importlib's ``_ERR_MSG.format(name)``
        # becomes ``"No module named "`` with the ``{!r}`` part missing.
        # File-scope static collisions: ``get_integer`` clashes with
        # the same name in ``stringlib/unicode_format.h`` (different
        # signature), and ``format_obj`` clashes with the same name in
        # bytesobject.c.  Rename both via macros for this file.
        self.macros["get_integer"] = cparser.Macro(rightside="get_integer_formatter")
        self.macros["format_obj"] = cparser.Macro(rightside="format_obj_formatter")
        cparser.parse(CPythonDir + "/Python/formatter_unicode.c", self) # _Py*_FormatAdvancedWriter
        self.macros.pop("get_integer", None)
        self.macros.pop("format_obj", None)
        cparser.parse(CPythonDir + "/Python/sysmodule.c", self) # PySys_ResetWarnOptions
        cparser.parse(CPythonDir + "/Objects/weakrefobject.c", self) # PyWeakref_NewRef
        # funcobject.c must be parsed BEFORE bytearrayobject.c (and others
        # that have METH_STATIC / METH_CLASS methods) so that PyStaticMethod_Type
        # / PyClassMethod_Type / PyFunction_Type get their static initializer
        # (tp_alloc = PyType_GenericAlloc etc.).  Without it, add_methods()
        # calls PyStaticMethod_New() which finds tp_alloc == NULL and returns
        # NULL, making PyType_Ready fail with no Python-level error message.
        # funcobject.c re-#defines OFF (originally from symtable.c).
        self.macros.pop("OFF", None)
        cparser.parse(CPythonDir + "/Objects/funcobject.c", self) # PyStaticMethod_New, PyFunction_Type
        cparser.parse(CPythonDir + "/Objects/longobject.c", self) # PyLong_FromVoidPtr, PyLong_FromLong etc.
        # bytes_methods.c provides the _Py_<method>__doc__ docstring
        # globals that both bytearrayobject.c and bytesobject.c reference
        # in their PyMethodDef tables (declared in Include/bytes_methods.h).
        # Stringlib template macros leaked from unicodedefs.h (via
        # unicodeobject.c) and need to be popped so bytes_methods.c can
        # set up the byte-flavoured stringlib cleanly.
        for _m in ("STRINGLIB_WANT_CONTAINS_OBJ",
                   "STRINGLIB_STR", "STRINGLIB_LEN",
                   "STRINGLIB_NEW", "STRINGLIB_CHECK", "STRINGLIB_CHECK_EXACT",
                   "STRINGLIB_TOSTR", "STRINGLIB_TOASCII",
                   "STRINGLIB_FAST_MEMCHR",
                   "STRINGLIB", "STRINGLIB_CHAR", "STRINGLIB_SIZEOF_CHAR",
                   "STRINGLIB_ISSPACE", "STRINGLIB_ISLINEBREAK",
                   "FASTSEARCH",
                   # ADJUST_INDICES is re-defined identically in
                   # bytes_methods.c, unicodeobject.c, and probably more.
                   "ADJUST_INDICES"):
            self.macros.pop(_m, None)
        # ``tailmatch`` collides: unicodeobject.c uses (PyObject*,
        # PyObject*, Py_ssize_t, Py_ssize_t, int), bytes_methods.c
        # uses (const char*, Py_ssize_t, PyObject*, ...).  Rename
        # bytes_methods's version.
        self.macros["tailmatch"] = cparser.Macro(rightside="tailmatch_bytes")
        cparser.parse(CPythonDir + "/Objects/bytes_methods.c", self)
        self.macros.pop("tailmatch", None)
        # bytearrayobject.c #defines STRINGLIB_* macros that asciilib.h
        # (included via unicodeobject.c above) already defined.  Drop the
        # earlier definitions so the file can re-#define them locally.
        for _m in ("STRINGLIB_ISSPACE", "STRINGLIB_ISLINEBREAK",
                   "STRINGLIB_CHECK_EXACT"):
            self.macros.pop(_m, None)
        # File-scope static collisions with unicodeobject.c.  Rename
        # bytearrayobject's versions to avoid type-confusion merging.
        self.macros["_common_reduce"] = cparser.Macro(rightside="_common_reduce_bytearray")
        self.macros["pad"] = cparser.Macro(rightside="pad_bytearray")
        cparser.parse(CPythonDir + "/Objects/bytearrayobject.c", self) # PyByteArray_Type
        self.macros.pop("_common_reduce", None)
        self.macros.pop("pad", None)
        # bytesobject.c includes stringlib/stringdefs.h which redefines a
        # bunch of STRINGLIB_* macros that asciilib.h (via unicodeobject.c)
        # already set up, plus the ADJUST_INDICES helper that bytearray and
        # unicodeobject both define.  Pop them all so the second definitions
        # aren't rejected as duplicates.
        for _m in (# stringlib template parameters
                   "STRINGLIB_WANT_CONTAINS_OBJ",
                   "STRINGLIB_STR", "STRINGLIB_LEN",
                   "STRINGLIB_NEW", "STRINGLIB_CHECK", "STRINGLIB_CHECK_EXACT",
                   "STRINGLIB_TOSTR", "STRINGLIB_TOASCII",
                   "STRINGLIB_FAST_MEMCHR",
                   "STRINGLIB", "STRINGLIB_CHAR", "STRINGLIB_SIZEOF_CHAR",
                   "STRINGLIB_ISSPACE", "STRINGLIB_ISLINEBREAK",
                   # stringdefs.h vs asciilib.h overlap
                   "STRINGLIB_OBJECT", "STRINGLIB_TYPE_NAME",
                   "STRINGLIB_PARSE_CODE", "STRINGLIB_EMPTY",
                   "STRINGLIB_ISDECIMAL", "STRINGLIB_TODECIMAL",
                   # helpers
                   "FASTSEARCH", "ADJUST_INDICES"):
            self.macros.pop(_m, None)
        # `formatfloat` is declared with INCOMPATIBLE TYPES across
        # unicodeobject.c (int) and bytesobject.c (char*).  Without a
        # rename, cparser would (correctly) error on this static
        # collision -- merging the two would cause type-confusion.
        # Rename bytesobject's `formatfloat` to disambiguate.
        self.macros["formatfloat"] = cparser.Macro(rightside="formatfloat_bytesobject")
        # bytesobject.c also has its own ``do_strip``, ``do_argstrip``,
        # ``pad`` colliding with unicodeobject.c versions of the same
        # name but different signatures.
        self.macros["do_strip"] = cparser.Macro(rightside="do_strip_bytes")
        self.macros["do_argstrip"] = cparser.Macro(rightside="do_argstrip_bytes")
        self.macros["pad"] = cparser.Macro(rightside="pad_bytes")
        cparser.parse(CPythonDir + "/Objects/bytesobject.c", self) # PyBytes_Type
        self.macros.pop("do_strip", None)
        self.macros.pop("do_argstrip", None)
        self.macros.pop("pad", None)
        self.macros.pop("formatfloat", None)
        cparser.parse(CPythonDir + "/Objects/rangeobject.c", self) # PyRange_Type
        cparser.parse(CPythonDir + "/Objects/enumobject.c", self) # PyEnum_Type
        cparser.parse(CPythonDir + "/Objects/fileobject.c", self) # PyStdPrinter_Type
        self.macros.pop("OFF", None)  # funcobject.c defines OFF; codeobject.c redefines it
        cparser.parse(CPythonDir + "/Objects/codeobject.c", self) # PyCode_Type
        self.macros.pop("OFF", None)  # frameobject.c redefines it
        cparser.parse(CPythonDir + "/Objects/frameobject.c", self) # PyFrame_Type
        cparser.parse(CPythonDir + "/Objects/genobject.c", self) # PyGen_Type, PyCoro_Type, PyAsyncGen_Type
        cparser.parse(CPythonDir + "/Objects/namespaceobject.c", self) # _PyNamespace_Type
        cparser.parse(CPythonDir + "/Objects/capsule.c", self) # PyCapsule_Type
        cparser.parse(CPythonDir + "/Objects/cellobject.c", self) # PyCell_Type
        cparser.parse(CPythonDir + "/Objects/iterobject.c", self) # PyCallIter_Type, PySeqIter_Type
        cparser.parse(CPythonDir + "/Objects/structseq.c", self) # PyStructSequence_InitType2
        cparser.parse(CPythonDir + "/Objects/odictobject.c", self) # PyODict_Type, PyODictKeys/Values/Items/Iter_Type
        cparser.parse(CPythonDir + "/Objects/setobject.c", self) # PySet_Type, PyFrozenSet_Type
        # setobject.c defines `#define dummy (&_dummy_struct)`,
        # but `dummy` is used in subsequent files,
        # like `(PyObject *dummy)` in Objects/memoryobject.c.
        self.macros.pop("dummy", None)
        cparser.parse(CPythonDir + "/Objects/sliceobject.c", self) # PySlice_Type, Py_Ellipsis
        cparser.parse(CPythonDir + "/Objects/exceptions.c", self) # PyExc_BaseException, PyExc_SystemError, all PyExc_*
        cparser.parse(CPythonDir + "/Python/bltinmodule.c", self) # Py_UTF8Mode, builtin functions
        # _warnings.c defines its own MODULE_NAME; pop the one bltinmodule.c left.
        self.macros.pop("MODULE_NAME", None)
        cparser.parse(CPythonDir + "/Python/_warnings.c", self) # _PyWarnings_Init
        cparser.parse(CPythonDir + "/Python/hamt.c", self) # _PyHamt_Init, PyHamt_Type
        cparser.parse(CPythonDir + "/Python/context.c", self) # _PyContext_Init, PyContext_Type
        cparser.parse(CPythonDir + "/Python/frozen.c", self) # _PyImport_FrozenModules, PyImport_FrozenModules
        # hashtable.c must be parsed BEFORE marshal.c -- marshal's
        # ``w_init_refs`` calls ``_Py_hashtable_new``, and a missing
        # body makes it return None which marshal treats as NULL ->
        # PyErr_NoMemory.  This broke ``import encodings`` during the
        # importlib bootstrap (encodings -> codecs -> get_code ->
        # _code_to_timestamp_pyc -> marshal.dumps -> w_init_refs).
        cparser.parse(CPythonDir + "/Modules/hashtable.c", self) # _Py_hashtable_new, _Py_hashtable_hash_ptr, _Py_hashtable_compare_direct
        cparser.parse(CPythonDir + "/Python/marshal.c", self) # PyMarshal_ReadObjectFromString
        cparser.parse(CPythonDir + "/Objects/complexobject.c", self) # PyComplex_Type
        cparser.parse(CPythonDir + "/Objects/memoryobject.c", self) # _PyManagedBuffer_Type, PyMemoryView_Type
        cparser.parse(CPythonDir + "/Objects/call.c", self) # PyObject_Call, PyCFunction_Call
        self.macros["free_list"] = cparser.Macro(rightside="free_list_tuple")
        self.macros["numfree"] = cparser.Macro(rightside="numfree_tuple")
        cparser.parse(CPythonDir + "/Objects/tupleobject.c", self) # PyTuple_New
        # We need these macro hacks because dictobject.c will use the same vars.
        self.macros["length_hint_doc"] = cparser.Macro(rightside="length_hint_doc__dict")
        self.macros["numfree"] = cparser.Macro(rightside="numfree__dict")
        self.macros["free_list"] = cparser.Macro(rightside="free_list__dict")
        cparser.parse(CPythonDir + "/Objects/dictobject.c", self)  # PyDict_New
        # We need this macro hack because stringobject.c will use the same var.
        self.macros["sizeof__doc__"] = cparser.Macro(rightside="sizeof__doc__str")
        if os.path.exists(CPythonDir + "/Objects/stringobject.c"):
            cparser.parse(CPythonDir + "/Objects/stringobject.c", self)  # PyString_FromString
        cparser.parse(CPythonDir + "/Objects/obmalloc.c", self) # PyObject_Free
        cparser.parse(CPythonDir + "/Modules/gcmodule.c", self) # _PyObject_GC_NewVar
        cparser.parse(CPythonDir + "/Objects/descrobject.c", self) # PyDescr_NewWrapper
        # `classobject.c` and `methodobject.c` both declare ``static
        # free_list`` and ``static numfree`` at file scope -- of
        # DIFFERENT types (PyMethodObject* vs PyCFunctionObject*).
        # Our cparser doesn't distinguish file-scope statics (known
        # limitation -- see ``cparser/tests/test_file_scope_statics.py``
        # for a minimal reproducer).  Without explicit per-file
        # renaming via macros, both end up as the SAME global var,
        # which causes ``method_dealloc`` to push PyMethodObjects
        # onto the list that ``PyCFunction_NewEx`` then pops -- it
        # interprets a 40-byte PyMethod slot as a 48-byte PyCFunction
        # and writes 8 bytes past the slot, corrupting the next
        # pymalloc allocation's PyGC_Head._gc_next.  The corrupted
        # gc-list link then triggers a segfault during host Python's
        # shutdown gc walk.  Same trick already applied for
        # bool/float/dict/tuple/list above and below.
        self.macros["numfree"] = cparser.Macro(rightside="numfree__methodobj")
        self.macros["free_list"] = cparser.Macro(rightside="free_list__methodobj")
        self.macros.pop("OFF", None)  # funcobject.c defines OFF; methodobject.c redefines it
        cparser.parse(CPythonDir + "/Objects/methodobject.c", self) # PyCFunction_NewEx
        self.macros["numfree"] = cparser.Macro(rightside="numfree__classobj")
        self.macros["free_list"] = cparser.Macro(rightside="free_list__classobj")
        # ``method_get_doc`` and ``method_repr`` collide between
        # classobject.c and descrobject.c (different first-arg types).
        self.macros["method_get_doc"] = cparser.Macro(rightside="method_get_doc__classobj")
        self.macros["method_repr"] = cparser.Macro(rightside="method_repr__classobj")
        cparser.parse(CPythonDir + "/Objects/classobject.c", self) # PyMethod_Type
        self.macros.pop("method_get_doc", None)
        self.macros.pop("method_repr", None)
        # We need these macro hacks because methodobject.c used the same vars.
        self.macros["numfree"] = cparser.Macro(rightside="numfree__list")
        self.macros["free_list"] = cparser.Macro(rightside="free_list__list")
        self.macros["sizeof_doc"] = cparser.Macro(rightside="sizeof_doc__list")
        self.macros["length_hint_doc"] = cparser.Macro(rightside="length_hint_doc__list")
        self.macros["index_doc"] = cparser.Macro(rightside="index_doc__list")
        self.macros["count_doc"] = cparser.Macro(rightside="count__list")
        self.macros.pop("OFF", None)   # reused later
        cparser.parse(CPythonDir + "/Objects/listobject.c", self) # PyList_New
        cparser.parse(CPythonDir + "/Objects/abstract.c", self) # PySequence_List
        cparser.parse(CPythonDir + "/Python/modsupport.c", self) # Py_BuildValue
        # fileutils.c must come before traceback.c (provides _Py_write_noraise)
        cparser.parse(CPythonDir + "/Python/fileutils.c", self) # _Py_ResetForceASCII, _Py_open_noraise
        cparser.parse(CPythonDir + "/Python/pathconfig.c", self) # _PyPathConfig_Init
        cparser.parse(CPythonDir + "/Python/traceback.c", self) # _Py_DumpTracebackThreads
        self.macros.pop("PUTS", None)  # traceback.c and faulthandler.c both define PUTS identically
        self.macros.pop("OFF", None)   # traceback.c and faulthandler.c both define OFF differently
        # Rename static struct fatal_error to fatal_error_faulthandler.
        self.macros["fatal_error"] = cparser.Macro(rightside="fatal_error_faulthandler")
        cparser.parse(CPythonDir + "/Modules/faulthandler.c", self) # _PyFaulthandler_Fini
        self.macros.pop("fatal_error")
        # Modules imported by ``importlib._bootstrap._setup`` at
        # startup -- without these, initimport fails fatally.
        cparser.parse(CPythonDir + "/Modules/_threadmodule.c", self) # PyInit__thread
        cparser.parse(CPythonDir + "/Modules/_weakref.c", self) # PyInit__weakref
        cparser.parse(CPythonDir + "/Modules/_stat.c", self) # PyInit__stat
        cparser.parse(CPythonDir + "/Modules/_opcode.c", self) # PyInit__opcode
        cparser.parse(CPythonDir + "/Modules/_contextvarsmodule.c", self) # PyInit__contextvars
        cparser.parse(CPythonDir + "/Modules/_bisectmodule.c", self) # PyInit__bisect
        cparser.parse(CPythonDir + "/Modules/atexitmodule.c", self) # PyInit_atexit
        cparser.parse(CPythonDir + "/Modules/_heapqmodule.c", self) # PyInit__heapq
        cparser.parse(CPythonDir + "/Modules/_randommodule.c", self) # PyInit__random
        cparser.parse(CPythonDir + "/Modules/errnomodule.c", self) # PyInit_errno
        cparser.parse(CPythonDir + "/Modules/xxsubtype.c", self) # PyInit_xxsubtype
        cparser.parse(CPythonDir + "/Modules/_abc.c", self) # PyInit__abc
        cparser.parse(CPythonDir + "/Modules/_functoolsmodule.c", self) # PyInit__functools
        # _collectionsmodule.c defines ``typedef struct BLOCK {...}
        # block;`` for the deque's internal node, but ``block`` is
        # already a typedef in pyarena.c (the arena's memory block --
        # with field ``ab_size``).  Without a rename, the deque
        # version overwrites the arena one, then pyarena.c's later
        # translation tries ``b->ab_size`` on the deque block and
        # AttributeErrors.  Rename the deque side.
        self.macros["block"] = cparser.Macro(rightside="block_deque")
        cparser.parse(CPythonDir + "/Modules/_collectionsmodule.c", self) # PyInit__collections
        self.macros.pop("block", None)
        # _functools.c re-#defines OFF (already defined elsewhere); pop
        # so _struct.c can redefine cleanly with its own value.
        self.macros.pop("OFF", None)
        cparser.parse(CPythonDir + "/Modules/_struct.c", self) # PyInit__struct
        cparser.parse(CPythonDir + "/Modules/_operator.c", self) # PyInit__operator
        cparser.parse(CPythonDir + "/Modules/mathmodule.c", self) # PyInit_math
        cparser.parse(CPythonDir + "/Modules/_codecsmodule.c", self) # PyInit__codecs
        # _csv.c has a file-scope ``static get_string(PyObject *)`` that
        # collides with exceptions.c's ``static get_string(PyObject *,
        # const char *)`` (incompatible types).  Rename the _csv side.
        self.macros["get_string"] = cparser.Macro(rightside="get_string_csv")
        cparser.parse(CPythonDir + "/Modules/_csv.c", self) # PyInit__csv
        self.macros.pop("get_string", None)
        # _json.c re-defines Py_BUILD_CORE_BUILTIN.
        self.macros.pop("Py_BUILD_CORE_BUILTIN", None)
        cparser.parse(CPythonDir + "/Modules/_json.c", self) # PyInit__json
        # NOTE: itertoolsmodule.c uses ``PyObject *(values[LINKCELLS]);``
        # (parenthesized array declarator) which our cparser doesn't
        # yet handle.  TODO: parse.
        cparser.parse(CPythonDir + "/Modules/sha1module.c", self) # PyInit__sha1
        cparser.parse(CPythonDir + "/Modules/md5module.c", self) # PyInit__md5
        # _randommodule.c defines `N` (Mersenne Twister state size);
        # cmathmodule.c redefines `N` as a series-length constant.
        self.macros.pop("N", None)
        cparser.parse(CPythonDir + "/Modules/cmathmodule.c", self) # PyInit_cmath
        cparser.parse(CPythonDir + "/Modules/sha256module.c", self) # PyInit__sha256
        # NOTE: sha512module.c shares many static helper names
        # (SHAobject, SHAcopy, SHA_init, longReverse, ...) with
        # sha256module.c, all incompatible types.  Each needs an
        # individual macro rename.  Skip for now -- TODO.
        cparser.parse(CPythonDir + "/Modules/arraymodule.c", self) # PyInit_array
        cparser.parse(CPythonDir + "/Python/_warnings.c", self) # _PyWarnings_Init
        # ``posix`` (Modules/posixmodule.c) -- importlib's
        # _bootstrap_external._setup() walks [posix, nt] looking for the
        # OS module and aborts initexternalimport with "importlib
        # requires posix or nt" when neither is in the inittab.  Parse
        # posixmodule.c so PyInit_posix has a real body.
        #
        # File-scope-static collisions with previously-parsed files
        # (same name in our single-translation-unit symbol space --
        # see notes on bool/float/dict/tuple/list/methodobj/classobj).
        # posixmodule.c declares ``static newfunc structseq_new`` as a
        # function-pointer VARIABLE that caches StatResultType.tp_new;
        # structseq.c has a same-named *function*.  Without a rename,
        # ``_struct_sequence_template.tp_new`` resolves to the
        # posixmodule.c variable and ``makeFuncPtr`` asserts.
        self.macros["structseq_new"] = cparser.Macro(rightside="structseq_new_posix")
        # ``initialized`` collision:
        #   posixmodule.c:1933 has ``static int initialized;`` at FILE
        #   scope, used as a guard around the per-type
        #   ``PyStructSequence_InitType2`` calls in PyInit_posix.
        #   pylifecycle.c:90 has ``static int initialized = 0;`` at
        #   FUNCTION scope (inside ``_PyRuntime_Initialize``), which sets
        #   itself to 1 after the runtime is initialized.
        # C distinguishes these by scope; our cparser merges all
        # same-named statics into one ``state.vars`` entry, so the
        # pylifecycle write to 1 (during startup) clobbers
        # posixmodule.c's value, and ``PyInit_posix`` then skips the
        # entire ``if (!initialized) { ... StatResultType InitType2 ...
        # }`` block.  The downstream symptom is ``StatResultType.tp_dict
        # == NULL`` -> NULL-deref the next time ``_pystat_fromstructstat``
        # runs (e.g. importlib calling ``os.stat`` during encoding
        # import).  Rename posixmodule.c's variant.
        self.macros["initialized"] = cparser.Macro(rightside="initialized_posix")
        cparser.parse(CPythonDir + "/Modules/posixmodule.c", self) # PyInit_posix
        self.macros.pop("initialized", None)
        self.macros.pop("structseq_new", None)
        # ``_io`` (Modules/_io/*.c) -- needed so PyInit__io has a real body
        # instead of the ImportError-raising stub installed by
        # ``_make_pyinit_stub`` in main().  Each file is parsed against
        # the same shared State (the project's single-translation-unit
        # design), so a few file-scope-static / macro collisions need
        # explicit handling here.
        #
        # ``CHECK_CLOSED`` / ``CHECK_INITIALIZED`` are re-#defined
        # identically in several files; pop between files so cparser
        # doesn't flag a duplicate macro definition.
        _io_macros_to_pop = ("CHECK_CLOSED", "CHECK_INITIALIZED")
        # File-scope statics with the same name but different types
        # across _io files would silently merge into one global -- the
        # same pattern bool/float/dict/tuple/list/methodobj/classobj
        # already deal with above.  Rename via macros.
        cparser.parse(CPythonDir + "/Modules/_io/iobase.c", self) # PyIOBase_Type
        for _m in _io_macros_to_pop:
            self.macros.pop(_m, None)
        # ``get_closed`` / ``get_mode`` collide with iobase.c versions
        # (already parsed).
        self.macros["get_closed"] = cparser.Macro(rightside="get_closed_fileio")
        self.macros["get_mode"] = cparser.Macro(rightside="get_mode_fileio")
        cparser.parse(CPythonDir + "/Modules/_io/fileio.c", self) # PyFileIO_Type
        self.macros.pop("get_closed", None)
        self.macros.pop("get_mode", None)
        for _m in _io_macros_to_pop:
            self.macros.pop(_m, None)
        cparser.parse(CPythonDir + "/Modules/_io/bytesio.c", self) # PyBytesIO_Type
        for _m in _io_macros_to_pop:
            self.macros.pop(_m, None)
        # ``resize_buffer`` collides with bytesio.c version.
        self.macros["resize_buffer"] = cparser.Macro(rightside="resize_buffer_stringio")
        cparser.parse(CPythonDir + "/Modules/_io/stringio.c", self) # PyStringIO_Type
        self.macros.pop("resize_buffer", None)
        for _m in _io_macros_to_pop:
            self.macros.pop(_m, None)
        cparser.parse(CPythonDir + "/Modules/_io/bufferedio.c", self) # PyBufferedReader_Type etc.
        for _m in _io_macros_to_pop:
            self.macros.pop(_m, None)
        cparser.parse(CPythonDir + "/Modules/_io/textio.c", self) # PyTextIOWrapper_Type
        for _m in _io_macros_to_pop:
            self.macros.pop(_m, None)
        cparser.parse(CPythonDir + "/Modules/_io/_iomodule.c", self) # PyInit__io


def init_faulthandler(sigusr1_chain=False):
    """
    :param bool sigusr1_chain: whether the default SIGUSR1 handler should also be called.
    """
    try:
        import faulthandler
    except ImportError as e:
        print("faulthandler import error. %s" % e)
        return
    # Only enable if not yet enabled -- otherwise, leave it in its current state.
    if not faulthandler.is_enabled():
        faulthandler.enable()
        if os.name != 'nt':
            import signal
            # This will print a backtrace on SIGUSR1.
            # Note that this also works when Python is hanging,
            # i.e. in cases where register_sigusr1_print_backtrace() will not work.
            faulthandler.register(signal.SIGUSR1, all_threads=True, chain=sigusr1_chain)


def install_quiet_crash_handlers():
    """Install C-level SIGSEGV/SIGBUS/SIGABRT handlers that dump a
    Python traceback and then call ``_exit()`` -- bypassing the
    macOS CrashReporter dialog that normally pops up when a process
    dies from an unhandled fatal signal.

    Mechanism: macOS's ``ReportCrash`` only fires when a process is
    terminated by an unhandled signal.  If we install our own
    handler that calls ``_exit()``, the OS sees a clean exit and no
    dialog appears.

    We still want the Python traceback for debugging, so the handler
    calls ``faulthandler.dump_traceback()`` first (designed to be
    safe from signal context).

    Why a ctypes-based C-level handler (not ``signal.signal()``):
    Python-level handlers run deferred (the C-level signal handler
    in CPython just sets a flag, the Python handler runs on the
    next bytecode dispatch).  For a SIGSEGV in C code, the
    instruction will re-fault on return from the signal frame, so
    a Python handler never runs.  A C-level handler that calls
    ``_exit()`` (async-signal-safe) does not return, breaking the
    refault loop.
    """
    import ctypes
    import ctypes.util
    libc_path = ctypes.util.find_library("c") or "libc.dylib"
    libc = ctypes.CDLL(libc_path, use_errno=False)
    libc._exit.argtypes = [ctypes.c_int]
    libc._exit.restype = None
    libc.write.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]
    libc.write.restype = ctypes.c_ssize_t
    HANDLER_T = ctypes.CFUNCTYPE(None, ctypes.c_int)
    libc.signal.argtypes = [ctypes.c_int, HANDLER_T]
    libc.signal.restype = ctypes.c_void_p
    # Pull faulthandler.dump_traceback for signal-safe Python-stack dumping.
    import faulthandler
    _dump = faulthandler.dump_traceback
    _stderr_fd = 2
    _msg_prefix = b"\n[quiet-crash] fatal signal "
    _msg_suffix = b" -- dumping traceback then exiting silently\n"

    def _handler(signum):
        # Best-effort write of a banner -- async-signal-safe.
        libc.write(_stderr_fd, _msg_prefix, len(_msg_prefix))
        # Stringifying the signum involves no allocations large enough
        # to be unsafe; the digit chars are computed inline.
        s = str(signum).encode("ascii")
        libc.write(_stderr_fd, s, len(s))
        libc.write(_stderr_fd, _msg_suffix, len(_msg_suffix))
        # faulthandler.dump_traceback is documented as safe to call
        # from a signal handler (it's the same primitive faulthandler's
        # own SIGSEGV handler uses internally).
        _dump(file=sys.stderr, all_threads=True)
        # Clean exit -- 128+signum is the conventional code.
        libc._exit(128 + signum)

    # Keep references to prevent ctypes-callback objects from being GC'd.
    install_quiet_crash_handlers._c_handler = HANDLER_T(_handler)
    install_quiet_crash_handlers._libc = libc
    import signal
    for sig in (signal.SIGSEGV, signal.SIGBUS, signal.SIGABRT):
        libc.signal(sig, install_quiet_crash_handlers._c_handler)


def register_sigusr1_print_backtrace():
    if os.name == "nt":
        return

    def sigusr1_handler(sig, frame):
        print("--- SIGUSR1 handler")
        better_exchook.print_tb(tb=frame)

    import signal
    signal.signal(signal.SIGUSR1, sigusr1_handler)


def watchdog_thread(*, timeout, mem_limit_gb, report_traceback_interval=None):
    import time
    import os
    import signal
    import resource
    start_time = time.time()
    last_traceback = time.time()
    mem_limit = mem_limit_gb * 1024**3
    while True:
        elapsed = time.time() - start_time
        if timeout > 0 and elapsed > timeout:
            print("\nWatchdog: Timeout reached (%ds). Terminating." % timeout, file=sys.stderr)
            os._exit(1)

        if mem_limit > 0:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform != "darwin":
                usage *= 1024  # Linux: kilobytes to bytes
            if usage > mem_limit:
                print("\nWatchdog: Memory limit exceeded (%.1fMB). Terminating." % (usage / 1024**2), file=sys.stderr)
                os._exit(1)

        if report_traceback_interval is not None and time.time() - last_traceback > report_traceback_interval:
            os.kill(os.getpid(), signal.SIGUSR1)
            last_traceback = time.time()

        time.sleep(5)


def main(argv):
    argparser = argparse.ArgumentParser(
        usage="%s [PyCPython options, see below] [CPython options, see via --help]" % argv[0],
        description="Emulate CPython by interpreting its C code via PyCParser.",
        epilog="All other options are passed on to CPython. Use --help to see them.",
        add_help=False  # we will add our own
    )
    argparser.add_argument(
        '--pycpython-help', action='help', help='show this help message and exit')
    argparser.add_argument(
        '--dump-python', action='store', nargs=1,
        help="Dumps the converted Python code of the specified function, e.g. Py_Main.")
    argparser.add_argument("--interactive-c", action="store_true", help="Interactive C mode")
    argparser.add_argument("--interactive-py", action="store_true", help="Interactive Python mode")
    argparser.add_argument(
        '--verbose-jit', action='store_true',
        help="Prints what functions and global vars we are going to translate.")
    argparser.add_argument(
        '--watchdog-timeout', type=int, default=0,
        help="Timeout in seconds for the watchdog thread (default 0, disabled).")
    argparser.add_argument(
        '--watchdog-memory', type=float, default=0,
        help="Memory limit in GB for the watchdog thread (default 0, disabled).")
    argparser.add_argument("--report-extended-tracebacks", action="store_true")
    argparser.add_argument("--watchdog-report-traceback-interval", type=int, default=None)
    argparser.add_argument(
        '--instrument', action='append', default=[],
        metavar="FUNC[,FUNC...]",
        help="Wrap each named (translated) C function with entry/exit logging "
             "to stderr.  Useful for finding which call in a chain silently "
             "returns 0/NULL.  May be repeated; values may be comma-separated.")
    argparser.add_argument(
        '--no-better-exchook', action='store_true',
        help="Disable better_exchook installation in __main__.  Use stdlib "
             "traceback.print_exc instead for uncaught exceptions.  "
             "better_exchook's `get_func_from_code_object` calls "
             "gc.get_referrers(co) which walks the entire GC heap; if our "
             "ctypes object graph has any invariant break (a freed object "
             "still in some `_objects`, a dangling `_b_base_`, ...) that "
             "walk segfaults.  Using stdlib traceback avoids the deep "
             "reflection so we at least see the actual exception.")
    argparser.add_argument(
        '--gc-check-interval', type=int, default=0, metavar="N",
        help="Call gc.get_referrers every N checkedFuncPtrCall "
             "invocations on a known-alive code object, and log the "
             "call count + status.  Cheap survey to find the rough "
             "iteration band where the GC heap goes bad.  Note: the "
             "absolute count varies with N because gc.get_referrers "
             "itself allocates -- use --gc-check-at for proper bisection.  "
             "N=0 (default) disables.")
    argparser.add_argument(
        '--gc-check-at', action='append', default=[],
        metavar="N[,N...]",
        help="Bisection mode: at exactly the named checkedFuncPtrCall "
             "iteration(s) (comma-separated or repeated), run "
             "gc.get_referrers(co) and dump the current Python call "
             "stack to stderr.  Typical usage is to pass at least the "
             "expected good and bad endpoints plus a midpoint -- e.g. "
             "`--gc-check-at 8000,9000,9500,9800` -- so a single run "
             "yields multiple data points.  Memory-corruption probes "
             "are often non-deterministic; the more probe points the "
             "better the chance of catching the crash.")
    argparser.add_argument(
        '--gc-check-range', action='append', default=[],
        metavar="START:END:STEP",
        help="Like --gc-check-at but as a range: do a gc-check at every "
             "STEP-th iteration in [START, END] (inclusive).  E.g. "
             "`--gc-check-range 9000:9800:100` probes 9000, 9100, ..., "
             "9800.  Combine with --gc-check-at for ad-hoc additional "
             "points.  May be repeated.")
    argparser.add_argument(
        '--quiet-crash', action='store_true', default=False,
        help="On fatal signals (SIGSEGV/SIGBUS/SIGABRT), dump the "
             "Python traceback and then exit cleanly via _exit() -- "
             "so the macOS CrashReporter dialog does NOT pop up.  "
             "Useful for unattended debug runs.")
    argparser.add_argument(
        '--check-gc-invariants', action='store_true', default=False,
        help="After runFunc, disable host gc and walk the host gen0 "
             "list via raw PyGC_Head reads (no tp_traverse, no "
             "allocator allocations), checking the doubly-linked "
             "invariant `next._gc_prev == this`.  Any break is "
             "memory corruption.  Implies temporarily disabling gc "
             "during runFunc so all tracked objects stay in gen0.")
    argparser.add_argument(
        '--invariant-check-interval', type=int, default=0, metavar="N",
        help="Every N checkedFuncPtrCall iterations, run the same "
             "gen0 invariant walk as --check-gc-invariants.  The "
             "first iteration where a break appears identifies WHEN "
             "the corruption happens (combine with --gc-check-at for "
             "tighter bisection).  N=0 (default) disables.  Implies "
             "gc disable during runFunc.")
    args_ns, argv_rest = argparser.parse_known_args(argv[1:])

    if args_ns.report_extended_tracebacks:
        register_sigusr1_print_backtrace()
    init_faulthandler(sigusr1_chain=args_ns.report_extended_tracebacks)
    if args_ns.quiet_crash:
        # Install AFTER faulthandler.enable -- our handler replaces
        # faulthandler's SIGSEGV/SIGBUS/SIGABRT slots.  Order matters.
        install_quiet_crash_handlers()

    if args_ns.watchdog_timeout > 0 or args_ns.watchdog_memory > 0 or args_ns.watchdog_report_traceback_interval is not None:
        import threading
        t = threading.Thread(
            target=watchdog_thread,
            kwargs={"timeout": args_ns.watchdog_timeout, "mem_limit_gb": args_ns.watchdog_memory,
                    "report_traceback_interval": args_ns.watchdog_report_traceback_interval},
            daemon=True)
        t.start()
    argv = argv[:1] + argv_rest
    print("PyCPython -", argparser.description,)
    print("(use --pycpython-help for help)")

    state = CPythonState()

    print("Parsing CPython...", end="")
    state.parse_cpython()

    if state._errors:
        print("finished, parse errors:")
        for m in state._errors:
            print(m)
    else:
        print("finished, no parse errors.")

    interpreter = cparser.interpreter.Interpreter()

    interpreter.register(state)

    # ``pathconfig.c``'s ``Py_GetPrefix`` / ``Py_GetPath`` / etc. all
    # call ``pathconfig_global_init`` which short-circuits if
    # ``_Py_path_config.module_search_path`` is already non-NULL.
    # Populate the struct directly so the real ``Py_Get*``
    # implementations work as-is.  This also bypasses
    # ``_PyPathConfig_Calculate`` (defined in Modules/getpath.c, not
    # parsed), which is only called when the struct is empty.
    #
    # We point at the bundled CPython submodule's ``Lib`` rather than
    # the host interpreter's ``sys.path``: the source tree we parsed
    # is the same CPython version we want to run, and its stdlib lives
    # right next to it.  Host paths would risk version skew (e.g.
    # parsing CPython 3.7 here while the host is 3.13).
    #
    # The C code calls ``PyMem_RawFree`` on these pointers from
    # ``_PyPathConfig_Clear`` (during ``Py_SetPath`` and shutdown);
    # allocate via ``_PyMem_RawWcsdup`` so the free is well-defined.
    _PyMem_RawWcsdup = interpreter.getFunc("_PyMem_RawWcsdup")
    _path_cfg = interpreter.globalsWrapper._Py_path_config
    _PathPtrT = type(_path_cfg)._fields_[0][1]  # wrapped LP_c_wchar
    def _set_path_field(field_name, value):
        wbuf = interpreter._make_wchar_string(value)
        # ``_PyMem_RawWcsdup`` takes ``const wchar_t *`` and returns
        # owned PyMem_Raw-allocated memory.
        dup = _PyMem_RawWcsdup(ctypes.cast(wbuf, _PathPtrT))
        setattr(_path_cfg, field_name, ctypes.cast(dup, _PathPtrT))
    _cpython_dir = CPythonDir
    _set_path_field("program_full_path", argv[0])
    _set_path_field("prefix", _cpython_dir)
    _set_path_field("exec_prefix", _cpython_dir)
    _set_path_field(
        "module_search_path",
        ":".join([_cpython_dir + "/Lib",
                  _cpython_dir + "/Lib/site-packages"]))
    _set_path_field("program_name", argv[0])
    _set_path_field("home", _cpython_dir)

    # ``PyGILState_Check`` asserts via the host TSS that the current
    # thread holds the GIL.  Our interpreter doesn't actually run a
    # real GIL state machine (we're driving translated C from Python),
    # so the check returns 0 even though logically the "GIL" is held
    # for the duration of every ``runFunc``.  CPython itself
    # documents an escape: setting ``_PyRuntime.gilstate.check_enabled
    # = 0`` makes the function always return 1 (sub-interpreters use
    # this).  Rather than depend on the order of ``_PyRuntime_Initialize``
    # vs. consumers of the check, just override the function.  Without
    # this, ``_Py_write`` and several ``fileutils.c`` helpers
    # ``assert(PyGILState_Check())`` and ``CAbortException`` is raised
    # mid-init -- visible only on paths that bypass our higher-level
    # ``pymain_init_python_main`` override.
    def _py_PyGILState_Check():
        return 1
    _py_PyGILState_Check.C_argTypes = []
    _py_PyGILState_Check.C_resType = ctypes.c_int

    # ``_PyLong_FromTime_t(time_t t)``: a one-liner in pytime.c that
    # wraps ``PyLong_FromLong(L)``.  We don't parse pytime.c (it pulls
    # in clock_gettime / CLOCK_MONOTONIC / struct timespec that we
    # don't yet bind), so it stays body-less and returns Python ``None``
    # by default -- which makes ``posixmodule.c::_pystat_fromstructstat``
    # populate ``stat_result.st_atime / st_mtime / st_ctime`` with
    # ``None``, and importlib's bootstrap then dies on
    # ``int(st['mtime'])`` for the bytecode-cache freshness check.
    # Surgical override: just call PyLong_FromLong directly.
    _PyLong_FromLong = interpreter.getFunc("PyLong_FromLong")
    def _py_PyLong_FromTime_t(t):
        t_val = t.value if hasattr(t, "value") else int(t)
        return _PyLong_FromLong(ctypes.c_long(int(t_val)))
    _py_PyLong_FromTime_t.C_argTypes = None
    _py_PyLong_FromTime_t.C_resType = ctypes.c_void_p
    interpreter._func_cache["_PyLong_FromTime_t"] = _py_PyLong_FromTime_t
    interpreter._func_cache["PyGILState_Check"] = _py_PyGILState_Check

    # Build minimal ``sys.stdout`` / ``sys.stderr`` stubs so the real
    # ``builtin_print`` works.  CPython's normal path sets these via
    # ``init_sys_streams`` (in pylifecycle.c) which imports the ``io``
    # module (huge, also depends on importlib).  We skip that and
    # instead install a ``PyModule`` with ``write`` and ``flush``
    # methods backed by ctypes callbacks that hit host
    # ``sys.stdout`` / ``sys.stderr``.  The real ``builtin_print``
    # then does ``PyFile_WriteObject`` -> ``write(s)`` on these.
    PyCFunction_NewEx = interpreter.getFunc("PyCFunction_NewEx")
    PyModule_New = interpreter.getFunc("PyModule_New")
    PyObject_SetAttrString = interpreter.getFunc("PyObject_SetAttrString")
    PySys_SetObject = interpreter.getFunc("PySys_SetObject")
    PyUnicode_AsUTF8 = interpreter.getFunc("PyUnicode_AsUTF8")
    PyMethodDef_t = interpreter.getCType(state.structs['PyMethodDef'])
    METH_O = 0x0008
    METH_NOARGS = 0x0004
    _none_obj = interpreter.globalScope.getVar("_Py_NoneStruct")
    _none_addr = ctypes.addressof(_none_obj)

    def _ret_none():
        # ``Py_RETURN_NONE`` convention: bump refcount and return Py_None.
        _none_obj.ob_refcnt.value = _none_obj.ob_refcnt.value + 1
        return _none_addr

    # ctypes signature for ``PyCFunction``:
    # ``PyObject *(*)(PyObject *self, PyObject *arg)``.
    _PYCFUNC_T = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    # Keep ctypes callbacks and PyMethodDef arrays alive for the
    # lifetime of the interpreter -- the C side stores raw pointers.
    interpreter._stream_keepalive = []

    def _make_stream_module(name, host_stream):
        def _do_write(arg_addr):
            if not arg_addr:
                return
            s_addr_ptr = PyUnicode_AsUTF8(ctypes.c_void_p(arg_addr))
            s_addr = s_addr_ptr.value if hasattr(s_addr_ptr, "value") else int(s_addr_ptr)
            if not s_addr:
                interpreter.getFunc("PyErr_Clear")()
                return
            host_stream.write(ctypes.string_at(s_addr).decode("utf-8", errors="replace"))

        @_PYCFUNC_T
        def _write_cb(self_addr, arg_addr):
            _do_write(arg_addr)
            return _ret_none()

        @_PYCFUNC_T
        def _flush_cb(self_addr, arg_addr):
            host_stream.flush()
            return _ret_none()

        # PyMethodDef sentinel-terminated array: write, flush, NULL.
        methods = (PyMethodDef_t * 3)()
        name_w = interpreter._make_string("write")
        name_f = interpreter._make_string("flush")
        BytePtrT = type(methods[0].ml_name)
        DocPtrT = type(methods[0].ml_doc)
        MethSlotT = type(methods[0].ml_meth)
        methods[0].ml_name = ctypes.cast(name_w, BytePtrT)
        methods[0].ml_meth = ctypes.cast(_write_cb, MethSlotT)
        methods[0].ml_flags.value = METH_O
        methods[0].ml_doc = ctypes.cast(0, DocPtrT)
        methods[1].ml_name = ctypes.cast(name_f, BytePtrT)
        methods[1].ml_meth = ctypes.cast(_flush_cb, MethSlotT)
        methods[1].ml_flags.value = METH_NOARGS
        methods[1].ml_doc = ctypes.cast(0, DocPtrT)
        # methods[2] zero-initialized = sentinel.

        # Create module object, attach write/flush methods.
        mod_name_buf = interpreter._make_string(name)
        mod = PyModule_New(ctypes.cast(mod_name_buf, BytePtrT))
        for i, mname_buf in [(0, name_w), (1, name_f)]:
            fn_obj = PyCFunction_NewEx(
                ctypes.cast(ctypes.addressof(methods[i]),
                            ctypes.POINTER(PyMethodDef_t)),
                ctypes.c_void_p(0),
                ctypes.c_void_p(0))
            PyObject_SetAttrString(mod, ctypes.cast(mname_buf, BytePtrT), fn_obj)

        # Keep refs alive.
        interpreter._stream_keepalive.extend(
            [_write_cb, _flush_cb, methods, name_w, name_f, mod_name_buf])
        return mod

    def _install_sys_streams():
        BytePtrT = type(PyMethodDef_t().ml_name)
        for name, host_stream in [("stdout", sys.stdout), ("stderr", sys.stderr)]:
            mod = _make_stream_module("<pycpython-%s>" % name, host_stream)
            key_buf = interpreter._make_string(name)
            PySys_SetObject(ctypes.cast(key_buf, BytePtrT), mod)
            interpreter._stream_keepalive.append(key_buf)

    # NOTE on ``pymain_init_python_main``: the real implementation
    # calls ``_Py_InitializeMainInterpreter`` which does
    # ``initfsencoding`` -> ``get_locale_encoding`` -> ``_PyCodec_Lookup``
    # -> ``_PyCodecRegistry_Init`` -> ``PyImport_ImportModuleNoBlock("encodings")``
    # which needs the FULL importlib bootstrap (the same one the
    # ``initexternalimport`` stub bypasses due to the
    # ``MarkupIterator_next`` postfix-++ infinite loop).  So we
    # keep a *partial* implementation here that does what
    # ``add_main_module`` would (set ``__main__.__builtins__``) so
    # user code can find ``print`` etc.  Removing this completely
    # is blocked on fixing the importlib bootstrap.
    def _py_pymain_init_python_main(pymain, interp_arg):
        """pymain_init_python_main: minimal substitute for
        ``_Py_InitializeMainInterpreter``.  Sets up
        ``__main__.__builtins__`` (otherwise ``print`` lookup raises
        NameError) via direct sys.modules access, skipping the slow
        ``PyImport_ImportModule("builtins")`` path.  Also installs the
        ``sys.stdout``/``sys.stderr`` stubs that ``init_sys_streams``
        would normally set up.
        """
        py_add_module = interpreter.getFunc("PyImport_AddModule")
        py_module_getdict = interpreter.getFunc("PyModule_GetDict")
        py_dict_setitem_string = interpreter.getFunc("PyDict_SetItemString")
        main_name = interpreter._make_string("__main__")
        main_name_ptr = ctypes.cast(main_name, ctypes.POINTER(ctypes.c_byte))
        builtins_name = interpreter._make_string("builtins")
        builtins_name_ptr = ctypes.cast(builtins_name, ctypes.POINTER(ctypes.c_byte))
        builtins_key = interpreter._make_string("__builtins__")
        builtins_key_ptr = ctypes.cast(builtins_key, ctypes.POINTER(ctypes.c_byte))
        main_mod = py_add_module(main_name_ptr)
        builtins_mod = py_add_module(builtins_name_ptr)
        main_dict = py_module_getdict(main_mod)
        py_dict_setitem_string(main_dict, builtins_key_ptr, builtins_mod)
        _install_sys_streams()
        # Provide an empty ``sys.path`` so the REAL ``pymain_init_sys_path``
        # (called immediately after this override in ``pymain_init``) can
        # do its ``PyList_Insert(sys.path, 0, argv0)``.  Without this we
        # had to additionally stub ``pymain_init_sys_path``.
        _PySys_SetObject = interpreter.getFunc("PySys_SetObject")
        _PyList_New = interpreter.getFunc("PyList_New")
        _path_name = interpreter._make_string("path")
        _path_name_ptr = ctypes.cast(_path_name, ctypes.POINTER(ctypes.c_byte))
        _empty_list = _PyList_New(ctypes.c_long(0))
        _PySys_SetObject(_path_name_ptr, ctypes.cast(_empty_list, ctypes.c_void_p))
        # NOTE: the real ``initexternalimport`` -> Python-level
        # ``importlib._install_external_importers`` no longer
        # infinite-loops (``MarkupIterator_next`` was unblocked by
        # other fixes), but the path translates a huge amount of
        # importlib bytecode on demand and takes several minutes per
        # run.  Until we have translation caching across runs, skip
        # it -- ``-c "..."`` programs that only use builtins don't
        # need the filesystem importers anyway.
        return 0
    _py_pymain_init_python_main.C_argTypes = None
    _py_pymain_init_python_main.C_resType = ctypes.c_int
    interpreter._func_cache["pymain_init_python_main"] = _py_pymain_init_python_main

    # Many of the C modules listed in `_PyImport_Inittab` (PC/config.c) --
    # `_thread`, `_io`, `itertools`, ... -- live in C source files we
    # don't parse.  Their `PyInit_xxx` is therefore a body-less function
    # that silently returns Python `None` -> NULL pointer when called.
    # During importlib bootstrap, `_imp.create_builtin(spec)` calls
    # `(*p->initfunc)()` and treats a NULL return as failure; the C
    # contract requires the initfunc to have set a Python error before
    # returning NULL.  Our silent-NULL stub violates that contract, the
    # eventual `_Py_CheckFunctionResult` raises "%R returned NULL
    # without setting an error", and importlib install fails.  Replace
    # the missing-body stub for every `PyInit_*` (and similarly-shaped)
    # initfunc with one that sets ImportError properly.
    _PyErr_SetString_func = interpreter.getFunc("PyErr_SetString")

    def _make_pyinit_stub(modname):
        msg = (
            "module not available in PyCPython "
            "(C source for PyInit_%s is not parsed): %s"
            % (modname, modname)
        )
        # Pre-build the message buffer once.  `_make_string` returns a
        # ctypes c_byte array stored in `interp.constStrings` (strong
        # ref kept for the lifetime of the interpreter).
        _msg_buf = interpreter._make_string(msg)
        _msg_ptr = ctypes.cast(_msg_buf, ctypes.POINTER(ctypes.c_byte))
        # `PyExc_ImportError` is a global; getVar returns the ctype value.
        _exc = interpreter.globalsWrapper.PyExc_ImportError

        def _stub():
            # Set ImportError and return NULL.  We bypass `runFunc`'s arg
            # marshaling (which expects Python str/int/list, not ctypes)
            # and call the translated PyErr_SetString directly -- both
            # args are already in ctypes form.
            _PyErr_SetString_func(_exc, _msg_ptr)
            return 0  # NULL PyObject*
        _stub.C_argTypes = []
        _stub.C_resType = ctypes.c_void_p
        return _stub

    # Wrap ``initexternalimport`` to also set ``sys.dont_write_bytecode
    # = True`` once the external importers are installed.  With
    # O_EXCL/O_CREAT/O_WRONLY now correctly defined on the ``posix``
    # module (see ``PyInit_posix`` wrap below), importlib's
    # ``_write_atomic`` can technically open .pyc cache files -- but
    # we'd actually persist bytecode caches into CPython's stdlib tree
    # on disk, which is undesirable side-effect.  Disable bytecode
    # writes to keep the run hermetic.
    if "initexternalimport" in state.funcs:
        # Lazy resolution to avoid eagerly translating ``initexternal\
        # import`` and ``PySys_SetObject`` at setup time -- those
        # translations don't pay off when the higher-level
        # ``pymain_init_python_main`` override is active (the wrapped
        # function is bypassed entirely).
        _resolved_initext = {}
        _dont_write_name_buf = interpreter._make_string("dont_write_bytecode")
        _dont_write_name_ptr = ctypes.cast(_dont_write_name_buf,
                                           ctypes.POINTER(ctypes.c_byte))
        _true_obj = interpreter.globalScope.getVar("_Py_TrueStruct")
        _true_addr = ctypes.addressof(_true_obj)
        def _wrapped_initext(interp_arg):
            if not _resolved_initext:
                _resolved_initext["orig"] = interpreter.getFunc("initexternalimport")
                _resolved_initext["setobj"] = interpreter.getFunc("PySys_SetObject")
            r = _resolved_initext["orig"](interp_arg)
            _resolved_initext["setobj"](_dont_write_name_ptr, ctypes.c_void_p(_true_addr))
            return r
        _wrapped_initext.C_argTypes = None
        _wrapped_initext.C_resType = ctypes.c_int
        interpreter._func_cache["initexternalimport"] = _wrapped_initext

    # Wrap ``PyInit_posix`` to backfill constants whose names got
    # mangled by ``PyModule_AddIntMacro(m, X) ->
    # PyModule_AddIntConstant(m, #X, X)``.  Our cparser preprocessor
    # expands ``X`` (a macro from <fcntl.h> etc.) BEFORE evaluating
    # the ``#`` stringification, so ``PyModule_AddIntMacro(m, O_EXCL)``
    # produces a constant named ``"0x0080"`` (the macro's value)
    # instead of ``"O_EXCL"`` (the literal token name).  Proper fix is
    # in the preprocessor (C99 §6.10.3.2: ``#`` stringifies the
    # original argument spelling); doing that without breaking
    # function-like macro recursion (e.g. ``Py_IS_FINITE(v)`` via
    # ``Py_IS_INFINITY(v)``) requires reworking arg
    # collection+expansion -- larger surgery, deferred.  For now the
    # values are already in the module under wrong names, so just add
    # the right names too.  Required for importlib's source loader,
    # whose ``_write_atomic`` opens ``.pyc`` cache files with
    # ``_os.O_EXCL | _os.O_CREAT | _os.O_WRONLY``.
    if "PyInit_posix" in state.funcs:
        # Names + values must match what ``handle_fcntl_h`` defines
        # in cparser/globalincludewrappers.py (the C side already
        # added these as ``str(value)``-named attrs via all_ins).
        _posix_int_constants = [
            ("O_RDONLY",   0x00000000),
            ("O_WRONLY",   0x00000001),
            ("O_RDWR",     0x00000002),
            ("O_NONBLOCK", 0x00000004),
            ("O_APPEND",   0x00000008),
            ("O_EXCL",     0x00000080),
            ("O_CREAT",    0x00000200),
            ("O_TRUNC",    0x00000400),
            ("O_CLOEXEC",  0x01000000),
            ("F_GETFD",    1),
            ("F_SETFD",    2),
            ("F_GETFL",    3),
            ("F_SETFL",    4),
            ("FD_CLOEXEC", 1),
        ]
        # Resolve dependencies lazily (on first call) so we don't
        # eagerly translate ``PyInit_posix`` -- a HUGE function whose
        # translation noticeably slows down startup.
        _resolved = {}
        def _wrapped_posix_init():
            if not _resolved:
                _resolved["orig"] = interpreter.getFunc("PyInit_posix")
                _resolved["addint"] = interpreter.getFunc("PyModule_AddIntConstant")
            mod = _resolved["orig"]()
            if mod:
                for _name, _val in _posix_int_constants:
                    _name_buf = interpreter._make_string(_name)
                    _name_ptr = ctypes.cast(_name_buf,
                                            ctypes.POINTER(ctypes.c_byte))
                    _resolved["addint"](
                        ctypes.cast(mod, ctypes.c_void_p),
                        _name_ptr, ctypes.c_long(_val))
            return mod
        _wrapped_posix_init.C_argTypes = None
        _wrapped_posix_init.C_resType = ctypes.c_void_p
        interpreter._func_cache["PyInit_posix"] = _wrapped_posix_init

    from cparser.cparser import CFunc as _CFunc
    for _fn, _cf in list(state.funcs.items()):
        if not isinstance(_cf, _CFunc):
            continue
        if _cf.body is not None:
            continue
        if not _fn.startswith("PyInit_"):
            continue
        if _fn in interpreter._func_cache:
            continue
        print("TODO (missing C source code file): %s is not loaded yet. Installing stub." % _fn)
        _modname = _fn[len("PyInit_"):]  # Derive module name from "PyInit_<modname>".
        interpreter._func_cache[_fn] = _make_pyinit_stub(_modname)

    # `--instrument FUNC[,FUNC...]` wraps the named translated C functions
    # with entry/exit logging.  This is the simplest way to find which call
    # in a long chain silently returns 0/NULL when the C contract was
    # broken (e.g. some helper returns failure without setting a Python
    # error, then a downstream `assert(PyErr_Occurred())` finally trips).
    # The wrapping happens after parsing but before the runFunc, so it
    # works for any function in state.funcs.
    _instrument_names = set()
    for _spec in args_ns.instrument:
        for _name in _spec.split(","):
            _name = _name.strip()
            if _name:
                _instrument_names.add(_name)
    if _instrument_names:
        from cparser.interpreter import _ctype_ptr_get_value as _gv
        def _short_arg(a):
            if a is None:
                return "None"
            if isinstance(a, int):
                return "0x%x" % a
            # Best-effort decode of `char *` / `const char *` (LP_c_byte
            # or LP_wrapCTypeClass_c_byte) as a C string -- useful for
            # PyErr_Format format strings, method names, etc.  Also
            # surface NULL pointers explicitly so they don't look like
            # any other typed pointer.
            if isinstance(a, ctypes._Pointer):
                raw = ctypes.cast(a, ctypes.c_void_p).value
                if not raw:
                    return "%s(NULL)" % type(a).__name__
                elem_t = type(a)._type_
                if issubclass(elem_t, ctypes.c_byte) or issubclass(elem_t, ctypes.c_char):
                    s = ctypes.cast(a, ctypes.c_char_p).value
                    if s is not None:
                        return "%r" % s.decode("utf-8", "replace")[:80]
                return "%s(0x%x)" % (type(a).__name__, raw)
            if hasattr(a, "value"):
                v = a.value
                if v is None:
                    return "%s(NULL)" % type(a).__name__
                if isinstance(v, int):
                    return "0x%x" % v
                return repr(v)[:60]
            return type(a).__name__
        def _wrap(_name):
            orig = interpreter.getFunc(_name)
            def _wrapped(*args):
                print("[instr] >>> %s(%s)" % (
                    _name, ", ".join(_short_arg(a) for a in args)),
                    file=sys.stderr, flush=True)
                try:
                    r = orig(*args)
                except BaseException as e:
                    print("[instr] !!! %s raised %s: %s" % (
                        _name, type(e).__name__, str(e)[:120]),
                        file=sys.stderr, flush=True)
                    raise
                print("[instr] <<< %s -> %s" % (_name, _short_arg(r)),
                      file=sys.stderr, flush=True)
                return r
            _wrapped.C_argTypes = orig.C_argTypes
            _wrapped.C_resType = orig.C_resType
            _wrapped.C_cFunc = getattr(orig, "C_cFunc", None)
            interpreter._func_cache[_name] = _wrapped
        for _name in sorted(_instrument_names):
            if _name not in state.funcs:
                print("[instr] warning: function %r not in parsed C source; skipping"
                      % _name, file=sys.stderr)
                continue
            _wrap(_name)
            print("[instr] wrapped %s" % _name, file=sys.stderr)

    if args_ns.dump_python:
        for fn in args_ns.dump_python:
            print()
            print("PyAST of %s:" % fn)
            interpreter.dumpFunc(fn)
        sys.exit()

    if args_ns.verbose_jit:
        interpreter.debug_print_getFunc = True
        interpreter.debug_print_getVar = True

    if args_ns.interactive_c:
        print("Interactive C mode")
        from cparser.interactive_interpreter import InteractiveInterpreter
        interactive_interpreter = InteractiveInterpreter(state=state, interpreter=interpreter)
        interactive_interpreter.loop()
        sys.exit()

    if args_ns.interactive_py:
        print("Interactive Python mode")
        better_exchook.debug_shell(locals(), globals())
        sys.exit()

    # `--gc-check-interval N` and `--gc-check-at N1,N2,...`: hook
    # `Helpers.checkedFuncPtrCall` (called for every C function-pointer
    # dispatch, roughly the most frequent "step") and at the chosen
    # iteration(s) call `gc.get_referrers(co)` on a known-alive code
    # object.  If the heap is healthy the call is harmless; once it's
    # corrupt the call segfaults.  Use `--gc-check-at` for proper
    # binary-search bisection -- it does single, targeted checks.
    _gc_check_at = set()
    for _spec in args_ns.gc_check_at:
        for _part in _spec.split(","):
            _part = _part.strip()
            if _part:
                _gc_check_at.add(int(_part))
    for _spec in args_ns.gc_check_range:
        _parts = _spec.split(":")
        if len(_parts) != 3:
            raise ValueError(
                "--gc-check-range expects START:END:STEP, got %r" % _spec)
        _start, _end, _step = (int(_p) for _p in _parts)
        if _step <= 0:
            raise ValueError(
                "--gc-check-range STEP must be > 0, got %d" % _step)
        if _end < _start:
            raise ValueError(
                "--gc-check-range END (%d) must be >= START (%d)"
                % (_end, _start))
        # Inclusive on both ends.
        _i = _start
        while _i <= _end:
            _gc_check_at.add(_i)
            _i += _step
    if args_ns.gc_check_interval > 0 or _gc_check_at:
        import gc as _gc_mod
        import traceback as _gc_tb
        _gc_co = interpreter.getFunc("Py_Main").__code__
        _gc_interval = args_ns.gc_check_interval
        _gc_count = [0]
        _orig_call = interpreter.helpers.checkedFuncPtrCall
        def _gc_check_wrapped(f, *args):
            _gc_count[0] += 1
            n = _gc_count[0]
            do_check = (_gc_interval > 0 and n % _gc_interval == 0) or (n in _gc_check_at)
            if do_check:
                # Log BEFORE the call -- so if the segfault is during
                # gc.get_referrers, the last line on stderr is exactly
                # the count where things blew up.
                print("[gc-check %d] calling gc.get_referrers..."
                      % n, file=sys.stderr, flush=True)
                if n in _gc_check_at:
                    # For bisection points: also dump the current Python
                    # call stack so we know which interpreter operation
                    # was running at that exact iteration.
                    print("[gc-check %d] current stack (innermost last):"
                          % n, file=sys.stderr, flush=True)
                    _gc_tb.print_stack(file=sys.stderr)
                refs = _gc_mod.get_referrers(_gc_co)
                print("[gc-check %d] ok (%d referrers)"
                      % (n, len(refs)), file=sys.stderr, flush=True)
            return _orig_call(f, *args)
        interpreter.helpers.checkedFuncPtrCall = _gc_check_wrapped
        print("[gc-check] hooked checkedFuncPtrCall, interval=%d, at=%s"
              % (_gc_interval, sorted(_gc_check_at) or "[]"),
              file=sys.stderr)

    # Marker for lldb: under ``PYCPYTHON_LLDB_TRAP=1``, raise SIGTRAP
    # right here -- *before* the interp's iter loop starts.  Ideal
    # point to attach lldb watchpoints.  Combine with lldb's
    # ``settings set target.disable-aslr true`` so the addresses
    # observed in one run carry over to the next.
    if os.environ.get("PYCPYTHON_LLDB_TRAP"):
        import signal as _sig_lldb
        print("[lldb-trap] PID=%d, raising SIGTRAP -- lldb should now "
              "stop here; set watchpoints and 'continue'."
              % os.getpid(), file=sys.stderr, flush=True)
        os.kill(os.getpid(), _sig_lldb.SIGTRAP)

    # If either --check-gc-invariants or --invariant-check-interval is
    # set, disable host gc during runFunc.  Otherwise gen0 would be
    # auto-collected/promoted and the post-runFunc walk would miss
    # most objects.  With gc disabled, every tracked obj stays in gen0
    # for the duration of the run.
    if args_ns.check_gc_invariants or args_ns.invariant_check_interval > 0:
        import gc as _gc_pre
        _gc_pre.disable()
        print("[gc-inv] gc.disable() before runFunc", file=sys.stderr)

    if args_ns.invariant_check_interval > 0:
        _inv_interval = args_ns.invariant_check_interval
        _inv_count = [0]
        _inv_detected = [False]
        _inv_orig_call = interpreter.helpers.checkedFuncPtrCall

        def _inv_wrapped(f, *args):
            _inv_count[0] += 1
            n = _inv_count[0]
            if (not _inv_detected[0]) and n % _inv_interval == 0:
                broken_head, visited = _walk_gen0_check_invariants()
                if broken_head is not None:
                    print("[inv-check iter=%d] FIRST BROKEN-LINK: "
                          "head=0x%x (visited=%d before break)"
                          % (n, broken_head, visited),
                          file=sys.stderr, flush=True)
                    import traceback as _t
                    _t.print_stack(file=sys.stderr)
                    _inv_detected[0] = True
                else:
                    print("[inv-check iter=%d] clean (visited=%d)"
                          % (n, visited), file=sys.stderr, flush=True)
            return _inv_orig_call(f, *args)
        interpreter.helpers.checkedFuncPtrCall = _inv_wrapped
        print("[inv-check] hooked checkedFuncPtrCall, interval=%d"
              % _inv_interval, file=sys.stderr)

    args = ("Py_Main", len(argv), argv + [None])
    print("Run", args, ":")
    try:
        interpreter.runFunc(*args)
    finally:
        if args_ns.check_gc_invariants:
            broken_head, visited = _walk_gen0_check_invariants()
            if broken_head is None:
                print("[gc-inv] gen0 invariant check OK (visited=%d)"
                      % visited, file=sys.stderr)
            else:
                print("[gc-inv] BROKEN gen0 link at head=0x%x "
                      "(visited=%d before break) -- gc-list corrupted "
                      "by interp activity"
                      % (broken_head, visited), file=sys.stderr)


def _walk_gen0_check_invariants():
    """Walk the host Python gen0 GC linked list via raw ``PyGC_Head``
    pointer reads (no tp_traverse, no allocator calls -- safe even if
    the gc-tracked object graph is structurally corrupt).

    Checks the doubly-linked-list invariant: for every node ``cur``
    reachable via ``_gc_next``, the successor's ``_gc_prev`` must point
    back to ``cur``.  Returns ``(broken_head, visited)`` where
    ``broken_head`` is the address of the first PyGC_Head whose
    invariant is broken (or ``None`` if the list is intact), and
    ``visited`` is the number of nodes walked before the break.

    Anchored on a fresh ``[]`` (always gc-tracked) at the head of the
    young generation.  Caller is responsible for disabling host gc
    before runFunc so all tracked objects accumulate in gen0.
    """
    HEAD_SIZE = 16  # CPython 3.13 PyGC_Head (2 * uintptr_t)
    PTR_MASK = ~0xF  # low 4 bits of _gc_prev are tag flags

    def u64(addr):
        return ctypes.cast(addr, ctypes.POINTER(ctypes.c_uint64))[0]

    anchor = []  # always gc-tracked
    head = id(anchor) - HEAD_SIZE
    seen = {head}
    cur = u64(head) & PTR_MASK
    visited = 0
    MAX_NODES = 50_000_000  # safety cap
    while visited < MAX_NODES:
        if cur == 0 or (cur & 0x7) or cur in seen:
            break  # NULL, unaligned, or cycle back -- end of walk
        seen.add(cur)
        visited += 1
        nxt = u64(cur) & PTR_MASK
        if nxt == 0:
            return (cur, visited)  # forward link broken (NULL)
        # Verify back-pointer.
        nxt_prev = u64(nxt + 8) & PTR_MASK
        if nxt_prev != cur:
            return (cur, visited)  # doubly-linked invariant broken
        cur = nxt
    return None, visited


if __name__ == '__main__':
    # `--no-better-exchook` is parsed inside main() but we need to peek
    # at it here to decide whether to install the global handler.  Do
    # a cheap pre-scan instead of a full argparse pass (which would
    # consume the unknown CPython options we forward).
    if "--no-better-exchook" in sys.argv:
        import traceback
        try:
            main(sys.argv)
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt", file=sys.stderr)
            sys.exit(1)
        except BaseException:
            # Stdlib traceback: prints frame info from the existing
            # traceback object without walking the GC heap, so a
            # corrupt ctypes graph won't crash the handler itself.
            traceback.print_exc()
            sys.exit(1)
    else:
        import better_exchook
        better_exchook.install()
        try:
            main(sys.argv)
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
            sys.exit(1)
