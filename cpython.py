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
                self.macros["SIZE_MAX"] = cparser.Macro(rightside=str(ctypes.c_size_t(-1).value))
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
        if not is_template_header:
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
        cparser.parse(CPythonDir + "/Objects/bytes_methods.c", self)
        # bytearrayobject.c #defines STRINGLIB_* macros that asciilib.h
        # (included via unicodeobject.c above) already defined.  Drop the
        # earlier definitions so the file can re-#define them locally.
        for _m in ("STRINGLIB_ISSPACE", "STRINGLIB_ISLINEBREAK",
                   "STRINGLIB_CHECK_EXACT"):
            self.macros.pop(_m, None)
        cparser.parse(CPythonDir + "/Objects/bytearrayobject.c", self) # PyByteArray_Type
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
        cparser.parse(CPythonDir + "/Objects/bytesobject.c", self) # PyBytes_Type
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
        # We need these macro hacks because methodobject.c will use the same vars.
        self.macros["numfree"] = cparser.Macro(rightside="numfree__methodobj")
        self.macros["free_list"] = cparser.Macro(rightside="free_list__methodobj")
        self.macros.pop("OFF", None)  # funcobject.c defines OFF; methodobject.c redefines it
        cparser.parse(CPythonDir + "/Objects/methodobject.c", self) # PyCFunction_NewEx
        cparser.parse(CPythonDir + "/Objects/classobject.c", self) # PyMethod_Type
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
        '--gc-list-diff', action='store_true',
        help="Before running, snapshot the ``_gc_next`` field of every "
             "PyGC_Head in Python's real gen2 GC list.  After the run "
             "(or at each --gc-check-at point, if both are set), walk "
             "the same entries and report any whose ``_gc_next`` was "
             "overwritten.  This is the canonical 'find which Python "
             "object's GC linkage got corrupted' probe.\n"
             "\n"
             "Background: every gc-tracked PyObject has a 16-byte "
             "PyGC_Head immediately before its address, containing "
             "``_gc_next`` and ``_gc_prev`` pointers.  Each generation "
             "(gen0, gen1, gen2) is a doubly-linked circular list of "
             "these heads.  ``gc.collect()`` walks the list via "
             "``_gc_next``; if any link is overwritten, the walk "
             "either segfaults (dereferencing junk) or enters a wrong "
             "list and loops forever.  This option detects exactly "
             "which entry's link changed and identifies the object.")
    argparser.add_argument(
        '--watch-write', action='append', default=[],
        metavar="ADDR",
        help="Hex address (eg. 0x1006f2e70) -- abort with a backtrace "
             "the moment any interp write goes through "
             "``_ctype_ptr_set_value`` to that exact cell address.  "
             "Repeatable.  Combine with --gc-list-diff to first "
             "identify the victim PyGC_Head, then re-run with "
             "--watch-write set to that address to pinpoint the "
             "exact interp instruction performing the write.")
    argparser.add_argument(
        '--watch-write-gen2-weakrefs', action='store_true',
        help="Auto-populate --watch-write with the PyGC_Head._gc_next "
             "address of every gen2 weakref present at startup.  Wide "
             "net for catching the first write to any of them -- "
             "useful when the corruption victim varies between runs.")
    argparser.add_argument(
        '--track-pointer-storage', action='store_true',
        help="Replace ``interp.pointerStorage`` with a tracking "
             "subclass that assigns a sequential ``entry_id`` to "
             "every registration, recording (entry_id, key, value "
             "type, registration stack).  Combined with "
             "--gc-list-diff, the diagnostic reports the entry_id "
             "and registration site of each corrupted weakref's "
             "referent.  Because the registration order is "
             "deterministic across runs, this lets us pinpoint the "
             "creation site of the values whose KeyedRef weakrefs "
             "get corrupted -- and re-run with "
             "--watch-pointer-storage-id to halt at that exact "
             "registration.")
    argparser.add_argument(
        '--watch-pointer-storage-id', action='append', default=[],
        metavar="ID[,ID...]",
        help="Comma-separated (or repeated) list of pointerStorage "
             "entry_id values.  Print stack + full context the "
             "moment each named id is being registered.  Requires "
             "--track-pointer-storage.")
    argparser.add_argument(
        '--mprotect-at-iter', type=int, default=0, metavar="N",
        help="(EXPERIMENTAL, **macOS BROKEN**) At iter N of "
             "checkedFuncPtrCall, ``mprotect`` READ-ONLY the 16 KB "
             "pages of each captured KeyedRef PyGC_Head (from "
             "--watch-pointer-storage-id) and/or every gen2 weakref "
             "(from --gc-list-diff).  The intent is to make any "
             "write -- including ctypes C-level writes hidden from "
             "Python-level hooks -- raise SIGSEGV with a Python "
             "stack via faulthandler.  Status: BUS-errors on macOS "
             "even on a single Python-heap page (verified with both "
             "``mprotect`` and ``mach_vm_protect`` -- the kernel "
             "rejects protection changes on pages allocated by "
             "pymalloc-style ``mmap``).  May still work on Linux.")
    args_ns, argv_rest = argparser.parse_known_args(argv[1:])

    if args_ns.report_extended_tracebacks:
        register_sigusr1_print_backtrace()
    init_faulthandler(sigusr1_chain=args_ns.report_extended_tracebacks)

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

    # --track-pointer-storage: instrument every pointerStorage
    # registration with a sequential entry_id + (key, value type,
    # registration stack).  Lets the diagnostic identify exactly
    # which interp values get their KeyedRef weakrefs corrupted, and
    # supports --watch-pointer-storage-id to halt at registration.
    # Must be done *before* register(state) -- which is the first
    # code path that populates pointerStorage.
    if args_ns.track_pointer_storage or args_ns.watch_pointer_storage_id:
        import weakref as _tps_wr
        import traceback as _tps_tb
        _tps_watch = set()
        for _spec in args_ns.watch_pointer_storage_id:
            for _part in _spec.split(","):
                _part = _part.strip()
                if _part:
                    _tps_watch.add(int(_part))
        # Shared *mutable* set: the KeyedRef PyGC_Head addresses of
        # every watched entry, captured the moment that entry is
        # registered.  Registrations happen during runFunc (which is
        # AFTER --watch-write set up its hook), so the watch hook
        # must read this set dynamically -- it must not snapshot.
        _tps_keyedref_heads = []  # legacy: list of (eid, addr, key, tname)
        _tps_keyedref_addr_set = set()  # fast lookup for write hook

        class _TrackedPointerStorage(_tps_wr.WeakValueDictionary):
            """Drop-in replacement for ``WeakValueDictionary`` that
            records each registration in a sequential id->info map
            and optionally halts on specific ids."""
            def __init__(self):
                super().__init__()
                # ``id(value) -> (entry_id, key_addr, type_name, stack_lines)``
                self._reg_info = {}
                self._reg_counter = 0
                self._reg_watch = _tps_watch
            def __setitem__(self, key, value):
                self._reg_counter += 1
                _eid = self._reg_counter
                _tname = type(value).__name__
                _stack_lines = None
                _is_watched = _eid in self._reg_watch
                if _is_watched:
                    _stack_lines = _tps_tb.format_stack(limit=12)
                    print("\n[track-ps] entry_id=%d registered: key=0x%x "
                          "value=%s at id=0x%x"
                          % (_eid, key, _tname, id(value)),
                          file=sys.stderr, flush=True)
                    for _ln in _stack_lines:
                        sys.stderr.write(_ln)
                    sys.stderr.flush()
                self._reg_info[id(value)] = (_eid, key, _tname, _stack_lines)
                super().__setitem__(key, value)
                if _is_watched:
                    # After super.__setitem__, ``self.data[key]`` is
                    # the freshly-created ``KeyedRef`` -- the very
                    # Python object whose ``PyGC_Head._gc_next`` we
                    # observe getting corrupted later.  Capture its
                    # PyGC_Head address so the write-watcher can
                    # arm a tripwire on it.
                    try:
                        _kref = self.data[key]
                        _kref_head = id(_kref) - 16
                        _tps_keyedref_heads.append(
                            (_eid, _kref_head, key, _tname))
                        _tps_keyedref_addr_set.add(_kref_head)
                        # Stamp with current checkedFuncPtrCall iter so
                        # we can tell when registration happens vs the
                        # known corruption iter (1343).
                        _iter_now = getattr(
                            interpreter.helpers.checkedFuncPtrCall,
                            "_count", [None])
                        _iter_val = _iter_now[0] if isinstance(_iter_now, list) else None
                        print("[track-ps]   -> KeyedRef PyGC_Head at 0x%x "
                              "(armed for --watch-write)  "
                              "[at checkedFuncPtrCall iter ~%s]"
                              % (_kref_head, _iter_val), file=sys.stderr, flush=True)
                    except KeyError:
                        pass

        interpreter.pointerStorage = _TrackedPointerStorage()
        print("[track-ps] installed TrackedPointerStorage (watch_ids=%s)"
              % sorted(_tps_watch), file=sys.stderr)

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
                # If --gc-list-diff is also set, do the (safe) snapshot
                # diff before the (potentially-crashing) gc.get_referrers
                # call -- so we capture the corruption even if the next
                # line segfaults.
                if args_ns.gc_list_diff and _gc_diff_baseline is not None:
                    _gc_list_diff_report("at %d" % n)
                refs = _gc_mod.get_referrers(_gc_co)
                print("[gc-check %d] ok (%d referrers)"
                      % (n, len(refs)), file=sys.stderr, flush=True)
            return _orig_call(f, *args)
        interpreter.helpers.checkedFuncPtrCall = _gc_check_wrapped
        print("[gc-check] hooked checkedFuncPtrCall, interval=%d, at=%s"
              % (_gc_interval, sorted(_gc_check_at) or "[]"),
              file=sys.stderr)

    # `--gc-list-diff`: snapshot Python's real gen2 GC list before
    # running, diff after.  See the option's help text for a full
    # explanation of what a "PyGC_Head" is and why this is useful.
    #
    # Note: this walks Python's actual gc-tracked-object linked list
    # via raw ctypes pointer reads.  It must not retain references to
    # the objects it inspects -- doing so changes the heap state (eg.
    # prevents otherwise-collectable objects from being GC'd) which
    # has been observed to alter the path through the interp and hide
    # the bug.  So we snapshot only ``(head_addr -> _gc_next_value)``
    # and identify objects post-run by reading their PyObject_HEAD
    # fields (refcnt, ob_type) directly.
    _gc_diff_baseline = None
    if args_ns.gc_list_diff:
        import gc as _gcl_mod
        _gcl_mod.collect()
        _gcl_mod.collect()
        # Snapshot gen2 by walking the linked list from a tracked
        # anchor (a builtins type, guaranteed in gen2 by the time we
        # get here).  At each step we read ``_gc_next`` only; we don't
        # retain the objects (would change the heap state).
        #
        # Termination: cycle back to start (the normal case) OR hit an
        # invalid pointer (NULL / unaligned).  The MAX cap is a
        # safety net -- if we walk past it, the list is bigger than
        # any reasonable real gen2 OR the walk crossed into another
        # linked structure via a bad link; in either case we stop.
        # After parsing all of cpython's C source, gen2 has ~5M
        # objects.  Walking the full circular list is too expensive
        # and most of those objects are irrelevant.  Filter to
        # ``weakref.ref`` instances -- empirically the corruption
        # observed always targets a weakref.  This narrows the
        # snapshot to ~thousands of entries and keeps the diff
        # signal/noise ratio high.
        import weakref as _gcl_wr
        _gen2 = _gcl_mod.get_objects(generation=2)
        _gen2_size = len(_gen2)
        # Capture (head_addr, _gc_next_value, identity-string) per
        # weakref while the heap is still healthy.  The identity
        # string is built from referent type + repr so we can
        # identify post-run without dereferencing potentially-
        # corrupt pointers.  Don't retain the weakref object itself.
        def _gcl_u64(addr):
            return ctypes.cast(addr, ctypes.POINTER(ctypes.c_uint64))[0]
        # Pre-build a set of id(v) for every value currently in our
        # interp's pointerStorage.  Then we can tag weakrefs that
        # refer to one of our pointerStorage entries -- these are the
        # KeyedRef instances WeakValueDictionary creates internally.
        _ps_value_ids = set()
        try:
            for _k in list(interpreter.pointerStorage):
                _v = interpreter.pointerStorage.get(_k)
                if _v is not None:
                    _ps_value_ids.add(id(_v))
                    del _v
        except BaseException:
            pass
        _baseline = {}
        _identity = {}  # head_addr -> string
        for _o in _gen2:
            if not isinstance(_o, _gcl_wr.ref):
                continue
            _head = id(_o) - 16
            _baseline[_head] = _gcl_u64(_head)
            try:
                _ref = _o()
            except BaseException:
                _ref = None
            if _ref is None:
                _ident = "weakref(dead)"
            else:
                _tname = type(_ref).__name__
                _in_ps = (id(_ref) in _ps_value_ids)
                _tag = " [interp.pointerStorage value]" if _in_ps else ""
                if isinstance(_ref, type):
                    _ident = "weakref to type %r%s" % (_ref.__name__, _tag)
                else:
                    _ident = "weakref to %s instance at 0x%x%s" % (
                        _tname, id(_ref), _tag)
                del _ref
            _identity[_head] = _ident
        del _gen2, _ps_value_ids
        print("[gc-list-diff] gen2 size at snapshot: %d, weakrefs: %d"
              % (_gen2_size, len(_baseline)), file=sys.stderr)
        _gc_diff_baseline = _baseline
        _gc_diff_identity = _identity
        _gc_diff_helpers = (_gcl_u64, interpreter)

    def _gc_list_diff_report(label):
        """Walk the snapshot, find changed _gc_next values, identify
        the corrupted Python objects.  Resolves PyObject metadata by
        reading raw memory -- no gc.get_objects() needed.
        """
        if _gc_diff_baseline is None:
            return
        _u64, _interp = _gc_diff_helpers
        _changed = []
        for _head, _before in _gc_diff_baseline.items():
            try:
                _after = _u64(_head)
            except OSError:
                _after = None
            if _after != _before:
                _changed.append((_head, _before, _after))
        if not _changed:
            print("[gc-list-diff %s] no changes detected (gen2 intact)"
                  % label, file=sys.stderr)
            return
        # A change is "benign" if new _gc_next still points at a
        # PyGC_Head we know about (one of the weakref heads we
        # snapshotted) -- i.e., Python's gc just shuffled the order
        # within our subgroup.  A change to an UNKNOWN address is
        # suspicious -- our snapshot covered all weakrefs that
        # existed pre-run, so a new value outside the set either
        # points to a non-weakref object (legitimate cross-type
        # neighbor) or to non-heap memory (the corruption signal).
        _known_heads = set(_gc_diff_baseline.keys())
        # Resolve weakref.ref type and its subclasses for ob_type
        # compares.  ``WeakValueDictionary`` uses ``KeyedRef`` (a
        # ``weakref.ref`` subclass), so we collect all subclass ids
        # too -- otherwise we'd miss those entries.
        import weakref as _wr
        _wr_ref_types = {id(_wr.ref)}
        for _sc in _wr.ref.__subclasses__():
            _wr_ref_types.add(id(_sc))
            for _ssc in _sc.__subclasses__():
                _wr_ref_types.add(id(_ssc))
        _ps_id = id(_interp.pointerStorage)
        _ps_type_id = id(type(_interp.pointerStorage))
        print("[gc-list-diff %s] %d PyGC_Head._gc_next changed:"
              % (label, len(_changed)), file=sys.stderr)
        for _head, _before, _after in _changed:
            _obj = _head + 16
            try:
                _rc = _u64(_obj)
                _tp = _u64(_obj + 8)
            except OSError:
                _rc = _tp = 0
            _benign = (_after in _known_heads)
            _classify = "benign-shuffle" if _benign else "UNKNOWN-target"
            _ident = _gc_diff_identity.get(_head, "(no identity)")
            print("[gc-list-diff %s]   PyGC_Head 0x%x  [%s]: %s"
                  % (label, _head, _classify, _ident), file=sys.stderr)
            print("[gc-list-diff %s]     _gc_next was 0x%x -> now 0x%x"
                  % (label, _before, _after if _after is not None else 0),
                  file=sys.stderr)
            print("[gc-list-diff %s]     PyObject at 0x%x: refcnt=%d ob_type=0x%x"
                  % (label, _obj, _rc, _tp), file=sys.stderr)
            if _tp in _wr_ref_types:
                # It's a weakref.  Decode the referent.
                _ref_obj = _u64(_obj + 16)  # PyWeakReference.wr_object
                if _ref_obj:
                    _ref_rc = _u64(_ref_obj)
                    _ref_tp = _u64(_ref_obj + 8)
                    # tp_name is at offset 24 in PyTypeObject.
                    _name_ptr = _u64(_ref_tp + 24)
                    _name = ctypes.string_at(_name_ptr) if _name_ptr else b""
                    print("[gc-list-diff %s]     -> weakref to instance of %r "
                          "(refcnt=%d) at 0x%x"
                          % (label, _name.decode("ascii", "replace"),
                             _ref_rc, _ref_obj), file=sys.stderr)
                    # If the referent is a type (Python real or our
                    # interp's), also dump ITS own tp_name (the class
                    # it represents).  Defensive: reading garbage
                    # tp_name pointers segfaults, so guard.
                    if _name in (b"type", b"_typeobject"):
                        _own_name_ptr = _u64(_ref_obj + 24)
                        # Only attempt the read if the pointer looks
                        # plausibly like a c-string address (heap
                        # range and aligned).
                        _own_name = b""
                        if (_own_name_ptr
                                and 0x100_000_000 <= _own_name_ptr < 0x1_000_000_000):
                            try:
                                _own_name = ctypes.string_at(
                                    _own_name_ptr, size=64).split(b"\x00", 1)[0]
                            except (OSError, ValueError):
                                _own_name = b"<unreadable>"
                        print("[gc-list-diff %s]        referent type tp_name: %r"
                              % (label,
                                 _own_name.decode("ascii", "replace")),
                              file=sys.stderr)
                    # Is the referent inside one of our interp's
                    # malloc'd buffers?  If yes, the weakref refers
                    # to memory that our interp owns -- pinpoints
                    # ctype objs we constructed via ``_malloc``.
                    _from_mallocs = False
                    if hasattr(_interp, "mallocs"):
                        for _b, _bv in _interp.mallocs.items():
                            try:
                                _bsz = ctypes.sizeof(_bv)
                            except (TypeError, OSError):
                                continue
                            if _b <= _ref_obj < _b + _bsz:
                                _from_mallocs = True
                                print("[gc-list-diff %s]        referent IS in "
                                      "interp.mallocs base=0x%x size=%d offset=%d"
                                      % (label, _b, _bsz, _ref_obj - _b),
                                      file=sys.stderr)
                                break
                    if not _from_mallocs:
                        print("[gc-list-diff %s]        referent NOT in interp.mallocs"
                              % label, file=sys.stderr)
                    # If we have tracked-pointerStorage metadata,
                    # look up the registration record for this
                    # referent.  ``_reg_info`` is keyed by
                    # ``id(value)`` which for a Python ctype object
                    # equals the wr_object address we just read.
                    _reg_info = getattr(_interp.pointerStorage, "_reg_info", None)
                    if _reg_info is not None:
                        _info = _reg_info.get(_ref_obj)
                        if _info is not None:
                            _eid, _key, _tname, _stk = _info
                            print("[gc-list-diff %s]        pointerStorage "
                                  "entry_id=%d key=0x%x type=%s"
                                  % (label, _eid, _key, _tname),
                                  file=sys.stderr)
                            if _stk:
                                print("[gc-list-diff %s]        registration stack:"
                                      % label, file=sys.stderr)
                                for _ln in _stk:
                                    sys.stderr.write(_ln)
                        else:
                            print("[gc-list-diff %s]        referent NOT found "
                                  "in tracked pointerStorage._reg_info"
                                  % label, file=sys.stderr)
                    if _ref_obj == _ps_id:
                        print("[gc-list-diff %s]        ** is interp.pointerStorage **"
                              % label, file=sys.stderr)
                    elif _ref_tp == _ps_type_id:
                        print("[gc-list-diff %s]        (same TYPE as "
                              "interp.pointerStorage but different INSTANCE)"
                              % label, file=sys.stderr)
                else:
                    print("[gc-list-diff %s]     -> weakref with dead referent"
                          % label, file=sys.stderr)

    # --watch-write: trap any write whose target cell lands on one of
    # the named addresses.  Targets the most common interp write path
    # (`_ctype_ptr_set_value` from `helpers.assignPtr` -> `_storePtr`).
    # If a match is found, print stack and re-raise -- the backtrace
    # identifies the exact translated-C function and source line that
    # wrote the corrupting value.
    _watch_addrs = set()
    for _spec in args_ns.watch_write:
        _spec = _spec.strip()
        if _spec:
            _watch_addrs.add(int(_spec, 0))
    if args_ns.watch_write_gen2_weakrefs:
        import gc as _ww_gc
        import weakref as _ww_wr
        _ww_gc.collect(); _ww_gc.collect()
        _gen2 = _ww_gc.get_objects(generation=2)
        for _o in _gen2:
            if isinstance(_o, _ww_wr.ref):
                _watch_addrs.add(id(_o) - 16)
        del _gen2
        print("[watch-write] populated %d addresses from gen2 weakrefs"
              % len(_watch_addrs), file=sys.stderr)
    # If --track-pointer-storage --watch-pointer-storage-id is also
    # active, the watch-write hook must consult the *dynamic*
    # ``_tps_keyedref_addr_set`` -- the entries are added DURING the
    # runFunc, not before.  Capture a reference here; the hook
    # closure below reads it on every write.
    try:
        _dynamic_watch = _tps_keyedref_addr_set
    except NameError:
        _dynamic_watch = None
    # Activate write-watching if either a fixed --watch-write set or
    # a dynamic --track-pointer-storage-fed set is available.
    if _watch_addrs or _dynamic_watch is not None:
        import traceback as _ww_tb
        _ctypes_addressof = ctypes.addressof
        _ctypes_sizeof = ctypes.sizeof
        _watch_set = frozenset(_watch_addrs)
        # Range-overlap: the write may cover [addr, addr+sizeof(value))
        # which can encompass a watched cell.  For the 16-byte
        # PyGC_Head we care about, even a 1-byte write inside the
        # 16-byte window matters.  Compute the watched 16-byte
        # windows once and use a fast point-in-range check at each
        # write.  (Using sorted list + bisect for O(log n) lookup.)
        import bisect as _ww_bisect
        _watch_starts = sorted(_watch_set)
        _WATCH_HEAD_SIZE = 16

        def _ww_overlaps(write_start, write_size):
            # Check static --watch-write set via bisect.
            _i = _ww_bisect.bisect_right(_watch_starts, write_start + write_size - 1)
            if _i > 0:
                _w = _watch_starts[_i - 1]
                if _w + _WATCH_HEAD_SIZE > write_start:
                    return _w
            # Check the dynamic --track-pointer-storage-fed set.  Linear
            # scan is fine: the set is small (number of watched
            # entry_ids).
            if _dynamic_watch:
                _we = write_start + write_size
                for _w in _dynamic_watch:
                    if _w < _we and _w + _WATCH_HEAD_SIZE > write_start:
                        return _w
            return None

        def _ww_report(kind, write_start, write_size, value_descr):
            _w = _ww_overlaps(write_start, write_size)
            if _w is None:
                return
            print("\n[watch-write] *** HIT *** %s overlaps watched window"
                  " [0x%x, 0x%x): write=[0x%x, 0x%x), value=%s"
                  % (kind, _w, _w + _WATCH_HEAD_SIZE,
                     write_start, write_start + write_size, value_descr),
                  file=sys.stderr, flush=True)
            _ww_tb.print_stack(file=sys.stderr)

        # Hook ``_ctype_ptr_set_value`` (writes 8 bytes at addressof(ptr)).
        _real_set = cparser.interpreter._ctype_ptr_set_value
        def _ww_hooked_set(ptr, addr):
            _ww_report("_ctype_ptr_set_value",
                       _ctypes_addressof(ptr), 8, "0x%x" % addr)
            return _real_set(ptr, addr)
        cparser.interpreter._ctype_ptr_set_value = _ww_hooked_set

        # Hook ``Helpers.assign`` (struct copy: writes sizeof(a) bytes).
        _real_assign = cparser.interpreter.Helpers.assign
        def _ww_hooked_assign(self, a, b):
            try:
                _addr = _ctypes_addressof(a)
                _sz = _ctypes_sizeof(a)
            except (TypeError, ctypes.ArgumentError):
                _addr = _sz = None
            if _addr is not None:
                _ww_report("Helpers.assign", _addr, _sz, repr(b)[:80])
            return _real_assign(self, a, b)
        cparser.interpreter.Helpers.assign = _ww_hooked_assign

        print("[watch-write] watching %d cell-address window(s) of "
              "%d bytes each" % (len(_watch_set), _WATCH_HEAD_SIZE),
              file=sys.stderr)

    # --mprotect-at-iter: at the named iter, make the page(s)
    # containing each watched KeyedRef READ-ONLY.  Subsequent writes
    # to those pages -- including the ctypes C-level writes our
    # Python hooks can't see -- raise SIGSEGV; faulthandler then
    # dumps the Python stack at the crash.
    if args_ns.mprotect_at_iter > 0:
        import ctypes.util as _mp_ctu
        _mp_libc_path = _mp_ctu.find_library("c") or "libc.dylib"
        _mp_libc = ctypes.CDLL(_mp_libc_path, use_errno=True)
        _mp_libc.mprotect.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        _mp_libc.mprotect.restype = ctypes.c_int
        _MP_PROT_READ = 1
        _MP_PAGE_SIZE = 16384  # macOS arm64 / Linux can be 4096; 16384 covers both safely
        _mp_count = [0]
        _mp_armed = [False]
        _mp_orig_call = interpreter.helpers.checkedFuncPtrCall

        def _mp_wrapped(f, *args):
            _mp_count[0] += 1
            if _mp_count[0] == args_ns.mprotect_at_iter and not _mp_armed[0]:
                _mp_armed[0] = True
                _pages = set()
                _addrs = []
                # Source 1: --watch-pointer-storage-id captured KeyedRef
                # addresses (may be empty if entry_ids register AFTER
                # the corruption iter; that turned out to be the case
                # for the known cpython.py bug, where the supposed
                # KeyedRef entries are slot-collision misidentifications
                # of pre-existing real Python weakrefs).
                try:
                    for _eid, _kh, _key, _tname in _tps_keyedref_heads:
                        _addrs.append(("kref_id=%d" % _eid, _kh))
                except NameError:
                    pass
                # Source 2: --gc-list-diff captured gen2 weakref
                # PyGC_Head addresses BEFORE runFunc.  These are the
                # actual victims in cpython.py's bug -- real Python
                # weakrefs that pre-exist our pointerStorage activity.
                try:
                    for _h in _gc_diff_baseline:
                        _addrs.append(("gen2_weakref", _h))
                except NameError:
                    pass
                if not _addrs:
                    print("[mprotect] WARN: no addresses to protect "
                          "(need --watch-pointer-storage-id or "
                          "--gc-list-diff).", file=sys.stderr)
                else:
                    # Pre-compute unique pages WITHOUT calling mprotect.
                    for _tag, _addr in _addrs:
                        _pages.add(_addr & ~(_MP_PAGE_SIZE - 1))
                    print("[mprotect] would protect %d unique pages "
                          "covering %d addresses; about to mprotect..."
                          % (len(_pages), len(_addrs)),
                          file=sys.stderr, flush=True)
                    # Sort pages so the run-order is reproducible.
                    _pages_sorted = sorted(_pages)
                    # Now actually mprotect.  ANY further write to
                    # these pages -- including writes done by the
                    # tail of THIS function (eg. ``print``-related
                    # heap activity that happens to allocate on a
                    # protected page) -- will BUS-error.  So we keep
                    # the rest of this branch minimal: no prints, no
                    # allocations.  Page-list is logged BEFORE.
                    _ok = 0
                    _fail = 0
                    for _page in _pages_sorted:
                        _rc = _mp_libc.mprotect(
                            _page, _MP_PAGE_SIZE, _MP_PROT_READ)
                        if _rc != 0:
                            _fail += 1
                        else:
                            _ok += 1
                    # Stash counts on the function object so we can
                    # log later if we survive.
                    _mp_wrapped._ok = _ok
                    _mp_wrapped._fail = _fail
            return _mp_orig_call(f, *args)
        # Expose the iter counter so other code (TrackedPointerStorage's
        # registration logger) can report "at iter ~N" stamps.
        _mp_wrapped._count = _mp_count
        interpreter.helpers.checkedFuncPtrCall = _mp_wrapped
        print("[mprotect] hook installed; will arm at iter %d "
              "(KeyedRef pages captured by --watch-pointer-storage-id "
              "during runFunc)" % args_ns.mprotect_at_iter,
              file=sys.stderr)

    # Marker for lldb: under ``PYCPYTHON_LLDB_TRAP=1``, raise SIGTRAP
    # right here -- *after* gc-list-diff baseline / tracked
    # pointerStorage state is built, *before* the interp's iter loop
    # starts.  Ideal point to attach lldb watchpoints on PyGC_Head
    # addresses we want to catch writes to.  Combine with lldb's
    # ``settings set target.disable-aslr true`` so the addresses
    # observed in one run carry over to the next.
    if os.environ.get("PYCPYTHON_LLDB_TRAP"):
        # Optionally dump the captured gc-list-diff baseline addresses
        # to a file so lldb can read them and set watchpoints on the
        # same PyGC_Head's that will be corrupted later.
        _lldb_addrs_path = os.environ.get(
            "PYCPYTHON_LLDB_ADDRS_FILE", "/tmp/pycpython_lldb_addrs.txt")
        try:
            _base = _gc_diff_baseline
        except NameError:
            _base = None
        if _base:
            with open(_lldb_addrs_path, "w") as _f:
                for _h in _base:
                    _f.write("0x%x\n" % _h)
            print("[lldb-trap] wrote %d baseline weakref addresses to %s"
                  % (len(_base), _lldb_addrs_path),
                  file=sys.stderr, flush=True)
        import signal as _sig_lldb
        print("[lldb-trap] PID=%d, raising SIGTRAP -- lldb should now "
              "stop here; set watchpoints and 'continue'."
              % os.getpid(), file=sys.stderr, flush=True)
        os.kill(os.getpid(), _sig_lldb.SIGTRAP)

    args = ("Py_Main", len(argv), argv + [None])
    print("Run", args, ":")
    try:
        interpreter.runFunc(*args)
    finally:
        if _gc_diff_baseline is not None:
            _gc_list_diff_report("final")


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
