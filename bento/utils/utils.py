import os
import sys
import stat
import re
import glob
import shutil
import errno
import subprocess
import shlex

from six.moves \
    import \
        cPickle

import os.path as op

from bento.compat.api \
    import \
        partial

try:
    from hashlib import md5
except ImportError:
    from md5 import md5



# Color handling for terminals (taken from waf)
COLORS_LST = {
        'USE' : True,
        'BOLD'  :'\x1b[01;1m',
        'RED'   :'\x1b[01;31m',
        'GREEN' :'\x1b[32m',
        'YELLOW':'\x1b[33m',
        'PINK'  :'\x1b[35m',
        'BLUE'  :'\x1b[01;34m',
        'CYAN'  :'\x1b[36m',
        'NORMAL':'\x1b[0m',
        'cursor_on'  :'\x1b[?25h',
        'cursor_off' :'\x1b[?25l',
}

GOT_TTY = not os.environ.get('TERM', 'dumb') in ['dumb', 'emacs']
if GOT_TTY:
    try:
        GOT_TTY = sys.stderr.isatty()
    except AttributeError:
        GOT_TTY = False
if not GOT_TTY or 'NOCOLOR' in os.environ:
    COLORS_LST['USE'] = False

def get_color(cl):
    if not COLORS_LST['USE']:
        return ''
    return COLORS_LST.get(cl, '')

class foo(object):
    def __getattr__(self, a):
        return get_color(a)
    def __call__(self, a):
        return get_color(a)
COLORS = foo()

def pprint(color, s, fout=None):
    if fout is None:
        fout = sys.stderr
    fout.write('%s%s%s\n' % (COLORS(color), s, COLORS('NORMAL')))

_IDPATTERN = "[a-zA-Z_][a-zA-Z_0-9]*"
_DELIM = "$"

def _simple_subst_vars(s, local_vars):
    """Like subst_vars, but does not handle escaping."""
    def _subst(m):
        var_name = m.group(1)
        if var_name in local_vars:
            return local_vars[var_name]
        else:
            raise ValueError("%s not defined" % var_name)
        
    def _resolve(d):
        ret = {}
        for k, v in list(d.items()):
            ret[k] = re.sub("\%s(%s)" % (_DELIM, _IDPATTERN), _subst, v)
        return ret

    ret = _resolve(s)
    while not ret == s:
        s = ret
        ret = _resolve(s)
    return ret

def subst_vars (s, local_vars):
    """Perform shell/Perl-style variable substitution.

    Every occurrence of '$' followed by a name is considered a variable, and
    variable is substituted by the value found in the `local_vars' dictionary.
    Raise ValueError for any variables not found in `local_vars'.

    '$' may be escaped by using '$$'

    Parameters
    ----------
    s: str
        variable to substitute
    local_vars: dict
        dict of variables
    """
    # Resolve variable substitution within the local_vars dict
    local_vars = _simple_subst_vars(local_vars, local_vars)

    def _subst (match):
        named = match.group("named")
        if named is not None:
            if named in local_vars:
                return str(local_vars[named])
            else:
                raise ValueError("Invalid variable '%s'" % named)
        if match.group("escaped") is not None:
            return _DELIM
        raise ValueError("This should not happen")

    def _do_subst(v):
        pattern_s = r"""
        %(delim)s(?:
            (?P<escaped>%(delim)s) |
            (?P<named>%(id)s)
        )""" % {"delim": r"\%s" % _DELIM, "id": _IDPATTERN}
        pattern = re.compile(pattern_s, re.VERBOSE)
        return pattern.sub(_subst, v)

    try:
        return _do_subst(s)
    except KeyError:
        raise ValueError("invalid variable '$%s'" % ex_stack())

# Taken from multiprocessing code
def cpu_count():
    '''
    Returns the number of CPUs in the system
    '''
    if sys.platform == 'win32':
        try:
            num = int(os.environ['NUMBER_OF_PROCESSORS'])
        except (ValueError, KeyError):
            num = 0
    elif 'bsd' in sys.platform or sys.platform == 'darwin':
        try:
            num = int(os.popen('sysctl -n hw.ncpu').read())
        except ValueError:
            num = 0
    else:
        try:
            num = os.sysconf('SC_NPROCESSORS_ONLN')
        except (ValueError, OSError, AttributeError):
            num = 0

    if num >= 1:
        return num
    else:
        return 1
        #raise NotImplementedError('cannot determine number of cpus')

def same_content(f1, f2):
    """Return true if files in f1 and f2 has the same content."""
    fid1 = open(f1, "rb")
    try:
        fid2 = open(f2, "rb")
        try:
            return md5(fid1.read()).digest() == md5(fid2.read()).digest()
        finally:
            fid2.close()
    finally:
        fid1.close()

