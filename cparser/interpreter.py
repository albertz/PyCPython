# PyCParser - interpreter
# by Albert Zeyer, 2011
# code under LGPL

from cparser import *
from cwrapper import CStateWrapper

import ast
import sys
import inspect

class CWrapValue:
	def __init__(self, value, decl=None):
		self.value = value
		self.decl = decl
	def __repr__(self):
		s = "<" + self.__class__.__name__ + " "
		if self.decl is not None: s += repr(self.decl) + " "
		s += repr(self.value)
		s += ">"
		return s

def iterIdentifierNames():
	S = "abcdefghijklmnopqrstuvwxyz0123456789"
	n = 0
	while True:
		v = []
		x = n
		while x > 0 or len(v) == 0:
			v = [x % len(S)] + v
			x /= len(S)
		yield "".join(map(lambda x: S[x], v))
		n += 1

def iterIdWithPostfixes(name):
	if name is None:
		for postfix in iterIdentifierNames():
			yield "__dummy_" + postfix
		return
	yield name
	for postfix in iterIdentifierNames():
		yield name + "_" + postfix

import keyword
PyReservedNames = set(dir(sys.modules["__builtin__"]) + keyword.kwlist + ["ctypes", "helpers"])

def isValidVarName(name):
	return name not in PyReservedNames

class GlobalScope:
	StateScopeDicts = ["vars", "typedefs", "funcs"]
	
	def __init__(self, interpreter, stateStruct):
		self.interpreter = interpreter
		self.stateStruct = stateStruct
		self.identifiers = {} # name -> CVarDecl | ...
		self.names = {} # id(decl) -> name
		self.vars = {} # name -> value
		
	def _findId(self, name):
		for D in self.StateScopeDicts:
			d = getattr(self.stateStruct, D)
			o = d.get(name)
			if o is not None: return o
		return None
	
	def findIdentifier(self, name):
		o = self.identifiers.get(name, None)
		if o is not None: return o
		o = self._findId(name)
		if o is None: return None
		self.identifiers[name] = o
		self.names[id(o)] = name
		return o
	
	def findName(self, decl):
		name = self.names.get(id(decl), None)
		if name is not None: return name
		o = self.findIdentifier(decl.name)
		if o is decl: return decl.name
		return None
	
	def registerExternVar(self, name_prefix, value=None):
		if not isinstance(value, CWrapValue):
			value = CWrapValue(value)
		for name in iterIdWithPostfixes(name_prefix):
			if self.findIdentifier(name) is not None: continue
			self.identifiers[name] = value
			return name

	def registerExterns(self):
		self.varname_ctypes = self.registerExternVar("ctypes", ctypes)
		self.varname_helpers = self.registerExternVar("helpers", Helpers)

	def getVar(self, name):
		if name in self.vars: return self.vars[name]
		decl = self.findIdentifier(name)
		assert isinstance(decl, CVarDecl)
		# TODO: We ignore any special initialization here. This is probably not what we want.
		initValue = decl.getCType(self.stateStruct)()
		self.vars[name] = initValue
		return initValue

class CTypeWrapper:
	def __init__(self, decl, globalScope):
		self.decl = decl
		self.globalScope = globalScope
		self._ctype_cache = None
	def __call__(self, *args):
		if self._ctype_cache is None:
			self._ctype_cache = getCType(self.decl, self.globalScope.stateStruct)
		# TODO: we are ignoring args here
		return self._ctype_cache()

class GlobalsWrapper:
	def __init__(self, globalScope):
		self.globalScope = globalScope
	
	def __setattr__(self, name, value):
		self.__dict__[name] = value
	
	def __getattr__(self, name):
		# TODO handle '__builtins__' ?
		print "dict wrapper getitem:", name
		decl = self.globalScope.findIdentifier(name)
		if decl is None: raise KeyError
		if isinstance(decl, CVarDecl):
			v = self.globalScope.getVar(name)
		elif isinstance(decl, CWrapValue):
			v = decl.value
		elif isinstance(decl, CFunc):
			v = self.globalScope.interpreter.getFunc(name)
		elif isinstance(decl, (CTypedef,CStruct,CUnion,CEnum)):
			v = CTypeWrapper(decl, self.globalScope)
		else:
			assert False, "didn't expected " + str(decl)
		self.__dict__[name] = v
		return v
	
	def __repr__(self):
		return "<" + self.__class__.__name__ + " " + repr(self._cache) + ">"

