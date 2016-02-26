#!/usr/bin/env python
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

import better_exchook
better_exchook.install()

import sys, os, os.path
if __name__ == '__main__':
	MyDir = os.path.dirname(sys.argv[0])
else:
	MyDir = "."

CPythonDir = MyDir + "/CPython"

import cparser
import cparser.interpreter
import argparse

class CPythonState(cparser.State):

	def __init__(self):
		super(CPythonState, self).__init__()
		self.autoSetupSystemMacros()
		self.autoSetupGlobalIncludeWrappers()

	def findIncludeFullFilename(self, filename, local):
		fullfn = CPythonDir + "/Include/" + filename
		if os.path.exists(fullfn): return fullfn
		return super(CPythonState, self).findIncludeFullFilename(filename, local)

	def readLocalInclude(self, filename):
		#print " ", filename, "..."
		if filename == "pyconfig.h":
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
				self.macros["SIZEOF_UINTPTR_T"] = sizeofMacro(ctypes.POINTER(ctypes.c_uint))
				self.macros["SIZEOF_PTHREAD_T"] = self.macros["SIZEOF_LONG"]
				self.macros["SIZEOF_PID_T"] = self.macros["SIZEOF_INT"]
				self.macros["SIZEOF_TIME_T"] = self.macros["SIZEOF_LONG"]
				self.macros["SIZEOF__BOOL"] = cparser.Macro(rightside="1")
				self.macros["HAVE_SIGNAL_H"] = cparser.Macro(rightside="1")
				self.macros["HAVE_STDARG_PROTOTYPES"] = cparser.Macro(rightside="1")
				# _GNU_SOURCE, _POSIX_C_SOURCE or so?
				return
				yield None # make it a generator
			return reader(), None
		return super(CPythonState, self).readLocalInclude(filename)

	def parse_cpython(self):
		# We keep all in the same state, i.e. the same static space.
		# This also means that we don't reset macro definitions. This speeds up header includes.
		# Usually this is not a problem.
		cparser.parse(CPythonDir + "/Modules/main.c", self) # Py_Main
		self.macros["FAST_LOOPS"] = cparser.Macro(rightside="0")  # not sure where this would come from
		cparser.parse(CPythonDir + "/Python/ceval.c", self) # PyEval_EvalFrameEx etc
		del self.macros["EMPTY"]  # will be redefined later
		cparser.parse(CPythonDir + "/Python/getopt.c", self) # _PyOS_GetOpt
		cparser.parse(CPythonDir + "/Python/pythonrun.c", self) # Py_Initialize
		cparser.parse(CPythonDir + "/Python/pystate.c", self) # PyInterpreterState_New
		cparser.parse(CPythonDir + "/Python/sysmodule.c", self) # PySys_ResetWarnOptions
		cparser.parse(CPythonDir + "/Python/random.c", self) # _PyRandom_Init
		cparser.parse(CPythonDir + "/Objects/object.c", self) # _Py_ReadyTypes etc
		cparser.parse(CPythonDir + "/Objects/typeobject.c", self) # PyType_Ready
		cparser.parse(CPythonDir + "/Objects/tupleobject.c", self) # PyTuple_New
		del self.macros["Return"]  # will be used differently
		# We need these macro hacks because dictobject.c will use the same vars.
		self.macros["length_hint_doc"] = cparser.Macro(rightside="length_hint_doc__dict")
		self.macros["numfree"] = cparser.Macro(rightside="numfree__dict")
		self.macros["free_list"] = cparser.Macro(rightside="free_list__dict")
		cparser.parse(CPythonDir + "/Objects/dictobject.c", self)  # PyDict_New
		# We need this macro hack because stringobject.c will use the same var.
		self.macros["sizeof__doc__"] = cparser.Macro(rightside="sizeof__doc__str")
		cparser.parse(CPythonDir + "/Objects/stringobject.c", self)  # PyString_FromString
		cparser.parse(CPythonDir + "/Objects/obmalloc.c", self) # PyObject_Free
		cparser.parse(CPythonDir + "/Modules/gcmodule.c", self) # _PyObject_GC_NewVar
		cparser.parse(CPythonDir + "/Objects/descrobject.c", self) # PyDescr_NewWrapper
		# We need these macro hacks because methodobject.c will use the same vars.
		self.macros["numfree"] = cparser.Macro(rightside="numfree__methodobj")
		self.macros["free_list"] = cparser.Macro(rightside="free_list__methodobj")
		cparser.parse(CPythonDir + "/Objects/methodobject.c", self) # PyCFunction_NewEx
		# We need these macro hacks because methodobject.c will use the same vars.
		self.macros["numfree"] = cparser.Macro(rightside="numfree__list")
		self.macros["free_list"] = cparser.Macro(rightside="free_list__list")
		self.macros["sizeof_doc"] = cparser.Macro(rightside="sizeof_doc__list")
		self.macros["length_hint_doc"] = cparser.Macro(rightside="length_hint_doc__list")
		self.macros["index_doc"] = cparser.Macro(rightside="index_doc__list")
		self.macros["count_doc"] = cparser.Macro(rightside="count__list")
		cparser.parse(CPythonDir + "/Objects/listobject.c", self) # PyList_New
		cparser.parse(CPythonDir + "/Objects/abstract.c", self) # PySequence_List
		cparser.parse(CPythonDir + "/Python/modsupport.c", self) # Py_BuildValue


def init_faulthandler(sigusr1_chain=False):
	"""
	:param bool sigusr1_chain: whether the default SIGUSR1 handler should also be called.
	"""
	try:
		import faulthandler
	except ImportError, e:
		print "faulthandler import error. %s" % e
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
	if os.name == "nt": return
	def sigusr1_handler(sig, frame):
		print "--- SIGUSR1 handler"
		better_exchook.print_tb(tb=frame)
	import signal
	signal.signal(signal.SIGUSR1, sigusr1_handler)


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
	argparser.add_argument(
		'--verbose-jit', action='store_true',
		help="Prints what functions and global vars we are going to translate.")
	args_ns, argv_rest = argparser.parse_known_args(argv[1:])
	argv = argv[:1] + argv_rest
	print "PyCPython -", argparser.description,
	print "(use --pycpython-help for help)"

	state = CPythonState()

	print "Parsing CPython...",
	state.parse_cpython()

	if state._errors:
		print "finished, parse errors:"
		for m in state._errors:
			print m
	else:
		print "finished, no parse errors."

	interpreter = cparser.interpreter.Interpreter()
	interpreter.register(state)

	if args_ns.dump_python:
		for fn in args_ns.dump_python:
			print
			print "PyAST of %s:" % fn
			interpreter.dumpFunc(fn)
		sys.exit()

	if args_ns.verbose_jit:
		interpreter.debug_print_getFunc = True
		interpreter.debug_print_getVar = True

	args = ("Py_Main", len(argv), argv + [None])
	print "Run", args, ":"
	interpreter.runFunc(*args)


if __name__ == '__main__':
	register_sigusr1_print_backtrace()
	init_faulthandler(sigusr1_chain=True)
	main(sys.argv)