import sys
import os
import copy
import distutils
import distutils.sysconfig
import re
import warnings

from subprocess \
    import \
        Popen, PIPE, STDOUT

from yaku.task_manager \
    import \
        topo_sort, build_dag, \
        CompiledTaskGen, set_extension_hook
from yaku.sysconfig \
    import \
        get_configuration, detect_distutils_cc
from yaku.compiled_fun \
    import \
        compile_fun
from yaku.task \
    import \
        Task
from yaku.utils \
    import \
        ensure_dir
from yaku.conftests \
    import \
        check_compiler, check_header

import yaku.tools

pylink, pylink_vars = compile_fun("pylink", "${PYEXT_SHLINK} ${PYEXT_LINK_TGT_F}${TGT[0].abspath()} ${PYEXT_LINK_SRC_F}${SRC} ${PYEXT_APP_LIBDIR} ${PYEXT_APP_LIBS} ${PYEXT_APP_FRAMEWORKS} ${PYEXT_SHLINKFLAGS}", False)

pycc, pycc_vars = compile_fun("pycc", "${PYEXT_CC} ${PYEXT_CFLAGS} ${PYEXT_INCPATH} ${PYEXT_CC_TGT_F}${TGT[0].abspath()} ${PYEXT_CC_SRC_F}${SRC}", False)

pycxx, pycxx_vars = compile_fun("pycxx", "${PYEXT_CXX} ${PYEXT_CXXFLAGS} ${PYEXT_INCPATH} ${PYEXT_CXX_TGT_F}${TGT[0].abspath()} ${PYEXT_CXX_SRC_F}${SRC}", False)

pycxxlink, pycxxlink_vars = compile_fun("pycxxlink", "${PYEXT_CXXSHLINK} ${PYEXT_LINK_TGT_F}${TGT[0].abspath()} ${PYEXT_LINK_SRC_F}${SRC} ${PYEXT_APP_LIBDIR} ${PYEXT_APP_LIBS} ${PYEXT_APP_FRAMEWORKS} ${PYEXT_SHLINKFLAGS}", False)

# pyext env <-> sysconfig env conversion

_SYS_TO_PYENV = {
        "PYEXT_SHCC": "CC",
        "PYEXT_CCSHARED": "CCSHARED",
        "PYEXT_SHLINK": "LDSHARED",
        "PYEXT_SUFFIX": "SO",
        "PYEXT_CFLAGS": "CFLAGS",
        "PYEXT_OPT": "OPT",
        "PYEXT_LIBDIR": "LIBDIR",
}

_PYENV_REQUIRED = [
        "LIBDIR_FMT",
        "LIBS",
        "LIB_FMT",
        "CPPPATH_FMT",
        "CC_TGT_F",
        "CC_SRC_F",
        "LINK_TGT_F",
        "LINK_SRC_F",
]

_SYS_TO_CCENV = {
        "CC": "CC",
        "SHCC": "CCSHARED",
        "SHLINK": "LDSHARED",
        "SO": "SO",
        "CFLAGS": "CFLAGS",
        "OPT": "OPT",
        "LIBDIR": "LIBDIR",
        "LIBDIR_FMT": "LIBDIR_FMT",
        "LIBS": "LIBS",
        "LIB_FMT": "LIB_FMT",
        "CPPPATH_FMT": "CPPPATH_FMT",
        "CC_TGT_F": "CC_TGT_F",
        "CC_SRC_F": "CC_SRC_F",
        "CXX": "CXX",
        "CXXSHLINK": "CXXSHLINK",
}

def setup_pyext_env(ctx, cc_type="default", use_distutils=True):
    pyenv = {}
    if use_distutils:
        if cc_type == "default":
            dist_env = get_configuration()
        else:
            dist_env = get_configuration(cc_type)
    else:
        dist_env = {
                "CC": ["clang"],
                "CPPPATH": [],
                "BASE_CFLAGS": ["-fno-strict-aliasing"],
                "OPT": [],
                "SHARED": ["-fPIC"],
                "SHLINK": ["clang", "-shared"],
                "LDFLAGS": [],
                "LIBDIR": [],
                "LIBS": [],
                "SO": ".so"}
        dist_env["CPPPATH"].append(distutils.sysconfig.get_python_inc())

    for name, value in dist_env.items():
        pyenv["PYEXT_%s" % name] = value
    pyenv["PYEXT_FMT"] = "%%s%s" % dist_env["SO"]
    pyenv["PYEXT_CFLAGS"] = pyenv["PYEXT_BASE_CFLAGS"] + \
            pyenv["PYEXT_OPT"] + \
            pyenv["PYEXT_SHARED"]
    pyenv["PYEXT_SHLINKFLAGS"] = dist_env["LDFLAGS"]
    return pyenv

