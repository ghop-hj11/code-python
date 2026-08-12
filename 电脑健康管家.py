# -*- coding: utf-8 -*-
"""
============================================================
  SystemGuard  ·  电脑健康管家（极客终端风格）
------------------------------------------------------------
  由 code-Python 团队制作
  官方网址: http://11110.cloud/static_web/6a7ac8a9ec5d35.70524182.html
============================================================

功能概述:
  - 黑绿极客终端风格界面
  - 分析资源占用 / 电池健康度 / 网络连接 / 硬盘状态
  - 多层滚轮(多层评分)判断浪费系统资源的进程
  - 绝不自动结束 Windows 进程与重要进程；如需结束先弹窗询问
  - 启发式判断电脑是否可能被病毒入侵(联网会尝试拉取在线特征库)
  - 发现异常立即弹窗，提示病毒类型并建议专业杀软介入

说明:
  真正的查毒需要专业杀毒引擎。本工具做的是"启发式可疑特征判断"，
  用于提示风险，不能替代专业杀毒软件。
"""

import os
import sys
import time
import ctypes
import threading
import subprocess

import tkinter as tk
from tkinter import messagebox

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

# 联网拉取特征库用；没有网络/库时自动降级为本地内置库
try:
    import urllib.request
    import json as _json
except Exception:  # pragma: no cover
    urllib = None
    _json = None


# ============================================================
#  常量与配色
# ============================================================
APP_NAME = "SystemGuard"
TEAM = "该软件由 code-Python 团队制作"
OFFICIAL_URL = "http://11110.cloud/static_web/6a7ac8a9ec5d35.70524182.html"

BG = "#000000"          # 背景黑色
FG = "#00ff66"          # 主文本绿色
FG_DIM = "#00aa44"      # 暗绿
FG_WARN = "#ffcc00"     # 警告黄
FG_DANGER = "#ff3333"   # 危险红
FONT = ("Consolas", 11)
FONT_BOLD = ("Consolas", 11, "bold")

LINE_WIDTH = 78         # 等号分隔线宽度

# 在线特征库地址(可换成你自己的接口)。拉取失败自动使用本地内置库。
VIRUS_FEED_URLS = [
    "http://11110.cloud/static_web/virus_feed.json",
]


# ============================================================
#  白名单 —— 千万不要动的进程 / 服务
# ============================================================
# 这些系统关键进程即使占用资源也绝不自动结束
WINDOWS_CRITICAL = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "lsm.exe",
    "svchost.exe", "fontdrvhost.exe", "dwm.exe", "explorer.exe",
    "sihost.exe", "taskhostw.exe", "ctfmon.exe", "runtimebroker.exe",
    "searchindexer.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "spoolsv.exe", "audiodg.exe",
    "wininit.exe", "conhost.exe", "dllhost.exe", "wudfhost.exe",
    "securityhealthservice.exe", "securityhealthsystray.exe",
    "msmpeng.exe", "nissrv.exe", "smartscreen.exe", "mpdefendercoreservice.exe",
    "textinputhost.exe", "applicationframehost.exe",
    "python.exe", "pythonw.exe",  # 保护本工具自身/解释器
    "systemguard.exe",
}

# 系统目录，位于其中的可执行文件视为受保护
SYSTEM_DIRS = [
    os.environ.get("SystemRoot", r"C:\Windows").lower(),
    r"c:\windows",
    r"c:\program files\windowsapps",
]

# 这些进程名"本应"位于系统目录；若发现同名进程却不在系统目录，才算可疑伪装。
# 只放那些确实由系统在 System32 等目录启动的核心进程，避免误报。
MASQUERADE_WATCH = {
    "svchost.exe", "lsass.exe", "winlogon.exe", "wininit.exe",
    "csrss.exe", "services.exe", "smss.exe", "explorer.exe",
    "spoolsv.exe", "conhost.exe", "dwm.exe", "taskhostw.exe",
}


def is_protected(proc_name, exe_path):
    """判断某进程是否受保护(不允许自动结束)。"""
    name = (proc_name or "").lower()
    if name in WINDOWS_CRITICAL:
        return True
    path = (exe_path or "").lower()
    for d in SYSTEM_DIRS:
        if d and path.startswith(d):
            return True
    return False


