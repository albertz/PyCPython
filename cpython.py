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
             "Useful for unattended debug runs; off by default to "
             "preserve normal crash-reporting in production usage.")
    argparser.add_argument(
        '--gen2-bisect', action='store_true', default=False,
        help="After runFunc returns, walk Python's gen2 GC list manually "
             "via PyGC_Head pointer-chasing (avoiding gc.get_objects("
             "generation=2) which crashes), then fork-bisect to find the "
             "single gen2 object whose tp_traverse crashes (the smoking "
             "gun for the shutdown-gc segfault).  Each child process "
             "runs gc.get_referents() on a subset; the crashing subset "
             "narrows the bad obj.  Disables gc during the bisect "
             "harness itself so the bisect is the only walker.")
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

    if args_ns.gen2_bisect:
        # Disable Python's automatic gc during runFunc -- with gc
        # disabled, nothing gets promoted past gen0, so post-runFunc
        # we enumerate via gc.get_objects(0).
        import gc as _gc_pre
        # Snapshot host-set IDs BEFORE disabling gc, so post-runFunc we
        # can tell which sets were created during runFunc itself.
        _gc_pre.collect()
        global _gen2_bisect_pre_set_ids
        _gen2_bisect_pre_set_ids = frozenset(
            id(s) for s in _gc_pre.get_objects()
            if type(s) is set
        )
        print("[gen2-bisect] pre-runFunc host-set count: %d"
              % len(_gen2_bisect_pre_set_ids), file=sys.stderr)
        _gc_pre.disable()
        print("[gen2-bisect] gc.disable() before runFunc",
              file=sys.stderr)
        # NOTE: a previous version of this code hooked interp._abort
        # to snapshot host-set IDs at the moment of CAbortException.
        # That perturbed timing enough to make the bug NOT reproduce
        # (heap-sensitive corruption).  Removed -- if you need an
        # abort-time snapshot, do it lazily / lighter-weight.

    args = ("Py_Main", len(argv), argv + [None])
    print("Run", args, ":")
    try:
        interpreter.runFunc(*args)
    finally:
        if args_ns.gen2_bisect:
            global _gen2_bisect_interp
            _gen2_bisect_interp = interpreter
            _gen2_bisect_after_runfunc()


_gen2_bisect_interp = None  # set by main() before calling the bisect
_gen2_bisect_pre_set_ids = frozenset()  # set by main() before runFunc
_gen2_bisect_abort_set_ids = frozenset()  # set by _hooked_abort


