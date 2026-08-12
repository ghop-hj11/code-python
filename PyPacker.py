# -*- coding: utf-8 -*-
"""
PyPacker - 一键打包工具
白灰简洁 · 商业风格 · 快速高效
该软件由 code-Python 团队制作
"""

import os
import sys
import queue
import shutil
import threading
import subprocess
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ------------------------------------------------------------------ #
# 配色方案：白灰商业风
# ------------------------------------------------------------------ #
COLOR_BG        = "#F5F6F8"   # 主背景（浅灰白）
COLOR_PANEL     = "#FFFFFF"   # 面板（纯白）
COLOR_BORDER    = "#E2E5EA"   # 边框
COLOR_TEXT      = "#2B2F36"   # 主文字（深灰）
COLOR_SUBTEXT   = "#8A9099"   # 次要文字
COLOR_ACCENT    = "#3A3F47"   # 强调（炭灰按钮）
COLOR_ACCENT_HV = "#20242A"   # 强调 hover
COLOR_LOG_BG    = "#FBFBFC"   # 日志背景
COLOR_LOG_INFO  = "#3A3F47"
COLOR_LOG_OK    = "#1E9E5A"
COLOR_LOG_WARN  = "#C7861C"
COLOR_LOG_ERR   = "#D64545"

FOOTER_TEXT = "该软件由 code-Python 团队制作"
OFFICIAL_URL = "http://11110.cloud/static_web/6a7ac8a9ec5d35.70524182.html"


# Windows 下彻底隐藏子进程控制台窗口（含 py.exe 这类会闪黑框的启动器）
if os.name == "nt":
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUPINFO.wShowWindow = 0  # SW_HIDE
else:
    _NO_WINDOW = 0
    _STARTUPINFO = None


def _silent_run(cmd, **kwargs):
    """subprocess.run 的静默封装：绝不弹出黑框。"""
    return subprocess.run(cmd, creationflags=_NO_WINDOW,
                          startupinfo=_STARTUPINFO, **kwargs)


def _silent_popen(cmd, **kwargs):
    """subprocess.Popen 的静默封装：绝不弹出黑框。"""
    return subprocess.Popen(cmd, creationflags=_NO_WINDOW,
                            startupinfo=_STARTUPINFO, **kwargs)


