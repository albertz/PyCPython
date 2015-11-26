#!/usr/bin/env python
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under GPL

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

def prepareState():
	state = cparser.State()
	state.autoSetupSystemMacros()
	
	def findIncludeFullFilename(filename, local):
		fullfn = CPythonDir + "/Include/" + filename
		if os.path.exists(fullfn): return fullfn
		return filename
	
	state.findIncludeFullFilename = findIncludeFullFilename
	
	def readLocalInclude(state, filename):
		#print " ", filename, "..."
		if filename == "pyconfig.h":
			def reader():
				# see CPython/pyconfig.h.in for reference
				import ctypes
				sizeofMacro = lambda t: cparser.Macro(rightside=str(ctypes.sizeof(t)))
				state.macros["SIZEOF_SHORT"] = sizeofMacro(ctypes.c_short)
				state.macros["SIZEOF_INT"] = sizeofMacro(ctypes.c_int)
				state.macros["SIZEOF_LONG"] = sizeofMacro(ctypes.c_long)
				state.macros["SIZEOF_LONG_LONG"] = sizeofMacro(ctypes.c_longlong)
				state.macros["SIZEOF_DOUBLE"] = sizeofMacro(ctypes.c_double)
				state.macros["SIZEOF_FLOAT"] = sizeofMacro(ctypes.c_float)
				state.macros["SIZEOF_VOID_P"] = sizeofMacro(ctypes.c_void_p)
				state.macros["SIZEOF_SIZE_T"] = sizeofMacro(ctypes.c_size_t)
				state.macros["SIZEOF_UINTPTR_T"] = sizeofMacro(ctypes.POINTER(ctypes.c_uint))
				state.macros["SIZEOF_PTHREAD_T"] = state.macros["SIZEOF_LONG"]
				state.macros["SIZEOF_PID_T"] = state.macros["SIZEOF_INT"]
				state.macros["SIZEOF_TIME_T"] = state.macros["SIZEOF_LONG"]
				state.macros["SIZEOF__BOOL"] = cparser.Macro(rightside="1")
				state.macros["HAVE_SIGNAL_H"] = cparser.Macro(rightside="1")
				# _GNU_SOURCE, _POSIX_C_SOURCE or so?
				return
				yield None # make it a generator
			return reader(), None
		return cparser.State.readLocalInclude(state, filename)
	
	state.readLocalInclude = lambda fn: readLocalInclude(state, fn)
	
	state.autoSetupGlobalIncludeWrappers()
	
	return state


def main(argv):
	state = prepareState()

	print "parsing..."
	# We keep all in the same state, i.e. the same static space.
	# This also means that we don't reset macro definitions. This speeds up header includes.
	# Usually this is not a problem.
	cparser.parse(CPythonDir + "/Modules/main.c", state) # Py_Main
	state.macros["FAST_LOOPS"] = cparser.Macro(rightside="0")  # not sure where this would come from
	cparser.parse(CPythonDir + "/Python/ceval.c", state) # PyEval_EvalFrameEx etc
	del state.macros["EMPTY"]  # will be redefined later
	cparser.parse(CPythonDir + "/Python/getopt.c", state) # _PyOS_GetOpt
	cparser.parse(CPythonDir + "/Python/pythonrun.c", state) # Py_Initialize
	cparser.parse(CPythonDir + "/Python/pystate.c", state) # PyInterpreterState_New
	cparser.parse(CPythonDir + "/Python/sysmodule.c", state) # PySys_ResetWarnOptions
	cparser.parse(CPythonDir + "/Python/random.c", state) # _PyRandom_Init
	cparser.parse(CPythonDir + "/Objects/object.c", state) # _Py_ReadyTypes etc
	cparser.parse(CPythonDir + "/Objects/typeobject.c", state) # PyType_Ready
	cparser.parse(CPythonDir + "/Include/structmember.h", state) # struct PyMemberDef. just for now to avoid errors :)

	if state._errors:
		print "parse errors:"
		for m in state._errors:
			print m
	else:
		print "no parse errors"

	interpreter = cparser.interpreter.Interpreter()
	interpreter.register(state)


	print
	print "PyAST of Py_Main:"
	interpreter.dumpFunc("Py_Main")

	args = ("Py_Main", len(argv), argv + [None])
	print "Run", args, ":"
	interpreter.runFunc(*args)


if __name__ == '__main__':
	main(sys.argv)