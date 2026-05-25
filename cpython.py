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
        # ast_opt.c is intentionally NOT parsed; ``_PyAST_Optimize`` is
        # replaced with a Python stub (see further down).
        # ast.c put those macros back.  Pop AGAIN before symtable.c /
        # compile.c -- compile.c uses ``VISIT(C, expr, V)`` to
        # token-paste ``compiler_visit_expr``; if ``expr`` is still a
        # macro = 315, it becomes ``compiler_visit_315`` (parse error).
        for _m in _grammar_macros_to_pop:
            self.macros.pop(_m, None)
        self.macros.pop("OFF", None)  # symtable.c re-defines OFF
        # Python-reserved-word / dunder C identifiers (``lambda``,
        # ``__doc__``, ``__class__``, ``__annotations__`` in
        # symtable.c / compile.c) are now handled automatically by
        # cparser's ``py_safe_identifier`` rename + ``GlobalsWrapper.
        # __getattribute__`` override -- no source-level renaming
        # needed here.
        cparser.parse(CPythonDir + "/Python/symtable.c", self) # _PySymtable_Build
        cparser.parse(CPythonDir + "/Python/compile.c", self) # PyAST_CompileObject
        cparser.parse(CPythonDir + "/Python/pystate.c", self) # PyInterpreterState_New
        cparser.parse(CPythonDir + "/Python/errors.c", self) # PyErr_Clear
        cparser.parse(CPythonDir + "/Python/getargs.c", self) # PyArg_ParseTuple, _PyArg_UnpackStack, etc.
        cparser.parse(CPythonDir + "/Python/structmember.c", self) # PyMember_GetOne, PyMember_SetOne
        self.macros.pop("FLAG_SIZE_T", None)
        cparser.parse(CPythonDir + "/PC/config.c", self) # _PyImport_Inittab
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
        cparser.parse(CPythonDir + "/Python/sysmodule.c", self) # PySys_ResetWarnOptions
        cparser.parse(CPythonDir + "/Objects/weakrefobject.c", self) # PyWeakref_NewRef
        # funcobject.c must be parsed BEFORE bytearrayobject.c (and others
        # that have METH_STATIC / METH_CLASS methods) so that PyStaticMethod_Type
        # / PyClassMethod_Type / PyFunction_Type get their static initializer
        # (tp_alloc = PyType_GenericAlloc etc.).  Without it, add_methods()
        # calls PyStaticMethod_New() which finds tp_alloc == NULL and returns
        # NULL, making PyType_Ready fail with no Python-level error message.
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
        cparser.parse(CPythonDir + "/Python/_warnings.c", self) # _PyWarnings_Init


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

    # Py_GetPrefix/ExecPrefix/Path/PythonHome/ProgramFullPath are defined in
    # pathconfig.c, which is intentionally not parsed.  Their C implementation
    # calls _PyPathConfig_Init() (from Modules/getpath.c, also not parsed),
    # which walks the real filesystem to discover where CPython is installed.
    # That filesystem-discovery logic is platform-specific, requires many
    # unwrapped syscalls, and would return the *wrong* paths anyway — we want
    # the host Python's prefix/path so the interpreted CPython can find its
    # stdlib.  We therefore supply these values directly from the host runtime.

    def _make_wchar_const(s):
        """Create a wchar_t* constant string suitable for returning from Py_Get* functions."""
        buf = interpreter._make_wchar_string(s)
        return ctypes.cast(buf, ctypes.c_void_p).value or 0

    for _fn, _s in [
        ("Py_GetProgramFullPath", argv[0]),
        ("Py_GetPrefix", sys.prefix),
        ("Py_GetExecPrefix", sys.exec_prefix),
        ("Py_GetPath", ":".join(sys.path)),
        ("Py_GetPythonHome", ""),
    ]:
        def _make_path_func(s=_s):
            return _make_wchar_const(s)
        _make_path_func.C_argTypes = None
        _make_path_func.C_resType = ctypes.c_void_p
        interpreter._func_cache[_fn] = _make_path_func

    # _PyPathConfig_Calculate is defined in Modules/getpath.c (not parsed).
    # It fills a _PyPathConfig struct from the filesystem.  We provide a stub
    # that returns success (_PyInitError with msg=NULL) and leaves the config
    # fields at zero — the public Py_Get* functions above supply the real values.
    _PyInitError_ctype = interpreter.getCType(state.typedefs['_PyInitError'])

    def _path_config_calculate_stub(*args):
        return _PyInitError_ctype()  # all-zero = success (msg=NULL)

    _path_config_calculate_stub.C_argTypes = None
    _path_config_calculate_stub.C_resType = state.typedefs['_PyInitError']
    interpreter._func_cache['_PyPathConfig_Calculate'] = _path_config_calculate_stub

    # PyCPython is single-threaded; we always "hold the GIL".  The
    # real PyGILState_Check walks `_PyRuntime.gilstate.autoTSSkey` and
    # `tstate`, which are unreliable in our interpreted setup (calls
    # into TSS helpers we don't model).  Many places `assert(PyGILState_Check())`
    # at function entry (e.g. `_Py_write` in fileutils.c) -- a wrong
    # return of 0 there aborts.  Stub it to always return 1.
    def _py_gil_state_check():
        return 1
    _py_gil_state_check.C_argTypes = []
    _py_gil_state_check.C_resType = ctypes.c_int
    interpreter._func_cache["PyGILState_Check"] = _py_gil_state_check

    # ``pymain_init_sys_path`` fails with
    # "pymain_update_sys_path: can't get sys.path" -- since we skipped
    # initexternalimport, ``sys.path`` was never populated.  Stub it
    # out to return success.
    def _py_pymain_init_sys_path(pymain, config):
        """pymain_init_sys_path(_PyMain *, _PyCoreConfig *) -> int."""
        return 0  # success
    _py_pymain_init_sys_path.C_argTypes = None
    _py_pymain_init_sys_path.C_resType = ctypes.c_int
    interpreter._func_cache["pymain_init_sys_path"] = _py_pymain_init_sys_path

    # Diagnostic override for ``_Py_FatalInitError``: prints
    # ``err.prefix`` and ``err.msg`` (which hold the failing function
    # name and a human-readable error message) BEFORE aborting.
    # Without this, we lose the most useful error information.
    def _py_fatal_init_error(err):
        """_Py_FatalInitError(_PyInitError err): print + abort."""
        # err is a wrapped struct; .prefix/.msg are char* (LP_c_byte).
        def _read_cstr(p):
            try:
                addr = ctypes.addressof(p.contents)
            except (ValueError, AttributeError):
                return "<null>"
            if not addr:
                return "<null>"
            return ctypes.string_at(addr).decode("utf-8", errors="replace")
        prefix = _read_cstr(err.prefix)
        msg = _read_cstr(err.msg)
        print(f"_Py_FatalInitError: prefix={prefix!r} msg={msg!r}",
              flush=True)
        interpreter._abort()
    _py_fatal_init_error.C_argTypes = None
    _py_fatal_init_error.C_resType = None
    interpreter._func_cache["_Py_FatalInitError"] = _py_fatal_init_error

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
        ``PyImport_ImportModule("builtins")`` path.
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

    # ``_PyAST_Optimize`` (in ast_opt.c) walks the AST applying
    # peephole optimizations.  Its translation currently fails on
    # ``node_->v.<UnionTag>.<field>`` chains because cparser is
    # confused by the function-like macros in Python-ast.h (``While``,
    # ``If``, ...) which share names with the union field tags.
    # Optimization is OPTIONAL -- compile.c works correctly with an
    # un-optimized AST too.  Stub it out to return success.
    def _py_ast_optimize(mod, arena, optimize):
        """_PyAST_Optimize(mod_ty, PyArena*, int) -> int.  Stub: skip."""
        return 1  # success
    _py_ast_optimize.C_argTypes = None
    _py_ast_optimize.C_resType = ctypes.c_int
    interpreter._func_cache["_PyAST_Optimize"] = _py_ast_optimize


    # Override ``builtin_print``: we skipped ``init_sys_streams``
    # (that imports the ``io`` module, which is huge), so sys.stdout
    # isn't set and the real ``builtin_print`` errors with
    # ``RuntimeError: lost sys.stdout``.  Replace with a direct write
    # to host stdout.  Reads positional args via ctypes from the
    # interp's vector, converts each to its UTF-8 ``str`` repr via
    # interp helpers, and prints with separator/end like real
    # ``print()``.
    def _py_builtin_print(self_arg, args_arr, nargs, kwnames):
        """builtin_print(self, args, nargs, kwnames): write to host stdout."""
        py_object_str = interpreter.getFunc("PyObject_Str")
        py_unicode_as_utf8 = interpreter.getFunc("PyUnicode_AsUTF8")
        nargs_v = nargs.value if hasattr(nargs, "value") else int(nargs)
        # args_arr is PyObject *const *; index it as void**.
        args_void = ctypes.cast(args_arr, ctypes.POINTER(ctypes.c_void_p))
        parts = []
        py_err_print = interpreter.getFunc("PyErr_Print")
        py_err_clear = interpreter.getFunc("PyErr_Clear")
        for i in range(nargs_v):
            item_addr = args_void[i]
            if not item_addr:
                parts.append("None")
                continue
            obj = ctypes.c_void_p(item_addr)
            s_ptr = py_object_str(obj)  # new PyUnicode
            s_addr = s_ptr.value if hasattr(s_ptr, "value") else int(s_ptr)
            if not s_addr:
                # PyObject_Str failed -- show the exception, then
                # clear it so subsequent args still try.
                print("<?str-failed?>", end="", flush=True)
                py_err_print()
                py_err_clear()
                parts.append("<?>")
                continue
            cstr_ptr = py_unicode_as_utf8(s_ptr)
            addr = cstr_ptr.value if hasattr(cstr_ptr, "value") else int(cstr_ptr)
            if not addr:
                print("<?utf8-failed?>", end="", flush=True)
                py_err_print()
                py_err_clear()
                parts.append("<?>")
                continue
            parts.append(ctypes.string_at(addr).decode("utf-8", errors="replace"))
        print(" ".join(parts), flush=True)
        # Return Py_None as a PyObject*.  Bump refcount per CPython
        # convention.  We return the address as an int -- the caller's
        # ``checkedFuncPtrCall`` will wrap via ``restype(int)`` which
        # for a pointer ctype means "pointer with that address".
        none_obj = interpreter.globalScope.getVar("_Py_NoneStruct")
        none_obj.ob_refcnt.value = none_obj.ob_refcnt.value + 1
        return ctypes.addressof(none_obj)
    _py_builtin_print.C_argTypes = None
    _py_builtin_print.C_resType = None
    interpreter._func_cache["builtin_print"] = _py_builtin_print

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