class FuncEnv:
	def __init__(self, globalScope):
		self.globalScope = globalScope
		self.vars = {} # name -> varDecl
		self.varNames = {} # id(varDecl) -> name
		self.scopeStack = [] # FuncCodeblockScope
		self.astNode = ast.FunctionDef(
			args=ast.arguments(args=[], vararg=None, kwarg=None, defaults=[]),
			body=[], decorator_list=[])
	def _registerNewVar(self, varName, varDecl):
		assert varDecl is not None
		assert id(varDecl) not in self.varNames
		for name in iterIdWithPostfixes(varName):
			if not isValidVarName(name): continue
			if self.searchVarName(name) is None:
				self.vars[name] = varDecl
				self.varNames[id(varDecl)] = name
				return name
	def searchVarName(self, varName):
		if varName in self.vars: return self.vars[varName]
		return self.globalScope.findIdentifier(varName)
	def registerNewVar(self, varName, varDecl):
		return self.scopeStack[-1].registerNewVar(varName, varDecl)
	def getAstNodeForVarDecl(self, varDecl):
		assert varDecl is not None
		if id(varDecl) in self.varNames:
			# local var
			name = self.varNames[id(varDecl)]
			assert name is not None
			return ast.Name(id=name, ctx=ast.Load())
		# we expect this is a global
		name = self.globalScope.findName(varDecl)
		assert name is not None, str(varDecl) + " is expected to be a global var"
		return getAstNodeAttrib("g", name)
	def _unregisterVar(self, varName):
		varDecl = self.vars[varName]
		del self.varNames[id(varDecl)]
		del self.vars[varName]
	def pushScope(self):
		scope = FuncCodeblockScope(funcEnv=self)
		self.scopeStack += [scope]
		return scope
	def popScope(self):
		scope = self.scopeStack.pop()
		scope.finishMe()

NoneAstNode = ast.Name(id="None", ctx=ast.Load())

def getAstNodeAttrib(value, attrib, ctx=ast.Load()):
	a = ast.Attribute(ctx=ctx)
	if isinstance(value, (str,unicode)):
		a.value = ast.Name(id=value, ctx=ctx)
	elif isinstance(value, ast.AST):
		a.value = value
	else:
		assert False, str(value) + " has invalid type"
	a.attr = attrib
	return a

def getAstNodeForCTypesBasicType(t):
	if t is None: return NoneAstNode
	if t is CVoidType: return NoneAstNode
	if not inspect.isclass(t) and isinstance(t, CVoidType): return NoneAstNode
	if issubclass(t, CVoidType): return None
	assert getattr(ctypes, t.__name__) is t
	return getAstNodeAttrib("ctypes", t.__name__)

def getAstNodeForVarType(t):
	if isinstance(t, CBuiltinType):
		return getAstNodeForCTypesBasicType(t.builtinType)
	elif isinstance(t, CStdIntType):
		return getAstNodeForCTypesBasicType(State.StdIntTypes[t.name])
	elif isinstance(t, CPointerType):
		a = getAstNodeAttrib("ctypes", "POINTER")
		return makeAstNodeCall(a, getAstNodeForVarType(t.pointerOf))
	elif isinstance(t, CTypedefType):
		return getAstNodeAttrib("g", t.name)
	else:
		try: return getAstNodeForCTypesBasicType(t)
		except: pass
	assert False, "cannot handle " + str(t)

def findHelperFunc(f):
	for k in dir(Helpers):
		v = getattr(Helpers, k)
		if v is f: return k
	return None