def virtualenv_prefix():
    """Return the virtual environment prefix if running python is "virtualized"
    (i.e. run inside virtualenv), None otherwise."""
    try:
        real_prefix = sys.real_prefix
    except AttributeError:
        return None
    else:
        if real_prefix != sys.prefix:
            return op.normpath(sys.prefix)
        else:
            return None

def to_camel_case(s):
    """Transform a string to camel case convention."""
    if len(s) < 1:
        return ""
    else:
        # XXX: could most likely be simpler with regex ?
        ret = []
        if s[0].isalpha():
            ret.append(s[0].upper())
            i = 1
        elif s[0] == "_":
            i = 0
            while i < len(s) and s[i] == "_":
                ret.append(s[i])
                i += 1
            if i < len(s) and s[i].isalpha():
                ret.append(s[i].upper())
                i += 1
        else:
            i = 0
        while i < len(s):
            c = s[i]
            if c == "_" and i < len(s) - 1 and s[i+1].isalpha():
                ret.append(s[i+1].upper())
                i += 1
            else:
                ret.append(c)
            i += 1
        return "".join(ret)


# We sometimes use keys from json dictionary as key word arguments. This may
# not work because python2.5 and below requires arguments to be string and not
# unicode while json may decode stuff as unicode, or alternatively encoding as
# ascii does not work in python3 which requires string (==unicode) there. Or
# maybe I just don't understand how this works...
def fix_kw(kw):
    """Make sure the given dictionary may be used as a kw dict independently on
    the python version and encoding of kw's keys."""
    return dict([(str(k), v) for k, v in list(kw.items())])

def cmd_is_runnable(cmd, **kw):
    """Test whether the given command can work.

    Notes
    -----
    Arguments are the same as subprocess.Popen, except for stdout/stderr
    defaults (to PIPE)
    """
    for stream in ["stdout", "stderr"]:
        if not stream in kw:
            kw[stream] = subprocess.PIPE
    try:
        p = subprocess.Popen(cmd, **kw)
        p.communicate()
        return p.returncode == 0
    except OSError:
        e = extract_exception()
        if e.errno == 2:
            return False
        else:
            raise

def explode_path(path):
    """Split a path into its components.

    If the path is absolute, the first value of the returned list will be '/',
    or the drive letter for platforms where it is applicable.

    Example
    -------
    >>> explode_path("/Users/joe")
    ["/", "Users", "joe"]
    """
    ret = []
    d, p = op.splitdrive(path)

    while p:
        head, tail = op.split(p)
        if head == p:
            ret.append(head)
            break
        if tail:
            ret.append(tail)
        p = head
    if d:
        ret.append(d)
    return ret[::-1]

if sys.version_info[0] < 3:
    def is_string(s):
        return isinstance(s, str) or isinstance(s, str)
else:
    def is_string(s):
        return isinstance(s, str)

def extract_exception():
    """Extract the last exception.

    Used to avoid the except ExceptionType as e, which cannot be written the
    same across supported versions. I.e::

        try:
            ...
        except Exception, e:
            ...

    becomes:

        try:
            ...
        except Exception:
            e = extract_exception()
    """
    return sys.exc_info()[1]

# We cannot use octal literal for compat with python 3.x
MODE_755 = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | \
    stat.S_IROTH | stat.S_IXOTH
MODE_777 = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | \
    stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP | \
    stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH

class CommaListLexer(object):
    def __init__(self, instream):
        self._lexer = shlex.shlex(instream, posix=True)
        self._lexer.whitespace += ','
        self._lexer.wordchars += './()*-'
        self.eof = self._lexer.eof

    def get_token(self):
        return self._lexer.get_token()

def comma_list_split(s):
    lexer = CommaListLexer(s)
    ret = []
    t = lexer.get_token()
    while t != lexer.eof:
        ret.append(t)
        t = lexer.get_token()

    return ret

class memoized(object):
    """Decorator that caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated.
    """
    def __init__(self, func):
       self.func = func
       self.cache = {}
    def __call__(self, *args):
       try:
          return self.cache[args]
       except KeyError:
          value = self.func(*args)
          self.cache[args] = value
          return value
       except TypeError:
          # uncachable -- for instance, passing a list as an argument.
          # Better to not cache than to blow up entirely.
          return self.func(*args)

    def __repr__(self):
       """Return the function's docstring."""
       return self.func.__doc__

    def __get__(self, obj, objtype):
       """Support instance methods."""
       return partial(self.__call__, obj)

def read_or_create_dict(filename):
    if op.exists(filename):
        fid = open(filename, "rb")
        try:
            return cPickle.load(fid)
        finally:
            fid.close()
    else:
        return {}
