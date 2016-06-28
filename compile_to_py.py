#!/usr/bin/env python
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

import sys, os
import argparse
from cpython import CPythonState, MyDir
import cparser
import cparser.interpreter
from cparser.py_demo_unparse import Unparser
import time
import ast
import ctypes


# See State.CBuiltinTypes.
builtin_ctypes_name_map = {
("void", "*"): "c_void_p",
("char",): "c_byte",
("unsigned", "char"): "c_ubyte",
("short",): "c_short",
("unsigned", "short"): "c_ushort",
("int",): "c_int",
("signed",): "c_int",
("unsigned", "int"): "c_uint",
("unsigned",): "c_uint",
("long",): "c_long",
("unsigned", "long"): "c_ulong",
("long", "long"): "c_longlong",
("unsigned", "long", "long"): "c_ulonglong",
("float",): "c_float",
("double",): "c_double",
("long", "double"): "c_longdouble",
}

def builtin_ctypes_name(s):
	# See State.CBuiltinTypes.
	assert isinstance(s, tuple)
	t = builtin_ctypes_name_map[s]
	assert hasattr(ctypes, t)
	return t

def stdint_ctypes_name(s):
	# See State.StdIntTypes.
	assert isinstance(s, (str, unicode))
	if s in ["ptrdiff_t", "intptr_t"]:
		s = "c_long"
	elif s == "FILE":
		s = "c_int"
	else:
		s = "c_%s" % s.replace("_t", "")
	assert hasattr(ctypes, s)
	return s

def set_name_for_typedeffed_struct(obj, state):
	assert isinstance(obj, cparser.CTypedef)
	assert obj.name
	assert isinstance(state, cparser.State)
	if not isinstance(obj.type, (cparser.CStruct, cparser.CUnion)):
		return False
	if not obj.type.name:
		obj.type.name = "_anonymous_%s" % obj.name
		return True
	if isinstance(obj.type, cparser.CStruct):
		if obj.type.name in state.structs:
			return False
		# So that we will find it next time. Not sure why this can even happen.
		state.structs[obj.type.name] = obj.type
	elif isinstance(obj.type, cparser.CUnion):
		if obj.type.name in state.unions:
			return False
		# See above.
		state.unions[obj.type.name] = obj.type
	return True

def fix_name(obj):
	assert obj.name
	if obj.name.startswith("__"):
		obj.name = "_M_%s" % obj.name[2:]

def get_py_type(t, state):
	if isinstance(t, cparser.CTypedef):
		assert t.name, "typedef target typedef must have name"
		return t.name
	elif isinstance(t, cparser.CStruct):
		assert t.name, "struct must have name, should have been assigned earlier also to anonymous structs"
		return "structs.%s" % t.name
	elif isinstance(t, cparser.CUnion):
		assert t.name, "union must have name, should have been assigned earlier also to anonymous unions"
		return "unions.%s" % t.name
	elif isinstance(t, cparser.CBuiltinType):
		return "ctypes.%s" % builtin_ctypes_name(t.builtinType)
	elif isinstance(t, cparser.CStdIntType):
		return "ctypes.%s" % stdint_ctypes_name(t.name)
	elif isinstance(t, cparser.CEnum):
		int_type_name = t.getMinCIntType()
		return "ctypes.%s" % stdint_ctypes_name(int_type_name)
	elif isinstance(t, cparser.CPointerType):
		if cparser.isVoidPtrType(t):
			return "ctypes.c_void_p"
		else:
			return "ctypes.POINTER(%s)" % get_py_type(t.pointerOf, state)
	elif isinstance(t, cparser.CFuncPointerDecl):
		if isinstance(t.type, cparser.CPointerType):
			# https://bugs.python.org/issue5710
			restype = "ctypes.c_void_p"
		elif t.type == cparser.CBuiltinType(("void",)):
			restype = "None"
		else:
			restype = get_py_type(t.type, state)
		return "ctypes.CFUNCTYPE(%s)" % ", ".join([restype] + [get_py_type(a, state) for a in t.args])
	elif isinstance(t, cparser.CFuncArgDecl):
		return get_py_type(t.type, state)
	else:
		raise Exception("unexpected type: %s" % type(t))