def pycc_hook(self, node):
    tasks = pycc_task(self, node)
    self.object_tasks.extend(tasks)
    return tasks

def pycc_task(self, node):
    base = self.env["CC_OBJECT_FMT"] % node.name
    target = node.parent.declare(base)
    ensure_dir(target.abspath())

    task = Task("pycc", inputs=[node], outputs=[target])
    task.gen = self
    task.env_vars = pycc_vars
    task.env = self.env
    task.func = pycc
    return [task]

def pycxx_hook(self, node):
    tasks = pycxx_task(self, node)
    self.object_tasks.extend(tasks)
    self.has_cxx = True
    return tasks

def pycxx_task(self, node):
    base = self.env["CXX_OBJECT_FMT"] % node.name
    target = node.parent.declare(base)
    ensure_dir(target.abspath())

    task = Task("pycxx", inputs=[node], outputs=[target])
    task.gen = self
    task.env_vars = pycxx_vars
    task.env = self.env
    task.func = pycxx
    return [task]

def pylink_task(self, name):
    objects = [tsk.outputs[0] for tsk in self.object_tasks]
    if len(objects) < 1:
        warnings.warn("task %s has no inputs !" % name)
    def declare_target():
        folder, base = os.path.split(name)
        tmp = folder + os.path.sep + self.env["PYEXT_FMT"] % base
        return self.bld.src_root.declare(tmp)
    target = declare_target()
    ensure_dir(target.abspath())

    task = Task("pylink", inputs=objects, outputs=[target])
    task.gen = self
    task.func = pylink
    task.env_vars = pylink_vars
    self.link_task = task

    return [task]

# XXX: fix merge env location+api
from yaku.tools.ctasks import _merge_env
class PythonBuilder(object):
    def clone(self):
        return PythonBuilder(self.ctx)

    def __init__(self, ctx):
        self.ctx = ctx
        self.env = copy.deepcopy(ctx.env)
        self.compiler_type = "default"
        self.use_distutils = True

    def extension(self, name, sources, env=None):
        sources = [self.ctx.src_root.find_resource(s) for s in sources]
        return create_pyext(self.ctx, name, sources,
                _merge_env(self.env, env))

def get_builder(ctx):
    return PythonBuilder(ctx)

CC_SIGNATURE = {
        "gcc": re.compile("gcc version"),
        "msvc": re.compile("Microsoft \(R\) 32-bit C/C\+\+ Optimizing Compiler")
}

def detect_cc_type(ctx, cc_cmd):
    cc_type = None

    def detect_type(vflag):
        cmd = cc_cmd + [vflag]
        try:
            p = Popen(cmd, stdout=PIPE, stderr=STDOUT)
            out = p.communicate()[0].decode()
            for k, v in CC_SIGNATURE.items():
                m = v.search(out)
                if m:
                    return k
        except OSError:
            pass
        return None

    sys.stderr.write("Detecting CC type... ")
    if sys.platform == "win32":
        for v in ["", "-v"]:
            cc_type = detect_type(v)
    else:
        for v in ["-v", "-V", "-###"]:
            cc_type = detect_type(v)
            if cc_type:
                break
        if cc_type is None:
            cc_type = "cc"
    sys.stderr.write("%s\n" % cc_type)
    return cc_type

def get_distutils_cc_exec(ctx, compiler_type="default"):
    from distutils import ccompiler

    sys.stderr.write("Detecting distutils CC exec ... ")
    if compiler_type == "default":
        compiler_type = \
                distutils.ccompiler.get_default_compiler()

    compiler = ccompiler.new_compiler(compiler=compiler_type)
    if compiler_type == "msvc":
        compiler.initialize()
        cc = [compiler.cc]
    else:
        cc = compiler.compiler_so
    sys.stderr.write("%s\n" % " ".join(cc))
    return cc

def configure(ctx):
    # How we do it
    # 1: for distutils-based configuration
    #   - get compile/flags flags from sysconfig
    #   - detect yaku tool name from CC used by distutils:
    #       - get the compiler executable used by distutils ($CC
    #       variable)
    #       - try to determine yaku tool name from $CC
    #   - apply necessary variables from yaku tool to $PYEXT_
    #   "namespace"
    compiler_type = ctx.builders["pyext"].compiler_type

    if ctx.builders["pyext"].use_distutils:
        dist_env = setup_pyext_env(ctx, compiler_type)
        ctx.env.update(dist_env)

        cc_exec = get_distutils_cc_exec(ctx, compiler_type)
        yaku_cc_type = detect_cc_type(ctx, cc_exec)

        _setup_compiler(ctx, yaku_cc_type)
    else:
        dist_env = setup_pyext_env(ctx, compiler_type, False)
        ctx.env.update(dist_env)
        _setup_compiler(ctx, compiler_type)

