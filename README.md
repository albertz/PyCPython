PyCPython
=========

Idea: Use [PyCParser](https://github.com/albertz/PyCParser) to parse and interpret CPython. :)

Status so far:

    $ ./cpython.py -V
    ...
    Python 2.7.1

Yea!

# Compatibility

PyPy, CPython 2.7 (so it can sort of host itself).

The C data structures itself are compatible with CPython,
so in theory, you can even load C extensions and it should work.

# Why

Just for fun.

(Maybe, to make it in any way serious: [here](https://mail.python.org/pipermail/pypy-dev/2012-January/009048.html))

# Details

See [PyCParser](https://github.com/albertz/PyCParser) for more.