def main(argv):
	state = CPythonState()

	out_fn = MyDir + "/cpython_static.py"
	print "Compile CPython to %s." % os.path.basename(out_fn)

	print "Parsing CPython...",
	try:
		state.parse_cpython()
	except Exception:
		print "!!! Exception while parsing. Should not happen. Cannot recover. Please report this bug."
		print "The parser currently is here:", state.curPosAsStr()
		raise
	if state._errors:
		print "finished, parse errors:"
		for m in state._errors:
			print m
	else:
		print "finished, no parse errors."

	interpreter = cparser.interpreter.Interpreter()
	interpreter.register(state)

	print "Compile..."
	f = open(out_fn, "w")
	f.write("#!/usr/bin/env python\n")
	f.write("# PyCPython - interpret CPython in Python\n")
	f.write("# Statically compiled CPython.\n\n")
	f.write("import sys\n")
	f.write("import better_exchook\n")
	f.write("import cparser\n")
	f.write("import cparser.interpreter\n")
	f.write("import ctypes\n")
	f.write("\n")
	f.write("better_exchook.install()\n")
	f.write("intp = cparser.interpreter.Interpreter()\n")
	f.write("intp.setupStatic()\n")
	f.write("helpers = intp.helpers\n")
	f.write("ctypes_wrapped = intp.ctypes_wrapped\n")
	f.write("\n\n")

	f.write("class structs:\n")
	last_log_time = time.time()
	for i, content in enumerate(state.contentlist):
		if time.time() - last_log_time > 2.0:
			last_log_time = time.time()
			perc_compl = 100.0 * i / len(state.contentlist)
			cur_content_s = "%s %s" % (content.__class__.__name__,
									   (getattr(content, "name", None) or "<noname>"))
			cur_file_s = getattr(content, "defPos", "<unknown source>")
			print "Compile structs... (%.0f%%) (%s) (%s)" % (perc_compl, cur_content_s, cur_file_s)
		if isinstance(content, cparser.CTypedef):
			if not set_name_for_typedeffed_struct(content, state):
				continue
			content = content.type
		if not isinstance(content, cparser.CStruct):
			continue
		if not content.name:
			content.name = "_anonymous_struct_%i" % i
		elif cparser.isExternDecl(content):
			content = state.getResolvedDecl(content)
			if cparser.isExternDecl(content):
				# Dummy placeholder.
				f.write("    %s = ctypes.c_int  # Dummy extern struct declaration\n" % content.name)
				continue
			else:
				# We have a full declaration available.
				continue  # we will write it later
		fix_name(content)
		# see _getCTypeStruct for reference
		# TODO. not simple.
		f.write("    class %s(ctypes.Structure): 'Dummy'\n" % content.name)  # Dummy for now
	f.write("\n\n")

	f.write("class unions:\n")
	for i, content in enumerate(state.contentlist):
		if time.time() - last_log_time > 2.0:
			last_log_time = time.time()
			perc_compl = 100.0 * i / len(state.contentlist)
			cur_content_s = "%s %s" % (content.__class__.__name__,
									   (getattr(content, "name", None) or "<noname>"))
			cur_file_s = getattr(content, "defPos", "<unknown source>")
			print "Compile unions... (%.0f%%) (%s) (%s)" % (perc_compl, cur_content_s, cur_file_s)
		if isinstance(content, cparser.CTypedef):
			if not set_name_for_typedeffed_struct(content, state):
				continue
			content = content.type
		if not isinstance(content, cparser.CUnion):
			continue
		if not content.name:
			content.name = "_anonymous_union_%i" % i
		elif cparser.isExternDecl(content):
			content = state.getResolvedDecl(content)
			if cparser.isExternDecl(content):
				# Dummy placeholder.
				f.write("    %s = ctypes.c_int  # Dummy extern union declaration\n" % content.name)
				continue
			else:
				# We have a full declaration available.
				continue  # we will write it later
		fix_name(content)
		# see _getCTypeStruct for reference
		# TODO. not simple. see above for structs
		f.write("    class %s(ctypes.Union): 'Dummy'\n" % content.name)  # Dummy for now
	f.write("\n\n")

	f.write("class g:\n")
	g_names = set()
	last_log_time = time.time()
	count = count_incomplete = 0
	for i, content in enumerate(state.contentlist):
		if time.time() - last_log_time > 2.0:
			last_log_time = time.time()
			perc_compl = 100.0 * i / len(state.contentlist)
			cur_content_s = "%s %s" % (content.__class__.__name__,
									   (getattr(content, "name", None) or "<noname>"))
			cur_file_s = getattr(content, "defPos", "<unknown source>")
			print "Compile... (%.0f%%) (%s) (%s)" % (perc_compl, cur_content_s, cur_file_s)
		if isinstance(content, (cparser.CStruct, cparser.CUnion)):
			continue  # Handled in the other loops.
		try:
			if cparser.isExternDecl(content):
				content = state.getResolvedDecl(content)
				if cparser.isExternDecl(content):
					# We will write some dummy placeholder.
					count_incomplete += 1
				else:
					# We have a full declaration available.
					continue  # we will write it later
			count += 1
			if content.name:
				fix_name(content)
				if content.name in g_names:
					print "Error (ignored): %r defined twice" % content.name
					continue
				g_names.add(content.name)
			else:
				continue
			if isinstance(content, cparser.CFunc):
				funcEnv = interpreter._translateFuncToPyAst(content, noBodyMode="code-with-exception")
				pyAst = funcEnv.astNode
				assert isinstance(pyAst, ast.FunctionDef)
				pyAst.decorator_list.append(ast.Name(id="staticmethod", ctx=ast.Load()))
				Unparser(pyAst, indent=1, file=f)
				f.write("\n")
			elif isinstance(content, (cparser.CStruct, cparser.CUnion)):
				pass  # Handled in the other loops.
			elif isinstance(content, cparser.CTypedef):
				f.write("    %s = %s\n" % (content.name, get_py_type(content.type, state)))
			elif isinstance(content, cparser.CVarDecl):
				f.write("    %s = 'Dummy vardecl'\n" % content.name)  # TODO
			elif isinstance(content, cparser.CEnum):
				int_type_name = content.getMinCIntType()
				f.write("    %s = ctypes.%s\n" % (content.name, stdint_ctypes_name(int_type_name)))
			else:
				raise Exception("unexpected content type: %s" % type(content))
		except Exception as exc:
			print "!!! Exception while compiling %r" % content
			if content.name:
				f.write("    %s = 'Compile exception ' %r\n" % (content.name, str(exc)))
			sys.excepthook(*sys.exc_info())
			# We continue...
	f.write("\n\n")

	f.write("class values:\n")
	def maybe_add_wrap_value(container_name, var_name, var):
		if not isinstance(var, cparser.CWrapValue): return
		v = cparser.interpreter.getAstForWrapValue(interpreter, var)
		assert isinstance(v, ast.Attribute)
		assert isinstance(v.value, ast.Name)
		assert v.value.id == "values"
		wrap_name = v.attr
		var2 = getattr(interpreter.wrappedValues, wrap_name, None)
		assert var2 is var
		f.write("    %s = intp.stateStructs[0].%s[%r]\n" % (wrap_name, container_name, var_name))
	# These are added by globalincludewrappers.
	for varname, var in sorted(state.vars.items()):
		maybe_add_wrap_value("vars", varname, var)
	for varname, var in sorted(state.funcs.items()):
		maybe_add_wrap_value("funcs", varname, var)
	f.write("\n\n")

	f.write("if __name__ == '__main__':\n")
	f.write("    g.Py_Main(ctypes_wrapped.c_int(len(sys.argv)),\n"
			"              (ctypes.POINTER(ctypes_wrapped.c_char) * (len(sys.argv) + 1))(\n"
			"               *[ctypes.cast(intp._make_string(arg), ctypes.POINTER(ctypes_wrapped.c_char))\n"
			"                 for arg in sys.argv]))\n")
	f.write("\n")
	f.close()

	print "Done."


if __name__ == "__main__":
	main(sys.argv)
