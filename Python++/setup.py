# -*- coding: utf-8 -*-
"""Python++ 的打包配置。

这里刻意做了一件在 Python 生态里不太常见、但对本项目很合适的事：
**把编译好的 .pyd 直接打进 wheel**，而不是在用户机器上现场编译。

原因：
    * 我们用稳定 ABI（Py_LIMITED_API=3.8），一个 .pyd 就能覆盖 3.8 ~ 3.14，
      不需要为每个 Python 版本各出一份；
    * 用户装包时不需要 C 编译器、不需要联网拉工具链，`pip install` 就能用；
    * 没匹配上的平台会自动装「纯 Python 版」——功能一样，只是慢一点。

产物命名规则见 README 的「发布」一节。
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

HERE = Path(__file__).resolve().parent
PKG = HERE / "pythonpp"
NATIVE = PKG / "_pythonpp_native.pyd"

LONG_DESCRIPTION = (HERE / "README.md").read_text(encoding="utf-8")

# 平台标签：Windows 只有 amd64 的产物，其它平台走纯 Python 版本
def _platform_tag():
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "windows":
        return "win_amd64" if machine in ("amd64", "x86_64") else "win_arm64"
    if system == "linux":
        return "manylinux2014_x86_64" if machine in ("x86_64", "amd64") else "manylinux2014_aarch64"
    if system == "darwin":
        return "macosx_11_0_arm64" if machine == "arm64" else "macosx_10_9_x86_64"
    return "any"


PLATFORM_TAG = _platform_tag()


class build_py(_build_py):
    """构建时顺手把 .pyd 一起带上。

    如果当前平台没有对应的 .pyd（比如在 Linux 上打 Windows 的包），
    就直接跳过，产出一个纯 Python 的 wheel —— 装上去照样能用。
    """

    def run(self):
        super().run()
        if NATIVE.exists():
            target = Path(self.build_lib) / "pythonpp" / NATIVE.name
            target.parent.mkdir(parents=True, exist_ok=True)
            self.copy_file(str(NATIVE), str(target))
            self.announce(f"打包原生内核：{NATIVE.name}", level=2)
        else:
            self.announce("没有找到 .pyd，产出纯 Python 版本", level=2)


def _has_native() -> bool:
    return NATIVE.exists()


setup(
    name="pythonpp",
    version="1.0.0",
    description="Python 语法 + C 加速：内置常用函数、中文报错、整数循环 JIT",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="Python++",
    license="MIT",
    python_requires=">=3.8",
    packages=["pythonpp"],
    package_data={
        "pythonpp": ["pythonpp_native.c"],
    },
    include_package_data=True,
    # 有 .pyd 就打平台包（platlib），没有就打纯 Python 包
    has_ext_modules=lambda: _has_native(),
    cmdclass={"build_py": build_py},
    zip_safe=False,
    entry_points={
        "console_scripts": [
            "pythonpp=pythonpp._cli:main",
            "pp=pythonpp._cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Programming Language :: C",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
        "Topic :: Software Development :: Interpreters",
        "Natural Language :: Chinese (Simplified)",
    ],
    keywords="python accelerator jit c-extension chinese",
)
