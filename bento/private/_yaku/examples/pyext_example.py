import os
import sys

from yaku.scheduler \
    import \
        run_tasks
from yaku.context \
    import \
        get_bld, get_cfg

from yaku.conftests \
    import \
        check_compiler, check_header

def configure(ctx):
    ctx.use_tools(["pyext", "ctasks"], ["tools"])

    check_compiler(ctx)
    check_header(ctx, "stdio.h")

def build(ctx):
    builder = ctx.builders["pyext"]
    builder.extension("_bar", ["src/hellomodule.c"])

if __name__ == "__main__":
    ctx = get_cfg()
    configure(ctx)
    ctx.store()

    ctx = get_bld()
    build(ctx)
    run_tasks(ctx)
    ctx.store()