def makeAstNodeCall(func, *args):
	if not isinstance(func, ast.AST):
		name = findHelperFunc(func)
		assert name is not None, str(func) + " unknown"
		func = getAstNodeAttrib("helpers", name)
	return ast.Call(func=func, args=list(args), keywords=[], starargs=None, kwargs=None)

def isPointerType(t):
	if isinstance(t, CPointerType): return True
	return False

def getAstNode_valueFromObj(objAst, objType):
	if isPointerType(objType):
		astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
		astCast = getAstNodeAttrib("ctypes", "cast")
		astVoidP = makeAstNodeCall(astCast, objAst, astVoidPT)
		astValue = getAstNodeAttrib(astVoidP, "value")
		return astValue
	else:
		astValue = getAstNodeAttrib(objAst, "value")
		return astValue		
		
def getAstNode_newTypeInstance(objType, argAst=None, argType=None):
	args = []
	if argAst is not None:
		if isinstance(argAst, (ast.Str, ast.Num)):
			args += [argAst]
		else:
			assert argType is not None
			args += [getAstNode_valueFromObj(argAst, argType)]

	typeAst = getAstNodeForVarType(objType)

	if isPointerType(objType) and argAst is not None:
		astVoidPT = getAstNodeAttrib("ctypes", "c_void_p")
		astCast = getAstNodeAttrib("ctypes", "cast")
		astVoidP = makeAstNodeCall(astVoidPT, *args)
		return makeAstNodeCall(astCast, astVoidP, typeAst)
	else:
		return makeAstNodeCall(typeAst, *args)

class FuncCodeblockScope:
	def __init__(self, funcEnv):
		self.varNames = set()
		self.funcEnv = funcEnv
	def registerNewVar(self, varName, varDecl):
		varName = self.funcEnv._registerNewVar(varName, varDecl)
		assert varName is not None
		self.varNames.add(varName)
		a = ast.Assign()
		a.targets = [ast.Name(id=varName, ctx=ast.Store())]
		if isinstance(varDecl, CFuncArgDecl):
			# Note: We just assume that the parameter has the correct/same type.
			a.value = getAstNode_newTypeInstance(varDecl.type, ast.Name(id=varName, ctx=ast.Load()), varDecl.type)
		elif isinstance(varDecl, CVarDecl):
			if varDecl.body is not None:
				bodyAst, t = astAndTypeForStatement(self.funcEnv, varDecl.body)
				a.value = getAstNode_newTypeInstance(varDecl.type, bodyAst, t)
			else:	
				a.value = getAstNode_newTypeInstance(varDecl.type)
		else:
			assert False, "didn't expected " + str(varDecl)
		self.funcEnv.astNode.body.append(a)
		return varName
	def _astForDeleteVar(self, varName):
		assert varName is not None
		return ast.Delete(targets=[ast.Name(id=varName, ctx=ast.Del())])
	def finishMe(self):
		astCmds = []
		for varName in self.varNames:
			astCmds += [self._astForDeleteVar(varName)]
			self.funcEnv._unregisterVar(varName)
		self.varNames.clear()
		self.funcEnv.astNode.body.extend(astCmds)

OpUnary = {
	"~": ast.Invert,
	"!": ast.Not,
	"+": ast.UAdd,
	"-": ast.USub,
}

OpBin = {
	"+": ast.Add,
	"-": ast.Sub,
	"*": ast.Mult,
	"/": ast.Div,
	"%": ast.Mod,
	"<<": ast.LShift,
	">>": ast.RShift,
	"|": ast.BitOr,
	"^": ast.BitXor,
	"&": ast.BitAnd,
}

OpBinBool = {
	"&&": ast.And,
	"||": ast.Or,
}

OpBinCmp = {
	"==": ast.Eq,
	"!=": ast.NotEq,
	"<": ast.Lt,
	"<=": ast.LtE,
	">": ast.Gt,
	">=": ast.GtE,
}

OpAugAssign = dict(map(lambda (k,v): (k + "=", v), OpBin.iteritems()))

