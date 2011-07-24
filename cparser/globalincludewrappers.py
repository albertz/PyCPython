# PyCParser - global include wrappers
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from interpreter import CWrapValue
import ctypes
import errno, os

def _fixCType(t):
	if t is ctypes.c_char_p: t = ctypes.POINTER(ctypes.c_char)
	return wrapCTypeClassIfNeeded(t)

def wrapCFunc(state, funcname, restype=None, argtypes=None):
	f = getattr(ctypes.pythonapi, funcname)
	if restype is None: restype = ctypes.c_int
	if restype is CVoidType:
		f.restype = None
	elif restype is not None:
		f.restype = _fixCType(restype)
	if argtypes is not None:
		f.argtypes = map(_fixCType, argtypes)
	state.funcs[funcname] = CWrapValue(f, funcname=funcname, returnType=restype)
	
class Wrapper:
	def handle_limits_h(self, state):
		state.macros["UCHAR_MAX"] = Macro(rightside="255")
	def handle_stdio_h(self, state):
		state.macros["NULL"] = Macro(rightside="0")
		wrapCFunc(state, "printf", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,))
		FileP = CPointerType(CStdIntType("FILE")).getCType(state)
		wrapCFunc(state, "fopen", restype=FileP, argtypes=(ctypes.c_char_p, ctypes.c_char_p))
		wrapCFunc(state, "fclose", restype=ctypes.c_int, argtypes=(FileP,))
		wrapCFunc(state, "fdopen", restype=FileP, argtypes=(ctypes.c_int, ctypes.c_char_p))
		state.vars["stdin"] = CWrapValue(ctypes.pythonapi.fdopen(0, "r"))
		state.vars["stdout"] = CWrapValue(ctypes.pythonapi.fdopen(1, "a"))
		state.vars["stderr"] = CWrapValue(ctypes.pythonapi.fdopen(2, "a"))
		wrapCFunc(state, "fprintf", restype=ctypes.c_int, argtypes=(FileP, ctypes.c_char_p))
		wrapCFunc(state, "fputs", restype=ctypes.c_int, argtypes=(ctypes.c_char_p, FileP))
		state.vars["errno"] = CWrapValue(0) # TODO
		state.macros["EOF"] = Macro(rightside="-1") # TODO?
		wrapCFunc(state, "setbuf", restype=CVoidType, argtypes=(FileP, ctypes.c_char_p))
		wrapCFunc(state, "isatty", restype=ctypes.c_int, argtypes=(ctypes.c_int,))
		wrapCFunc(state, "fileno")
		wrapCFunc(state, "getc")
		wrapCFunc(state, "ungetc", restype=ctypes.c_int, argtypes=(ctypes.c_int,FileP))
		struct_stat = state.structs["stat"] = CStruct(name="stat") # TODO
		struct_stat.body = CBody(parent=struct_stat)
		CVarDecl(parent=struct_stat, name="st_mode", type=ctypes.c_int).finalize(state)
		state.funcs["fstat"] = CWrapValue(lambda *args: None, returnType=CVoidType()) # TODO
		state.macros["S_IFMT"] = Macro(rightside="0") # TODO
		state.macros["S_IFDIR"] = Macro(rightside="0") # TODO
	def handle_stdlib_h(self, state):
		wrapCFunc(state, "malloc")
		wrapCFunc(state, "free")
		state.funcs["getenv"] = CWrapValue(
			lambda x: ctypes.c_char_p(os.getenv(ctypes.cast(x, ctypes.c_char_p).value)),
			returnType=CPointerType(ctypes.c_char))
	def handle_stdarg_h(self, state): pass
	def handle_math_h(self, state): pass
	def handle_string_h(self, state):
		wrapCFunc(state, "strlen")
		wrapCFunc(state, "strcpy")
		wrapCFunc(state, "strcat")
		wrapCFunc(state, "strcmp", restype=ctypes.c_int, argtypes=(ctypes.c_char_p,ctypes.c_char_p))
		wrapCFunc(state, "strtok")
		wrapCFunc(state, "strchr")
		wrapCFunc(state, "strerror")
	def handle_time_h(self, state): pass
	def handle_ctype_h(self, state): pass
	def handle_wctype_h(self, state): pass
	def handle_assert_h(self, state): pass

	def find_handler_func(self, filename):
		funcname = "handle_" + filename.replace("/", "__").replace(".", "_")
		return getattr(self, funcname, None)
		
	def readGlobalInclude(self, state, oldFunc, filename):
		f = self.find_handler_func(filename)
		if f is not None:
			def reader():
				f(state)
				return
				yield None # to make it a generator
			return reader(), None
		return oldFunc(filename) # fallback
	
	def install(self, state):
		oldFunc = state.readGlobalInclude
		state.readGlobalInclude = lambda fn: self.readGlobalInclude(state, oldFunc, fn)
		