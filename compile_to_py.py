#!/usr/bin/env python
# PyCPython - interpret CPython in Python
# by Albert Zeyer, 2011
# code under BSD 2-Clause License

import sys, os
import argparse
from cpython import CPythonState
import cparser
import cparser.interpreter



def main(argv):
	state = CPythonState()

	print "Parsing CPython...",
	state.parse_cpython()

	interpreter = cparser.interpreter.Interpreter()
	interpreter.register(state)

	# TODO...


if __name__ == "__main__":
	main(sys.argv)