def _astOpToFunc(op):
	if inspect.isclass(op): op = op()
	assert isinstance(op, ast.operator)
	l = ast.Lambda()
	a = l.args = ast.arguments()
	a.args = [
		ast.Name(id="a", ctx=ast.Param()),
		ast.Name(id="b", ctx=ast.Param())]
	a.vararg = None
	a.kwarg = None
	a.defaults = []
	t = l.body = ast.BinOp()
	t.left = ast.Name(id="a", ctx=ast.Load())
	t.right = ast.Name(id="b", ctx=ast.Load())
	t.op = op
	expr = ast.Expression(body=l)
	ast.fix_missing_locations(expr)
	code = compile(expr, "<_astOpToFunc>", "eval")
	f = eval(code)
	return f

OpBinFuncs = dict(map(lambda op: (op, _astOpToFunc(op)), OpBin.itervalues()))

class Helpers:
	@staticmethod
	def prefixInc(a):
		a.value += 1
		return a
	
	@staticmethod
	def prefixDec(a):
		a.value -= 1
		return a
	
	@staticmethod
	def postfixInc(a):
		b = Helpers.copy(a)
		a.value += 1
		return b
	
	@staticmethod
	def postfixDec(a):
		b = Helpers.copy(a)
		a.value -= 1
		return b
	
	@staticmethod
	def prefixIncPtr(a):
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(c_void_p))
		aPtr.contents.value += ctypes.sizeof(a._type_)
		return a

	@staticmethod
	def prefixDecPtr(a):
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(c_void_p))
		aPtr.contents.value -= ctypes.sizeof(a._type_)
		return a
	
	@staticmethod
	def postfixIncPtr(a):
		b = Helpers.copy(a)
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(c_void_p))
		aPtr.contents.value += ctypes.sizeof(a._type_)
		return b

	@staticmethod
	def postfixDecPtr(a):
		b = Helpers.copy(a)
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(c_void_p))
		aPtr.contents.value -= ctypes.sizeof(a._type_)
		return b

	@staticmethod
	def copy(a):
		if isinstance(a, _ctypes._SimpleCData):
			c = a.__class__()
			pointer(c)[0] = a
			return c
		assert False, "cannot copy " + str(a)
	
	@staticmethod
	def assign(a, bValue):
		a.value = bValue
		return a
	
	@staticmethod
	def assignPtr(a, bValue):
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(c_void_p))
		aPtr.contents.value = bValue
		return a

	@staticmethod
	def augAssign(a, op, bValue):
		a.value = OpBinFuncs[op](a.value, bValue)
		return a

	@staticmethod
	def augAssignPtr(a, op, bValue):
		aPtr = ctypes.cast(ctypes.pointer(a), ctypes.POINTER(c_void_p))
		aPtr.contents.value = OpBinFuncs[op](aPtr.contents.value, bValue)
		return a


def astForHelperFunc(helperFuncName, *astArgs):
	helperFuncAst = getAstNodeAttrib("helpers", helperFuncName)
	a = ast.Call(keywords=[], starargs=None, kwargs=None)
	a.func = helperFuncAst
	a.args = list(astArgs)
	return a