def _setup_compiler(ctx, cc_type):
    old_env = ctx.env
    ctx.env = {}
    cc_env = None
    sys.path.insert(0, os.path.dirname(yaku.tools.__file__))
    try:
        try:
            mod = __import__(cc_type)
            mod.setup(ctx)
        except ImportError:
            raise RuntimeError("No tool %s is available (import failed)" \
                            % cc_type)

        # XXX: this is ugly - find a way to have tool-specific env...
        cc_env = ctx.env
    finally:
        sys.path.pop(0)
        ctx.env = old_env

    copied_values = ["CPPPATH_FMT", "LIBDIR_FMT", "LIB_FMT",
            "CC_OBJECT_FMT", "CC_TGT_F", "CC_SRC_F", "LINK_TGT_F",
            "LINK_SRC_F"]
    for k in copied_values:
        ctx.env["PYEXT_%s" % k] = cc_env[k]

    def setup_cxx():
        old_env = ctx.env
        ctx.env = {}
        sys.path.insert(0, os.path.dirname(yaku.tools.__file__))
        try:
            mod = __import__("gxx")
            mod.setup(ctx)
            cxx_env = ctx.env
        finally:
            sys.path.pop(0)
            ctx.env = old_env

        for k in ["CXX", "CXXFLAGS", "CXX_TGT_F", "CXX_SRC_F",
                  "CXXSHLINK"]:
            ctx.env["PYEXT_%s" % k] = cxx_env[k]
    setup_cxx()

def create_pyext(bld, name, sources, env):
    base = name.replace(".", os.sep)

    tasks = []

    task_gen = CompiledTaskGen("pyext", bld, sources, name)
    task_gen.bld = bld
    old_hook = set_extension_hook(".c", pycc_hook)
    old_hook_cxx = set_extension_hook(".cxx", pycxx_hook)

    task_gen.env = env
    apply_cpppath(task_gen)
    apply_libpath(task_gen)
    apply_libs(task_gen)
    apply_frameworks(task_gen)

    tasks = task_gen.process()

    ltask = pylink_task(task_gen, base)
    if task_gen.has_cxx:
        task_gen.link_task.func = pycxxlink
        task_gen.link_task.env_vars = pycxxlink_vars

    tasks.extend(ltask)
    for t in tasks:
        t.env = task_gen.env

    set_extension_hook(".c", old_hook)
    set_extension_hook(".cxx", old_hook_cxx)
    bld.tasks.extend(tasks)

    outputs = []
    for t in ltask:
        outputs.extend(t.outputs)
    task_gen.outputs = outputs
    return tasks

# FIXME: find a way to reuse this kind of code between tools
def apply_frameworks(task_gen):
    # XXX: do this correctly (platform specific tool config)
    if sys.platform == "darwin":
        frameworks = task_gen.env["PYEXT_FRAMEWORKS"]
        task_gen.env["PYEXT_APP_FRAMEWORKS"] = []
        for framework in frameworks:
            task_gen.env["PYEXT_APP_FRAMEWORKS"].extend(["-framework", framework])
    else:
        task_gen.env["PYEXT_APP_FRAMEWORKS"] = []

def apply_libs(task_gen):
    libs = task_gen.env["PYEXT_LIBS"]
    task_gen.env["PYEXT_APP_LIBS"] = [
            task_gen.env["PYEXT_LIB_FMT"] % lib for lib in libs]

def apply_libpath(task_gen):
    libdir = task_gen.env["PYEXT_LIBDIR"]
    #implicit_paths = set([
    #    os.path.join(task_gen.env["BLDDIR"], os.path.dirname(s))
    #    for s in task_gen.sources])
    implicit_paths = []
    libdir = list(implicit_paths) + libdir
    task_gen.env["PYEXT_APP_LIBDIR"] = [
            task_gen.env["PYEXT_LIBDIR_FMT"] % d for d in libdir]

def apply_cpppath(task_gen):
    cpppaths = task_gen.env["PYEXT_CPPPATH"]
    implicit_paths = set([s.parent.srcpath() \
                          for s in task_gen.sources])
    srcnode = task_gen.sources[0].ctx.srcnode

    relcpppaths = []
    for p in cpppaths:
        if not os.path.isabs(p):
            node = srcnode.find_node(p)
            assert node is not None, "could not find %s" % p
            relcpppaths.append(node.bldpath())
        else:
            relcpppaths.append(p)
    cpppaths = list(implicit_paths) + relcpppaths
    task_gen.env["PYEXT_INCPATH"] = [
            task_gen.env["PYEXT_CPPPATH_FMT"] % p
            for p in cpppaths]
