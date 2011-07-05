#!/usr/bin/python
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under GPL

import better_exchook
better_exchook.install()

import sys, os, os.path
MyDir = os.path.dirname(sys.argv[0])

CPythonDir = MyDir + "/Python-2.7.1"

# test
import cparser
state = cparser.parse(CPythonDir + "/Include/Python.h")

print "erros so far:"
for m in state._errors:
	print m
