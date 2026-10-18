# -*- coding: utf-8 -*-
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

__all__ = [
    "Lang",
    "MemPool",
    "bocodepy",
    "mkdir",
    "nex",
    "pwd",
    "random",
    "read",
    "seed",
    "touch",
    "write",
]

_MISSING = object()


def _deep_sizeof(obj):
    seen = set()
    pending = [obj]
    total = 0
    while pending:
        current = pending.pop()
        obj_id = id(current)
        if obj_id in seen:
            continue
        seen.add(obj_id)
        try:
            total += sys.getsizeof(current)
        except TypeError:
            continue
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple, set, frozenset)):
            pending.extend(current)
    return total


class MemPool:
    def __init__(self, max_bytes=64 * 1024 * 1024,
                 high_watermark=0.8, low_watermark=0.5,
                 on_evict=None):
        if not 0 < low_watermark < high_watermark <= 1:
            raise ValueError("水位参数必须满足 0 < low < high <= 1")
        self._max_bytes = int(max_bytes)
        self._high = float(high_watermark)
        self._low = float(low_watermark)
        self._on_evict = on_evict
        self._store = OrderedDict()
        self._sizes = {}
        self._used = 0
        self._lock = threading.RLock()

    def add(self, name, value=_MISSING):
        if not isinstance(name, str):
            raise TypeError("变量名必须是字符串")
        if value is _MISSING:
            value = self._resolve_from_caller(name)
        size = _deep_sizeof(value)
        with self._lock:
            if size > self._max_bytes:
                raise MemoryError(
                    f"变量 {name!r} 估算占用 {size} 字节，"
                    f"已超过池子上限 {self._max_bytes} 字节"
                )
            if name in self._store:
                self._drop(name)
            high_limit = int(self._max_bytes * self._high)
            low_limit = int(self._max_bytes * self._low)
            if self._used + size > high_limit:
                while self._used + size > low_limit and self._store:
                    self._evict_one()
            self._store[name] = value
            self._sizes[name] = size
            self._used += size
        return name

    def takeout(self, name):
        with self._lock:
            if name not in self._store:
                raise KeyError(f"池子里没有名为 {name!r} 的变量")
            value = self._store[name]
            self._drop(name)
            return value

    def remove(self, name):
        with self._lock:
            if name not in self._store:
                raise KeyError(f"池子里没有名为 {name!r} 的变量")
            self._drop(name)

    def peek(self, name):
        with self._lock:
            if name not in self._store:
                raise KeyError(f"池子里没有名为 {name!r} 的变量")
            self._store.move_to_end(name)
            return self._store[name]

    def keys(self):
        with self._lock:
            return list(self._store.keys())

    def clear(self):
        with self._lock:
            self._store.clear()
            self._sizes.clear()
            self._used = 0

    @property
    def used_bytes(self):
        with self._lock:
            return self._used

    @property
    def free_bytes(self):
        with self._lock:
            return self._max_bytes - self._used

    @property
    def max_bytes(self):
        return self._max_bytes

    def stats(self):
        with self._lock:
            return {
                "变量个数": len(self._store),
                "已用字节": self._used,
                "容量字节": self._max_bytes,
                "占用比例": round(self._used / self._max_bytes, 4) if self._max_bytes else 0,
                "变量列表": list(self._store.keys()),
            }

    def _resolve_from_caller(self, name):
        frame = sys._getframe(2)
        if name in frame.f_locals:
            return frame.f_locals[name]
        if name in frame.f_globals:
            return frame.f_globals[name]
        raise NameError(
            f"找不到名为 {name!r} 的变量；"
            f"也可以显式传值：pool.add({name!r}, value)"
        )

    def _drop(self, name):
        value = self._store.pop(name)
        self._used -= self._sizes.pop(name)
        return value

    def _evict_one(self):
        name, value = self._store.popitem(last=False)
        self._used -= self._sizes.pop(name)
        if self._on_evict is not None:
            try:
                self._on_evict(name, value)
            except Exception:
                pass
        return name

    def __contains__(self, name):
        with self._lock:
            return name in self._store

    def __len__(self):
        with self._lock:
            return len(self._store)

    def __getitem__(self, name):
        return self.peek(name)

    def __setitem__(self, name, value):
        self.add(name, value)

    def __delitem__(self, name):
        self.remove(name)

    def __repr__(self):
        with self._lock:
            return (f"<MemPool {len(self._store)} 项, "
                    f"{self._used}/{self._max_bytes} 字节>")


