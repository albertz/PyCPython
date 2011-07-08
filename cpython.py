#!/usr/bin/python
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under GPL

import better_exchook
better_exchook.install()

import sys, os, os.path
MyDir = os.path.dirname(sys.argv[0])

CPythonDir = MyDir + "/Python-2.7.1"

import cparser
state = cparser.State()
state.autoSetupSystemMacros()

def findIncludeFullFilename(filename, local):
	fullfn = CPythonDir + "/Include/" + filename
	if os.path.exists(fullfn): return fullfn
	return filename

state.findIncludeFullFilename = findIncludeFullFilename

state = cparser.parse(CPythonDir + "/Modules/main.c", state)

print "erros so far:"
for m in state._errors:
	print m

for f in state.contentlist:
	if not isinstance(f, cparser.CFunc): continue
	if not f.body: continue
	
	print
	print "parsed content of " + str(f) + ":"
	for c in f.body.contentlist:
		print c
