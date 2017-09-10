import os
import sys
import marshal

# XXX: implementation details from py_compile
from py_compile import \
    wr_long, MAGIC, PyCompileError
import builtins

try:
    from io import StringIO
except ImportError:
    from io import StringIO

def bcompile(source):
    """Return the compiled bytecode from the given filename as a string ."""
    f = open(source, 'U')
    try:
        try:
            timestamp = int(os.fstat(f.fileno()).st_mtime)
        except AttributeError:
            timestamp = int(os.stat(file).st_mtime)
        codestring = f.read()
        f.close()
        if codestring and codestring[-1] != '\n':
            codestring = codestring + '\n'
        try:
            codeobject = builtins.compile(codestring, source, 'exec')
        except Exception as err:
            raise PyCompileError(err.__class__, err.args, source)
        fc = StringIO()
        try:
            fc.write('\0\0\0\0')
            wr_long(fc, timestamp)
            fc.write(marshal.dumps(codeobject))
            fc.flush()
            fc.seek(0, 0)
            fc.write(MAGIC)
            return fc.getvalue()
        finally:
            fc.close()
    finally:
        f.close()