def _gen2_bisect_after_runfunc():
    """Walk Python's gen2 GC list manually and fork-bisect to find the
    object whose `tp_traverse` crashes during gc.collect.

    The shutdown segfault happens inside `deduce_unreachable` walking
    gen2 -- a single bad object's `tp_traverse` follows a stale pointer
    into freed memory.  We can't use `gc.get_objects(generation=2)` to
    enumerate gen2 (it crashes for the same reason).  Instead we walk
    the doubly-linked PyGC_Head list directly via raw ctypes reads.

    Then we fork(): each child calls `gc.get_referents(obj)` on a
    subset of gen2.  ``get_referents`` invokes ``tp_traverse`` on each
    given object without walking the gen list itself, so a crash
    indicates the SET contains the bad obj.  Binary-search narrows
    down which one.
    """
    import gc as _gc
    # We cannot use ``gc.get_objects(0)`` -- it walks gen0 via
    # tp_traverse to build a Python list and crashes on the bad obj
    # for the same reason gc.collect does.  Walk PyGC_Head links
    # manually (no tp_traverse) to enumerate addresses.
    addrs = _walk_gen_via_pygc_head()
    print("[gen2-bisect] gen0 size (via PyGC_Head walk): %d"
          % len(addrs), file=sys.stderr, flush=True)
    if not addrs:
        return
    # Filter all addresses to ones whose ob_type == host `set` type.
    # That gives us every host set currently in gen0.  We can read
    # ob_refcnt and (cautiously) PySet body fields to identify the
    # leaker (broken body / refcnt=0).
    def _u64sc(a):
        return ctypes.cast(a, ctypes.POINTER(ctypes.c_uint64))[0]
    host_set_id = id(set)
    set_addrs = [a for a in addrs if _u64sc(a + 8) == host_set_id]
    print("[gen2-bisect] host-set instances in gen0: %d"
          % len(set_addrs), file=sys.stderr, flush=True)
    # Dump each set's refcnt and body sanity.  PySetObject body
    # plausibility check: 0 <= used <= mask+1, mask is a power of 2
    # minus 1, mask >= PySet_MINSIZE-1=7.  table is either the
    # smalltable inside the object (very common) or an external buffer.
    weird_sets = []
    # Real PySetObject invariants (Python 3.13):
    #   mask is power-of-2 minus 1, >= 7 (PySet_MINSIZE-1 = 7)
    #   0 <= used <= fill <= mask
    #   table points to either &smalltable (offset +64) or an external
    #     buffer; the external buffer is well-defined memory
    # For our broken set we expect: huge mask (not power-of-2 - 1),
    # huge fill/used, table in bizarre range.
    _POW2_MINUS_1 = {(1 << k) - 1 for k in range(3, 31)}
    for sa in set_addrs:
        rc = _u64sc(sa)
        fill = _u64sc(sa + 16)
        used = _u64sc(sa + 24)
        mask = _u64sc(sa + 32)
        table = _u64sc(sa + 40)
        smalltable = sa + 64
        mask_ok = mask in _POW2_MINUS_1
        sizes_ok = (used <= fill <= mask) if mask_ok else False
        table_ok = (
            table == smalltable
            or 0x100_000_000 <= table < 0x10_000_000_000
        )
        if not (mask_ok and sizes_ok and table_ok):
            weird_sets.append((sa, rc, fill, used, mask, table, smalltable))
    print("[gen2-bisect] sets with broken body invariants: %d"
          % len(weird_sets), file=sys.stderr)
    for (sa, rc, fill, used, mask, table, smalltable) in weird_sets[:5]:
        print("[gen2-bisect]   weird-set addr=0x%x refcnt=%d "
              "fill=%d used=%d mask=0x%x table=0x%x smalltable=0x%x"
              % (sa, rc, fill, used, mask, table, smalltable),
              file=sys.stderr)
    # Sanity: dump first/last 5 entries' types so we can see if the
    # walker is sane (real objects, not garbage memory).
    def _u64x(a):
        return ctypes.cast(a, ctypes.POINTER(ctypes.c_uint64))[0]
    for label, sample in [("first", addrs[:5]), ("last", addrs[-5:])]:
        for i, a in enumerate(sample):
            tp = _u64x(a + 8)
            nm = b""
            if tp:
                npr = _u64x(tp + 24)
                if 0x100_000_000 <= npr < 0x10_000_000_000:
                    nm = ctypes.string_at(npr, 64).split(b"\x00", 1)[0]
            print("[gen2-bisect]   %s[%d]: addr=0x%x refcnt=%d ob_type=0x%x tp_name=%r"
                  % (label, i, a, _u64x(a), tp,
                     nm.decode("ascii", "replace")), file=sys.stderr)
    # Scan for ALL objects with refcnt=0 OR _gc_prev=0 in the gen list
    # -- both are indicators of an object that should have been
    # deallocated/untracked but stayed in gc-list.
    refcnt_zero = []
    gp_zero = []
    for a in addrs:
        if _u64x(a) == 0:
            refcnt_zero.append(a)
        if _u64x(a - 8) == 0:  # _gc_prev field
            gp_zero.append(a)
    print("[gen2-bisect] objects with refcnt=0 still in gc-list: %d"
          % len(refcnt_zero), file=sys.stderr)
    print("[gen2-bisect] objects with _gc_prev=0 still in gc-list: %d"
          % len(gp_zero), file=sys.stderr)
    for label, suspects in [("refcnt=0", refcnt_zero),
                            ("_gc_prev=0", gp_zero)]:
        for i, a in enumerate(suspects[:10]):
            tp = _u64x(a + 8)
            nm = b""
            if tp:
                npr = _u64x(tp + 24)
                if 0x100_000_000 <= npr < 0x10_000_000_000:
                    nm = ctypes.string_at(
                        npr, 64).split(b"\x00", 1)[0]
            rc = _u64x(a)
            gp = _u64x(a - 8)
            print("[gen2-bisect]   %s[%d]: addr=0x%x rc=%d type=%r "
                  "_gc_prev=0x%x"
                  % (label, i, a, rc, nm.decode("ascii", "replace"), gp),
                  file=sys.stderr)
    # Reconstruct Python object refs from addresses.  ctypes
    # ``py_object`` cast reads the PyObject* at the address (treating
    # the address-int as a value of type ``void*`` then casting).  We
    # need actual object handles to pass to gc.get_referents in the
    # child.  Note: this does NOT INCREF -- the parent's heap already
    # holds them via the gc list itself.
    all_objs = []
    for a in addrs:
        try:
            all_objs.append(ctypes.cast(a, ctypes.py_object).value)
        except (ValueError, OSError):
            pass
    print("[gen2-bisect] reconstructed %d object refs from addresses"
          % len(all_objs), file=sys.stderr, flush=True)
    if not all_objs:
        return
    # Probe 0: walk the linked list bidirectionally and check the
    # doubly-linked invariant.  For each obj at head h, verify
    # ``u64(h) == h_next`` AND ``u64(h_next + 8) == h`` (h_next's
    # _gc_prev should point back to h).  Any break is the bug.
    print("[gen2-bisect] checking doubly-linked invariants in gen0...",
          file=sys.stderr, flush=True)
    HEAD_SIZE = 16
    PTR_MASK = ~0xF
    def _u64v(a):
        return ctypes.cast(a, ctypes.POINTER(ctypes.c_uint64))[0]
    bad_links = []
    for a in addrs:
        head = a - HEAD_SIZE
        nxt = _u64v(head) & PTR_MASK
        if nxt == 0 or (nxt & 0x7):
            bad_links.append((head, "nxt invalid 0x%x" % nxt))
            continue
        # nxt is the NEXT object's PyGC_Head address.  nxt's _gc_prev
        # should equal head (modulo low-bit flags).
        nxt_prev = _u64v(nxt + 8) & PTR_MASK
        if nxt_prev != head:
            bad_links.append((head,
                              "nxt(0x%x)._gc_prev=0x%x but expected 0x%x"
                              % (nxt, nxt_prev, head)))
    print("[gen2-bisect] doubly-linked invariant breaks: %d"
          % len(bad_links), file=sys.stderr)
    for head, msg in bad_links[:10]:
        # Decode the obj at this head.
        obj = head + HEAD_SIZE
        rc = _u64v(obj)
        tp = _u64v(obj + 8)
        nm = b""
        if tp:
            npr = _u64v(tp + 24)
            if 0x100_000_000 <= npr < 0x10_000_000_000:
                nm = ctypes.string_at(npr, 64).split(b"\x00", 1)[0]
        # Is this a host object or interp-managed?  Host types live in
        # the host Python binary (low addresses); interp types live in
        # our _malloc'd memory.
        is_host_dict = (tp == id(dict))
        is_host_set = (tp == id(set))
        is_host_list = (tp == id(list))
        is_host_tuple = (tp == id(tuple))
        host_str = ""
        if is_host_dict: host_str = " HOST dict"
        elif is_host_set: host_str = " HOST set"
        elif is_host_list: host_str = " HOST list"
        elif is_host_tuple: host_str = " HOST tuple"
        print("[gen2-bisect]   broken-link head=0x%x obj=0x%x rc=%d "
              "type=%r%s: %s"
              % (head, obj, rc, nm.decode("ascii", "replace"),
                 host_str, msg),
              file=sys.stderr)
        # Try to identify the dict's content: dict basic layout
        # (CPython 3.7): ob_refcnt (8) ob_type (8) ma_used (8)
        # ma_version_tag (8) ma_keys (8) ma_values (8).  Read ma_used.
        if is_host_dict:
            ma_used = _u64v(obj + 16)
            print("[gen2-bisect]     ma_used=%d (dict size at break time)"
                  % ma_used, file=sys.stderr)
        # Also try to find what's in interp.mallocs or any other ref
        # to this address.
        interp = _gen2_bisect_interp
        if interp is not None and hasattr(interp, "mallocs"):
            for _base, _buf in interp.mallocs.items():
                try:
                    _sz = ctypes.sizeof(_buf)
                except (TypeError, OSError):
                    continue
                if _base <= obj < _base + _sz:
                    print("[gen2-bisect]     in interp.mallocs at base=0x%x "
                          "offset=%d" % (_base, obj - _base),
                          file=sys.stderr)
                    break
    # Probe 1: does an explicit gc.collect() (mirroring what host
    # shutdown does) trigger the bug?  This walks the gen linked
    # list, different code path than get_referents/tp_traverse.
    print("[gen2-bisect] explicitly calling gc.collect()...",
          file=sys.stderr, flush=True)
    crashed_in_collect = _fork_call_gc_collect()
    if crashed_in_collect:
        print("[gen2-bisect] gc.collect() CRASHES -- bug IS in gen-list "
              "walk machinery", file=sys.stderr)
    else:
        print("[gen2-bisect] gc.collect() did NOT crash",
              file=sys.stderr)
    # Probe 2: does the whole-set traverse crash?  If not, the bug
    # is in the gen-list walk machinery, not any single object.
    crashed = _fork_traverse_subset(all_objs, 0, len(all_objs))
    if not crashed:
        print("[gen2-bisect] FULL set did NOT crash in get_referents."
              " Bug is likely in gen-list-walk machinery, not in any"
              " single object's tp_traverse.", file=sys.stderr)
        return
    print("[gen2-bisect] FULL set crashes -- bisecting...",
          file=sys.stderr, flush=True)
    idx = _bisect_traverse(all_objs)
    if idx is None:
        print("[gen2-bisect] bisect failed to narrow down", file=sys.stderr)
        return
    bad = all_objs[idx]
    print("[gen2-bisect] *** BAD OBJ: idx=%d addr=0x%x type=%s ***"
          % (idx, id(bad), type(bad).__name__),
          file=sys.stderr, flush=True)
    # Hypothesis: leaker's body holds garbage because the slot was
    # previously used as one of our interp's _malloc'd buffers,
    # then freed and given back to pymalloc which reused it for a
    # host set without zeroing.  Check the overlap.
    bad_addr_val = id(bad)
    overlap = None
    interp = _gen2_bisect_interp
    if interp is not None and hasattr(interp, "mallocs"):
        for _base, _buf in interp.mallocs.items():
            try:
                _sz = ctypes.sizeof(_buf)
            except (TypeError, OSError):
                continue
            if _base <= bad_addr_val < _base + _sz:
                overlap = (_base, _sz)
                break
    if overlap is not None:
        print("[gen2-bisect]   bad set address IS INSIDE interp.mallocs "
              "buffer: base=0x%x size=%d offset=%d  *** PYMALLOC/INTERP "
              "MEMORY COLLISION ***"
              % (overlap[0], overlap[1], bad_addr_val - overlap[0]),
              file=sys.stderr)
    else:
        print("[gen2-bisect]   bad set address NOT in any interp.mallocs "
              "buffer (so the garbage body isn't our interp's data)",
              file=sys.stderr)
    # Was this set created BEFORE runFunc (pre-existing host machinery)
    # or DURING runFunc (created by interp activity)?
    if bad_addr_val in _gen2_bisect_pre_set_ids:
        print("[gen2-bisect]   bad set existed BEFORE runFunc -- it's a "
              "pre-existing host set whose body got clobbered during runFunc",
              file=sys.stderr)
    else:
        print("[gen2-bisect]   bad set was created DURING runFunc -- "
              "leak happened via interp activity",
              file=sys.stderr)
    # Is the bad set's ob_type the HOST `set` type (= same as `id(set)`)?
    # If yes: this is a HOST python set, leaked by something our interp
    # does to host objects.  If no: it's an interp-built set type,
    # leaked by interpreted CPython source.
    def _u64x_typecheck(a):
        return ctypes.cast(a, ctypes.POINTER(ctypes.c_uint64))[0]
    bad_ob_type = _u64x_typecheck(id(bad) + 8)
    host_set_id = id(set)
    host_frozenset_id = id(frozenset)
    if bad_ob_type == host_set_id:
        print("[gen2-bisect]   bad obj's ob_type == HOST set type "
              "(0x%x).  Leak is in HOST Python." % bad_ob_type,
              file=sys.stderr)
    elif bad_ob_type == host_frozenset_id:
        print("[gen2-bisect]   bad obj's ob_type == HOST frozenset type "
              "(0x%x).  Leak is in HOST Python." % bad_ob_type,
              file=sys.stderr)
    else:
        print("[gen2-bisect]   bad obj's ob_type=0x%x is NOT host "
              "set/frozenset (host set=0x%x, frozenset=0x%x). Probably "
              "an interp-built set type."
              % (bad_ob_type, host_set_id, host_frozenset_id),
              file=sys.stderr)
    _dump_pygc_head_forensics(id(bad))
    # Dump neighbors in the linked list (idx-5 .. idx+5) -- temporally
    # adjacent allocations, may hint at what code was running when the
    # leaked set was created.
    print("[gen2-bisect] neighbors in gen0 list (by walk order):",
          file=sys.stderr)
    def _u64x2(a):
        return ctypes.cast(a, ctypes.POINTER(ctypes.c_uint64))[0]
    lo_n = max(0, idx - 5)
    hi_n = min(len(addrs), idx + 6)
    for j in range(lo_n, hi_n):
        a = addrs[j]
        tp = _u64x2(a + 8)
        nm = b""
        if tp:
            npr = _u64x2(tp + 24)
            if 0x100_000_000 <= npr < 0x10_000_000_000:
                nm = ctypes.string_at(npr, 64).split(b"\x00", 1)[0]
        marker = "  <-- BAD" if j == idx else ""
        rc = _u64x2(a)
        gp = _u64x2(a - 16 + 8)
        print("[gen2-bisect]   [%d] addr=0x%x refcnt=%d type=%r _gc_prev=0x%x%s"
              % (j, a, rc, nm.decode("ascii", "replace"), gp, marker),
              file=sys.stderr)


