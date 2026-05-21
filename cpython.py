#!/usr/bin/env python3
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

from __future__ import print_function

import argparse
import os
import sys

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
                import ctypes
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
    interpreter.register(state)

    # Py_GetPrefix/ExecPrefix/Path/PythonHome/ProgramFullPath are defined in
    # pathconfig.c, which is intentionally not parsed.  Their C implementation
    # calls _PyPathConfig_Init() (from Modules/getpath.c, also not parsed),
    # which walks the real filesystem to discover where CPython is installed.
    # That filesystem-discovery logic is platform-specific, requires many
    # unwrapped syscalls, and would return the *wrong* paths anyway — we want
    # the host Python's prefix/path so the interpreted CPython can find its
    # stdlib.  We therefore supply these values directly from the host runtime.
    import ctypes as _ctypes

    def _make_wchar_const(s):
        """Create a wchar_t* constant string suitable for returning from Py_Get* functions."""
        buf = interpreter._make_wchar_string(s)
        return _ctypes.cast(buf, _ctypes.c_void_p).value or 0

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
        _make_path_func.C_resType = _ctypes.c_void_p
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

    args = ("Py_Main", len(argv), argv + [None])
    print("Run", args, ":")
    interpreter.runFunc(*args)


if __name__ == '__main__':
    import better_exchook
    better_exchook.install()
    try:
        main(sys.argv)
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt")
        sys.exit(1)