def astAndTypeForStatement(funcEnv, stmnt):
	if isinstance(stmnt, (CVarDecl,CFuncArgDecl)):
		return funcEnv.getAstNodeForVarDecl(stmnt), stmnt.type
	elif isinstance(stmnt, CStatement):
		return astAndTypeForCStatement(funcEnv, stmnt)
	elif isinstance(stmnt, CAttribAccessRef):
		assert stmnt.name is not None
		a = ast.Attribute(ctx=ast.Load())
		a.value, t = astAndTypeForStatement(funcEnv, stmnt.base)
		a.attr = stmnt.name
		while isinstance(t, CTypedefType):
			t = funcEnv.globalScope.stateStruct.typedefs[t.name]
		assert isinstance(t, (CStruct,CUnion))
		attrDecl = t.findAttrib(a.attr)
		assert attrDecl is not None
		return a, attrDecl.type
	elif isinstance(stmnt, CNumber):
		t = minCIntTypeForNums(stmnt.content)
		if t is None: t = "int64_t" # it's an overflow; just take a big type
		t = CStdIntType(t)
		return getAstNode_newTypeInstance(t, ast.Num(n=stmnt.content)), t
	elif isinstance(stmnt, CStr):
		return makeAstNodeCall(getAstNodeAttrib("ctypes", "c_char_p"), ast.Str(s=stmnt.content)), ctypes.c_char_p
	elif isinstance(stmnt, CChar):
		return makeAstNodeCall(getAstNodeAttrib("ctypes", "c_char"), ast.Str(s=stmnt.content)), ctypes.c_char
	elif isinstance(stmnt, CFuncCall):
		if isinstance(stmnt.base, CFunc):
			assert stmnt.base.name is not None
			a = ast.Call(keywords=[], starargs=None, kwargs=None)
			a.func = getAstNodeAttrib("g", stmnt.base.name)
			a.args = map(lambda arg: astAndTypeForStatement(funcEnv, arg)[0], stmnt.args)
			return a, stmnt.type
		elif isinstance(stmnt.base, CStatement) and stmnt.base.isCType():
			assert len(stmnt.args) == 1
			v, _ = astAndTypeForStatement(funcEnv, stmnt.args[0])
			return v, stmnt.base.asType()
		else:
			assert False, "cannot handle " + str(stmnt.base) + " call"
	elif isinstance(stmnt, CWrapValue):
		# TODO
		return ast.Num(0), ctypes.c_int
	else:
		assert False, "cannot handle " + str(stmnt)

def getAstNode_assign(aAst, aType, bAst, bType):
	bValueAst = getAstNode_valueFromObj(bAst, bType)
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.assignPtr, aAst, bValueAst)
	return makeAstNodeCall(Helpers.assign, aAst, bValueAst)

def getAstNode_augAssign(aAst, aType, op, bAst, bType):
	opAst = ast.Str(op)
	bValueAst = getAstNode_valueFromObj(bAst, bType)
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.augAssignPtr, aAst, opAst, bValueAst)
	return makeAstNodeCall(Helpers.augAssign, aAst, opAst, bValueAst)

def getAstNode_prefixInc(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.prefixIncPtr, aAst)
	return makeAstNodeCall(Helpers.prefixInc, aAst)

def getAstNode_prefixDec(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.prefixDecPtr, aAst)
	return makeAstNodeCall(Helpers.prefixDec, aAst)

def getAstNode_postfixInc(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.postfixIncPtr, aAst)
	return makeAstNodeCall(Helpers.postfixInc, aAst)

def getAstNode_postfixDec(aAst, aType):
	if isPointerType(aType):
		return makeAstNodeCall(Helpers.postfixDecPtr, aAst)
	return makeAstNodeCall(Helpers.postfixDec, aAst)
	