def _walk_gen_via_pygc_head():
    """Walk Python's gc-tracked-object linked list via raw PyGC_Head
    pointer reads.  Returns a list of object addresses (=id of obj).

    PyGC_Head layout (Python 3.13): 16 bytes -- ``uintptr_t _gc_next,
    _gc_prev``.  Object body starts at head + 16.  The list is
    circular with a sentinel head whose body is not a real PyObject.

    With ``gc.disable()`` in effect, every gc-tracked obj lives in
    the same young-gen list (no promotion happens).  We anchor on a
    locally-created list ``anchor = []`` (gc-tracked dict/list/etc.
    work; ``type`` does NOT because builtin types are statically
    allocated and not in the gc list).  Walk forward via ``_gc_next``
    until we cycle.

    Filtering: the gen-list contains a sentinel PyGC_Head whose
    object body is not a real PyObject.  We skip entries whose
    ``ob_refcnt`` looks implausible (must be > 0 and < 2^32).
    """
    HEAD_SIZE = 16
    PTR_MASK = ~0xF  # _gc_prev encodes flags in low 4 bits
    def u64(addr):
        return ctypes.cast(addr, ctypes.POINTER(ctypes.c_uint64))[0]
    anchor = []  # gc-tracked container
    anchor_head = id(anchor) - HEAD_SIZE
    anchor_next = u64(anchor_head) & PTR_MASK
    anchor_prev = u64(anchor_head + 8) & PTR_MASK
    print("[gen2-bisect] anchor PyGC_Head 0x%x: _gc_next=0x%x _gc_prev=0x%x"
          % (anchor_head, anchor_next, anchor_prev), file=sys.stderr)
    addrs = []
    seen = {anchor_head}
    cur = anchor_next  # _gc_next
    MAX = 50_000_000
    for _ in range(MAX):
        if cur == 0 or (cur & 0x7):
            break
        if cur in seen:
            break
        seen.add(cur)
        rc = u64(cur + HEAD_SIZE)
        tp = u64(cur + HEAD_SIZE + 8)
        # Filter unfilterable garbage but accept refcnt=0 -- a refcnt=0
        # object still in the gc list IS what we want to find.
        if rc < (1 << 32) and tp != 0:
            addrs.append(cur + HEAD_SIZE)
        nxt = u64(cur) & PTR_MASK
        cur = nxt
    return addrs