def _has_pyinstaller(py: str) -> bool:
    """检测给定解释器是否安装了 PyInstaller。"""
    try:
        r = _silent_run(
            [py, "-m", "PyInstaller", "--version"],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _candidate_interpreters() -> list[str]:
    """收集所有可能的真实 Python 解释器路径（去重，保持顺序）。

    关键：当本程序被 PyInstaller 打包成 exe 运行时，sys.executable 指向的是
    exe 自身而非 Python 解释器，绝不能用它去调用 PyInstaller，否则会不断
    启动新的程序窗口、看似「一直转但没有结果」。
    """
    cands: list[str] = []

    def add(p):
        if p and p not in cands:
            cands.append(p)

    frozen = getattr(sys, "frozen", False)
    # 仅在「未被打包」时，才信任 sys.executable 是真正的解释器
    if not frozen:
        exe = sys.executable
        try:
            if exe and os.path.isfile(exe) and os.path.getsize(exe) > 0:
                add(exe)
        except OSError:
            pass

    # PATH 上的解释器
    for name in ("python", "python3"):
        found = shutil.which(name)
        try:
            if found and os.path.getsize(found) > 0:  # 排除 0 字节的商店别名
                add(found)
        except OSError:
            continue

    # 通过 py 启动器询问真实解释器路径
    py_launcher = shutil.which("py")
    if py_launcher:
        try:
            r = _silent_run(
                [py_launcher, "-c", "import sys;print(sys.executable)"],
                capture_output=True, text=True, timeout=15)
            out = r.stdout.strip()
            if r.returncode == 0 and out and os.path.isfile(out):
                add(out)
        except (OSError, subprocess.SubprocessError):
            pass
        add(py_launcher)

    # 常见安装位置兜底
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        base = os.path.join(local, "Programs", "Python")
        if os.path.isdir(base):
            for d in os.listdir(base):
                add(os.path.join(base, d, "python.exe"))
    return cands


def resolve_python() -> tuple[str | None, bool]:
    """返回 (可用于打包的 Python 解释器, 该解释器是否已装 PyInstaller)。

    优先返回「已安装 PyInstaller」的解释器；若都没装，则返回第一个可用的
    解释器并标记为未安装，方便上层给出安装提示。找不到任何解释器时返回
    (None, False)。
    """
    cands = _candidate_interpreters()
    first_valid = None
    for py in cands:
        # 确认它真的是个能跑的 Python
        try:
            r = _silent_run(
                [py, "-c", "import sys;print(sys.version)"],
                capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                continue
        except (OSError, subprocess.SubprocessError):
            continue
        if first_valid is None:
            first_valid = py
        if _has_pyinstaller(py):
            return py, True
    return first_valid, False


class PyPackerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.packing = False

        self._setup_window()
        self._setup_style()
        self._build_ui()
        self._poll_log_queue()

    # -------------------------------------------------------------- #
    # 窗口 & 样式
    # -------------------------------------------------------------- #
    def _setup_window(self):
        self.root.title("PyPacker · 一键打包")
        self.root.configure(bg=COLOR_BG)
        w, h = 940, 620
        self.root.minsize(860, 560)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=COLOR_BG)
        style.configure("Panel.TFrame", background=COLOR_PANEL)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Panel.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=COLOR_BG, foreground=COLOR_TEXT,
                        font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Sub.TLabel", background=COLOR_BG, foreground=COLOR_SUBTEXT,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Field.TLabel", background=COLOR_PANEL, foreground=COLOR_SUBTEXT,
                        font=("Microsoft YaHei UI", 9))

        style.configure("TEntry",
                        fieldbackground=COLOR_PANEL, background=COLOR_PANEL,
                        foreground=COLOR_TEXT, bordercolor=COLOR_BORDER,
                        lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER,
                        padding=6)

        # 次要按钮（浏览）
        style.configure("Ghost.TButton",
                        background=COLOR_PANEL, foreground=COLOR_TEXT,
                        bordercolor=COLOR_BORDER, focuscolor=COLOR_PANEL,
                        font=("Microsoft YaHei UI", 9), padding=(12, 6))
        style.map("Ghost.TButton",
                  background=[("active", "#EDEFF2")],
                  bordercolor=[("active", COLOR_SUBTEXT)])

        # 主按钮（开始打包）
        style.configure("Accent.TButton",
                        background=COLOR_ACCENT, foreground="#FFFFFF",
                        bordercolor=COLOR_ACCENT, focuscolor=COLOR_ACCENT,
                        font=("Microsoft YaHei UI", 11, "bold"), padding=(18, 9))
        style.map("Accent.TButton",
                  background=[("active", COLOR_ACCENT_HV), ("disabled", "#C4C8CE")],
                  foreground=[("disabled", "#FFFFFF")])

        style.configure("TCheckbutton", background=COLOR_PANEL,
                        foreground=COLOR_TEXT, font=("Microsoft YaHei UI", 9))
        style.map("TCheckbutton", background=[("active", COLOR_PANEL)])

        style.configure("TProgressbar", background=COLOR_ACCENT,
                        troughcolor=COLOR_BORDER, bordercolor=COLOR_BORDER,
                        lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT)

    # -------------------------------------------------------------- #
    # 界面构建
    # -------------------------------------------------------------- #
    def _build_ui(self):
        outer = ttk.Frame(self.root, style="TFrame")
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        # ---- 顶部标题 ----
        header = ttk.Frame(outer, style="TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="PyPacker", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Python 一键打包 · 直接生成 EXE",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        # 分隔线
        tk.Frame(outer, height=1, bg=COLOR_BORDER).pack(fill="x", pady=(12, 12))

        # ---- 主体：左侧配置 / 右侧日志 ----
        body = ttk.Frame(outer, style="TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=380)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_config_panel(body)
        self._build_log_panel(body)

        # ---- 底部署名 ----
        self._build_footer(outer)

    def _build_config_panel(self, parent):
        panel = tk.Frame(parent, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER,
                         highlightthickness=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        inner = tk.Frame(panel, bg=COLOR_PANEL)
        inner.pack(fill="both", expand=True, padx=20, pady=20)

        self.var_src = tk.StringVar()
        self.var_cache = tk.StringVar()
        self.var_out = tk.StringVar()

        self._field(inner, "源码路径", self.var_src, self._pick_src, is_file=True)
        self._field(inner, "缓存目录", self.var_cache, self._pick_cache)
        self._field(inner, "输出目录", self.var_out, self._pick_out)

        # 选项
        tk.Frame(inner, height=1, bg=COLOR_BORDER).pack(fill="x", pady=(6, 12))
        self.var_onefile = tk.BooleanVar(value=True)
        self.var_noconsole = tk.BooleanVar(value=False)
        self.var_clean = tk.BooleanVar(value=True)
        ttk.Checkbutton(inner, text="打包为单个 EXE 文件 (--onefile)",
                        variable=self.var_onefile).pack(anchor="w", pady=2)
        ttk.Checkbutton(inner, text="隐藏控制台窗口 (--noconsole，适用于GUI程序)",
                        variable=self.var_noconsole).pack(anchor="w", pady=2)
        ttk.Checkbutton(inner, text="打包前清理缓存 (--clean)",
                        variable=self.var_clean).pack(anchor="w", pady=2)

        # 进度条
        self.progress = ttk.Progressbar(inner, mode="indeterminate")
        self.progress.pack(fill="x", pady=(18, 8))

        # 主按钮
        self.btn_pack = ttk.Button(inner, text="开始打包", style="Accent.TButton",
                                   command=self._on_pack_click)
        self.btn_pack.pack(fill="x", pady=(4, 0))

        # 状态
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(inner, textvariable=self.var_status, style="Field.TLabel").pack(
            anchor="w", pady=(10, 0))

    def _field(self, parent, label, var, cmd, is_file=False):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor="w", pady=(0, 3))
        row = tk.Frame(parent, bg=COLOR_PANEL)
        row.pack(fill="x", pady=(0, 12))
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览", style="Ghost.TButton", command=cmd).pack(
            side="left", padx=(8, 0))

    def _build_log_panel(self, parent):
        panel = tk.Frame(parent, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER,
                         highlightthickness=1)
        panel.grid(row=0, column=1, sticky="nsew")

        head = tk.Frame(panel, bg=COLOR_PANEL)
        head.pack(fill="x", padx=16, pady=(14, 6))
        ttk.Label(head, text="打包日志", style="Panel.TLabel",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Button(head, text="清空", style="Ghost.TButton",
                   command=self._clear_log).pack(side="right")

        tk.Frame(panel, height=1, bg=COLOR_BORDER).pack(fill="x", padx=16)

        wrap = tk.Frame(panel, bg=COLOR_PANEL)
        wrap.pack(fill="both", expand=True, padx=16, pady=(10, 16))

        self.log = tk.Text(wrap, bg=COLOR_LOG_BG, fg=COLOR_LOG_INFO,
                           relief="flat", wrap="word", borderwidth=0,
                           font=("Consolas", 9), padx=10, pady=8,
                           state="disabled", cursor="arrow")
        scroll = ttk.Scrollbar(wrap, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.log.tag_config("info", foreground=COLOR_LOG_INFO)
        self.log.tag_config("ok", foreground=COLOR_LOG_OK)
        self.log.tag_config("warn", foreground=COLOR_LOG_WARN)
        self.log.tag_config("err", foreground=COLOR_LOG_ERR)
        self.log.tag_config("time", foreground=COLOR_SUBTEXT)

        self._log("info", "欢迎使用 PyPacker，请选择源码与目录后点击「开始打包」。")

    def _build_footer(self, parent):
        tk.Frame(parent, height=1, bg=COLOR_BORDER).pack(fill="x", pady=(12, 8))
        footer = ttk.Frame(parent, style="TFrame")
        footer.pack(fill="x")
        ttk.Label(footer, text=FOOTER_TEXT, style="Sub.TLabel").pack(side="left")

        link = tk.Label(footer, text="官方网址", bg=COLOR_BG, fg="#2E6FE6",
                        cursor="hand2", font=("Microsoft YaHei UI", 9, "underline"))
        link.pack(side="left", padx=(6, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(OFFICIAL_URL))

        ttk.Label(footer, text=OFFICIAL_URL, style="Sub.TLabel").pack(side="left", padx=(6, 0))

    # -------------------------------------------------------------- #
    # 文件选择
    # -------------------------------------------------------------- #
    def _pick_src(self):
        path = filedialog.askopenfilename(
            title="选择要打包的 Python 源码",
            filetypes=[("Python 文件", "*.py *.pyw"), ("所有文件", "*.*")])
        if path:
            self.var_src.set(path)
            if not self.var_out.get():
                self.var_out.set(os.path.join(os.path.dirname(path), "dist"))
            if not self.var_cache.get():
                self.var_cache.set(os.path.join(os.path.dirname(path), "build"))

    def _pick_cache(self):
        path = filedialog.askdirectory(title="选择缓存目录")
        if path:
            self.var_cache.set(path)

    def _pick_out(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.var_out.set(path)

    # -------------------------------------------------------------- #
    # 日志
    # -------------------------------------------------------------- #
    def _log(self, level, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{ts}] ", "time")
        self.log.insert("end", msg + "\n", level)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                level, msg = self.log_queue.get_nowait()
                if level == "__done__":
                    self._on_pack_finished(success=(msg == "ok"))
                else:
                    self._log(level, msg)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log_queue)

    # -------------------------------------------------------------- #
    # 打包流程
    # -------------------------------------------------------------- #
    def _on_pack_click(self):
        if self.packing:
            return
        src = self.var_src.get().strip()
        cache = self.var_cache.get().strip()
        out = self.var_out.get().strip()

        if not src or not os.path.isfile(src):
            messagebox.showwarning("提示", "请选择有效的源码文件（.py）。")
            return
        if not cache:
            messagebox.showwarning("提示", "请指定缓存目录。")
            return
        if not out:
            messagebox.showwarning("提示", "请指定输出目录。")
            return

        os.makedirs(cache, exist_ok=True)
        os.makedirs(out, exist_ok=True)

        self.packing = True
        self.btn_pack.configure(state="disabled", text="打包中…")
        self.progress.start(12)
        self.var_status.set("正在打包…")
        self._log("info", "=" * 46)
        self._log("info", f"源码：{src}")
        self._log("info", f"缓存：{cache}")
        self._log("info", f"输出：{out}")

        self.worker = threading.Thread(
            target=self._run_pyinstaller, args=(src, cache, out), daemon=True)
        self.worker.start()

    def _build_command(self, py, src, cache, out):
        cmd = [py, "-m", "PyInstaller",
               "--distpath", out,
               "--workpath", cache,
               "--specpath", cache,
               "--noconfirm"]
        if self.var_onefile.get():
            cmd.append("--onefile")
        if self.var_noconsole.get():
            cmd.append("--noconsole")
        if self.var_clean.get():
            cmd.append("--clean")
        cmd.append(src)
        return cmd

    def _run_pyinstaller(self, src, cache, out):
        # 1) 定位真正可用的 Python 解释器（打包成 exe 后不能用自身）
        self.log_queue.put(("info", "正在查找可用的 Python 解释器…"))
        try:
            py, has_pi = resolve_python()
        except Exception as e:
            self.log_queue.put(("err", f"查找解释器时出错：{e}"))
            self.log_queue.put(("__done__", "fail"))
            return

        if not py:
            self.log_queue.put(("err", "未找到可用的 Python 解释器。"))
            self.log_queue.put(("warn", "请先安装 Python（勾选 Add to PATH），"
                                        "并执行：pip install pyinstaller"))
            self.log_queue.put(("__done__", "fail"))
            return
        self.log_queue.put(("info", f"使用解释器：{py}"))

        # 2) 确认 PyInstaller 已安装；若没装则自动安装
        if not has_pi:
            self.log_queue.put(("warn", "未检测到 PyInstaller，正在自动安装（首次可能需要 1-3 分钟）…"))
            ok = self._auto_install_pyinstaller(py)
            if not ok:
                self.log_queue.put(("err", "PyInstaller 自动安装失败。"))
                self.log_queue.put(("warn", f'可手动执行："{py}" -m pip install pyinstaller'))
                self.log_queue.put(("__done__", "fail"))
                return
            self.log_queue.put(("ok", "PyInstaller 安装完成，继续打包。"))

        cmd = self._build_command(py, src, cache, out)
        self.log_queue.put(("info", "执行命令：" + " ".join(f'"{c}"' if " " in c else c
                                                          for c in cmd)))
        self.log_queue.put(("info", "-" * 46))

        try:
            proc = _silent_popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,  # 避免子进程等待输入而卡死
                text=True, encoding="utf-8", errors="replace",
                bufsize=1)

            saw_output = False
            for line in proc.stdout:
                saw_output = True
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                low = line.lower()
                if "error" in low or "traceback" in low:
                    level = "err"
                elif "warning" in low or "warn" in low:
                    level = "warn"
                else:
                    level = "info"
                self.log_queue.put((level, line))

            proc.wait()
            if not saw_output:
                self.log_queue.put(("warn", "子进程没有任何输出，请检查解释器是否正确。"))

            if proc.returncode == 0:
                exe = self._find_exe(out, src)
                self.log_queue.put(("ok", "-" * 46))
                if exe:
                    self.log_queue.put(("ok", "✔ 打包完成！"))
                    self.log_queue.put(("ok", f"生成文件：{exe}"))
                    self.log_queue.put(("__done__", "ok"))
                else:
                    # 退出码 0 但找不到产物，视为异常
                    self.log_queue.put(("err", "打包进程结束，但未找到生成的 EXE，"
                                               "请检查输出目录与源码。"))
                    self.log_queue.put(("__done__", "fail"))
            else:
                self.log_queue.put(("err", f"✗ 打包失败，退出码 {proc.returncode}"))
                self.log_queue.put(("__done__", "fail"))
        except FileNotFoundError:
            self.log_queue.put(("err", f"无法启动解释器：{py}"))
            self.log_queue.put(("__done__", "fail"))
        except Exception as e:
            self.log_queue.put(("err", f"发生异常：{e}"))
            self.log_queue.put(("__done__", "fail"))

    def _auto_install_pyinstaller(self, py) -> bool:
        """自动为指定解释器安装 PyInstaller，安装过程日志实时输出到界面。

        依次尝试：普通安装 -> 国内镜像 -> --break-system-packages / --user，
        以适配「externally-managed」等受限环境。
        """
        base = [py, "-m", "pip", "install", "-U", "pyinstaller"]
        attempts = [
            base,
            base + ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
            base + ["--user"],
            base + ["--break-system-packages"],
        ]
        for idx, cmd in enumerate(attempts, 1):
            self.log_queue.put(("info", f"[安装尝试 {idx}/{len(attempts)}] "
                                        + " ".join(cmd[2:])))
            try:
                proc = _silent_popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                    errors="replace", bufsize=1)
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    if line.strip():
                        low = line.lower()
                        level = "err" if "error" in low else "info"
                        self.log_queue.put((level, "  " + line))
                proc.wait()
            except Exception as e:
                self.log_queue.put(("err", f"  安装命令执行异常：{e}"))
                continue
            # 无论 pip 返回码如何，都以「能否检测到 PyInstaller」为准
            if _has_pyinstaller(py):
                return True
            self.log_queue.put(("warn", "  本次尝试未生效，换用下一种方式…"))
        return _has_pyinstaller(py)

    def _find_exe(self, out, src):
        base = os.path.splitext(os.path.basename(src))[0]
        candidates = [
            os.path.join(out, base + ".exe"),
            os.path.join(out, base, base + ".exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def _on_pack_finished(self, success):
        self.packing = False
        self.progress.stop()
        self.btn_pack.configure(state="normal", text="开始打包")
        if success:
            self.var_status.set("打包成功 ✔")
            out = self.var_out.get().strip()
            if messagebox.askyesno("完成", "打包成功！是否打开输出目录？"):
                if os.path.isdir(out):
                    os.startfile(out) if os.name == "nt" else None
        else:
            self.var_status.set("打包失败 ✗")


def main():
    root = tk.Tk()
    PyPackerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