def astAndTypeForCStatement(funcEnv, stmnt):
	assert isinstance(stmnt, CStatement)
	if stmnt._leftexpr is None: # prefixed only
		rightAstNode,rightType = astAndTypeForStatement(funcEnv, stmnt._rightexpr)
		if stmnt._op.content == "++":
			return getAstNode_prefixInc(rightAstNode, rightType), rightType
		elif stmnt._op.content == "--":
			return getAstNode_prefixDec(rightAstNode, rightType), rightType
		elif stmnt._op.content in OpUnary:
			a = ast.UnaryOp()
			a.op = OpUnary[stmnt._op.content]()
			a.operand = rightAstNode
			return a, rightType
		else:
			assert False, "unary prefix op " + str(stmnt._op) + " is unknown"
	if stmnt._op is None:
		return astAndTypeForStatement(funcEnv, stmnt._leftexpr)
	if stmnt._rightexpr is None:
		leftAstNode, leftType = astAndTypeForStatement(funcEnv, stmnt._leftexpr)
		if stmnt._op.content == "++":
			return getAstNode_postfixInc(leftAstNode, leftType), leftType
		elif stmnt._op.content == "--":
			return getAstNode_postfixDec(leftAstNode, leftType), leftType
		else:
			assert False, "unary postfix op " + str(stmnt._op) + " is unknown"
	leftAstNode, leftType = astAndTypeForStatement(funcEnv, stmnt._leftexpr)
	rightAstNode, rightType = astAndTypeForStatement(funcEnv, stmnt._rightexpr)
	if stmnt._op.content in OpBin:
		a = ast.BinOp()
		a.op = OpBin[stmnt._op.content]()
		a.left = leftAstNode
		a.right = rightAstNode
		return a, leftType # TODO: not really correct. e.g. int + float -> float
	elif stmnt._op.content in OpBinBool:
		a = ast.BoolOp()
		a.op = OpBinBool[stmnt._op.content]()
		a.values = [leftAstNode, rightAstNode]
		return a, ctypes.c_int
	elif stmnt._op.content in OpBinCmp:
		a = ast.Compare()
		a.ops = [OpBinCmp[stmnt._op.content]()]
		a.left = leftAstNode
		a.comparators = [rightAstNode]
		return a, ctypes.c_int
	elif stmnt._op.content == "=":
		return getAstNode_assign(leftAstNode, leftType, rightAstNode, rightType), leftType
	elif stmnt._op.content in OpAugAssign:
		return getAstNode_augAssign(leftAstNode, leftType, stmnt._op.content, rightAstNode, rightType), leftType
	elif stmnt._op.content == "?:":
		middleAstNode, middleType = astAndTypeForStatement(funcEnv, stmnt._middleexpr)
		a = ast.IfExp()
		a.test = leftAstNode
		a.body = middleAstNode
		a.orelse = rightAstNode
		return a, middleType # TODO: not really correct...
	else:
		assert False, "binary op " + str(stmnt._op) + " is unknown"

PyAstNoOp = ast.Assert(test=ast.Name(id="True", ctx=ast.Load()), msg=None)

def astForCWhile(funcEnv, stmnt):
	assert isinstance(stmnt, CWhileStatement)
	assert len(stmnt.args) == 1
	# TODO ...
	return PyAstNoOp

