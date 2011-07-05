# Test the Unicode versions of normal file functions
# open, os.open, os.stat. os.listdir, os.rename, os.remove, os.mkdir, os.chdir, os.rmdir
import sys, os, unittest
from unicodedata import normalize
from test import test_support

filenames = [
    'abc',
    u'ascii',
    u'Gr\xfc\xdf-Gott',
    u'\u0393\u03b5\u03b9\u03ac-\u03c3\u03b1\u03c2',
    u'\u0417\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435',
    u'\u306b\u307d\u3093',
    u'\u05d4\u05e9\u05e7\u05e6\u05e5\u05e1',
    u'\u66e8\u66e9\u66eb',
    u'\u66e8\u05e9\u3093\u0434\u0393\xdf',
    # Specific code points: fn, NFC(fn) and NFKC(fn) all differents
    u'\u1fee\u1ffd',
    # Specific code points: NFC(fn), NFD(fn), NFKC(fn) and NFKD(fn) all differents
    u'\u0385\u03d3\u03d4',
    u'\u00a8\u0301\u03d2\u0301\u03d2\u0308',    # == NFD(u'\u0385\u03d3\u03d4')
    u'\u0020\u0308\u0301\u038e\u03ab',          # == NFKC(u'\u0385\u03d3\u03d4')
    u'\u1e9b\u1fc1\u1fcd\u1fce\u1fcf\u1fdd\u1fde\u1fdf\u1fed',
    ]

# Mac OS X decomposes Unicode names, using Normal Form D.
# http://developer.apple.com/mac/library/qa/qa2001/qa1173.html
# "However, most volume formats do not follow the exact specification for
# these normal forms.  For example, HFS Plus uses a variant of Normal Form D
# in which U+2000 through U+2FFF, U+F900 through U+FAFF, and U+2F800 through
# U+2FAFF are not decomposed."
if sys.platform != 'darwin':
    filenames.extend([
        # Specific code points: fn, NFC(fn) and NFKC(fn) all differents
        u'\u1fee\u1ffd\ufad1',
        u'\u2000\u2000\u2000A',
        u'\u2001\u2001\u2001A',
        u'\u2003\u2003\u2003A', # == NFC(u'\u2001\u2001\u2001A')
        u'\u0020\u0020\u0020A', # u'\u0020' == u' ' == NFKC(u'\u2000') ==
                                #   NFKC(u'\u2001') == NFKC(u'\u2003')
])


# Is it Unicode-friendly?
if not os.path.supports_unicode_filenames:
    fsencoding = sys.getfilesystemencoding() or sys.getdefaultencoding()
    try:
        for name in filenames:
            name.encode(fsencoding)
    except UnicodeEncodeError:
        raise unittest.SkipTest("only NT+ and systems with "
                                "Unicode-friendly filesystem encoding")


# Destroy directory dirname and all files under it, to one level.
def deltree(dirname):
    # Don't hide legitimate errors:  if one of these suckers exists, it's
    # an error if we can't remove it.
    if os.path.exists(dirname):
        # must pass unicode to os.listdir() so we get back unicode results.
        for fname in os.listdir(unicode(dirname)):
            os.unlink(os.path.join(dirname, fname))
        os.rmdir(dirname)


