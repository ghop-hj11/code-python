# -*- coding: utf-8 -*-
"""Python++ —— 兼容入口（单文件版）。

以前它是整个解释器，现在真正的实现搬到了同目录下的 ``pythonpp/`` 包里，
这个文件只做转发，保证老的写法一行都不用改：

    from pythonpp import Lang
    lang = Lang()
    lang.run("x = 1 + 1")

两种导入方式行为完全一致：

    import pythonpp          # 导入这个文件 -> 转发到 pythonpp/(包)
    from pythonpp import ... # 同上

新功能（@jit 加速、中文报错、CLI 等）都在包里，用法见 README.md。
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 关键：这个文件本身叫 pythonpp.py，会和 pythonpp/ 包同名。
# 先把"自己"从模块表里摘掉，再导入包，包才能正常初始化。
_self_name = __name__
if _self_name in sys.modules:
    del sys.modules[_self_name]

_pkg_name = "pythonpp"
_existing = sys.modules.get(_pkg_name)
if _existing is not None and getattr(_existing, "__file__", "").endswith("pythonpp.py"):
    del sys.modules[_pkg_name]

import importlib as _importlib

_impl = _importlib.import_module(_pkg_name)

if getattr(_impl, "__file__", "").endswith("pythonpp.py"):
    raise ImportError(
        "pythonpp 包没能加载：请确认 pythonpp/ 目录和本文件在同一个文件夹里。"
    )

# 把包的全部公开名字搬到本模块，这样 pythonpp.Lang 之类照旧可用
for _name in dir(_impl):
    if _name.startswith("__") and _name not in ("__version__", "__all__"):
        continue
    globals()[_name] = getattr(_impl, _name)

# 让 sys.modules['pythonpp'] 指向真正的包，后续 import 直接命中包
sys.modules[_pkg_name] = _impl

__doc__ = _impl.__doc__
__all__ = getattr(_impl, "__all__", [])
