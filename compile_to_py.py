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


def main(argv):
	state = CPythonState()

	out_fn = MyDir + "/cpython_static.py"
	print "Compile CPython to %s." % os.path.basename(out_fn)

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

	print "Compile..."
	f = open(out_fn, "w")
	f.write("#!/usr/bin/env python\n")
	f.write("# PyCPython - interpret CPython in Python\n")
	f.write("# Statically compiled CPython.\n\n")
	f.write("import sys\n")
	f.write("import cparser\n")
	f.write("import cparser.interpreter\n")
	f.write("\nintp = cparser.interpreter.Interpreter()\n")
	f.write("\nclass g:\n")
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
				Unparser(pyAst, indent=1, file=f)
			#elif isinstance(content, cparser.CStruct):
			# TODO...
		except Exception:
			print "!!! Exception while compiling %r" % content
			raise
	f.write("\nif __name__ == '__main__':\n")
	f.write("    g.Py_Main(len(sys.argv), sys.argv + [None])\n\n")
	f.close()

	print "Done."


if __name__ == "__main__":
	main(sys.argv)