class UnicodeFileTests(unittest.TestCase):
    files = set(filenames)
    normal_form = None

    def setUp(self):
        try:
            os.mkdir(test_support.TESTFN)
        except OSError:
            pass
        files = set()
        for name in self.files:
            name = os.path.join(test_support.TESTFN, self.norm(name))
            with open(name, 'w') as f:
                f.write((name+'\n').encode("utf-8"))
            os.stat(name)
            files.add(name)
        self.files = files

    def tearDown(self):
        deltree(test_support.TESTFN)

    def norm(self, s):
        if self.normal_form and isinstance(s, unicode):
            return normalize(self.normal_form, s)
        return s

    def _apply_failure(self, fn, filename, expected_exception,
                       check_fn_in_exception = True):
        with self.assertRaises(expected_exception) as c:
            fn(filename)
        exc_filename = c.exception.filename
        # the "filename" exception attribute may be encoded
        if isinstance(exc_filename, str):
            filename = filename.encode(sys.getfilesystemencoding())
        if check_fn_in_exception:
            self.assertEqual(exc_filename, filename, "Function '%s(%r) failed "
                             "with bad filename in the exception: %r" %
                             (fn.__name__, filename, exc_filename))

    def test_failures(self):
        # Pass non-existing Unicode filenames all over the place.
        for name in self.files:
            name = "not_" + name
            self._apply_failure(open, name, IOError)
            self._apply_failure(os.stat, name, OSError)
            self._apply_failure(os.chdir, name, OSError)
            self._apply_failure(os.rmdir, name, OSError)
            self._apply_failure(os.remove, name, OSError)
            # listdir may append a wildcard to the filename, so dont check
            self._apply_failure(os.listdir, name, OSError, False)

    def test_open(self):
        for name in self.files:
            f = open(name, 'w')
            f.write((name+'\n').encode("utf-8"))
            f.close()
            os.stat(name)

    def test_normalize(self):
        files = set(f for f in self.files if isinstance(f, unicode))
        others = set()
        for nf in set(['NFC', 'NFD', 'NFKC', 'NFKD']):
            others |= set(normalize(nf, file) for file in files)
        others -= files
        if sys.platform == 'darwin':
            files = set(normalize('NFD', file) for file in files)
        for name in others:
            if sys.platform == 'darwin' and normalize('NFD', name) in files:
                # Mac OS X decomposes Unicode names.  See comment above.
                os.stat(name)
                continue
            self._apply_failure(open, name, IOError)
            self._apply_failure(os.stat, name, OSError)
            self._apply_failure(os.chdir, name, OSError)
            self._apply_failure(os.rmdir, name, OSError)
            self._apply_failure(os.remove, name, OSError)
            # listdir may append a wildcard to the filename, so dont check
            self._apply_failure(os.listdir, name, OSError, False)

    def test_listdir(self):
        sf0 = set(self.files)
        f1 = os.listdir(test_support.TESTFN)
        f2 = os.listdir(unicode(test_support.TESTFN,
                                sys.getfilesystemencoding()))
        if sys.platform == 'darwin':
            # Mac OS X decomposes Unicode names.  See comment above.
            sf0 = set(normalize('NFD', unicode(f)) for f in self.files)
            f2 = [normalize('NFD', unicode(f)) for f in f2]
        sf2 = set(os.path.join(unicode(test_support.TESTFN), f) for f in f2)
        self.assertEqual(sf0, sf2)
        self.assertEqual(len(f1), len(f2))

    def test_rename(self):
        for name in self.files:
            os.rename(name, "tmp")
            os.rename("tmp", name)

    def test_directory(self):
        dirname = os.path.join(test_support.TESTFN,
                               u'Gr\xfc\xdf-\u66e8\u66e9\u66eb')
        filename = u'\xdf-\u66e8\u66e9\u66eb'
        oldwd = os.getcwd()
        os.mkdir(dirname)
        os.chdir(dirname)
        try:
            with open(filename, 'w') as f:
                f.write((filename + '\n').encode("utf-8"))
            os.access(filename,os.R_OK)
            os.remove(filename)
        finally:
            os.chdir(oldwd)
            os.rmdir(dirname)


class UnicodeNFCFileTests(UnicodeFileTests):
    normal_form = 'NFC'


class UnicodeNFDFileTests(UnicodeFileTests):
    normal_form = 'NFD'


class UnicodeNFKCFileTests(UnicodeFileTests):
    normal_form = 'NFKC'


class UnicodeNFKDFileTests(UnicodeFileTests):
    normal_form = 'NFKD'


def test_main():
    try:
        test_support.run_unittest(
            UnicodeFileTests,
            UnicodeNFCFileTests,
            UnicodeNFDFileTests,
            UnicodeNFKCFileTests,
            UnicodeNFKDFileTests,
        )
    finally:
        deltree(test_support.TESTFN)


if __name__ == "__main__":
    test_main()