def astForCFor(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCDoWhile(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCIf(funcEnv, stmnt):
	# TODO
	return PyAstNoOp

def astForCReturn(funcEnv, stmnt):
	# TODO
	return PyAstNoOp



class Interpreter:
	def __init__(self):
		self.stateStructs = []
		self._cStateWrapper = CStateWrapper(self)
		self.globalScope = GlobalScope(self, self._cStateWrapper)
		self._func_cache = {}
		self.globalsWrapper = GlobalsWrapper(self.globalScope)
		self.globalsDict = {"ctypes": ctypes, "helpers": Helpers, "g": self.globalsWrapper, "intp": self}
		
	def register(self, stateStruct):
		self.stateStructs += [stateStruct]
	
	def registerFinalize(self):
		self.globalScope.registerExterns()
	
	def getCType(self, obj):
		wrappedStateStruct = self._cStateWrapper
		for T,DictName in [(CStruct,"structs"), (CUnion,"unions"), (CEnum,"enums")]:
			if isinstance(obj, T):
				if obj.name is not None:
					return getattr(wrappedStateStruct, DictName)[obj.name].getCValue(wrappedStateStruct)
				else:
					return obj.getCValue(wrappedStateStruct)
		return obj.getCValue(wrappedStateStruct)
	
	def _translateFuncToPyAst(self, func):
		assert isinstance(func, CFunc)
		base = FuncEnv(globalScope=self.globalScope)
		assert func.name is not None
		base.astNode.name = func.name
		base.pushScope()
		for arg in func.args:
			name = base.registerNewVar(arg.name, arg)
			assert name is not None
			base.astNode.args.args.append(ast.Name(id=name, ctx=ast.Param()))
		for c in func.body.contentlist:
			if isinstance(c, CVarDecl):
				base.registerNewVar(c.name, c)
			elif isinstance(c, CStatement):
				a, t = astAndTypeForCStatement(base, c)
				if isinstance(a, ast.expr):
					a = ast.Expr(value=a)
				base.astNode.body.append(a)
			elif isinstance(c, CWhileStatement):
				base.astNode.body.append(astForCWhile(base, c))
			elif isinstance(c, CForStatement):
				base.astNode.body.append(astForCFor(base, c))
			elif isinstance(c, CDoStatement):
				base.astNode.body.append(astForCDoWhile(base, c))
			elif isinstance(c, CIfStatement):
				base.astNode.body.append(astForCIf(base, c))
			elif isinstance(c, CReturnStatement):
				base.astNode.body.append(astForCReturn(base, c))
			else:
				assert False, "cannot handle " + str(c)
		base.popScope()
		return base

	def _compile(self, pyAst):
		# We unparse + parse again for now for better debugging (so we get some code in a backtrace).
		def _unparse(pyAst):
			from cStringIO import StringIO
			output = StringIO()
			from py_demo_unparse import Unparser
			Unparser(pyAst, output)
			return output.getvalue()
		def _set_linecache(filename, source):
			import linecache
			linecache.cache[filename] = None, None, [line+'\n' for line in source.splitlines()], filename
		SRC_FILENAME = "<PyCParser_" + pyAst.name + ">"
		def _unparseAndParse(pyAst):
			src = _unparse(pyAst)
			_set_linecache(SRC_FILENAME, src)
			return compile(src, SRC_FILENAME, "single")
		def _justCompile(pyAst):
			exprAst = ast.Interactive(body=[pyAst])		
			ast.fix_missing_locations(exprAst)
			return compile(exprAst, SRC_FILENAME, "single")
		return _unparseAndParse(pyAst)
	
	def _translateFuncToPy(self, funcname):
		cfunc = self._cStateWrapper.funcs[funcname]
		funcEnv = self._translateFuncToPyAst(cfunc)
		pyAst = funcEnv.astNode
		compiled = self._compile(pyAst)
		d = {}
		exec compiled in self.globalsDict, d
		func = d[funcname]
		func.C_cFunc = cfunc
		func.C_pyAst = pyAst
		func.C_interpreter = self
		func.C_argTypes = map(lambda a: a.type, cfunc.args)
		return func

	def getFunc(self, funcname):
		if funcname in self._func_cache:
			return self._func_cache[funcname]
		else:
			func = self._translateFuncToPy(funcname)
			self._func_cache[funcname] = func
			return func
	
	def dumpFunc(self, funcname, output=sys.stdout):
		f = self.getFunc(funcname)
		from py_demo_unparse import Unparser
		Unparser(f.C_pyAst, output)
	
	def _castArgToCType(self, arg, typ):
		if isinstance(typ, CPointerType):
			ctyp = getCType(typ, self._cStateWrapper)
			if arg is None:
				return ctyp()
			elif isinstance(arg, (str,unicode)):
				return ctypes.cast(ctypes.c_char_p(arg), ctyp)
			assert isinstance(arg, (list,tuple))
			o = (ctyp._type_ * (len(arg) + 1))()
			for i in xrange(len(arg)):
				o[i] = self._castArgToCType(arg[i], typ.pointerOf)
			op = ctypes.pointer(o)
			op = ctypes.cast(op, ctyp)
			# TODO: what when 'o' goes out of scope and freed?
			return op
		elif isinstance(arg, (int,long)):
			t = minCIntTypeForNums(arg)
			if t is None: t = "int64_t" # it's an overflow; just take a big type
			return self._cStateWrapper.StdIntTypes[t](arg)			
		else:
			assert False, "cannot cast " + str(arg) + " to " + str(typ)
	
	def runFunc(self, funcname, *args):
		f = self.getFunc(funcname)
		assert len(args) == len(f.C_argTypes)
		args = map(lambda (arg,typ): self._castArgToCType(arg,typ), zip(args,f.C_argTypes))
		return f(*args)