def _fork_call_gc_collect():
    """Fork a child, re-enable gc, call gc.collect().  Returns True
    if the child died from a crash (signal or _exit 134/138/139)."""
    import gc as _gc
    pid = os.fork()
    if pid == 0:
        _gc.enable()
        _gc.collect()
        os._exit(0)
    _pid, status = os.waitpid(pid, 0)
    if os.WIFSIGNALED(status):
        return True
    if os.WEXITSTATUS(status) in (134, 138, 139):
        return True
    return False


def _fork_traverse_subset(all_objs, lo, hi):
    """Fork a child that calls gc.get_referents() on every object in
    ``all_objs[lo:hi]``.  Return True iff the child died abnormally
    (segfault / signal).

    Uses os.fork() so the child inherits the heap state exactly.
    """
    import gc as _gc
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        # Child.
        os.close(r)
        try:
            for i in range(lo, hi):
                _gc.get_referents(all_objs[i])
            os.write(w, b"OK")
            os._exit(0)
        except BaseException as e:
            try:
                os.write(w, ("EX:%s" % type(e).__name__).encode())
            except OSError:
                pass
            os._exit(2)
    # Parent.
    os.close(w)
    _pid, status = os.waitpid(pid, 0)
    try:
        msg = os.read(r, 64)
    except OSError:
        msg = b""
    os.close(r)
    # Crashed = signal death (WIFSIGNALED) -- OR -- exit code 139
    # (128+SIGSEGV), which is what our --quiet-crash handler uses
    # when it intercepts a SIGSEGV in the child and calls _exit().
    # Also 134 (128+SIGABRT) and 138 (128+SIGBUS) for completeness.
    if os.WIFSIGNALED(status):
        return True
    if os.WEXITSTATUS(status) in (134, 138, 139):
        return True
    if os.WEXITSTATUS(status) == 0 and msg == b"OK":
        return False
    # Exception in child -- not a memory crash but still a failure
    # mode worth reporting.
    print("[gen2-bisect] child non-segv failure: status=%d msg=%r"
          % (status, msg), file=sys.stderr)
    return False