# ============================================================
#  启发式病毒特征库(本地内置 + 可联网更新)
# ============================================================
# 已知恶意家族的名称/关键词特征。命中仅作"疑似"提示，不做误判处置。
LOCAL_VIRUS_SIGNATURES = [
    {"keywords": ["silverfox", "yinhu", "银狐"], "family": "银狐 (SilverFox) 远控木马"},
    {"keywords": ["gh0st"], "family": "Gh0st 远控木马"},
    {"keywords": ["njrat", "njw0rm"], "family": "njRAT 远控木马"},
    {"keywords": ["mimikatz"], "family": "Mimikatz 凭据窃取工具"},
    {"keywords": ["xmrig", "minerd", "cpuminer"], "family": "挖矿木马 (Miner)"},
    {"keywords": ["trojan", "backdoor", "keylog", "ransom", "worm"],
     "family": "通用木马/后门 (Trojan/Backdoor)"},
    {"keywords": ["cobaltstrike", "beacon"], "family": "CobaltStrike Beacon"},
    {"keywords": ["svhost", "scvhost", "svch0st", "expl0rer", "lssass", "csrss32"],
     "family": "伪装系统进程的木马 (Masquerading)"},
]


def fetch_online_signatures():
    """联网拉取特征库；失败则返回空列表(降级为本地库)。"""
    if urllib is None:
        return []
    for url in VIRUS_FEED_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read().decode("utf-8", "ignore")
                obj = _json.loads(data)
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, dict) and "signatures" in obj:
                    return obj["signatures"]
        except Exception:
            continue
    return []


