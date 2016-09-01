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
		#state.structs[obj.type.name] = obj.type
	elif isinstance(obj.type, cparser.CUnion):
		if obj.type.name in state.unions:
			return False
		# See above.
		#state.unions[obj.type.name] = obj.type
	return True

def fix_name(obj):
	assert obj.name
	if obj.name.startswith("__"):
		obj.name = "_M_%s" % obj.name[2:]


class CodeGen:

	def __init__(self, f, state, interpreter):
		self.f = f
		self.state = state
		self.interpreter = interpreter
		self.structs = {}
		self.unions = {}
		self.delayed_structs = []
		self._py_in_structs = False
		self._py_in_unions = False
		self._py_in_delayed = False
		self._py_in_globals = False
		self._get_py_type_stack = []
		self._anonymous_name_counter = 0

	def write_header(self):
		f = self.f
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

	def write_structs(self):
		self._py_in_structs = True
		self._write_structs("struct")
		self._py_in_structs = False

	def write_unions(self):
		self._py_in_unions = True
		self._write_structs("union")
		self._py_in_unions = False

	def fix_names(self):
		for content in self.state.contentlist:
			if isinstance(content, cparser.CTypedef):
				set_name_for_typedeffed_struct(content, self.state)
			if isinstance(content, (cparser.CStruct, cparser.CUnion, cparser.CFunc, cparser.CTypedef, cparser.CVarDecl)):
				assert content.name
				fix_name(content)

	def _get_anonymous_name_counter(self):
		self._anonymous_name_counter += 1
		return self._anonymous_name_counter

	def _get_anonymous_name(self):
		return "_anonymous_%i" % self._get_anonymous_name_counter()

	def _write_structs(self, base_type):
		f = self.f
		f.write("class %ss:\n" % base_type)
		f.write("    pass\n")
		f.write("\n")
		cparse_base_type = {"struct": cparser.CStruct, "union": cparser.CUnion}[base_type]
		last_log_time = time.time()
		for i, content in enumerate(self.state.contentlist):
			if time.time() - last_log_time > 2.0:
				last_log_time = time.time()
				perc_compl = 100.0 * i / len(self.state.contentlist)
				cur_content_s = "%s %s" % (content.__class__.__name__,
										   (getattr(content, "name", None) or "<noname>"))
				cur_file_s = getattr(content, "defPos", "<unknown source>")
				print "Compile %ss... (%.0f%%) (%s) (%s)" % (base_type, perc_compl, cur_content_s, cur_file_s)
			if isinstance(content, cparser.CTypedef):
				content = content.type
			if not isinstance(content, cparse_base_type):
				continue
			if cparser.isExternDecl(content):
				content = self.state.getResolvedDecl(content)
				if cparser.isExternDecl(content):
					# Dummy placeholder.
					self._write_struct_dummy_extern(content)
					continue
				else:
					# We have a full declaration available.
					# It will be written later when we come to it in this loop.
					continue  # we will write it later
			self._try_write_struct(content)
		f.write("\n\n")

	class WriteStructException(Exception): pass
	class NoBody(WriteStructException): pass
	class RecursiveConstruction(WriteStructException): pass
	class IncompleteStructCannotCompleteHere(WriteStructException): pass

	def _write_struct(self, content):
		assert content.name
		if content.body is None:
			raise self.NoBody()
		if getattr(content, "_comppy_constructing", None):
			raise self.RecursiveConstruction()
		content._comppy_constructing = True
		base_type = {cparser.CStruct: "struct", cparser.CUnion: "union"}[type(content)]
		ctype_base = {"struct": "ctypes.Structure", "union": "ctypes.Union"}[base_type]
		struct_dict = {"struct": self.structs, "union": self.unions}[base_type]
		# see _getCTypeStruct for reference
		fields = []
		try:
			for c in content.body.contentlist:
				if not isinstance(c, cparser.CVarDecl): continue
				t = self.get_py_type(c.type)
				if c.arrayargs:
					if len(c.arrayargs) != 1: raise Exception(str(c) + " has too many array args")
					n = c.arrayargs[0].value
					t = "%s * %i" % (t, n)
				if hasattr(c, "bitsize"):
					fields.append("(%r, %s, %s)" % (str(c.name), t, c.bitsize))
				else:
					fields.append("(%r, %s)" % (str(c.name), t))
		finally:
			content._comppy_constructing = False
		f = self.f
		f.write("class _class_%s_%s(%s):\n" % (base_type, content.name, ctype_base))
		f.write("    _fields_ = [\n")
		f.write("        %s]\n" % (",\n" + " " * 8).join(fields))
		f.write("%ss.%s = _class_%s_%s\n" % (base_type, content.name, base_type, content.name))
		f.write("del _class_%s_%s\n" % (base_type, content.name))
		f.write("\n")
		content._comppy_written = True
		assert content.name not in struct_dict
		struct_dict[content.name] = content

	def _write_struct_dummy_extern(self, content):
		base_type = {cparser.CStruct: "struct", cparser.CUnion: "union"}[type(content)]
		self.f.write("%ss.%s = ctypes_wrapped.c_int  # Dummy extern declaration\n" % (base_type, content.name))
		struct_dict = {"struct": self.structs, "union": self.unions}[base_type]
		assert content.name
		assert content.name not in struct_dict
		struct_dict[content.name] = content

	def _try_write_struct(self, content):
		assert content.name
		assert content.body is not None
		base_type = {cparser.CStruct: "struct", cparser.CUnion: "union"}[type(content)]
		struct_dict = {"struct": self.structs, "union": self.unions}[base_type]
		if getattr(content, "_comppy_written", None):
			assert struct_dict[content.name] is content
			return
		try:
			self._write_struct(content)
		except self.WriteStructException:
			if content not in self.delayed_structs:
				assert content.name not in struct_dict
				self.delayed_structs.append(content)
				content._delayed_write = True

	def _check_local_struct_type(self, t):
		if not t.name:
			t.name = "_local_" + self._get_anonymous_name()
		if t.body is None:
			t2 = self.state.getResolvedDecl(t)
			if t2 is not None:
				assert t2.name == t.name
				t = t2
		base_type = {cparser.CStruct: "struct", cparser.CUnion: "union"}[type(t)]
		struct_dict = {"struct": self.structs, "union": self.unions}[base_type]
		if t.name not in struct_dict:
			if {"struct": self._py_in_structs, "union": self._py_in_unions}[base_type]:
				self._write_struct(t)
			elif self._py_in_delayed:
				self._write_delayed_struct(t)
			else:
				raise self.IncompleteStructCannotCompleteHere()

	def _write_delayed_struct(self, content):
		# See cparser._getCTypeStruct for reference.
		f = self.f
		assert content.name
		base_type = {cparser.CStruct: "struct", cparser.CUnion: "union"}[type(content)]
		struct_dict = getattr(self, "%ss" % base_type)
		assert content.name not in struct_dict
		ctype_base = {"struct": "ctypes.Structure", "union": "ctypes.Union"}[base_type]
		if not getattr(content, "_wrote_header", False):
			f.write("class _class_%s_%s(%s): pass\n" % (base_type, content.name, ctype_base))
			f.write("%ss.%s = _class_%s_%s\n" % (base_type, content.name, base_type, content.name))
			content._wrote_header = True
		if content.body is None:
			return

		parent_type = None
		type_stack = list(self._get_py_type_stack)
		if type_stack:
			# type_stack[-1], or getResolvedDecl of it, that is the current content.
			type_stack.pop()
			# Take next non-typedef type.
			while type_stack:
				parent_type = type_stack.pop()
				if not isinstance(parent_type, cparser.CTypedef):
					break

		if getattr(content, "_comppy_constructing", None):
			if parent_type is not None:
				# If the parent referred to us as a pointer, it's fine,
				# we can use our incomplete type and don't need to construct it now.
				if cparser.isPointerType(parent_type, alsoFuncPtr=True, alsoArray=False):
					return
			# Otherwise, we must construct it now.
			content._comppy_constructing.append(parent_type)
			if len(content._comppy_constructing) > 2:
				# We got called more than once. This is an infinite loop.
				raise self.RecursiveConstruction(
					"The parent types when we were called: %s" % (content._comppy_constructing,))
		else:
			content._comppy_constructing = [parent_type]
		fields = []
		try:
			for c in content.body.contentlist:
				if not isinstance(c, cparser.CVarDecl): continue
				t = self.get_py_type(c.type)
				if c.arrayargs:
					if len(c.arrayargs) != 1: raise Exception(str(c) + " has too many array args")
					n = c.arrayargs[0].value
					t = "%s * %i" % (t, n)
				if hasattr(c, "bitsize"):
					fields.append("(%r, %s, %s)" % (str(c.name), t, c.bitsize))
				else:
					fields.append("(%r, %s)" % (str(c.name), t))
		finally:
			content._comppy_constructing.pop()

		# finalize the type
		if content.name not in struct_dict:
			struct_dict[content.name] = content
			f.write("_class_%s_%s.fields = [\n    %s]\n" % (base_type, content.name, ",\n    ".join(fields)))
			f.write("del _class_%s_%s\n" % (base_type, content.name))
			f.write("\n")

	def write_delayed_structs(self):
		self._py_in_delayed = True
		f = self.f
		for t in self.delayed_structs:
			base_type = {cparser.CStruct: "struct", cparser.CUnion: "union"}[type(t)]
			struct_dict = getattr(self, "%ss" % base_type)
			if t.name in struct_dict: continue  # could be written meanwhile
			self._write_delayed_struct(t)
		del self.delayed_structs[:]
		f.write("\n\n")
		self._py_in_delayed = False

	def get_py_type(self, t):
		self._get_py_type_stack.append(t)
		try:
			return self._get_py_type(t)
		finally:
			self._get_py_type_stack.pop()

	def _get_py_type(self, t):
		if isinstance(t, cparser.CTypedef):
			if self._py_in_globals:
				assert t.name, "typedef target typedef must have name"
				return t.name
			return self.get_py_type(t.type)
		elif isinstance(t, (cparser.CStruct, cparser.CUnion)):
			base_type = {cparser.CStruct: "struct", cparser.CUnion: "union"}[type(t)]
			self._check_local_struct_type(t)
			assert t.name, "struct must have name, should have been assigned earlier also to anonymous structs"
			return "%ss.%s" % (base_type, t.name)
		elif isinstance(t, cparser.CBuiltinType):
			return "ctypes_wrapped.%s" % builtin_ctypes_name(t.builtinType)
		elif isinstance(t, cparser.CStdIntType):
			return "ctypes_wrapped.%s" % stdint_ctypes_name(t.name)
		elif isinstance(t, cparser.CEnum):
			int_type_name = t.getMinCIntType()
			return "ctypes_wrapped.%s" % stdint_ctypes_name(int_type_name)
		elif isinstance(t, cparser.CPointerType):
			if cparser.isVoidPtrType(t):
				return "ctypes_wrapped.c_void_p"
			else:
				return "ctypes.POINTER(%s)" % self.get_py_type(t.pointerOf)
		elif isinstance(t, cparser.CArrayType):
			if not t.arrayLen:
				return "ctypes.POINTER(%s)" % self.get_py_type(t.arrayOf)
			l = cparser.getConstValue(self.state, t.arrayLen)
			if l is None:
				l = 1
			return "%s * %i" % (self.get_py_type(t.arrayOf), l)
		elif isinstance(t, cparser.CFuncPointerDecl):
			if isinstance(t.type, cparser.CPointerType):
				# https://bugs.python.org/issue5710
				restype = "ctypes_wrapped.c_void_p"
			elif t.type == cparser.CBuiltinType(("void",)):
				restype = "None"
			else:
				restype = self.get_py_type(t.type)
			return "ctypes.CFUNCTYPE(%s)" % ", ".join([restype] + [self.get_py_type(a) for a in t.args])
		elif isinstance(t, cparser.CFuncArgDecl):
			return self.get_py_type(t.type)
		raise Exception("unexpected type: %s" % type(t))

	def write_globals(self):
		self._py_in_globals = True
		f = self.f
		f.write("class g:\n")
		g_names = set()
		last_log_time = time.time()
		count = count_incomplete = 0
		for i, content in enumerate(self.state.contentlist):
			if time.time() - last_log_time > 2.0:
				last_log_time = time.time()
				perc_compl = 100.0 * i / len(self.state.contentlist)
				cur_content_s = "%s %s" % (content.__class__.__name__,
										   (getattr(content, "name", None) or "<noname>"))
				cur_file_s = getattr(content, "defPos", "<unknown source>")
				print "Compile... (%.0f%%) (%s) (%s)" % (perc_compl, cur_content_s, cur_file_s)
			if isinstance(content, (cparser.CStruct, cparser.CUnion)):
				continue  # Handled in the other loops.
			try:
				if cparser.isExternDecl(content):
					content = self.state.getResolvedDecl(content)
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
					funcEnv = self.interpreter._translateFuncToPyAst(content, noBodyMode="code-with-exception")
					pyAst = funcEnv.astNode
					assert isinstance(pyAst, ast.FunctionDef)
					pyAst.decorator_list.append(ast.Name(id="staticmethod", ctx=ast.Load()))
					Unparser(pyAst, indent=1, file=f)
					f.write("\n")
				elif isinstance(content, (cparser.CStruct, cparser.CUnion)):
					pass  # Handled in the other loops.
				elif isinstance(content, cparser.CTypedef):
					f.write("    %s = %s\n" % (content.name, self.get_py_type(content.type)))
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
		self._py_in_globals = False

	def write_values(self):
		f = self.f
		f.write("class values:\n")

		def maybe_add_wrap_value(container_name, var_name, var):
			if not isinstance(var, cparser.CWrapValue): return
			v = cparser.interpreter.getAstForWrapValue(self.interpreter, var)
			assert isinstance(v, ast.Attribute)
			assert isinstance(v.value, ast.Name)
			assert v.value.id == "values"
			wrap_name = v.attr
			var2 = getattr(self.interpreter.wrappedValues, wrap_name, None)
			assert var2 is var
			f.write("    %s = intp.stateStructs[0].%s[%r]\n" % (wrap_name, container_name, var_name))

		# These are added by globalincludewrappers.
		for varname, var in sorted(self.state.vars.items()):
			maybe_add_wrap_value("vars", varname, var)
		for varname, var in sorted(self.state.funcs.items()):
			maybe_add_wrap_value("funcs", varname, var)
		f.write("\n\n")

	def write_footer(self):
		f = self.f
		f.write("if __name__ == '__main__':\n")
		f.write("    g.Py_Main(ctypes_wrapped.c_int(len(sys.argv)),\n"
				"              (ctypes.POINTER(ctypes_wrapped.c_char) * (len(sys.argv) + 1))(\n"
				"               *[ctypes.cast(intp._make_string(arg), ctypes.POINTER(ctypes_wrapped.c_char))\n"
				"                 for arg in sys.argv]))\n")
		f.write("\n")


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
	code_gen = CodeGen(f, state, interpreter)
	code_gen.write_header()
	code_gen.fix_names()
	code_gen.write_structs()
	code_gen.write_unions()
	code_gen.write_delayed_structs()
	code_gen.write_values()
	code_gen.write_globals()
	code_gen.write_footer()
	f.close()

	print "Done."


if __name__ == "__main__":
	main(sys.argv)