def _bisect_traverse(all_objs):
    """Binary-search the bad obj index by halving and fork-testing.
    Returns the offending index in ``all_objs``, or None if narrowing
    failed.
    """
    lo, hi = 0, len(all_objs)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        print("[gen2-bisect] testing left [%d:%d] (%d items)..."
              % (lo, mid, mid - lo), file=sys.stderr, flush=True)
        if _fork_traverse_subset(all_objs, lo, mid):
            hi = mid
            continue
        print("[gen2-bisect] testing right [%d:%d] (%d items)..."
              % (mid, hi, hi - mid), file=sys.stderr, flush=True)
        if _fork_traverse_subset(all_objs, mid, hi):
            lo = mid
            continue
        print("[gen2-bisect] neither half crashes at lo=%d hi=%d mid=%d"
              % (lo, hi, mid), file=sys.stderr)
        return None
    if hi - lo == 1:
        return lo
    return None


def _dump_pygc_head_forensics(obj_addr):
    """Dump PyGC_Head + PyObject_HEAD + tp_name + (if set) elements
    for forensic logging.  All reads go through ctypes raw memory,
    bypassing tp_traverse which is the crashing path.
    """
    def u64(a):
        return ctypes.cast(a, ctypes.POINTER(ctypes.c_uint64))[0]
    head = obj_addr - 16
    _next = u64(head)
    _prev = u64(head + 8)
    rc = u64(obj_addr)
    tp = u64(obj_addr + 8)
    name_ptr = u64(tp + 24) if tp else 0
    name = b""
    if 0x100_000_000 <= name_ptr < 0x10_000_000_000:
        name = ctypes.string_at(name_ptr, 64).split(b"\x00", 1)[0]
    print("[gen2-bisect]   PyGC_Head 0x%x: _gc_next=0x%x _gc_prev=0x%x"
          % (head, _next, _prev), file=sys.stderr)
    print("[gen2-bisect]   PyObject  0x%x: refcnt=%d ob_type=0x%x tp_name=%r"
          % (obj_addr, rc, tp, name.decode("ascii", "replace")),
          file=sys.stderr)
    # If it's a set/frozenset, dump PySetObject internals: fill,
    # used, mask, table pointer.  PySetObject layout (Python 3.13):
    #   ob_refcnt (8), ob_type (8),             // 0..16   (PyObject_HEAD)
    #   fill (8),       used (8),               // 16..32
    #   mask (8),       table (8 ptr),          // 32..48
    #   hash (8),       finger (8),             // 48..64
    #   smalltable[8] (each entry = hash + key = 16 bytes -> 128 bytes),
    #   weakreflist (8 ptr).
    if name in (b"set", b"frozenset"):
        fill = u64(obj_addr + 16)
        used = u64(obj_addr + 24)
        mask = u64(obj_addr + 32)
        table = u64(obj_addr + 40)
        weaklist = u64(obj_addr + 16 + 64 + 128)  # rough; layout may shift
        print("[gen2-bisect]   PySet: fill=%d used=%d mask=0x%x table=0x%x"
              % (fill, used, mask, table), file=sys.stderr)
        # Walk table for (hash, key) entries.  Sanity-check table
        # addr and used/mask before iterating -- the body is likely
        # corrupt (the bug), so unchecked reads here will segfault.
        TABLE_OK = (
            0x100_000_000 <= table < 0x10_000_000_000
            and 0 < used < 1024 and 0 < mask < 4096
        )
        if not TABLE_OK:
            print("[gen2-bisect]   PySet body fields look corrupt -- "
                  "skipping entry walk (table/used/mask out of plausible "
                  "range)", file=sys.stderr)
            return
        if table and used > 0:
            print("[gen2-bisect]   PySet entries (up to mask+1=%d slots):"
                  % (mask + 1), file=sys.stderr)
            shown = 0
            for i in range(min(mask + 1, 64)):
                ent = table + i * 16
                ehash = u64(ent)
                ekey = u64(ent + 8)
                if ekey == 0 or ekey == 1:  # NULL=empty, 1=dummy in CPython
                    continue
                # Read key's refcnt and ob_type defensively.
                ek_rc = ek_tp = ek_tn = 0
                ek_name = b""
                if 0x100_000_000 <= ekey < 0x10_000_000_000:
                    ek_rc = u64(ekey)
                    ek_tp = u64(ekey + 8)
                    if ek_tp:
                        ek_tn = u64(ek_tp + 24)
                        if 0x100_000_000 <= ek_tn < 0x10_000_000_000:
                            ek_name = ctypes.string_at(
                                ek_tn, 64).split(b"\x00", 1)[0]
                print("[gen2-bisect]     slot[%d]: hash=0x%x key=0x%x "
                      "key.refcnt=%d key.type=0x%x key.tp_name=%r"
                      % (i, ehash, ekey, ek_rc, ek_tp,
                         ek_name.decode("ascii", "replace")),
                      file=sys.stderr)
                shown += 1
                if shown >= 12:
                    print("[gen2-bisect]     ... (more slots truncated)",
                          file=sys.stderr)
                    break


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
