"""抖音带货达人采集 — 桌面 GUI (Tkinter)

启动方式:
    python gui_app.py
    python main.py --gui
"""

import asyncio
import json
import os
import sys
import threading
from datetime import datetime
from typing import Optional
from tkinter import Tk, Frame, Label, Entry, Button, Text, Scrollbar, \
    ttk, StringVar, IntVar, messagebox, filedialog, END, N, S, E, W, \
    DISABLED, NORMAL, HORIZONTAL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    SCAN_POST_COUNT, SEARCH_SORT_TYPE, SEARCH_PUBLISH_TIME,
    SEARCH_MAX_COUNT, MIN_FOLLOWER_COUNT, MAX_CONCURRENCY, OUTPUT_DIR, load_cookie,
    SPEED_PROFILES, DEFAULT_SPEED_MODE,
)
from utils.cookie_util import save_cookie_to_env
from utils.logger import logger as loguru_logger
from utils.browser_manager import BrowserCookieManager

# ── 配色 ──
BG_DARK = "#0f172a"
BG_CARD = "#1e293b"
FG = "#e2e8f0"
FG_MUTED = "#94a3b8"
ACCENT = "#818cf8"
ACCENT_HOVER = "#6366f1"
GREEN = "#34d399"
RED = "#f87171"
YELLOW = "#fbbf24"
BORDER = "#334155"
INPUT_BG = "#0f172a"

FONT = ("Microsoft YaHei UI", 10)
FONT_TITLE = ("Microsoft YaHei UI", 12, "bold")
FONT_LOG = ("Consolas", 9)
FONT_SMALL = ("Microsoft YaHei UI", 9)


class DouyinGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("抖音带货达人采集")
        self.root.geometry("860x700")
        self.root.minsize(700, 550)
        self.root.configure(bg=BG_DARK)

        self.task_thread = None
        self.running = False
        self._event_loop = None
        self._active_tasks = []
        self.browser_mgr: Optional[BrowserCookieManager] = None

        self._build_ui()
        self.root.after(500, self._auto_try_clipboard)

    def _init_browser(self):
        """异步初始化浏览器管理器（后台线程）"""
        def _work():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self.browser_mgr = BrowserCookieManager()
                loop.run_until_complete(self.browser_mgr.start())
                self.root.after(0, self._update_cookie_status)
            except Exception as e:
                self.root.after(0, lambda: self._log(f"浏览器启动失败: {e}", "warning"))
                self.root.after(0, self._update_cookie_status)
        threading.Thread(target=_work, daemon=True).start()

    def _auto_try_clipboard(self):
        """启动时静默尝试剪贴板（不覆盖已有的有效 Cookie）"""
        from utils.cookie_util import extract_from_clipboard, is_cookie_logged_in, verify_cookie_api
        try:
            info = load_cookie()
            if info["cookie_str"] and is_cookie_logged_in(info["cookie_str"]):
                if verify_cookie_api(info["cookie_str"]):
                    self.cookie_label.configure(text="🔑 Cookie: ✅ .env 有效", fg=GREEN)
                    return
                else:
                    self.cookie_label.configure(text="🔑 Cookie: ⚠️ .env 中 Cookie API 不可用", fg=YELLOW)
                    return
            elif info.get("cookie_str"):
                self.cookie_label.configure(text="🔑 Cookie: ⚠️ .env 中 Cookie 未登录", fg=YELLOW)
                return
        except Exception:
            pass
        cookie = extract_from_clipboard()
        if cookie and is_cookie_logged_in(cookie):
            save_cookie_to_env(cookie)
            self.cookie_label.configure(text="🔑 Cookie: ✅ 已从剪贴板提取", fg=GREEN)
        else:
            self.cookie_label.configure(text="🔑 Cookie: ⚠️ 未设置，请选择方式后点 🔐提取 或 📋粘贴", fg=YELLOW)

    # ═══════════════════════════════════════════
    # UI 构建
    # ═══════════════════════════════════════════

    def _build_ui(self):
        # 主容器
        main = Frame(self.root, bg=BG_DARK, padx=16, pady=12)
        main.pack(fill="both", expand=True)

        # ── 标题栏 ──
        title_bar = Frame(main, bg=BG_DARK)
        title_bar.pack(fill="x", pady=(0, 10))
        Label(title_bar, text="🎯 抖音带货达人采集",
              font=FONT_TITLE, fg=ACCENT, bg=BG_DARK).pack(side="left")
        Label(title_bar, text="话题 → 达人筛选 → 视频带货 → Excel",
              font=FONT_SMALL, fg=FG_MUTED, bg=BG_DARK).pack(side="left", padx=8)

        # ── Cookie 状态栏 ──
        cookie_frame = Frame(main, bg=BG_CARD, padx=12, pady=8,
                             highlightbackground=BORDER, highlightthickness=1)
        cookie_frame.pack(fill="x", pady=(0, 10))

        self.cookie_label = Label(cookie_frame, text="🔑 Cookie: 检测中...",
                                  font=FONT_SMALL, fg=FG_MUTED, bg=BG_CARD)
        self.cookie_label.pack(side="left")

        btn_frame = Frame(cookie_frame, bg=BG_CARD)
        btn_frame.pack(side="right")

        self._extract_method = StringVar(value="登录提取 (推荐)")
        method_combo = ttk.Combobox(btn_frame, textvariable=self._extract_method,
                                     values=["登录提取 (推荐)", "rookiepy 提取 (需管理员)", "CDP 提取 (备用)"],
                                     state="readonly", font=FONT_SMALL, width=22)
        method_combo.pack(side="left", padx=2)
        self._tooltip(method_combo,
            "选择 Cookie 提取方式:\n"
            "• 登录提取 (推荐) — Playwright 持久化浏览器，Cookie 存数据库，最可靠\n"
            "• rookiepy 提取 (需管理员) — 直接读取 Chrome/Edge 加密 Cookie 数据库\n"
            "• CDP 提取 (备用) — 通过 DevTools 协议连接浏览器提取")
        self._btn(btn_frame, "🔐 提取", self._on_login_extract, fg=GREEN,
                   tooltip="用选定的方式获取 Cookie 并保存到 .env").pack(side="left", padx=2)
        self._btn(btn_frame, "📋 粘贴", self._on_paste_cookie, fg=FG_MUTED,
                   tooltip="从剪贴板识别 Cookie。操作: 在已登录的浏览器中 F12→Network→右键请求→Copy as cURL→点此按钮。").pack(side="left", padx=2)

        # ── 采集配置 ──
        cfg_card = Frame(main, bg=BG_CARD, padx=14, pady=10,
                         highlightbackground=BORDER, highlightthickness=1)
        cfg_card.pack(fill="x", pady=(0, 10))

        Label(cfg_card, text="采集配置", font=FONT_TITLE, fg=FG, bg=BG_CARD).pack(anchor="w")

        # 第1行: 关键词 + 扫描数量
        row1 = Frame(cfg_card, bg=BG_CARD)
        row1.pack(fill="x", pady=4)
        self._labeled_input(row1, "话题关键词 *", 240, "keyword",
                            tooltip="要搜索的抖音话题词，如 '防晒'、'美妆'、'穿搭'。不要加 # 号。")
        self._labeled_input(row1, "扫描作品数/人", 100, "scan_count",
                            default=str(SCAN_POST_COUNT), width=8,
                            tooltip="对每位找到的达人，拉取最近 N 条作品来判断是否为带货达人。数值越大判断越准，但速度越慢。")

        # 第2行: 排序 + 时间 + 搜索上限 + 粉丝门槛
        row2 = Frame(cfg_card, bg=BG_CARD)
        row2.pack(fill="x", pady=4)
        self._labeled_combo(row2, "排序方式", 140, "sort_type",
                            ["最多点赞", "最新发布", "综合排序"],
                            [1, 2, 0], SEARCH_SORT_TYPE,
                            tooltip="搜索结果排序: 最多点赞→看热门作品, 最新发布→看新作品, 综合→抖音默认排序")
        self._labeled_combo(row2, "发布时间", 120, "publish_time",
                            ["半年内", "一周内", "不限"],
                            [180, 7, 0], SEARCH_PUBLISH_TIME,
                            tooltip="只抓取此时间范围内发布的视频")
        self._labeled_input(row2, "搜索上限", 90, "max_search",
                            default=str(SEARCH_MAX_COUNT), width=6,
                            tooltip="搜索结果视频总条数(不是达人个数)。抖音API单次搜索最多返回约500条，设太高也没用。数值越大达人数越多但耗时越长。")
        self._labeled_input(row2, "最低粉丝数", 100, "min_followers",
                            default=str(MIN_FOLLOWER_COUNT), width=8,
                            tooltip="粉丝数低于此值的作者直接跳过不扫描。0=不过滤。")
        self._labeled_input(row2, "并发数", 80, "concurrency",
                            default=str(MAX_CONCURRENCY), width=5,
                            tooltip="同时扫描的达人数。安全模式建议2~4；快速模式建议3~6；极速模式建议5~8。过高会触发风控(444封禁)，请根据速度模式合理设置！")

        # 第3行: 速度模式 + 多轮搜索
        row3 = Frame(cfg_card, bg=BG_CARD)
        row3.pack(fill="x", pady=4)
        self._labeled_combo(row3, "速度模式", 130, "speed_mode",
                            list(SPEED_PROFILES.keys()), list(SPEED_PROFILES.keys()),
                            DEFAULT_SPEED_MODE,
                            tooltip="控制请求间隔延迟。安全=保守延迟避免风控；快速=缩短间隔提速约2倍；极速=最小间隔但风控风险最高，并发数请控制在8以内。极速模式下自动跳过作品详情检测。")

        self._multi_round_var = IntVar(value=0)
        cb = ttk.Checkbutton(row3, text="多轮搜索(突破500条限制)",
                              variable=self._multi_round_var,
                              style="TCheckbutton")
        cb.pack(side="left", padx=(4, 0))
        self._tooltip(cb,
            "用「最多点赞」和「最新发布」两种排序各搜一轮后合并去重。\n"
            "可比单轮多获得 30%~80% 的达人和视频，但搜索耗时翻倍。\n"
            "建议与极速模式搭配使用以抵消额外的时间开销。")

        # ── 操作按钮 + 进度条 ──
        action_row = Frame(main, bg=BG_DARK)
        action_row.pack(fill="x", pady=(0, 8))

        self.start_btn = Button(action_row, text="🚀 开始采集", font=FONT,
                                bg=ACCENT, fg="white", activebackground=ACCENT_HOVER,
                                activeforeground="white", relief="flat",
                                padx=24, pady=6, cursor="hand2",
                                command=self._on_start)
        self.start_btn.pack(side="left")
        self._tooltip(self.start_btn, "开始按配置搜索话题→提取作者→扫描主页→分析带货→导出Excel")

        self.stop_btn = Button(action_row, text="⏹ 停止", font=FONT,
                               bg=RED, fg="white", activebackground="#dc2626",
                               activeforeground="white", relief="flat",
                               padx=16, pady=6, cursor="hand2", state=DISABLED,
                               command=self._on_stop)
        self.stop_btn.pack(side="left", padx=8)

        self.export_btn = Button(action_row, text="📥 导出 Excel", font=FONT,
                                 bg=GREEN, fg=BG_DARK, relief="flat",
                                 padx=16, pady=6, cursor="hand2", state=DISABLED,
                                 command=self._on_export)
        self.export_btn.pack(side="right")
        self._tooltip(self.export_btn, "打开最近一次采集结果。采集完成后自动启用。")

        # 进度条
        progress_frame = Frame(main, bg=BG_CARD, padx=10, pady=6,
                               highlightbackground=BORDER, highlightthickness=1)
        progress_frame.pack(fill="x", pady=(0, 8))
        self.progress_var = IntVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var,
                                            maximum=100, style="TProgressbar")
        self.progress_bar.pack(fill="x", side="left", expand=True)
        self.progress_label = Label(progress_frame, text="0%",
                                    font=FONT_SMALL, fg=FG_MUTED, bg=BG_CARD, width=6)
        self.progress_label.pack(side="right", padx=(8, 0))
        self._tooltip(self.progress_bar, "0%搜索→15%提取作者→20%~95%逐人扫描→95%导出→100%完成")

        # ── 结果表格 ──
        table_frame = Frame(main, bg=BG_CARD, padx=10, pady=8,
                            highlightbackground=BORDER, highlightthickness=1)
        table_frame.pack(fill="both", expand=True, pady=(0, 8))

        table_header = Frame(table_frame, bg=BG_CARD)
        table_header.pack(fill="x")
        Label(table_header, text="结果", font=FONT_TITLE, fg=FG, bg=BG_CARD).pack(side="left")
        self._clear_btn = Button(table_header, text="清空", font=FONT_SMALL, bg=BG_DARK, fg=FG_MUTED,
               relief="flat", padx=8, pady=1, cursor="hand2",
               command=self._on_clear_results)
        self._clear_btn.pack(side="right")

        columns = ("#", "昵称", "状态", "视频/挂车")
        self.result_tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                        height=6, selectmode="extended")
        self.result_tree.heading("#", text="#", anchor="center")
        self.result_tree.heading("昵称", text="昵称")
        self.result_tree.heading("状态", text="状态", anchor="center")
        self.result_tree.heading("视频/挂车", text="视频/挂车", anchor="center")
        self.result_tree.column("#", width=50, anchor="center", stretch=False)
        self.result_tree.column("昵称", width=160, anchor="w")
        self.result_tree.column("状态", width=100, anchor="center")
        self.result_tree.column("视频/挂车", width=120, anchor="center")

        scroll_y = Scrollbar(table_frame, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scroll_y.set)
        self.result_tree.pack(fill="both", expand=True, side="left")
        scroll_y.pack(fill="y", side="right")

        # 双击打开主页/查看错误
        self.result_tree.bind("<Double-1>", self._on_row_double_click)
        self._author_urls = {}
        self._author_errors = {}

        # ── 日志 ──
        log_frame = Frame(main, bg=BG_CARD, padx=10, pady=6,
                          highlightbackground=BORDER, highlightthickness=1)
        log_frame.pack(fill="both", pady=(0, 4))
        Label(log_frame, text="运行日志", font=FONT_TITLE, fg=FG, bg=BG_CARD).pack(anchor="w")
        self.log_text = Text(log_frame, font=FONT_LOG, bg=INPUT_BG, fg=FG,
                             wrap="word", height=8, state=DISABLED,
                             relief="flat", padx=6, pady=4)
        self.log_text.pack(fill="both", expand=True)

        # 日志颜色 tags
        self.log_text.tag_config("time", foreground="#64748b")
        self.log_text.tag_config("success", foreground=GREEN)
        self.log_text.tag_config("warning", foreground=YELLOW)
        self.log_text.tag_config("error", foreground=RED)
        self.log_text.tag_config("info", foreground=FG)

        # ── 状态栏 ──
        self.status_bar = Label(main, text="就绪", font=FONT_SMALL,
                                fg=FG_MUTED, bg=BG_DARK, anchor="w")
        self.status_bar.pack(fill="x")

        # 进度条样式
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TProgressbar", thickness=8, troughcolor=BG_DARK,
                        background=ACCENT, borderwidth=0)
        style.configure("TCheckbutton", background=BG_CARD, foreground=FG,
                        font=FONT_SMALL)
        style.map("TCheckbutton",
                  background=[("active", BG_CARD)])

        self._last_filepath = None

    # ═══════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════

    def _tooltip(self, widget, text):
        """悬停提示 — 鼠标移入显示，移出消失"""
        if not text:
            return
        tip_win = None

        def _enter(event):
            nonlocal tip_win
            if tip_win:
                return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            tip_win = Tk()
            tip_win.wm_overrideredirect(True)
            tip_win.wm_geometry(f"+{x}+{y}")
            tip_win.configure(bg="#1e293b")
            Label(tip_win, text=text, font=FONT_SMALL, fg="#e2e8f0", bg="#1e293b",
                  padx=8, pady=4, relief="solid", bd=1).pack()
            tip_win.lift()

        def _leave(event):
            nonlocal tip_win
            if tip_win:
                tip_win.destroy()
                tip_win = None

        widget.bind("<Enter>", _enter, add="+")
        widget.bind("<Leave>", _leave, add="+")

    def _btn(self, parent, text, cmd, fg=FG, tooltip=""):
        b = Button(parent, text=text, font=FONT_SMALL,
                   bg=BG_CARD, fg=fg, activebackground=BG_DARK,
                   activeforeground=fg, relief="flat",
                   padx=10, pady=3, cursor="hand2", command=cmd)
        self._tooltip(b, tooltip)
        return b

    def _labeled_input(self, parent, label, label_width, key, default="", width=14, tooltip="", **kw):
        f = Frame(parent, bg=parent["bg"])
        f.pack(side="left", padx=(0, 8))
        lb = Label(f, text=label, font=FONT_SMALL, fg=FG_MUTED,
                   bg=parent["bg"], width=label_width // 7)
        lb.pack(anchor="w")
        self._tooltip(lb, tooltip)
        e = Entry(f, font=FONT, bg=INPUT_BG, fg=FG, insertbackground=FG,
                  relief="flat", highlightbackground=BORDER, highlightthickness=1,
                  width=width, **kw)
        e.insert(0, default)
        e.pack()
        self._tooltip(e, tooltip)
        setattr(self, f"_entry_{key}", e)

    def _labeled_combo(self, parent, label, label_width, key, texts, values, default_val, tooltip=""):
        f = Frame(parent, bg=parent["bg"])
        f.pack(side="left", padx=(0, 8))
        lb = Label(f, text=label, font=FONT_SMALL, fg=FG_MUTED, bg=parent["bg"])
        lb.pack(anchor="w")
        self._tooltip(lb, tooltip)
        var = StringVar()
        idx = values.index(default_val) if default_val in values else 0
        cb = ttk.Combobox(f, textvariable=var, values=texts,
                          state="readonly", font=FONT, width=10)
        cb.current(idx)
        cb.pack()
        self._tooltip(cb, tooltip)
        setattr(self, f"_combo_{key}", (var, values))

    def _log(self, msg, tag="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=NORMAL)
        self.log_text.insert(END, ts + " ", "time")
        self.log_text.insert(END, msg + "\n", tag)
        self.log_text.see(END)
        self.log_text.configure(state=DISABLED)

    def _set_running(self, running: bool):
        self.running = running
        state = DISABLED if running else NORMAL
        self.start_btn.configure(state=state,
                                 text="⏳ 采集中..." if running else "🚀 开始采集")
        self.stop_btn.configure(state=NORMAL if running else DISABLED)
        self.status_bar.configure(text="采集中..." if running else "就绪")

    def _get_config(self):
        def _val(key, default):
            e = getattr(self, f"_entry_{key}", None)
            return e.get().strip() if e else str(default)

        def _combo(key, default):
            t = getattr(self, f"_combo_{key}", None)
            if t:
                var, vals = t
                idx = var.get()
                if idx in vals:
                    return idx
            return default

        kw = _val("keyword", "")
        if not kw:
            messagebox.showwarning("提示", "请输入话题关键词")
            return None

        kw = kw.lstrip("#")

        return {
            "keyword": kw,
            "scan_count": int(_val("scan_count", SCAN_POST_COUNT)),
            "sort_type": _combo("sort_type", SEARCH_SORT_TYPE),
            "publish_time": _combo("publish_time", SEARCH_PUBLISH_TIME),
            "max_search": int(_val("max_search", SEARCH_MAX_COUNT)),
            "min_followers": int(_val("min_followers", MIN_FOLLOWER_COUNT)),
            "concurrency": int(_val("concurrency", MAX_CONCURRENCY)),
            "speed_mode": _combo("speed_mode", DEFAULT_SPEED_MODE),
            "multi_round": bool(self._multi_round_var.get()),
        }

    # ═══════════════════════════════════════════
    # Cookie 操作
    # ═══════════════════════════════════════════

    def _update_cookie_status(self):
        """综合检查 Cookie 状态：浏览器管理器 + .env"""
        if self.browser_mgr and self.browser_mgr.is_logged_in:
            self.cookie_label.configure(text="🔑 Cookie: ✅ 浏览器已登录", fg=GREEN)
            self._log("浏览器 Cookie 管理器: 已登录 ✓", "success")
            return

        try:
            from utils.cookie_util import verify_cookie_api
            info = load_cookie()
            if info["cookie_str"]:
                api_ok = verify_cookie_api(info["cookie_str"])
                if api_ok:
                    self.cookie_label.configure(text="🔑 Cookie: ✅ .env 有效", fg=GREEN)
                    return
        except Exception:
            pass

        if self.browser_mgr:
            self.cookie_label.configure(
                text="🔑 Cookie: ⚠️ 浏览器未登录，点 🔐提取 按钮", fg=YELLOW)
        else:
            self.cookie_label.configure(
                text="🔑 Cookie: ⚠️ 未设置，请选择方式后点 🔐提取 或 📋粘贴", fg=YELLOW)

    def _on_login_extract(self):
        """根据下拉选择分发到不同的 Cookie 提取方式"""
        method = self._extract_method.get()
        if "rookiepy" in method:
            self._extract_with_rookiepy()
        elif "CDP" in method:
            self._extract_with_cdp()
        else:
            self._extract_with_browser()

    @staticmethod
    def _find_browser_exe():
        """查找系统 Chrome/Edge 浏览器可执行文件路径"""
        import platform
        import os as _os
        system = platform.system()
        if system == "Windows":
            import winreg
            for browser in ["chrome", "msedge"]:
                try:
                    key_path = {
                        "chrome": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                        "msedge": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
                    }
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path[browser])
                    path, _ = winreg.QueryValueEx(key, "")
                    winreg.CloseKey(key)
                    if _os.path.exists(path):
                        return path
                except Exception:
                    pass
            for path in [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]:
                if _os.path.exists(path):
                    return path
        elif system == "Darwin":
            for path in [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            ]:
                if _os.path.exists(path):
                    return path
        return ""

    def _extract_with_browser(self):
        """系统浏览器直接打开抖音 + rookiepy 轮询检测登录 — 不依赖 Playwright"""
        self.cookie_label.configure(text="🔑 Cookie: ⏳ 正在打开浏览器...", fg=ACCENT)
        self._log("正在打开系统浏览器，请在浏览器中登录抖音...", "info")

        def _work():
            import subprocess
            import time as _time
            try:
                exe_path = self._find_browser_exe()
                if not exe_path:
                    self.root.after(0, lambda: self.cookie_label.configure(
                        text="🔑 Cookie: ⚠️ 未找到 Chrome/Edge", fg=YELLOW))
                    self.root.after(0, lambda: self._log("未找到系统 Chrome/Edge 浏览器，请用 📋粘贴 方式", "error"))
                    self.root.after(0, lambda: self._on_cookie_result(None, interactive=True))
                    return

                self.root.after(0, lambda: self.cookie_label.configure(
                    text="🔑 Cookie: ⏳ 等待登录中...", fg=YELLOW))
                self.root.after(0, lambda: self._log(f"浏览器: {exe_path}", "info"))

                proc = subprocess.Popen(
                    [exe_path, "https://www.douyin.com/"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

                from utils.cookie_util import extract_with_rookiepy, is_cookie_logged_in
                max_wait = 300
                elapsed = 0
                while elapsed < max_wait:
                    _time.sleep(3)
                    elapsed += 3
                    try:
                        cookie = extract_with_rookiepy()
                        if cookie and is_cookie_logged_in(cookie):
                            self.root.after(0, lambda: self._log(
                                f"✓ 检测到登录态! (已等待 {elapsed}s)", "success"))
                            self.root.after(0, lambda: self._on_cookie_result(
                                cookie, interactive=True))
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            return
                    except Exception:
                        pass
                    if elapsed % 15 == 0:
                        self.root.after(0, lambda: self._log(
                            f"  等待登录中... ({elapsed}s/{max_wait}s)", "info"))

                self.root.after(0, lambda: self._log("登录等待超时，未检测到登录态", "warning"))
                self.root.after(0, lambda: self._log("  请确保在浏览器中完成登录后重试，或换用 📋粘贴", "info"))
                try:
                    proc.terminate()
                except Exception:
                    pass
                self.root.after(0, lambda: self._on_cookie_result(None, interactive=True))

            except Exception as e:
                import traceback
                self.root.after(0, lambda: self._log(f"登录过程异常: {e}", "error"))
                self.root.after(0, lambda: self._log(traceback.format_exc(), "error"))
                self.root.after(0, lambda: self._on_cookie_result(None, interactive=True))
        threading.Thread(target=_work, daemon=True).start()

    def _extract_with_rookiepy(self):
        """rookiepy: 直接读取 Chrome/Edge 加密 Cookie 数据库 (需要管理员权限)"""
        self.cookie_label.configure(text="🔑 Cookie: ⏳ rookiepy 提取中...", fg=ACCENT)
        self._log("正在通过 rookiepy 读取浏览器 Cookie 数据库...", "info")
        self._log("  ⚠ 如果提示权限不足，请以管理员身份运行", "warning")

        def _work():
            try:
                from utils.cookie_util import extract_with_rookiepy
                cookie = extract_with_rookiepy()
                if cookie:
                    self.root.after(0, lambda: self._on_cookie_result(cookie, interactive=True))
                else:
                    self.root.after(0, lambda: self.cookie_label.configure(
                        text="🔑 Cookie: ⚠️ rookiepy 提取失败", fg=YELLOW))
                    self.root.after(0, lambda: self._log(
                        "rookiepy 提取失败，请尝试以管理员身份运行或切换到其他方式", "warning"))
            except Exception as e:
                import traceback
                self.root.after(0, lambda: self._log(f"rookiepy 异常: {e}", "error"))
                self.root.after(0, lambda: self._log(traceback.format_exc(), "error"))
                self.root.after(0, lambda: self._on_cookie_result(None, interactive=True))
        threading.Thread(target=_work, daemon=True).start()

    def _extract_with_cdp(self):
        """CDP: 通过 Chrome DevTools Protocol 弹出浏览器等待登录 (备用方案)"""
        self.cookie_label.configure(text="🔑 Cookie: ⏳ CDP 启动浏览器...", fg=ACCENT)
        self._log("正在通过 CDP 打开浏览器窗口，请登录抖音...", "info")

        def _progress(status, msg):
            if status == "waiting":
                self.root.after(0, lambda: self.cookie_label.configure(
                    text="🔑 Cookie: ⏳ CDP 等待登录...", fg=YELLOW))
                self.root.after(0, lambda: self._log(msg, "info"))
            elif status == "logged_in":
                self.root.after(0, lambda: self.cookie_label.configure(
                    text="🔑 Cookie: ✅ CDP 已登录", fg=GREEN))
                self.root.after(0, lambda: self._log(msg, "success"))

        def _work():
            try:
                from utils.cookie_util import extract_cookie_interactive
                cookie = extract_cookie_interactive(
                    max_wait=300,
                    progress_callback=_progress,
                )
                if cookie:
                    self.root.after(0, lambda: self._on_cookie_result(cookie, interactive=True))
                else:
                    self.root.after(0, lambda: self._on_cookie_result(None, interactive=True))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"CDP 异常: {e}", "error"))
                self.root.after(0, lambda: self._on_cookie_result(None, interactive=True))
        threading.Thread(target=_work, daemon=True).start()

    def _on_paste_cookie(self):
        from utils.cookie_util import extract_from_clipboard, is_cookie_logged_in
        cookie = extract_from_clipboard()
        if cookie:
            if not is_cookie_logged_in(cookie):
                self._log("剪贴板中的 Cookie 未包含登录态，请确认已登录抖音后复制", "warning")
                messagebox.showwarning("Cookie 未登录",
                                       "剪贴板中的 Cookie 似乎未包含登录信息。\n\n"
                                       "请确保:\n"
                                       "1. 已在浏览器中登录 douyin.com\n"
                                       "2. 按 F12 → Network → 右键请求 → Copy as cURL\n"
                                       "3. 再点 📋 粘贴")
                return
            save_cookie_to_env(cookie)
            self.cookie_label.configure(text="🔑 Cookie: ✅ 已从剪贴板保存", fg=GREEN)
            self._log("Cookie 已从剪贴板保存 ✓", "success")
        else:
            messagebox.showinfo("如何获取 Cookie",
                                "请按以下步骤操作：\n\n"
                                "1. 打开 Chrome/Edge → 访问 douyin.com 并登录\n"
                                "2. 按 F12 → 切换到 Network (网络) 标签\n"
                                "3. 刷新页面 (F5)\n"
                                "4. 在左侧列表中右键任意请求\n"
                                "   → Copy → Copy as cURL (bash)\n"
                                "5. 回到本程序，再次点击 📋 粘贴\n\n"
                                "💡 提示: 之后每次启动都会自动读取剪贴板",
                                detail="复制后 Cookie 会自动保存到 .env 文件")

    def _on_cookie_result(self, cookie, interactive=False):
        if cookie:
            from utils.cookie_util import verify_cookie_api
            from utils.cookie_util import is_cookie_logged_in
            save_cookie_to_env(cookie)
            self._log("Cookie 已保存到 .env", "success")

            self._log("API 有效性自检中...", "info")
            if is_cookie_logged_in(cookie) and verify_cookie_api(cookie):
                self.cookie_label.configure(text="🔑 Cookie: ✅ 有效", fg=GREEN)
                self._log("✓ Cookie API 自检通过，可以开始采集", "success")
            elif self.browser_mgr and self.browser_mgr.is_logged_in:
                self.cookie_label.configure(
                    text="🔑 Cookie: ✅ 浏览器已登录 (Provider 模式)", fg=GREEN)
                self._log("✓ 使用浏览器 Provider 模式，每次请求动态获取 Cookie", "success")
            else:
                self.cookie_label.configure(text="🔑 Cookie: ⚠️ API 自检未通过", fg=YELLOW)
                self._log("⚠ Cookie 已保存但 API 自检未通过", "warning")
                self._log("  可尝试切换到其他提取方式，或用 📋粘贴 F12 DevTools 获取有效 Cookie", "info")
            self._update_cookie_status()
        else:
            if interactive:
                self.cookie_label.configure(text="🔑 Cookie: ⚠️ 登录超时", fg=YELLOW)
                self._log("登录超时或未检测到登录态", "warning")
                self._log("请重试，确保在弹出的浏览器窗口中完成抖音登录", "info")
            else:
                self.cookie_label.configure(text="🔑 Cookie: ⚠️ 获取失败", fg=YELLOW)
                self._log("获取 Cookie 失败", "warning")

    # ═══════════════════════════════════════════
    # 采集流程
    # ═══════════════════════════════════════════

    def _on_start(self):
        cfg = self._get_config()
        if not cfg:
            return

        self._log("=" * 45, "info")
        self._log(f"开始采集: {cfg['keyword']}", "success")
        speed = cfg.get("speed_mode", "安全")
        mr = "多轮" if cfg.get("multi_round") else "单轮"
        self._log(f"速度模式={speed} | {mr}搜索 | 并发x{cfg['concurrency']} | 每达人{cfg['scan_count']}条", "info")

        self.result_tree.delete(*self.result_tree.get_children())
        self._author_urls.clear()
        self._author_errors.clear()
        self._last_filepath = None
        self._qualified_data = []       # 实时收集的合格达人数据
        self._pending_export = cfg      # 供中断时立即导出
        self._auto_exported = False     # 仅自动导出一次
        self.export_btn.configure(state=DISABLED)
        self._set_running(True)
        self._set_progress(0, "搜索中...")

        self.task_thread = threading.Thread(
            target=self._async_runner, args=(cfg,),
            daemon=True,
        )
        self.task_thread.start()

    def _async_runner(self, cfg):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._event_loop = loop
        try:
            import sniffio, anyio
            import httpcore._async.http11
            loop.run_until_complete(self._run_pipeline(cfg))
        except Exception as e:
            import traceback as _tb
            tb_str = _tb.format_exc()
            self.root.after(0, lambda msg=str(e): self._log(f"异步依赖缺失: {msg}", "error"))
            self.root.after(0, lambda t=tb_str: self._log(t, "error"))
            self.root.after(0, self._gui_done)
        finally:
            self._event_loop = None
            loop.close()

    def _on_stop(self):
        self.running = False
        loop = getattr(self, '_event_loop', None)
        if loop and not loop.is_closed():
            for task in self._active_tasks:
                if not task.done():
                    loop.call_soon_threadsafe(task.cancel)
        self._set_running(False)
        self._log("用户手动停止", "warning")

    def _try_export_partial(self):
        """尝试导出目前已收集到的数据（中途停止时调用）"""
        if self._auto_exported:
            return
        self._auto_exported = True
        data = getattr(self, "_qualified_data", [])
        cfg = getattr(self, "_pending_export", {})
        keyword = cfg.get("keyword", "data") if cfg else "data"
        out_dir = cfg.get("output_dir", OUTPUT_DIR) if cfg else OUTPUT_DIR
        try:
            from storage.excel import save_to_xlsx
            fp = save_to_xlsx(data, keyword, out_dir)
            self._last_filepath = fp
            if data:
                self._log(f"✅ 已导出 {len(data)} 位达人 → {os.path.basename(fp)}", "success")
            else:
                self._log("已生成空表，暂未找到带货达人", "warning")
            self.root.after(0, lambda: self.export_btn.configure(state=NORMAL))
        except Exception as e:
            self._log(f"导出失败: {e}", "error")

    def _on_export(self):
        if self._last_filepath and os.path.exists(self._last_filepath):
            os.startfile(self._last_filepath)
            self._log(f"已打开文件: {os.path.basename(self._last_filepath)}", "success")
        elif self._last_filepath:
            messagebox.showinfo("提示", f"文件已被移动或删除:\n{self._last_filepath}")
        else:
            messagebox.showinfo("提示", "暂无可导出的文件，请先完成采集\n\n"
                                       "如果采集已完成但无结果，Excel 文件在 output/ 目录中")

    def _on_row_double_click(self, event):
        sel = self.result_tree.selection()
        if sel:
            idx = int(self.result_tree.item(sel[0], "values")[0]) - 1
            url = self._author_urls.get(idx)
            if url:
                os.startfile(url)
            else:
                err = self._author_errors.get(idx, "")
                if err:
                    messagebox.showinfo("错误详情", f"达人 #{idx + 1} 的错误信息:\n\n{err}")

    def _on_clear_results(self):
        self.result_tree.delete(*self.result_tree.get_children())
        self._author_urls.clear()
        self._author_errors.clear()
        self._last_filepath = None
        self._qualified_data = []
        self._log("结果已清空", "info")

    async def _run_pipeline(self, cfg):
        try:
            from crawler.engine import DouyinEngine
            from crawler.search import crawl_search_results, crawl_search_multi, extract_unique_authors
            from crawler.user import crawl_user_posts
            from analyzer.filter import InfluencerAnalyzer
            from storage.excel import save_to_xlsx
            from utils.retry import RateLimiter

            info = load_cookie()
            cookie_provider = None
            if self.browser_mgr and self.browser_mgr.is_logged_in:
                cookie_provider = self.browser_mgr.make_cookie_provider()
                self._gui_log("使用浏览器 Provider 模式 (动态 Cookie)", "success")

            def _make_engine():
                return DouyinEngine(
                    cookie_str=info.get("cookie_str", "") if not cookie_provider else None,
                    cookie_provider=cookie_provider,
                )

            engine = _make_engine()
            analyzer = InfluencerAnalyzer()
            limiter = RateLimiter()
            limiter.apply_profile(SPEED_PROFILES[cfg["speed_mode"]])
            concurrency = max(1, cfg.get("concurrency", MAX_CONCURRENCY))
            skip_detail = cfg["speed_mode"] == "极速"

            # Step 1: 搜索
            multi = cfg.get("multi_round", False)
            if multi:
                self._gui_log(f"Step 1/4: 多轮搜索中 (速度={cfg['speed_mode']})...", "info")
                await engine.close()
                videos = await crawl_search_multi(
                    _make_engine, cfg["keyword"],
                    sort_types=[1, 2],
                    publish_time=cfg["publish_time"],
                    max_per_round=cfg["max_search"],
                    limiter=limiter,
                )
            else:
                self._gui_log(f"Step 1/4: 搜索中 (速度={cfg['speed_mode']})...", "info")
                videos = await crawl_search_results(
                    engine, cfg["keyword"],
                    sort_type=cfg["sort_type"],
                    publish_time=cfg["publish_time"],
                    max_count=cfg["max_search"],
                    limiter=limiter,
                )
                await engine.close()
            if not self.running: return
            if not videos:
                self._gui_log("未搜索到相关视频", "error")
                self._gui_done()
                return
            self._gui_log(f"✓ 获取 {len(videos)} 条视频", "success")
            self._set_progress(15, "提取作者...")

            # Step 2: 提取作者
            self._gui_log("Step 2/4: 提取作者...", "info")
            authors = extract_unique_authors(videos, min_followers=cfg["min_followers"])
            if not self.running: return
            self._gui_log(f"✓ 去重后 {len(authors)} 位达人", "success")
            if not authors:
                self._gui_done()
                return
            self._set_progress(20, f"扫描达人主页 (并发x{concurrency})...")

            # Step 3: 并发扫描达人
            self._gui_log(f"Step 3/4: 并发扫描达人主页 (并发数={concurrency})...", "info")
            self._qualified_data = []
            total = len(authors)
            sem = asyncio.Semaphore(concurrency)
            lock = asyncio.Lock()
            completed = [0]

            async def _scan_one(author, index):
                if not self.running:
                    return
                async with sem:
                    if not self.running:
                        return
                    sec_uid = author["sec_uid"]
                    nickname = author["nickname"]

                    await limiter.wait("user")
                    task_engine = _make_engine()
                    try:
                        task_engine.rotate_ua()
                        posts = await crawl_user_posts(
                            task_engine, sec_uid,
                            max_count=cfg["scan_count"],
                            limiter=limiter,
                        )
                        if not posts:
                            self._gui_table_add(index, nickname, "无作品", "")
                            return

                        result = await analyzer.analyze(author, posts, engine=task_engine, skip_detail=skip_detail)
                        if result["qualified"]:
                            d = result["data"]
                            async with lock:
                                self._qualified_data.append(d)
                            extra = f"{d['total_video_count']}视频/{d['shopping_video_count']}挂车"
                            self._gui_table_add(index, nickname, "✓ 带货达人", extra)
                            async with lock:
                                self._author_urls[index] = d["homepage_url"]
                        else:
                            self._gui_table_add(index, nickname, "✗ 非带货", "")
                    except Exception as e:
                        self._gui_table_add(index, nickname, f"⚠ {str(e)[:20]}", "", error_msg=str(e))
                    finally:
                        await task_engine.close()

                    async with lock:
                        completed[0] += 1
                        pct = 20 + int(completed[0] / total * 75)
                        self._set_progress(pct, f"达人 {completed[0]}/{total}")

            tasks = [_scan_one(a, i) for i, a in enumerate(authors)]
            self._active_tasks = [asyncio.ensure_future(t) for t in tasks]
            results = await asyncio.gather(*self._active_tasks, return_exceptions=True)
            self._active_tasks = []

            if not self.running:
                self._try_export_partial()
                self._gui_log("已停止，现有数据已导出", "warning")
                self._gui_done()
                return

            # Step 4: 导出
            self._set_progress(95, "导出 Excel...")
            self._gui_log(f"Step 4/4: 导出 → {len(self._qualified_data)} 位视频带货达人", "success")
            out_dir = cfg.get("output_dir", OUTPUT_DIR)
            self._last_filepath = save_to_xlsx(self._qualified_data, cfg["keyword"], out_dir)
            self._gui_log(f"✅ 已保存: {self._last_filepath}", "success")
            if self._qualified_data:
                self._gui_log(f"共 {len(self._qualified_data)} 位视频带货达人", "success")
            else:
                self._gui_log("未找到带货达人，已生成空表", "warning")

            self.root.after(0, lambda: self.export_btn.configure(state=NORMAL))
            self._gui_done()

        except Exception as e:
            self._gui_log(f"异常: {e}", "error")
            self.root.after(0, lambda: self.export_btn.configure(state=NORMAL))
            self._gui_done()

    def _gui_log(self, msg, tag="info"):
        self.root.after(0, lambda: self._log(msg, tag))

    def _set_progress(self, pct, label):
        def _do():
            self.progress_var.set(pct)
            self.progress_label.configure(text=label)
        self.root.after(0, _do)

    def _gui_table_add(self, idx, nickname, status, extra, error_msg=""):
        def _add():
            tag = ""
            if "✓" in status:
                tag = "qualified"
            elif "✗" in status or "无" in status:
                tag = "not_qualified"
            else:
                tag = "error"
                if error_msg:
                    self._author_errors[idx] = error_msg
            self.result_tree.insert("", "end", values=(idx + 1, nickname, status, extra), tags=(tag,))
            self.result_tree.see(self.result_tree.get_children()[-1])
        self.root.after(0, _add)

    def _gui_done(self):
        self._set_progress(100, "100%")
        self.root.after(0, lambda: self._set_running(False))
        self.root.after(0, lambda: self.status_bar.configure(text="完成"))

        # 表格颜色
        self.result_tree.tag_configure("qualified", background="#065f46", foreground=GREEN)
        self.result_tree.tag_configure("not_qualified", background=BG_DARK, foreground=FG_MUTED)
        self.result_tree.tag_configure("error", background="#7f1d1d", foreground=RED)


def main():
    root = Tk()
    app = DouyinGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
