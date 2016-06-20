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
	f.write("intp = cparser.interpreter.Interpreter()\n")
	f.write("intp.setupStatic()\n")
	f.write("helpers = intp.helpers\n")
	f.write("ctypes_wrapped = intp.ctypes_wrapped\n")
	# TODO: structs, unions, values
	f.write("\n\nclass g:\n")
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
			if isinstance(content, cparser.CFunc):
				funcEnv = interpreter._translateFuncToPyAst(content, noBodyMode="code-with-exception")
				pyAst = funcEnv.astNode
				assert isinstance(pyAst, ast.FunctionDef)
				pyAst.decorator_list.append(ast.Name(id="staticmethod", ctx=ast.Load()))
				Unparser(pyAst, indent=1, file=f)
			#elif isinstance(content, cparser.CStruct):
			# TODO...
		except Exception:
			print "!!! Exception while compiling %r" % content
			sys.excepthook(*sys.exc_info())
			# We continue...

	f.write("\n\n\n")
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

	f.write("\n\n\n")
	f.write("if __name__ == '__main__':\n")
	f.write("    better_exchook.install()\n")
	f.write("    g.Py_Main(ctypes_wrapped.c_int(len(sys.argv)),\n"
			"              (ctypes.POINTER(ctypes_wrapped.c_char) * (len(sys.argv) + 1))(\n"
			"               *[ctypes.cast(intp._make_string(arg), ctypes.POINTER(ctypes_wrapped.c_char))\n"
			"                 for arg in sys.argv]))\n\n")
	f.close()

	print "Done."


if __name__ == "__main__":
	main(sys.argv)