# ============================================================
#  数据采集
# ============================================================
class Collector:
    """负责采集各类系统健康数据 & 做多层评分判断。"""

    def __init__(self):
        self.online_sigs = []
        self.killed_log = []  # 被停止任务的记录

    # ---------- 资源占用 ----------
    def cpu_mem(self):
        if not psutil:
            return "psutil 未安装，无法读取", 0.0, 0.0
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        text = f"CPU 占用 {cpu:5.1f}%   内存 {mem.percent:5.1f}% " \
               f"({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)"
        return text, cpu, mem.percent

    # ---------- 电池健康度 ----------
    def battery(self):
        if not psutil or not hasattr(psutil, "sensors_battery"):
            return "无电池信息(可能是台式机)"
        try:
            bat = psutil.sensors_battery()
        except Exception:
            bat = None
        if bat is None:
            return "无电池 / 台式机，使用外接电源"
        plugged = "充电中/已接电源" if bat.power_plugged else "使用电池"
        # 剩余时间
        secs = bat.secsleft
        if secs in (getattr(psutil, "POWER_TIME_UNLIMITED", -1),
                    getattr(psutil, "POWER_TIME_UNKNOWN", -2)) or secs < 0:
            remain = "—"
        else:
            remain = f"{secs // 3600}h{(secs % 3600) // 60}m"
        # 健康度粗略评估
        pct = bat.percent
        if pct >= 80:
            health = "良好"
        elif pct >= 40:
            health = "一般"
        else:
            health = "偏低"
        return f"电量 {pct:4.0f}%  状态 {plugged}  剩余 {remain}  健康评估 {health}"

    # ---------- 网络连接状态 ----------
    def network(self):
        online = self.check_internet()
        if not psutil:
            return ("联网" if online else "断网"), online
        try:
            io = psutil.net_io_counters()
            up = io.bytes_sent // (1024**2)
            down = io.bytes_recv // (1024**2)
            conn = len(psutil.net_connections(kind="inet"))
        except Exception:
            up = down = conn = 0
        status = "已联网 (Internet OK)" if online else "已断网 (No Internet)"
        text = f"{status}  上行 {up}MB  下行 {down}MB  活动连接 {conn}"
        return text, online

    @staticmethod
    def check_internet():
        """快速判断是否能连外网。"""
        if urllib is None:
            return False
        for host in ("http://www.msftconnecttest.com/connecttest.txt",
                     "http://www.baidu.com"):
            try:
                req = urllib.request.Request(host, headers={"User-Agent": APP_NAME})
                urllib.request.urlopen(req, timeout=3)
                return True
            except Exception:
                continue
        return False

    # ---------- 硬盘状态 ----------
    def disk(self):
        if not psutil:
            return "psutil 未安装，无法读取"
        parts = []
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            flag = ""
            if u.percent >= 90:
                flag = " [!空间紧张]"
            parts.append(f"{p.device} {u.percent:4.1f}%用"
                         f"({u.used // (1024**3)}G/{u.total // (1024**3)}G){flag}")
        return "  ".join(parts) if parts else "无可读磁盘分区"

    # ---------- 多层滚轮：判断浪费资源的进程 ----------
    def scan_wasteful(self):
        """
        多层评分(多层滚轮判断):
          第1层 CPU 占用
          第2层 内存占用
          第3层 磁盘/IO 行为
          第4层 名称/路径特征
          第5层 网络外连情况
        累加分数越高越可疑。返回(可疑进程列表, 病毒疑似列表)。
        受保护进程即使高分也不会进入"可结束"列表。
        """
        wasteful = []
        virus_hits = []
        if not psutil:
            return wasteful, virus_hits

        # 合并特征库(本地 + 在线)
        sigs = list(LOCAL_VIRUS_SIGNATURES) + list(self.online_sigs)

        for proc in psutil.process_iter(attrs=["pid", "name", "exe",
                                               "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                name = info.get("name") or "?"
                exe = info.get("exe") or ""
                cpu = info.get("cpu_percent") or 0.0
                mem = info.get("memory_percent") or 0.0

                score = 0
                reasons = []

                # 第1层滚轮：CPU
                if cpu >= 60:
                    score += 3; reasons.append(f"CPU{cpu:.0f}%")
                elif cpu >= 30:
                    score += 2; reasons.append(f"CPU{cpu:.0f}%")
                elif cpu >= 15:
                    score += 1

                # 第2层滚轮：内存
                if mem >= 25:
                    score += 3; reasons.append(f"内存{mem:.0f}%")
                elif mem >= 12:
                    score += 2; reasons.append(f"内存{mem:.0f}%")
                elif mem >= 6:
                    score += 1

                # 第3层滚轮：IO 行为
                try:
                    io = proc.io_counters()
                    if (io.read_bytes + io.write_bytes) > 500 * 1024**2:
                        score += 1; reasons.append("高IO")
                except Exception:
                    pass

                # 第5层滚轮：网络外连(可疑外连计入病毒判断)
                ext_conn = 0
                try:
                    for c in proc.connections(kind="inet"):
                        if c.raddr and c.status == psutil.CONN_ESTABLISHED:
                            ext_conn += 1
                except Exception:
                    pass
                if ext_conn > 20:
                    score += 1; reasons.append(f"外连{ext_conn}")

                protected = is_protected(name, exe)

                # 第4层滚轮：病毒特征匹配(名称 + 路径)
                low_name = name.lower()
                low_path = exe.lower()
                family = None
                for sig in sigs:
                    for kw in sig.get("keywords", []):
                        kw = str(kw).lower()
                        if kw and (kw in low_name or kw in low_path):
                            family = sig.get("family", "未知恶意家族")
                            break
                    if family:
                        break

                # 伪装系统进程但不在系统目录 —— 高度可疑
                # 仅对"本应位于系统目录"的核心进程判断，且必须拿得到真实路径，避免误报
                masquerade = False
                if low_name in MASQUERADE_WATCH and exe:
                    in_sys = any(low_path.startswith(d) for d in SYSTEM_DIRS if d)
                    if not in_sys:
                        masquerade = True

                if family or masquerade:
                    virus_hits.append({
                        "pid": info.get("pid"),
                        "name": name,
                        "exe": exe or "(未知路径)",
                        "family": family or "伪装系统进程的可疑程序",
                        "ext_conn": ext_conn,
                    })

                # 达到阈值且非受保护 —— 判定为浪费资源，允许(经询问后)结束
                if score >= 3 and not protected:
                    wasteful.append({
                        "pid": info.get("pid"),
                        "name": name,
                        "exe": exe or "(未知路径)",
                        "score": score,
                        "cpu": cpu,
                        "mem": mem,
                        "reasons": ",".join(reasons) or "综合评分",
                        "protected": protected,
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                continue

        wasteful.sort(key=lambda x: x["score"], reverse=True)
        return wasteful, virus_hits


# ============================================================
#  GUI
# ============================================================
class GuardApp:
    def __init__(self, root):
        self.root = root
        self.col = Collector()
        self.wasteful_cache = []

        root.title(f"{APP_NAME} · 电脑健康管家")
        root.configure(bg=BG)
        root.geometry("880x640")
        root.minsize(760, 560)

        # 顶部标题
        title = tk.Label(root, text=f"  {APP_NAME}  ::  电脑健康管家  ::  GEEK TERMINAL",
                         bg=BG, fg=FG, font=FONT_BOLD, anchor="w")
        title.pack(fill="x")

        # 主终端文本
        self.text = tk.Text(root, bg=BG, fg=FG, insertbackground=FG,
                            font=FONT, borderwidth=0, highlightthickness=0,
                            wrap="none")
        self.text.pack(fill="both", expand=True, padx=6, pady=4)
        self.text.configure(state="disabled")

        # 颜色标签
        self.text.tag_config("fg", foreground=FG)
        self.text.tag_config("dim", foreground=FG_DIM)
        self.text.tag_config("warn", foreground=FG_WARN)
        self.text.tag_config("danger", foreground=FG_DANGER)
        self.text.tag_config("bold", foreground=FG, font=FONT_BOLD)

        # 底部按钮栏
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", pady=4)
        self._btn(bar, "立即刷新", self.manual_refresh)
        self._btn(bar, "扫描并清理可疑占用", self.clean_wasteful)
        self._btn(bar, "病毒风险自检", self.virus_selfcheck)
        self._btn(bar, "关于", self.about)

        # 启动时联网拉取特征库(后台线程)
        threading.Thread(target=self._load_feed, daemon=True).start()

        # 首次渲染 + 定时刷新
        self.refresh()
        self._auto_loop()

    def _btn(self, parent, text, cmd):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=BG, fg=FG, activebackground=FG_DIM,
                      activeforeground=BG, font=FONT_BOLD,
                      relief="ridge", borderwidth=1, padx=8)
        b.pack(side="left", padx=4)
        return b

    def _load_feed(self):
        sigs = fetch_online_signatures()
        if sigs:
            self.col.online_sigs = sigs

    # ---------- 渲染 ----------
    def _line(self):
        return "=" * LINE_WIDTH + "\n"

    def _write(self, s, tag="fg"):
        self.text.insert("end", s, tag)

    def refresh(self):
        # 采集
        res_text, cpu, mem = self.col.cpu_mem()
        bat_text = self.col.battery()
        net_text, online = self.col.network()
        disk_text = self.col.disk()
        wasteful, virus_hits = self.col.scan_wasteful()
        self.wasteful_cache = wasteful

        self.text.configure(state="normal")
        self.text.delete("1.0", "end")

        # 第一行：等号铺满
        self._write(self._line(), "bold")

        # 下面四行：各种数据
        self._write(f" 资源占用  : {res_text}\n", "fg")
        self._write(f" 电池健康  : {bat_text}\n", "fg")
        self._write(f" 网络连接  : {net_text}\n", "fg")
        self._write(f" 硬盘状态  : {disk_text}\n", "fg")

        # 等号隔开
        self._write(self._line(), "bold")

        # 是否有占用资源 + 被停止任务记录
        if wasteful:
            self._write(f" 检测到 {len(wasteful)} 个疑似浪费资源的进程"
                        f"(多层滚轮评分):\n", "warn")
            for w in wasteful[:8]:
                self._write(f"   [评分{w['score']}] PID {w['pid']:>6}  "
                            f"{w['name']:<24} {w['reasons']}\n", "warn")
            self._write("   —— 可点击下方[扫描并清理可疑占用]，"
                        "结束前会弹窗询问 ——\n", "dim")
        else:
            self._write(" 未发现明显浪费资源的进程，系统运行清爽。\n", "fg")

        self._write("\n 占资源日志 · 被停止任务记录:\n", "dim")
        if self.col.killed_log:
            for rec in self.col.killed_log[-8:]:
                self._write(f"   {rec}\n", "dim")
        else:
            self._write("   (暂无被停止的任务)\n", "dim")

        # 等号隔开
        self._write(self._line(), "bold")

        # 程序运行状态
        abnormal = bool(virus_hits)
        state = self._run_state(online, abnormal)
        tag = "danger" if abnormal else "fg"
        self._write(f" 程序运行状态: {state}\n", tag)
        self._write("   状态释义: 断网正常运行 / 联网正常运行 / "
                    "断网异常运行 / 联网异常运行 / 离线\n", "dim")

        if virus_hits:
            self._write("\n [!] 病毒风险提示:\n", "danger")
            for v in virus_hits[:6]:
                self._write(f"   PID {v['pid']}  {v['name']}  "
                            f"疑似: {v['family']}\n", "danger")

        # 最后一行等号 + 团队署名
        self._write(self._line(), "bold")
        self._write(f" {TEAM}\n", "fg")
        self._write(f" 官方网址: {OFFICIAL_URL}\n", "dim")

        self.text.configure(state="disabled")

        # 病毒弹窗(异常立即通知)
        if virus_hits and not getattr(self, "_virus_alerted", False):
            self._virus_alerted = True
            self._alert_virus(virus_hits)

    @staticmethod
    def _run_state(online, abnormal):
        if online and not abnormal:
            return "联网正常运行"
        if online and abnormal:
            return "联网异常运行 (发现风险)"
        if (not online) and not abnormal:
            return "断网正常运行"
        if (not online) and abnormal:
            return "断网异常运行 (发现风险)"
        return "离线"

    # ---------- 病毒弹窗 ----------
    def _alert_virus(self, virus_hits):
        families = "、".join(sorted({v["family"] for v in virus_hits}))
        detail = "\n".join(
            f"· {v['name']} (PID {v['pid']}) —— 疑似 {v['family']}"
            for v in virus_hits[:6]
        )
        messagebox.showerror(
            "⚠ 检测到疑似病毒/异常",
            f"检测到疑似恶意/异常程序！\n\n"
            f"疑似类型: {families}\n\n{detail}\n\n"
            f"强烈建议立即让专业杀毒软件(如 Windows Defender、火绒、卡巴斯基等)介入全盘查杀！\n\n"
            f"注意: 本工具仅做启发式提示，不能替代专业杀毒软件。"
        )

    # ---------- 定时刷新 ----------
    def _auto_loop(self):
        self.refresh()
        self.root.after(8000, self._auto_loop)  # 每 8 秒刷新

    def manual_refresh(self):
        self._virus_alerted = False
        self.refresh()

    # ---------- 清理可疑占用(结束前必弹窗) ----------
    def clean_wasteful(self):
        if not psutil:
            messagebox.showwarning("缺少依赖", "未安装 psutil，无法结束进程。")
            return
        wasteful, _ = self.col.scan_wasteful()
        if not wasteful:
            messagebox.showinfo("扫描结果", "未发现可清理的浪费资源进程。")
            return

        for w in wasteful:
            # 再次确认受保护 —— 双保险，绝不动 Windows/重要进程
            if is_protected(w["name"], w["exe"]):
                continue
            ans = messagebox.askyesno(
                "结束进程确认",
                f"进程: {w['name']}\nPID : {w['pid']}\n"
                f"路径: {w['exe']}\n"
                f"评分: {w['score']}  ({w['reasons']})\n\n"
                f"该进程疑似浪费系统资源。\n"
                f"确定要结束它吗？(系统/重要进程已被自动排除)"
            )
            if not ans:
                continue
            self._kill(w)

        self.manual_refresh()

    def _kill(self, w):
        try:
            p = psutil.Process(w["pid"])
            # 结束前最后一次白名单校验
            if is_protected(p.name(), (p.exe() if _safe_exe(p) else "")):
                messagebox.showwarning("已阻止",
                                       f"{w['name']} 属于受保护进程，已阻止结束。")
                return
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
            stamp = time.strftime("%H:%M:%S")
            self.col.killed_log.append(
                f"[{stamp}] 已停止 {w['name']} (PID {w['pid']}) "
                f"评分{w['score']} {w['reasons']}"
            )
        except psutil.AccessDenied:
            messagebox.showwarning("权限不足",
                                   f"结束 {w['name']} 需要管理员权限。请以管理员身份运行。")
        except Exception as e:
            messagebox.showwarning("失败", f"结束 {w['name']} 失败: {e}")

    # ---------- 病毒风险自检 ----------
    def virus_selfcheck(self):
        _, virus_hits = self.col.scan_wasteful()
        if not virus_hits:
            messagebox.showinfo(
                "病毒风险自检",
                "启发式自检未发现明显可疑程序。\n\n"
                "提示: 这不代表 100% 安全，建议定期用专业杀毒软件全盘扫描。"
            )
        else:
            self._virus_alerted = True
            self._alert_virus(virus_hits)

    def about(self):
        messagebox.showinfo(
            "关于",
            f"{APP_NAME} · 电脑健康管家\n\n{TEAM}\n官方网址:\n{OFFICIAL_URL}\n\n"
            f"极客终端风格 · 仅供健康监测与风险提示。"
        )


def _safe_exe(p):
    try:
        p.exe()
        return True
    except Exception:
        return False


# ============================================================
#  管理员权限：需要则自动提权(UAC)
# ============================================================
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def ensure_admin():
    if is_admin():
        return True
    try:
        # 以管理员身份重新启动自身
        params = " ".join([f'"{a}"' for a in sys.argv])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
    except Exception:
        pass
    return False


def main():
    # 需要管理员权限：非管理员则尝试提权并退出当前实例
    if not is_admin():
        if not ensure_admin():
            # 提权失败也允许只读运行(结束进程会失败并提示)
            pass
        else:
            sys.exit(0)

    root = tk.Tk()
    GuardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