def nex():
    pass


def bocodepy():
    print("8:16")


def pwd():
    """返回当前工作目录。"""
    return str(Path.cwd())


def mkdir(path):
    """创建目录（含不存在的父目录），并返回其路径。"""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def touch(path):
    """创建空文件；文件已存在时保留内容并更新时间。"""
    target = Path(path)
    target.touch(exist_ok=True)
    return str(target)


def read(path, encoding="utf-8"):
    """读取文本文件。"""
    return Path(path).read_text(encoding=encoding)


def write(path, content, append=False, encoding="utf-8"):
    """写入文本文件；append=True 时追加到文件末尾。"""
    target = Path(path)
    mode = "a" if append else "w"
    with target.open(mode, encoding=encoding) as file:
        file.write(content)
    return str(target)


# ================= fastrand =================
_MASK = 0xFFFFFFFF
_state = 0x9E3779B9


def seed(s=None):
    global _state
    if s is None:
        s = time.time_ns() & _MASK
    s &= _MASK
    _state = s if s else 0x9E3779B9


def _next():
    global _state
    x = _state
    x ^= (x << 13) & _MASK
    x ^= x >> 17
    x ^= (x << 5) & _MASK
    _state = x
    return x


def random(a="1~20", b=None):
    """
    random()            -> 1~20
    random(1, 20)       -> 1~20
    random("1~20")      -> 1~20
    random("5~100")     -> 5~100
    """
    if b is not None:
        lo, hi = int(a), int(b)
    elif isinstance(a, str):
        lo, hi = a.split("~")
        lo, hi = int(lo.strip()), int(hi.strip())
    elif isinstance(a, int):
        lo, hi = a, 20
    else:
        raise TypeError
    if hi < lo:
        lo, hi = hi, lo
    return lo + _next() % (hi - lo + 1)


# ================= Lang =================
class Lang:
    """
    继承 Python 语法的迷你语言。
    执行引擎：CPython 的 exec / eval（内存由 Python 管）
    变量收纳：MemPool（跨函数共享，不用传参）
    容量管理：池子自动兜底，你不用管
    """

    def __init__(self, pool=None):
        self.pool = pool if pool is not None else MemPool()
        self._builtins = {
            "random": random,
            "seed": seed,
            "nex": nex,
            "bocodepy": bocodepy,
            "pwd": pwd,
            "mkdir": mkdir,
            "touch": touch,
            "read": read,
            "write": write,
        }
        self._ns = {"__name__": "__main__"}
        self._ns.update(self._builtins)

    def run(self, source):
        """执行一段 Python 代码。顶层变量自动进池子。"""
        self._ns.update(self.pool._store)
        exec(compile(source, "<lang>", "exec"), self._ns)
        self._sync_back()

    def eval(self, expr):
        """算一个表达式并返回。"""
        self._ns.update(self.pool._store)
        return eval(compile(expr, "<lang>", "eval"), self._ns)

    def _sync_back(self):
        user = {k: v for k, v in self._ns.items()
                if not (k.startswith("__") and k.endswith("__"))
                and k not in self._builtins}
        # 写回池子：先清空，再逐个 add
        self.pool.clear()
        for k, v in user.items():
            try:
                self.pool.add(k, v)
            except MemoryError:
                pass

    # ---------- Linux 风格操作 ----------
    def rm(self, name):
        """删除变量。"""
        self.pool.remove(name)
        self._ns.pop(name, None)

    def ls(self):
        """列出所有变量名。"""
        return self.pool.keys()

    def cat(self, name):
        """查看变量值（不删）。"""
        return self.pool.peek(name)

    def stats(self):
        """池子状态。"""
        return self.pool.stats()

    def add(self, name, value=_MISSING):
        """手动加变量。不传 value 时抓调用方的同名变量。"""
        if value is _MISSING:
            value = self.pool._resolve_from_caller(name)
        self.pool.add(name, value)
        self._ns[name] = value

    def pwd(self):
        """返回当前工作目录。"""
        return pwd()

    def mkdir(self, path):
        """创建目录并返回其路径。"""
        return mkdir(path)

    def touch(self, path):
        """创建空文件并返回其路径。"""
        return touch(path)

    def read(self, path, encoding="utf-8"):
        """读取文本文件。"""
        return read(path, encoding)

    def write(self, path, content, append=False, encoding="utf-8"):
        """写入文本文件并返回其路径。"""
        return write(path, content, append, encoding)
        