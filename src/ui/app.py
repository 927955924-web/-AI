import csv
import os
import uuid
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from src.infrastructure.db import connect, init_db
from src.infrastructure.logger import get_logger
from src.infrastructure.paths import app_data_dir, app_db_path, app_log_path
from src.infrastructure.secret_store import unprotect
from src.infrastructure.repositories.user_repository import UserRepository
from src.infrastructure.repositories.shop_repository import ShopRepository
from src.infrastructure.repositories.product_repository import ProductRepository
from src.infrastructure.repositories.chat_session_repository import ChatSessionRepository
from src.infrastructure.repositories.message_repository import MessageRepository
from src.infrastructure.repositories.settings_repository import SettingsRepository
from src.infrastructure.repositories.stats_repository import StatsRepository
from src.infrastructure.knowledge_base import KnowledgeBase
from src.services.ai_service import AI服务
from src.services.browser_manager import BrowserManager
from src.services.monitoring_service import MonitoringService, create_monitoring_decorator


class DesktopApp:
    def __init__(self, root, conn):
        self.root = root
        self.conn = conn
        self.logger = get_logger()
        self.users = UserRepository(conn)
        self.shops = ShopRepository(conn)
        self.products = ProductRepository(conn)
        self.sessions = ChatSessionRepository(conn)
        self.messages = MessageRepository(conn)
        self.settings = SettingsRepository(conn)
        self.stats = StatsRepository(conn)
        self.kb = KnowledgeBase("knowledge.db")
        self.ai = AI服务(conn)
        self.monitor = MonitoringService(self.stats)
        self.monitor_decorator = create_monitoring_decorator(self.monitor)
        self.browser = BrowserManager(conn, self.monitor)

        self.current_user = None
        self.current_shop_id = ""
        self.current_session_id = ""

        self.root.title("智语AI客服")
        self.root.geometry("1280x760")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 默认不强制登录，直接进入主界面
        # self.ensure_login() 
        self.create_widgets()
        
        # 刷新仪表盘状态（如果已登录）
        if self.current_user:
            self.refresh_top_filters()
            self.refresh_shop_table()
            self.refresh_statistics()
            self.refresh_debug()

    def set_current_user(self, user):
        old_user = self.current_user
        self.current_user = user
        if self.monitor.enabled:
            self.monitor.record_state_change(
                entity_type="user",
                entity_id=user.user_id if user else "",
                old_state=old_user.username if old_user else "None",
                new_state=user.username if user else "None",
                metadata={
                    "old_user_id": old_user.user_id if old_user else "",
                    "new_user_id": user.user_id if user else ""
                }
            )

    def set_current_shop_id(self, shop_id):
        old_shop_id = self.current_shop_id
        self.current_shop_id = shop_id
        if self.monitor.enabled:
            self.monitor.record_state_change(
                entity_type="shop",
                entity_id=shop_id if shop_id else "",
                old_state=old_shop_id,
                new_state=shop_id,
                metadata={}
            )

    def set_current_session_id(self, session_id):
        old_session_id = self.current_session_id
        self.current_session_id = session_id
        if self.monitor.enabled:
            self.monitor.record_state_change(
                entity_type="session",
                entity_id=session_id if session_id else "",
                old_state=old_session_id,
                new_state=session_id,
                metadata={}
            )

    def on_close(self):
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.kb.close()
        except Exception:
            pass
        self.root.destroy()

    def ensure_login(self):
        # 创建模态对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("欢迎登录")
        dialog.geometry("400x580") # 增加高度以适应注册表单
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.configure(bg='white')
        
        # 居中显示
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - 400) // 2
        y = (screen_height - 580) // 2
        dialog.geometry(f"+{x}+{y}")

        # 标题变量
        title_var = tk.StringVar(value="欢迎登录")
        
        # 顶部标题
        tk.Label(dialog, textvariable=title_var, font=("微软雅黑", 18, "bold"), bg="white", fg="#333").pack(pady=(30, 20))

        # Tab切换区域
        tab_frame = tk.Frame(dialog, bg="white")
        tab_frame.pack(fill="x", padx=40)

        # Tab指示器线条
        indicator = tk.Frame(tab_frame, bg="#2962ff", height=3, width=40)
        
        # 内容容器
        content_frame = tk.Frame(dialog, bg="white")
        content_frame.pack(fill="both", expand=True, padx=40, pady=20)

        # 登录表单
        login_frame = tk.Frame(content_frame, bg="white")
        
        # 注册表单
        register_frame = tk.Frame(content_frame, bg="white")

        # 变量定义
        login_phone = tk.StringVar()
        login_pwd = tk.StringVar()
        
        reg_phone = tk.StringVar()
        reg_code = tk.StringVar()
        reg_pwd = tk.StringVar()
        reg_pwd_confirm = tk.StringVar()
        reg_invite = tk.StringVar()

        def send_code():
            phone = reg_phone.get().strip()
            if not phone or phone == "手机号":
                messagebox.showwarning("提示", "请输入手机号")
                return
            if not phone.isdigit() or len(phone) != 11:
                 messagebox.showwarning("提示", "请输入有效的11位手机号")
                 return
            
            # 模拟发送验证码
            messagebox.showinfo("提示", f"验证码已发送至 {phone}\n(模拟验证码: 888888)")
            
            # 倒计时逻辑
            def countdown(count):
                if count > 0:
                    btn_send_code.config(text=f"{count}s后重试", state="disabled", cursor="arrow", fg="#999")
                    dialog.after(1000, countdown, count-1)
                else:
                    btn_send_code.config(text="发送验证码", state="normal", cursor="hand2", fg="#666")
            
            countdown(60)

        def create_entry(parent, var, placeholder, show=None, is_code=False):
            bg_frame = tk.Frame(parent, bg="white", highlightbackground="#ddd", highlightthickness=1, highlightcolor="#2962ff")
            bg_frame.pack(fill="x", pady=(0, 15), ipady=5)
            
            entry = tk.Entry(bg_frame, textvariable=var, font=("微软雅黑", 10), bd=0, bg="white", show=show)
            
            btn_obj = None
            if is_code:
                entry.pack(side="left", fill="x", expand=True, padx=10, pady=5)
                # 分割线
                tk.Frame(bg_frame, width=1, bg="#ddd").pack(side="left", fill="y", pady=5)
                # 发送验证码按钮
                btn_obj = tk.Button(bg_frame, text="发送验证码", font=("微软雅黑", 9), fg="#666", bg="white", 
                                     relief="flat", cursor="hand2", activebackground="white")
                btn_obj.pack(side="right", padx=10)
            else:
                entry.pack(fill="x", padx=10, pady=5)

            # Placeholder逻辑
            def on_focusin(e):
                if entry.get() == placeholder:
                    entry.delete(0, "end")
                    entry.config(fg='black')
                    if show == "*": entry.config(show="*")

            def on_focusout(e):
                if entry.get() == '':
                    if show == "*": entry.config(show="")
                    entry.insert(0, placeholder)
                    entry.config(fg='#999')
            
            # 初始化Placeholder
            if not var.get():
                if show == "*": entry.config(show="")
                entry.insert(0, placeholder)
                entry.config(fg='#999')
            
            entry.bind("<FocusIn>", on_focusin)
            entry.bind("<FocusOut>", on_focusout)
            
            if is_code:
                return entry, btn_obj
            return entry

        # 构建登录表单
        create_entry(login_frame, login_phone, "手机号")
        create_entry(login_frame, login_pwd, "密码", show="*")
        
        btn_login = tk.Button(login_frame, text="登录", font=("微软雅黑", 12, "bold"), bg="#2962ff", fg="white", 
                              relief="flat", cursor="hand2")
        btn_login.pack(fill="x", pady=(20, 0), ipady=5)
        
        login_links = tk.Frame(login_frame, bg="white")
        login_links.pack(fill="x", pady=20)
        tk.Label(login_links, text="忘记密码?", font=("微软雅黑", 9), bg="white", fg="#2962ff", cursor="hand2").pack(side="left")
        lbl_to_reg = tk.Label(login_links, text="没有账户? 去注册", font=("微软雅黑", 9), bg="white", fg="#2962ff", cursor="hand2")
        lbl_to_reg.pack(side="right")

        # 构建注册表单
        create_entry(register_frame, reg_phone, "手机号")
        _, btn_send_code = create_entry(register_frame, reg_code, "验证码", is_code=True)
        btn_send_code.config(command=send_code)
        
        create_entry(register_frame, reg_pwd, "密码", show="*")
        create_entry(register_frame, reg_pwd_confirm, "确认密码", show="*")
        create_entry(register_frame, reg_invite, "邀请码 (选填)")
        
        btn_reg = tk.Button(register_frame, text="注册", font=("微软雅黑", 12, "bold"), bg="#2962ff", fg="white", 
                            relief="flat", cursor="hand2")
        btn_reg.pack(fill="x", pady=(10, 0), ipady=5)
        
        reg_links = tk.Frame(register_frame, bg="white")
        reg_links.pack(fill="x", pady=20)
        lbl_to_login = tk.Label(reg_links, text="已有账户? 去登录", font=("微软雅黑", 9), bg="white", fg="#2962ff", cursor="hand2")
        lbl_to_login.pack(side="right")

        def switch_mode(is_login):
            self.login_mode = is_login
            if is_login:
                title_var.set("欢迎登录")
                btn_login_tab.config(fg="#2962ff", font=("微软雅黑", 12, "bold"))
                btn_register_tab.config(fg="#999", font=("微软雅黑", 12))
                indicator.place(x=45, y=35)
                register_frame.pack_forget()
                login_frame.pack(fill="both", expand=True)
            else:
                title_var.set("欢迎注册")
                btn_login_tab.config(fg="#999", font=("微软雅黑", 12))
                btn_register_tab.config(fg="#2962ff", font=("微软雅黑", 12, "bold"))
                indicator.place(x=135, y=35)
                login_frame.pack_forget()
                register_frame.pack(fill="both", expand=True)

        btn_login_tab = tk.Label(tab_frame, text="登录", font=("微软雅黑", 12, "bold"), bg="white", fg="#2962ff", cursor="hand2")
        btn_login_tab.place(x=45, y=5)
        btn_login_tab.bind("<Button-1>", lambda e: switch_mode(True))

        btn_register_tab = tk.Label(tab_frame, text="注册", font=("微软雅黑", 12), bg="white", fg="#999", cursor="hand2")
        btn_register_tab.place(x=135, y=5)
        btn_register_tab.bind("<Button-1>", lambda e: switch_mode(False))
        
        tk.Frame(tab_frame, bg="white", height=40).pack()
        tk.Frame(tab_frame, bg="#eee", height=1).pack(fill="x", side="bottom")
        
        # 绑定跳转事件
        lbl_to_reg.bind("<Button-1>", lambda e: switch_mode(False))
        lbl_to_login.bind("<Button-1>", lambda e: switch_mode(True))

        # 业务逻辑
        def perform_login():
            u = login_phone.get()
            p = login_pwd.get()
            if u == "手机号" or p == "密码":
                messagebox.showwarning("提示", "请输入手机号和密码")
                return
            user = self.users.authenticate(u, p)
            if not user:
                messagebox.showerror("登录失败", "手机号或密码错误")
                return
            self.set_current_user(user)
            
            # 先销毁窗口，再更新主界面，避免主界面耗时操作阻塞销毁
            dialog.destroy()
            self.root.update() # 强制刷新UI
            
            self.update_ui_after_login()

        def perform_register():
            u = reg_phone.get()
            p = reg_pwd.get()
            pc = reg_pwd_confirm.get()
            if u == "手机号" or p == "密码":
                messagebox.showwarning("提示", "请输入完整信息")
                return
            if p != pc:
                messagebox.showerror("错误", "两次输入的密码不一致")
                return
            if self.users.get_by_username(u):
                messagebox.showwarning("提示", "该手机号已注册")
                return
            user = self.users.create(u, p, role="user")
            self.set_current_user(user)
            
            # 先销毁窗口，再更新主界面
            dialog.destroy()
            self.root.update() # 强制刷新UI
            
            self.update_ui_after_login()

        btn_login.config(command=perform_login)
        btn_reg.config(command=perform_register)

        # 初始化显示
        switch_mode(True)
        
        dialog.grab_set()
        dialog.wait_window()
        return True

    def update_ui_after_login(self):
        # 刷新顶部栏
        if hasattr(self, 'user_status_label'):
             self.user_status_label.configure(text=f"当前用户：{self.current_user.username}", foreground="#333")
        
        # 刷新其他数据
        self.refresh_top_filters()
        self.refresh_shop_table()
        self.refresh_statistics()
        self.refresh_debug()

        # 登录成功后，自动跳转到“店铺管理”页面
        # 0 代表第一个Tab，即店铺管理
        self.switch_to_tab(0)

    def create_widgets(self):
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        # 定义颜色样式 - 统一设计系统
        style = ttk.Style()
        # 颜色定义
        self.colors = {
            "primary": "#2962ff",
            "secondary": "#7265e6",
            "success": "#52c41a",
            "warning": "#fa8c16",
            "error": "#ff4d4f",
            "background": "#f5f7fa",
            "card": "#ffffff",
            "text_primary": "#333333",
            "text_secondary": "#666666",
            "border": "#eeeeee"
        }
        # 背景样式
        style.configure("Console.TFrame", background=self.colors["card"])
        style.configure("Dashboard.TFrame", background=self.colors["background"])
        style.configure("Log.TFrame", background=self.colors["card"])
        # 按钮样式
        style.configure("Primary.TButton", background=self.colors["primary"], foreground="white", borderwidth=0, focusthickness=0, focuscolor="none")
        style.map("Primary.TButton", background=[("active", self.colors["primary"]), ("disabled", "#cccccc")])
        style.configure("Success.TButton", background=self.colors["success"], foreground="white", borderwidth=0)
        style.configure("Warning.TButton", background=self.colors["warning"], foreground="white", borderwidth=0)
        style.configure("Error.TButton", background=self.colors["error"], foreground="white", borderwidth=0)
        # 输入框样式
        style.configure("Modern.TEntry", fieldbackground=self.colors["card"], bordercolor=self.colors["border"], lightcolor=self.colors["border"])
        # 标签样式
        style.configure("Title.TLabel", font=("微软雅黑", 16, "bold"), foreground=self.colors["text_primary"])
        style.configure("Subtitle.TLabel", font=("微软雅黑", 12), foreground=self.colors["text_secondary"])
        style.configure("Caption.TLabel", font=("微软雅黑", 10), foreground=self.colors["text_secondary"])
        
        # 顶部工具栏（可选保留，或整合到控制台）
        # self.create_top_toolbar() 

        # 三栏布局
        # 左侧：控制台 (20%)
        self.left_panel = ttk.Frame(self.main_container, style="Console.TFrame", width=280)
        self.left_panel.pack(side="left", fill="y", padx=2, pady=2)
        self.left_panel.pack_propagate(False)

        # 右侧：日志/状态 (20%)
        self.right_panel = ttk.Frame(self.main_container, style="Log.TFrame", width=280)
        self.right_panel.pack(side="right", fill="y", padx=2, pady=2)
        self.right_panel.pack_propagate(False)

        # 中间：仪表盘/主工作区 (60%)
        self.center_panel = ttk.Frame(self.main_container, style="Dashboard.TFrame")
        self.center_panel.pack(side="left", fill="both", expand=True, padx=2, pady=2)

        self.create_console_panel()
        self.create_dashboard_panel()
        self.create_log_panel()

        # 隐藏的Notebook用于功能模块（后续通过Dashboard点击切换）
        self.notebook_frame = ttk.Frame(self.center_panel) # 初始隐藏
        
        # 使用自定义样式的Notebook来隐藏Tabs
        style.layout("NoTabs.TNotebook", []) # 移除Tab栏布局
        self.notebook = ttk.Notebook(self.notebook_frame, style="NoTabs.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        
        # 初始化各个功能Tab
        self.init_tabs()
        
        # 添加监控菜单
        self.add_monitoring_menu()

    def create_console_panel(self):
        # 顶部标题按钮
        header = tk.Label(self.left_panel, text="打开控制台", bg=self.colors["primary"], fg="white", font=("微软雅黑", 14, "bold"), pady=15)
        header.pack(fill="x", pady=(0, 10))

        # 控制按钮组
        ctrl_frame = ttk.Frame(self.left_panel)
        ctrl_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(ctrl_frame, text="启动全部", width=12, style="Primary.TButton").pack(side="left", padx=2)
        ttk.Button(ctrl_frame, text="停止全部", width=12, style="Primary.TButton").pack(side="right", padx=2)

        # 搜索框
        search_frame = ttk.Frame(self.left_panel)
        search_frame.pack(fill="x", padx=10, pady=10)
        entry = ttk.Entry(search_frame, style="Modern.TEntry")
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(search_frame, text="🔍", width=3, style="Primary.TButton").pack(side="right")

        # 列表区域（模拟）
        list_frame = ttk.Frame(self.left_panel, relief="sunken")
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        # 这里可以放置消息列表或设备列表

        # 底部操作区
        bottom_frame = ttk.Frame(self.left_panel)
        bottom_frame.pack(fill="x", side="bottom", padx=10, pady=10)
        
        # 二维码占位
        qr_label = tk.Label(bottom_frame, text="二维码区域", bg=self.colors["border"], width=10, height=5)
        qr_label.pack(side="left", padx=(0, 5))
        
        # 底部按钮
        btn_box = ttk.Frame(bottom_frame)
        btn_box.pack(side="left", fill="both", expand=True)
        ttk.Button(btn_box, text="操作教程", style="Primary.TButton").pack(fill="x", pady=2)
        ttk.Button(btn_box, text="视频演示", style="Primary.TButton").pack(fill="x", pady=2)

    def create_dashboard_panel(self):
        # 仪表盘主容器
        self.dashboard_frame = ttk.Frame(self.center_panel)
        self.dashboard_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 顶部欢迎语
        top_bar = ttk.Frame(self.dashboard_frame)
        top_bar.pack(fill="x", pady=(0, 10))
        
        user_text = f"个人摘要：{self.current_user.username}" if self.current_user else "个人摘要：请注册后登录查看"
        self.user_status_label = ttk.Label(top_bar, text=user_text, foreground=self.colors["text_secondary"])
        self.user_status_label.pack(side="left")
        
        ttk.Button(top_bar, text="登录/注册", command=self.ensure_login, style="Primary.TButton").pack(side="right")

        # 公告栏
        notice_frame = ttk.LabelFrame(self.dashboard_frame, text="公告")
        notice_frame.pack(fill="x", pady=(0, 15))
        ttk.Label(notice_frame, text="有问题欢迎反馈，官网：https://www.example.com 下载最新版本使用。", padding=10).pack(anchor="w")

        # 核心功能区 (Grid布局)
        grid_frame = ttk.Frame(self.dashboard_frame)
        grid_frame.pack(fill="both", expand=True)
        grid_frame.columnconfigure(0, weight=3) # 情景监控
        grid_frame.columnconfigure(1, weight=2) # 关键词/敏感词
        grid_frame.columnconfigure(2, weight=2) # 
        grid_frame.rowconfigure(0, weight=2) # 顶部大块
        grid_frame.rowconfigure(1, weight=2) # 中间块
        grid_frame.rowconfigure(2, weight=1) # 底部块

        # 1. 店铺/商品/知识 (主色大块) - 跨3列
        btn_shop = tk.Button(grid_frame, text="🏬 📦 🧠\n店铺/商品/知识", bg=self.colors["primary"], fg="white", 
                             font=("微软雅黑", 16, "bold"), relief="flat", command=lambda: self.check_login_and_switch(0))
        btn_shop.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=2, pady=2)

        # 2. 情景监控 (次要色左块)
        btn_monitor = tk.Button(grid_frame, text="📹\n情景监控", bg=self.colors["secondary"], fg="white", 
                                font=("微软雅黑", 14), relief="flat", command=lambda: self.check_login_and_switch(6)) # 调试工具暂代
        btn_monitor.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=2, pady=2)

        # 3. 关键词回复 (成功色右上)
        btn_keyword = tk.Button(grid_frame, text="🎯\n关键词回复", bg=self.colors["success"], fg="white", 
                                font=("微软雅黑", 12), relief="flat", command=lambda: self.check_login_and_switch(2)) # AI客服暂代
        btn_keyword.grid(row=1, column=1, sticky="nsew", padx=2, pady=2)

        # 4. 敏感词拦截 (警告色右中)
        btn_filter = tk.Button(grid_frame, text="🚫\n敏感词拦截", bg=self.colors["warning"], fg="white", 
                               font=("微软雅黑", 12), relief="flat", command=lambda: self.check_login_and_switch(5)) # 设置暂代
        btn_filter.grid(row=1, column=2, sticky="nsew", padx=2, pady=2)

        # 5. 历史数据 (次要色右下) - 跨2列
        btn_history = tk.Button(grid_frame, text="💬 历史数据", bg=self.colors["secondary"], fg="white", 
                                font=("微软雅黑", 14), relief="flat", command=lambda: self.check_login_and_switch(3))
        btn_history.grid(row=2, column=1, columnspan=2, sticky="nsew", padx=2, pady=2)

        # 6. 测试AI客服 (成功色长条)
        btn_test = tk.Button(self.dashboard_frame, text="💡 测试AI客服", bg=self.colors["success"], fg="white", 
                             font=("微软雅黑", 12, "bold"), relief="flat", command=lambda: self.check_login_and_switch(2))
        btn_test.pack(fill="x", pady=10)

        # 底部平台图标栏
        platform_bar = ttk.Frame(self.dashboard_frame)
        platform_bar.pack(fill="x", side="bottom")
        platforms = ["千牛", "拼多多", "抖店", "快手", "京东", "闲鱼", "微信", "小红书"]
        for p in platforms:
            ttk.Label(platform_bar, text=f"🏷️{p}", relief="solid", borderwidth=1, padding=5).pack(side="left", padx=2, fill="x", expand=True)

    def check_login_and_switch(self, index):
        if not self.current_user:
            if self.ensure_login() and self.current_user:
                self.switch_to_tab(index)
        else:
            self.switch_to_tab(index)

    def create_log_panel(self):
        # 1. 顶部状态 (成功色大块)
        status_frame = tk.Frame(self.right_panel, bg=self.colors["success"], height=120)
        status_frame.pack(fill="x")
        status_frame.pack_propagate(False)
        
        tk.Label(status_frame, text="AI接待中\n点击暂停\nCtrl+Alt+S", bg=self.colors["success"], fg="white", 
                 font=("微软雅黑", 16, "bold"), justify="left").pack(expand=True, anchor="center")

        # 2. 更多功能 (开关组)
        opt_frame = ttk.LabelFrame(self.right_panel, text="更多功能")
        opt_frame.pack(fill="x", padx=5, pady=5)
        
        # 自定义开关样式 (这里用Checkbutton模拟)
        def create_switch(parent, text, default=False):
            var = tk.BooleanVar(value=default)
            # 使用 Unicode 字符模拟开关外观
            cb = tk.Checkbutton(parent, text=text, variable=var, font=("微软雅黑", 10), 
                                onvalue=True, offvalue=False, bg="white", activebackground="white")
            cb.pack(anchor="w", pady=5, padx=5)
            return var

        # 由于 ttk.Checkbutton 样式受限，这里使用 tk.Checkbutton 并设置背景为白色以匹配截图
        switch_bg = tk.Frame(opt_frame, bg="white")
        switch_bg.pack(fill="x")
        
        self.sw_monitor = create_switch(switch_bg, "情景监控", True)
        self.sw_order = create_switch(switch_bg, "识别订单", False)
        self.sw_debug = create_switch(switch_bg, "调试模式", False)

        # 3. 日志区域 (窄边框，显示日期和内容)
        log_container = ttk.LabelFrame(self.right_panel, text="日志")
        log_container.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        
        self.log_text = tk.Text(log_container, font=("微软雅黑", 9), state="disabled", wrap="char", 
                                bg="white", bd=0, padx=5, pady=5)
        scroll = ttk.Scrollbar(log_container, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        
        # 模拟初始日志 (还原截图内容)
        self.log_raw("02-12\n23:38:06\n[INFO] :\n已开启抖店监听!")
        self.log_raw("02-12\n23:38:06\n[INFO] :\n已开启千牛客户端监听，接待千牛需要设置消息弹窗提醒，且关闭对当前对话的免打扰!")
        self.log_raw("如果客户的消息未激发千牛的弹窗提醒，那么客户回复的应该是‘谢谢’‘好的’之类的，此情况下千牛不会有未回复计时，ai也不会回复!")
        self.log_raw("首次运行请务必前往官网查看接待千牛的必要设置！！！")
        self.log_raw("02-12\n23:38:06\n[INFO] :\n已开启微信客户端监听，请保持系统托盘微信图标始终可见")

    def log(self, message):
        # 保持旧接口兼容，但转发到新样式
        time_str = datetime.datetime.now().strftime('%m-%d\n%H:%M:%S')
        formatted = f"{time_str}\n[INFO] :\n{message}"
        self.log_raw(formatted)

    def log_raw(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def switch_to_tab(self, index):
        # 隐藏仪表盘，显示Notebook
        self.dashboard_frame.pack_forget()
        self.notebook_frame.pack(fill="both", expand=True)
        self.notebook.select(index)
        
        # 已移除返回按钮，根据需求删除
        if hasattr(self, 'back_btn'):
            self.back_btn.place_forget()

    def show_dashboard(self):
        self.notebook_frame.pack_forget()
        self.dashboard_frame.pack(fill="both", expand=True, padx=10, pady=10)
        if hasattr(self, 'back_btn'):
            self.back_btn.place_forget()

    def init_tabs(self):
        self.shop_tab = ttk.Frame(self.notebook)
        self.product_tab = ttk.Frame(self.notebook)
        self.ai_tab = ttk.Frame(self.notebook)
        self.history_tab = ttk.Frame(self.notebook)
        self.stats_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)
        self.debug_tab = ttk.Frame(self.notebook)

        self.monitor_tab = ttk.Frame(self.notebook) # 新增情景监控Tab
        self.notebook.add(self.monitor_tab, text="情景监控")
        
        # 调整Tab顺序以匹配截图（店铺管理, 商品管理, AI客服, 聊天历史, 情景监控...）
        # 这里为了简单，直接添加到末尾，然后重新排序或直接按index引用
        # 更好的方式是直接定义正确的顺序：
        # 店铺管理(0), 情景监控(1), 数据监控(2), 关键词(3), 平台设置(4), 通用知识库(5)
        
        # 清空现有Tabs重新添加
        for tab in self.notebook.tabs():
            self.notebook.forget(tab)
            
        self.notebook.add(self.shop_tab, text="店铺空间")
        self.notebook.add(self.monitor_tab, text="情景监控")
        self.notebook.add(self.stats_tab, text="数据监控") # 原数据统计
        self.notebook.add(self.ai_tab, text="关键词") # 原AI客服暂代
        self.notebook.add(self.settings_tab, text="平台设置")
        self.notebook.add(self.product_tab, text="通用知识库") # 原商品管理暂代
        
        self.build_shop_tab()
        self.build_monitor_tab() # 新增构建方法
        # self.build_product_tab() # 暂时复用旧逻辑，后续可按需调整
        # self.build_ai_tab()
        # self.build_stats_tab()
        # self.build_settings_tab()
        
    def build_monitor_tab(self):
        # 1. 顶部标题和搜索
        header = tk.Frame(self.monitor_tab, bg="white", height=80)
        header.pack(fill="x")
        
        tk.Label(header, text="情景监控", font=("微软雅黑", 18, "bold"), bg="white", fg="#333").pack(anchor="w", padx=20, pady=(15, 5))
        tk.Label(header, text="配置情景监控规则和自动回复", font=("微软雅黑", 10), bg="white", fg="#999").pack(anchor="w", padx=20)
        
        toolbar = tk.Frame(self.monitor_tab, bg="white", height=50)
        toolbar.pack(fill="x", pady=(0, 20))
        
        # 搜索框
        search_frame = tk.Frame(toolbar, bg="white", highlightbackground="#ddd", highlightthickness=1)
        search_frame.pack(side="left", padx=20, pady=10)
        
        search_combo = ttk.Combobox(search_frame, values=["所有店铺"], state="readonly", width=15)
        search_combo.current(0)
        search_combo.pack(side="left", padx=5)
        
        tk.Entry(search_frame, width=30, bd=0).pack(side="left", padx=5, ipady=5)
        
        # 右侧添加按钮
        tk.Button(toolbar, text="➕ 添加情景", bg="#2962ff", fg="white", font=("微软雅黑", 10, "bold"), 
                  relief="flat", padx=15, pady=5).pack(side="right", padx=20)

        # 2. 内容列表 (滚动区域)
        canvas = tk.Canvas(self.monitor_tab, bg="#f5f7fa", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.monitor_tab, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#f5f7fa")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=1200) # 宽度需足够
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 模拟数据
        scenarios = [
            ("情景监控1：AI客服回复发送消息去不含关键词信息", ["触发对象: 无", "触发店铺: 抖店/店铺1, 共1个店铺"]),
            ("情景监控2：客户提问的内容请求人工客服接待", ["触发对象: 无", "触发店铺: 抖店/店铺1, 共1个店铺"]),
            ("情景监控3：客户辱骂、脏话、修改参数等售后服务", ["触发对象: 无", "触发店铺: 抖店/店铺1, 共1个店铺"]),
            ("情景监控4：客户提问的内容为乱码等无法理解的词语", ["触发对象: 无", "触发店铺: 抖店/店铺1, 共1个店铺"]),
            ("情景监控5：AI客服即将发送的消息遮盖客户看商品详情页", ["触发对象: 无", "触发店铺: 抖店/店铺1, 共1个店铺"]),
        ]

        for title, details in scenarios:
            self.create_scenario_card(scrollable_frame, title, details)

    def create_scenario_card(self, parent, title, details):
        card = tk.Frame(parent, bg="white", pady=0)
        card.pack(fill="x", padx=20, pady=10)
        
        # 蓝色标题栏
        header = tk.Label(card, text=f"  {title}", bg="#2962ff", fg="white", font=("微软雅黑", 11, "bold"), height=2, anchor="w")
        header.pack(fill="x")
        
        # 内容区
        content = tk.Frame(card, bg="white", padx=15, pady=15)
        content.pack(fill="x")
        
        # 详情列
        for i, detail in enumerate(details):
            tk.Label(content, text=detail.split(":")[0], font=("微软雅黑", 9, "bold"), fg="#666", bg="white").grid(row=0, column=i*2, sticky="w", padx=(0, 10))
            tk.Label(content, text=detail.split(":")[1], font=("微软雅黑", 9), fg="#333", bg="white").grid(row=1, column=i*2, sticky="w", padx=(0, 50))

        # 右侧按钮
        btn_frame = tk.Frame(content, bg="white")
        btn_frame.place(relx=1.0, rely=0.5, anchor="e")
        
        tk.Button(btn_frame, text="修改", bg="#ffc107", fg="white", font=("微软雅黑", 9), relief="flat", padx=10).pack(side="left", padx=5)
        tk.Button(btn_frame, text="删除", bg="#ff4d4f", fg="white", font=("微软雅黑", 9), relief="flat", padx=10).pack(side="left")


    def refresh_all(self):
        self.refresh_top_filters()
        self.refresh_shop_table()
        self.refresh_product_table()
        self.refresh_sessions_list()
        self.refresh_history_sessions()
        self.refresh_statistics()
        self.refresh_settings()
        self.refresh_debug()

    def on_platform_change(self):
        self.refresh_top_filters()
        self.refresh_shop_table()
        self.refresh_product_table()
        self.refresh_sessions_list()
        self.refresh_history_sessions()
        self.refresh_statistics()

    def on_shop_change(self):
        shop_id = self._shop_name_to_id(self.shop_filter_var.get())
        self.set_current_shop_id(shop_id)
        self.set_current_session_id("")
        self.refresh_product_table()
        self.refresh_sessions_list()
        self.refresh_history_sessions()
        self.refresh_statistics()

    def on_global_search(self):
        self.refresh_shop_table()
        self.refresh_product_table()
        self.refresh_history_sessions()
        self.refresh_sessions_list()

    def refresh_top_filters(self):
        platforms = ["全部平台"] + sorted({s.platform_type for s in self.shops.list() if s.platform_type})
        if "全部平台" not in platforms:
            platforms.insert(0, "全部平台")
        current = self.platform_var.get() or "全部平台"
        self.platform_combo["values"] = platforms
        if current not in platforms:
            current = "全部平台"
        self.platform_var.set(current)

        platform_filter = "" if current == "全部平台" else current
        shops = self.shops.list(platform_type=platform_filter)
        shop_names = ["全部店铺"] + [s.shop_name for s in shops]
        self.shop_combo["values"] = shop_names
        current_shop_name = self.shop_filter_var.get() or "全部店铺"
        if current_shop_name not in shop_names:
            current_shop_name = "全部店铺"
        self.shop_filter_var.set(current_shop_name)

        self.set_current_shop_id(self._shop_name_to_id(current_shop_name))

    def _shop_name_to_id(self, name: str):
        if not name or name == "全部店铺":
            return ""
        rows = self.shops.list(keyword=name)
        for s in rows:
            if s.shop_name == name:
                return s.shop_id
        return ""

    def build_shop_tab(self):
        # 1. 顶部导航栏 (白色背景，图标+文字)
        top_nav = tk.Frame(self.shop_tab, bg="white", height=60)
        top_nav.pack(fill="x")
        
        # 定义导航项及其对应的Tab索引
        # 店铺空间(0), 情景监控(1), 数据监控(2), 关键词(3), 平台设置(4), 通用知识库(5)
        nav_items = [
            ("🏬", "店铺空间", True, 0), 
            ("🖥️", "情景监控", False, 1),
            ("🛡️", "风控监控", False, 2), # 暂时映射到数据监控
            ("🔑", "关键词", False, 3),
            ("⚙️", "平台设置", False, 4),
            ("📄", "通用语料库", False, 5)
        ]
        
        for icon, text, selected, tab_index in nav_items:
            color = "#2962ff" if selected else "#666"
            font_style = ("微软雅黑", 10, "bold") if selected else ("微软雅黑", 10)
            
            # 使用Label作为按钮容器
            btn_frame = tk.Frame(top_nav, bg="white", padx=15, pady=10, cursor="hand2")
            btn_frame.pack(side="left")
            
            lbl = tk.Label(btn_frame, text=f"{icon} {text}", font=font_style, fg=color, bg="white", cursor="hand2")
            lbl.pack()
            
            if selected:
                tk.Frame(btn_frame, bg="#2962ff", height=3, width=40).pack(fill="x", pady=(2,0))
            
            # 绑定点击事件到 Frame 和 Label
            # 使用闭包捕获当前的 tab_index
            def on_click(e, index=tab_index):
                self.switch_to_tab(index)
            
            btn_frame.bind("<Button-1>", on_click)
            lbl.bind("<Button-1>", on_click)

        # 右侧顶部按钮区
        top_right = tk.Frame(top_nav, bg="white")
        top_right.pack(side="right", padx=20)
        
        tk.Button(top_right, text="💡 测试AI客服", bg="#2962ff", fg="white", font=("微软雅黑", 9), relief="flat").pack(side="left", padx=5)
        
        # VIP 按钮容器 (用于点击)
        self.vip_btn_frame = tk.Frame(top_right, bg="#ffd700", cursor="hand2")
        self.vip_btn_frame.pack(side="left", padx=5)
        
        # 左侧 VIP 标签
        vip_label = tk.Label(self.vip_btn_frame, text="VIP", bg="#bf8800", fg="white", font=("Arial", 9, "bold"), padx=5, pady=2)
        vip_label.pack(side="left", fill="y")
        
        # 右侧信息
        info_frame = tk.Frame(self.vip_btn_frame, bg="#ffd700", padx=5)
        info_frame.pack(side="left")
        tk.Label(info_frame, text="1000/1000", font=("Arial", 8, "bold"), bg="#ffd700", fg="#5a3e00").pack(anchor="e")
        tk.Label(info_frame, text="2026-02-15", font=("Arial", 7), bg="#ffd700", fg="#5a3e00").pack(anchor="e")
        
        # 下拉箭头
        tk.Label(self.vip_btn_frame, text="v", font=("Arial", 7), bg="#ffd700", fg="#5a3e00").pack(side="right", padx=(0, 5))

        # 绑定点击事件
        self.vip_btn_frame.bind("<Button-1>", self.show_vip_dropdown)
        for child in self.vip_btn_frame.winfo_children():
            child.bind("<Button-1>", self.show_vip_dropdown)
            for sub in child.winfo_children():
                sub.bind("<Button-1>", self.show_vip_dropdown)
        
        # 添加店铺管理界面
        self._unused_build_shop_tab()

    def show_vip_dropdown(self, event):
        if hasattr(self, 'vip_popup') and self.vip_popup.winfo_exists():
            self.vip_popup.destroy()
            return

        # 获取按钮位置
        x = self.vip_btn_frame.winfo_rootx()
        y = self.vip_btn_frame.winfo_rooty() + self.vip_btn_frame.winfo_height() + 5
        
        self.vip_popup = tk.Toplevel(self.root)
        self.vip_popup.overrideredirect(True) # 无边框
        # 增加高度以容纳所有内容，从420px增加到580px
        self.vip_popup.geometry(f"280x580+{x-120}+{y}") 
        self.vip_popup.configure(bg="white")
        
        # 1. 顶部警告色区域
        top_frame = tk.Frame(self.vip_popup, bg="#fff7e6", padx=15, pady=15)
        top_frame.pack(fill="x")
        
        tk.Label(top_frame, text="当前套餐", font=("微软雅黑", 9), bg="#fff7e6", fg="#d46b08").pack(anchor="w")
        
        # 白色卡片
        card = tk.Frame(top_frame, bg="white", padx=15, pady=15)
        card.pack(fill="x", pady=(10, 0))
        
        tk.Label(card, text="体验专业版", font=("微软雅黑", 11, "bold"), bg="white", fg="#5a3e00").pack(anchor="w")
        
        count_frame = tk.Frame(card, bg="white")
        count_frame.pack(anchor="w", pady=10)
        tk.Label(count_frame, text="1000", font=("Arial", 20, "bold"), bg="white", fg=self.colors["warning"]).pack(side="left")
        tk.Label(count_frame, text=" / 1000", font=("Arial", 12), bg="white", fg="#999").pack(side="left", pady=(8, 0))
        
        tk.Label(card, text="📅 本月结算:  2026-02-15", font=("微软雅黑", 9), bg="white", fg=self.colors["text_primary"]).pack(anchor="w")

        # 2. 会员套餐信息
        mid_frame = tk.Frame(self.vip_popup, bg="white", padx=15, pady=15)
        mid_frame.pack(fill="both", expand=True)
        
        tk.Label(mid_frame, text="会员套餐", font=("微软雅黑", 9), bg="white", fg=self.colors["text_secondary"]).pack(anchor="w")
        
        pkg_card = tk.Frame(mid_frame, bg="#f9f9f9", padx=10, pady=10, relief="solid", bd=1)
        pkg_card.config(highlightbackground="#eee", highlightthickness=1, bd=0)
        pkg_card.pack(fill="x", pady=10)
        
        tk.Label(pkg_card, text="体验专业版", font=("微软雅黑", 10, "bold"), bg="#f9f9f9", fg=self.colors["text_primary"]).pack(anchor="w")
        info_row = tk.Frame(pkg_card, bg="#f9f9f9")
        info_row.pack(fill="x", pady=(5, 0))
        tk.Label(info_row, text="1000 条/月", font=("微软雅黑", 9), bg="#f9f9f9", fg=self.colors["text_secondary"]).pack(side="left")
        tk.Label(info_row, text="🕒 2026-02-15 23:39:21", font=("Arial", 8), bg="#f9f9f9", fg=self.colors["text_secondary"]).pack(side="right")

        # 3. 邀请码
        tk.Label(mid_frame, text="我的邀请码", font=("微软雅黑", 9), bg="white", fg=self.colors["text_secondary"]).pack(anchor="w", pady=(10, 5))
        
        code_row = tk.Frame(mid_frame, bg="white")
        code_row.pack(fill="x")
        
        code_entry = tk.Entry(code_row, font=("Arial", 10), justify="center", fg=self.colors["primary"], relief="solid", bd=1)
        code_entry.insert(0, "657187")
        code_entry.config(state="readonly", readonlybackground="white")
        code_entry.pack(side="left", fill="x", expand=True, ipady=5)
        
        tk.Button(code_row, text="📋复制", font=("微软雅黑", 9), bg=self.colors["border"], relief="flat", padx=10).pack(side="right", padx=(10, 0))

        # 4. 退出登录
        tk.Frame(mid_frame, height=1, bg=self.colors["border"]).pack(fill="x", pady=15)
        
        # 红色边框效果
        logout_btn_frame = tk.Frame(mid_frame, bg=self.colors["error"], padx=1, pady=1)
        logout_btn_frame.pack(fill="x")
        
        tk.Button(logout_btn_frame, text="🛑 退出登录", font=("微软雅黑", 10), bg="white", fg=self.colors["error"], relief="flat", 
                  activebackground="#ffeaea", activeforeground=self.colors["error"], command=self.logout).pack(fill="x", ipady=5)

        # 5. 底部按钮 (固定在底部)
        btm_frame = tk.Frame(self.vip_popup, bg="white", padx=15, pady=15)
        btm_frame.pack(side="bottom", fill="x")
        
        tk.Button(btm_frame, text="💳 充值套餐", bg=self.colors["primary"], fg="white", font=("微软雅黑", 10, "bold"), relief="flat", 
                  command=self.show_recharge_window).pack(side="left", fill="x", expand=True, padx=(0, 5), ipady=5)
        tk.Button(btm_frame, text="🎫 兑换", bg=self.colors["success"], fg="white", font=("微软雅黑", 10, "bold"), relief="flat").pack(side="right", fill="x", expand=True, padx=(5, 0), ipady=5)

        # 点击外部关闭
        def close_popup(e):
            if not (0 <= e.x <= self.vip_popup.winfo_width() and 0 <= e.y <= self.vip_popup.winfo_height()):
                self.vip_popup.destroy()
        
        self.vip_popup.bind("<FocusOut>", lambda e: self.vip_popup.destroy())
        self.vip_popup.focus_set()

    def show_recharge_window(self):
        # 关闭下拉菜单
        if hasattr(self, 'vip_popup') and self.vip_popup.winfo_exists():
            self.vip_popup.destroy()

        win = tk.Toplevel(self.root)
        win.title("我的VIP套餐")
        win.geometry("1100x800")
        win.configure(bg=self.colors["background"])
        win.transient(self.root)
        
        # 滚动区域
        canvas = tk.Canvas(win, bg=self.colors["background"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=self.colors["background"])
        
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=1080) # 宽度适配
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 1. 顶部信息卡 (浅绿色背景)
        header = tk.Frame(scroll_frame, bg="#e8f5e8", height=100)
        header.pack(fill="x", padx=20, pady=20)
        header.pack_propagate(False)
        
        h_content = tk.Frame(header, bg="#e8f5e8")
        h_content.pack(fill="both", expand=True, padx=20, pady=10)
        
        tk.Label(h_content, text="体验专业版", font=("微软雅黑", 12, "bold"), bg="#e8f5e8", fg="#135200").pack(anchor="w")
        tk.Label(h_content, text="每月包含量: 1000", font=("微软雅黑", 9), bg="#e8f5e8", fg="#389e0d").pack(anchor="w", pady=5)
        tk.Label(h_content, text="到期时间: 2026-02-15 23:39", font=("微软雅黑", 9), bg="#e8f5e8", fg=self.colors["success"]).pack(anchor="w")

        # 2. 充值套餐标题
        bar = tk.Frame(scroll_frame, bg=self.colors["primary"], height=40)
        bar.pack(fill="x", padx=20)
        bar.pack_propagate(False)
        tk.Label(bar, text="充值套餐", font=("微软雅黑", 10, "bold"), bg=self.colors["primary"], fg="white").pack(expand=True)

        # 3. 套餐卡片网格
        cards_grid = tk.Frame(scroll_frame, bg=self.colors["background"])
        cards_grid.pack(fill="x", padx=10, pady=20)
        
        def create_card(parent, title, features, price, unit, color="#2962ff", tag=None, is_custom=False):
            card = tk.Frame(parent, bg="white", width=250, height=320, padx=20, pady=20)
            card.pack_propagate(False)
            
            # 标题
            title_frame = tk.Frame(card, bg="white")
            title_frame.pack(fill="x", pady=(0, 20))
            tk.Label(title_frame, text=title, font=("微软雅黑", 12, "bold"), bg="white", fg="#333").pack(expand=True)
            if tag:
                tk.Label(title_frame, text=tag, font=("Arial", 8, "bold"), bg="#ff4d4f", fg="white", padx=5).place(relx=1.0, y=0, anchor="ne")
            
            # 特性列表
            for feat in features:
                f_row = tk.Frame(card, bg="white")
                f_row.pack(fill="x", pady=2)
                tk.Label(f_row, text="✔" if not is_custom else "🎯", font=("Arial", 10), bg="white", fg="#52c41a" if not is_custom else "#ff4d4f").pack(side="left")
                tk.Label(f_row, text=feat, font=("微软雅黑", 9), bg="white", fg="#666").pack(side="left", padx=5)

            # 数量选择器
            if not is_custom:
                cnt_frame = tk.Frame(card, bg="white", pady=20)
                cnt_frame.pack()
                tk.Label(cnt_frame, text="每月包含量 (条)", font=("微软雅黑", 8), bg="white", fg="#999").pack()
                
                ctrl_row = tk.Frame(cnt_frame, bg="white")
                ctrl_row.pack(pady=5)
                tk.Button(ctrl_row, text="➖", relief="flat", bg="white", fg="#2962ff", font=("Arial", 12)).pack(side="left")
                tk.Label(ctrl_row, text="6000" if "月" in unit or "年" in unit else "10000", font=("Arial", 14, "bold"), bg="white", width=6).pack(side="left")
                tk.Button(ctrl_row, text="➕", relief="flat", bg="white", fg="#2962ff", font=("Arial", 12)).pack(side="left")
            else:
                tk.Label(card, text="\n\n", bg="white").pack() # 占位
                tk.Label(card, text="联系我们定制\n适合您店铺的套餐\n(包含企业版功能)", font=("微软雅黑", 9), bg="white", fg="#999", justify="center").pack(pady=20)

            # 价格与按钮
            price_box = tk.Frame(card, bg="white")
            price_box.pack(side="bottom", fill="x")
            
            if not is_custom:
                tk.Label(price_box, text="价格", font=("微软雅黑", 8), bg="white", fg="#999").pack()
                p_row = tk.Frame(price_box, bg="white")
                p_row.pack(pady=5)
                tk.Label(p_row, text=f"¥ {price}", font=("Arial", 16, "bold"), bg="white", fg="#ff4d4f").pack(side="left")
                tk.Label(p_row, text=f" /{unit}", font=("微软雅黑", 9), bg="white", fg="#999").pack(side="left")
                
                tk.Button(price_box, text="立即购买", bg="#00c853", fg="white", font=("微软雅黑", 10, "bold"), relief="flat", pady=5).pack(fill="x", pady=(10, 0))
            else:
                tk.Button(price_box, text="联系客服", bg="#fa8c16", fg="white", font=("微软雅黑", 10, "bold"), relief="flat", pady=5).pack(fill="x", pady=(10, 0))
            
            return card

        # 创建四个卡片
        c1 = create_card(cards_grid, "月度会员", ["云端7x24小时", "多店铺1-5个", "AI自动回复/辅助回复"], "258", "月")
        c1.grid(row=0, column=0, padx=10)
        
        c2 = create_card(cards_grid, "年度会员", ["云端7x24小时", "多店铺1-5个", "AI自动回复/辅助回复"], "2476", "年", tag="-20%")
        c2.grid(row=0, column=1, padx=10)
        
        c3 = create_card(cards_grid, "消息加油包", ["有效期12个月", "叠加已有套餐使用"], "150", "次")
        c3.grid(row=0, column=2, padx=10)
        
        c4 = create_card(cards_grid, "定制套餐", [], "", "", is_custom=True)
        c4.grid(row=0, column=3, padx=10)
        # 定制卡片背景色微调
        c4.config(bg="#fff7e6") 
        for child in c4.winfo_children():
            child.config(bg="#fff7e6")

        # 4. 消息使用情况 & 加油包
        info_row = tk.Frame(scroll_frame, bg="#f5f7fa")
        info_row.pack(fill="x", padx=20, pady=20)
        
        # 左侧：使用情况
        u_panel = tk.Frame(info_row, bg="white", width=500, height=120)
        u_panel.pack_propagate(False)
        u_panel.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        tk.Label(u_panel, text="消息使用情况", font=("微软雅黑", 10, "bold"), bg="white").pack(anchor="w", padx=15, pady=10)
        tk.Frame(u_panel, height=1, bg="#eee").pack(fill="x")
        
        u_cnt = tk.Frame(u_panel, bg="white", padx=15, pady=10)
        u_cnt.pack(fill="x")
        tk.Label(u_cnt, text="本月剩余消息量", font=("微软雅黑", 9), bg="white", fg="#666").pack(side="left")
        tk.Label(u_cnt, text="1000", font=("Arial", 9, "bold"), bg="white", fg="#333").pack(side="right")
        
        u_time = tk.Frame(u_panel, bg="white", padx=15)
        u_time.pack(fill="x")
        tk.Label(u_time, text="本月过期时间", font=("微软雅黑", 9), bg="white", fg="#666").pack(side="left")
        tk.Label(u_time, text="2026-02-15 23:39", font=("Arial", 9), bg="white", fg="#333").pack(side="right")
        
        # 右侧：加油包
        a_panel = tk.Frame(info_row, bg="white", width=500, height=120)
        a_panel.pack_propagate(False)
        a_panel.pack(side="left", fill="x", expand=True, padx=(10, 0))
        
        tk.Label(a_panel, text="消息加油包", font=("微软雅黑", 10, "bold"), bg="white").pack(anchor="w", padx=15, pady=10)
        tk.Frame(a_panel, height=1, bg="#eee").pack(fill="x")
        
        a_cnt = tk.Frame(a_panel, bg="white", padx=15, pady=15)
        a_cnt.pack(fill="x")
        tk.Label(a_cnt, text="剩余量", font=("微软雅黑", 9), bg="white", fg="#666").pack(side="left")
        tk.Label(a_cnt, text="详情 >", font=("微软雅黑", 9), bg="white", fg="#999").pack(side="right")
        
        tk.Label(a_panel, text="0", font=("Arial", 12, "bold"), bg="white", fg="#333").pack(anchor="w", padx=15)

        # 5. 邀请计划
        inv_frame = tk.Frame(scroll_frame, bg="white")
        inv_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        tk.Label(inv_frame, text="邀请计划", font=("微软雅黑", 10, "bold"), bg="white").pack(anchor="w", padx=15, pady=10)
        
        # 三色卡片
        stats_row = tk.Frame(inv_frame, bg="white", padx=15)
        stats_row.pack(fill="x")
        
        def create_stat(parent, title, val, color):
            box = tk.Frame(parent, bg=color, width=320, height=80)
            box.pack_propagate(False)
            box.pack(side="left", fill="x", expand=True, padx=5)
            tk.Label(box, text=title, font=("微软雅黑", 9), bg=color, fg="white").pack(anchor="w", padx=15, pady=(15, 5))
            tk.Label(box, text=f"¥{val}", font=("Arial", 16, "bold"), bg=color, fg="white").pack(anchor="w", padx=15)
            
        create_stat(stats_row, "总佣金", "0.00", "#7265e6")
        create_stat(stats_row, "已提现", "0.00", "#00b96b")
        create_stat(stats_row, "待提现", "0.00", "#fa8c16")
        
        # 佣金规则
        rule_row = tk.Frame(inv_frame, bg="white", padx=15, pady=15)
        rule_row.pack(fill="x")
        tk.Label(rule_row, text="佣金规则:", font=("微软雅黑", 9), bg="white", fg="#666").pack(side="left")
        for rule in ["首充佣金: 20%", "二充佣金: 15%", "三充佣金: 10%"]:
            tk.Label(rule_row, text=rule, font=("微软雅黑", 9), bg="#fff7e6", fg="#d46b08", padx=5).pack(side="left", padx=5)

        # 邀请码和链接
        link_box = tk.Frame(inv_frame, bg="white", padx=15, pady=(0, 20))
        link_box.pack(fill="x")
        
        # 邀请码
        r1 = tk.Frame(link_box, bg="white")
        r1.pack(fill="x", pady=5)
        tk.Label(r1, text="我的邀请码", font=("微软雅黑", 9), bg="white", fg="#666", width=10, anchor="w").pack(side="left")
        tk.Label(r1, text="657187", font=("Arial", 10, "bold"), bg="white", fg="#333").pack(side="left", expand=True, anchor="e", padx=10)
        tk.Button(r1, text="复制", bg="#f0f0f0", relief="flat").pack(side="right")
        
        # 专属邀请链接
        r2 = tk.Frame(link_box, bg="white")
        r2.pack(fill="x", pady=5)
        tk.Label(r2, text="专属邀请链接", font=("微软雅黑", 9), bg="white", fg="#666", width=10, anchor="w").pack(side="left")
        tk.Label(r2, text="https://www.zhiyu.chat/?from_code=657187", font=("Arial", 9), bg="white", fg="#999").pack(side="left", expand=True, anchor="e", padx=10)
        tk.Button(r2, text="复制", bg="#f0f0f0", relief="flat").pack(side="right")

        # 6. 底部登出大按钮
        logout_bar = tk.Button(scroll_frame, text="登出", font=("微软雅黑", 12, "bold"), bg="#cf1322", fg="white", 
                               relief="flat", pady=10, command=self.logout)
        logout_bar.pack(fill="x", padx=20, pady=30)

    def logout(self):
        if messagebox.askyesno("确认", "确定要退出登录吗？"):
            if hasattr(self, 'vip_popup'):
                self.vip_popup.destroy()
            self.set_current_user(None)
            self.notebook_frame.pack_forget()
            self.show_login_dialog()

    def _old_vip_section(self):
        # 备份原代码
        pass

    def start_shop_by_obj(self, shop):
        if shop.status == "running":
            messagebox.showinfo("提示", "店铺已在运行中")
            return
        # 模拟启动逻辑
        self.shops.update_status(shop.shop_id, "running")
        self.refresh_shop_grid()
        messagebox.showinfo("成功", f"店铺 {shop.shop_name} 已启动")

    def refresh_shop_table(self):
        self.refresh_shop_grid()

    def _unused_build_shop_tab(self):
        # 保留旧代码以防万一
        top = ttk.Frame(self.shop_tab)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text="新增", command=self.add_shop, style="Primary.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="编辑", command=self.edit_shop, style="Primary.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="启动", command=self.start_shop, style="Success.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="停止", command=self.stop_shop, style="Warning.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="删除", command=self.delete_shop, style="Error.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="配置选择器", command=self.configure_shop_selectors, style="Primary.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="刷新", command=self.refresh_shop_table, style="Primary.TButton").pack(side="left", padx=4)

        frame = ttk.Frame(self.shop_tab)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ("店铺名称", "平台", "账号", "状态", "最后登录", "备注")
        self.shop_tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            self.shop_tree.heading(c, text=c)
            self.shop_tree.column(c, width=120, anchor="w")
        self.shop_tree.column("店铺名称", width=170)
        self.shop_tree.column("备注", width=220)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.shop_tree.yview)
        self.shop_tree.configure(yscrollcommand=sb.set)
        self.shop_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.shop_tree.bind("<Double-1>", lambda e: self.edit_shop())

    def add_shop(self):
        self._shop_form_dialog(title="新增店铺")

    def edit_shop(self):
        sel = self.shop_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择一个店铺")
            return
        shop = self.shops.get(sel[0])
        if not shop:
            return
        self._shop_form_dialog(title="编辑店铺", shop=shop)

    def delete_shop(self):
        sel = self.shop_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择一个店铺")
            return
        if not messagebox.askyesno("确认", "确定删除所选店铺吗？"):
            return
        for sid in sel:
            self.shops.delete(sid)
            self.stats.emit("shop_deleted", sid)
        self.refresh_all()

    def start_shop(self):
        sel = self.shop_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择一个店铺")
            return
        for sid in sel:
            shop = self.shops.get(sid)
            if not shop:
                continue
            try:
                self.browser.auto_login(shop)
                shop.start()
                self.shops.update(shop)
                self.stats.emit("shop_started", sid)
            except Exception as e:
                messagebox.showerror("启动失败", str(e))
        self.refresh_shop_table()

    def stop_shop(self):
        sel = self.shop_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择一个店铺")
            return
        for sid in sel:
            try:
                self.browser.close(sid)
            except Exception:
                pass
            shop = self.shops.get(sid)
            if shop:
                shop.stop()
                self.shops.update(shop)
                self.stats.emit("shop_stopped", sid)
        self.refresh_shop_table()

    def configure_shop_selectors(self):
        sel = self.shop_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择一个店铺")
            return
        shop = self.shops.get(sel[0])
        if not shop:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("配置登录选择器")
        dialog.geometry("520x320")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        selectors = (shop.config or {}).get("selectors") or {}
        account_name = tk.StringVar(value=selectors.get("account_name", "account"))
        password_name = tk.StringVar(value=selectors.get("password_name", "password"))
        submit_xpath = tk.StringVar(value=selectors.get("submit_xpath", "//button[@type='submit']"))

        ttk.Label(frame, text="账号输入框 name").grid(row=0, column=0, sticky="w", pady=10)
        ttk.Entry(frame, textvariable=account_name).grid(row=0, column=1, sticky="ew", pady=10)
        ttk.Label(frame, text="密码输入框 name").grid(row=1, column=0, sticky="w", pady=10)
        ttk.Entry(frame, textvariable=password_name).grid(row=1, column=1, sticky="ew", pady=10)
        ttk.Label(frame, text="提交按钮 XPath").grid(row=2, column=0, sticky="w", pady=10)
        ttk.Entry(frame, textvariable=submit_xpath).grid(row=2, column=1, sticky="ew", pady=10)

        def save():
            cfg = shop.config or {}
            cfg["selectors"] = {
                "account_name": account_name.get().strip(),
                "password_name": password_name.get().strip(),
                "submit_xpath": submit_xpath.get().strip(),
            }
            shop.config = cfg
            self.shops.update(shop)
            dialog.destroy()

        btns = ttk.Frame(frame)
        btns.grid(row=3, column=0, columnspan=2, pady=20)
        ttk.Button(btns, text="保存", width=14, command=save).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", width=14, command=dialog.destroy).pack(side="left", padx=8)

        frame.grid_columnconfigure(1, weight=1)

    def _shop_form_dialog(self, title: str, shop=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("680x750")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="white")

        # 变量定义
        name_var = tk.StringVar(value=getattr(shop, "shop_name", ""))
        platform_var = tk.StringVar(value=getattr(shop, "platform_type", "千牛") or "千牛")
        account_var = tk.StringVar(value=getattr(shop, "account", ""))
        password_var = tk.StringVar(value=unprotect(getattr(shop, "password", "")) if shop else "")
        bind_shop_var = tk.StringVar(value="不绑定其他店铺")
        bind_kb_var = tk.StringVar(value="不绑定通用知识库，使用自动创建的店铺知识库")

        # 主容器
        main_frame = tk.Frame(dialog, bg="white", padx=40, pady=20)
        main_frame.pack(fill="both", expand=True)

        # 标题
        tk.Label(main_frame, text=title, font=("微软雅黑", 16, "bold"), bg="white", fg="#333").pack(anchor="w", pady=(0, 20))
        tk.Frame(main_frame, height=1, bg="#eee").pack(fill="x", pady=(0, 20))

        # 1. 备注名称
        row1 = tk.Frame(main_frame, bg="white")
        row1.pack(fill="x", pady=10)
        tk.Label(row1, text="* 备注名称", font=("微软雅黑", 10, "bold"), bg="white", width=12, anchor="e", fg="#333").pack(side="left")
        entry_name = tk.Entry(row1, textvariable=name_var, font=("微软雅黑", 10), bg="white", relief="solid", bd=1, fg="#333")
        entry_name.pack(side="left", fill="x", expand=True, padx=(15, 0), ipady=5)
        tk.Label(row1, text="0 / 200", bg="white", fg="#999").pack(side="right", padx=5)

        # 2. 平台选择
        row2 = tk.Frame(main_frame, bg="white")
        row2.pack(fill="x", pady=10)
        tk.Label(row2, text="* 平台", font=("微软雅黑", 10, "bold"), bg="white", width=12, anchor="e", fg="#333").pack(side="left", anchor="n", pady=5)
        
        platforms_frame = tk.Frame(row2, bg="white")
        platforms_frame.pack(side="left", fill="x", expand=True, padx=15)
        
        platforms = [
            ("千牛", "#1890ff", "🔵"), 
            ("拼多多", "#f5222d", "🔴"), 
            ("抖店", "#2f54eb", "🎵"), 
            ("快手", "#fa8c16", "🟠"), 
            ("京东", "#e02020", "🐶"), 
            ("闲鱼", "#fadb14", "🐟"), 
            ("微信", "#52c41a", "💬")
        ]
        
        self.platform_btns = []
        
        def select_platform(p_name):
            platform_var.set(p_name)
            for btn, name, color in self.platform_btns:
                if name == p_name:
                    btn.config(bg=color, fg="white", relief="flat")
                else:
                    btn.config(bg="white", fg="#666", relief="solid", bd=1)

        # 分两行显示平台按钮
        p_row1 = tk.Frame(platforms_frame, bg="white")
        p_row1.pack(fill="x", pady=(0, 10))
        p_row2 = tk.Frame(platforms_frame, bg="white")
        p_row2.pack(fill="x")

        for i, (p_name, p_color, p_icon) in enumerate(platforms):
            parent = p_row1 if i < 4 else p_row2
            # 创建自定义样式的按钮
            btn = tk.Button(parent, text=f"{p_icon} {p_name}", font=("微软雅黑", 9), 
                            width=10, cursor="hand2",
                            command=lambda n=p_name: select_platform(n))
            btn.pack(side="left", padx=5)
            self.platform_btns.append((btn, p_name, p_color))
        
        # 初始化选中状态
        select_platform(platform_var.get())

        # 3. 警告提示
        warn_frame = tk.Frame(main_frame, bg="#fffbe6", padx=15, pady=10)
        warn_frame.pack(fill="x", pady=15)
        warn_msg = "请关闭千牛客户端的自动登录！否则每次启动店铺都会登录同一个账号！并且按照官网教程打开千牛的讲述人模式"
        tk.Label(warn_frame, text=warn_msg, font=("微软雅黑", 9), bg="#fffbe6", fg="#fa8c16", wraplength=500, justify="left").pack(anchor="w")

        # 4. 登录账号
        row4 = tk.Frame(main_frame, bg="white")
        row4.pack(fill="x", pady=10)
        tk.Label(row4, text="登录账号", font=("微软雅黑", 10), bg="white", width=12, anchor="e", fg="#333").pack(side="left")
        tk.Entry(row4, textvariable=account_var, font=("微软雅黑", 10), bg="white", relief="solid", bd=1, fg="#333").pack(side="left", fill="x", expand=True, padx=(15, 0), ipady=5)
        tk.Label(row4, text="0 / 200", bg="white", fg="#999").pack(side="right", padx=5)

        # 5. 登录密码
        row5 = tk.Frame(main_frame, bg="white")
        row5.pack(fill="x", pady=10)
        tk.Label(row5, text="登录密码", font=("微软雅黑", 10), bg="white", width=12, anchor="e", fg="#333").pack(side="left")
        tk.Entry(row5, textvariable=password_var, show="*", font=("微软雅黑", 10), bg="white", relief="solid", bd=1, fg="#333").pack(side="left", fill="x", expand=True, padx=(15, 0), ipady=5)

        # 6. 绑定已有店铺
        row6 = tk.Frame(main_frame, bg="white")
        row6.pack(fill="x", pady=10)
        tk.Label(row6, text="绑定已有店铺", font=("微软雅黑", 10), bg="white", width=12, anchor="e", fg="#333").pack(side="left", anchor="n", pady=5)
        
        v_frame = tk.Frame(row6, bg="white")
        v_frame.pack(side="left", fill="x", expand=True, padx=15)
        
        cb_shop = ttk.Combobox(v_frame, textvariable=bind_shop_var, state="readonly", values=["不绑定其他店铺"], font=("微软雅黑", 10))
        cb_shop.pack(fill="x", ipady=3)
        tk.Label(v_frame, text="仅绑定目标店铺的店铺知识库和商品库，仅在创建店铺时可以指定绑定的店铺", font=("微软雅黑", 8), bg="white", fg="#999").pack(anchor="w", pady=2)

        # 7. 绑定通用知识库
        row7 = tk.Frame(main_frame, bg="white")
        row7.pack(fill="x", pady=10)
        tk.Label(row7, text="绑定通用知识库", font=("微软雅黑", 10), bg="white", width=12, anchor="e", fg="#333").pack(side="left")
        ttk.Combobox(row7, textvariable=bind_kb_var, state="readonly", values=["不绑定通用知识库，使用自动创建的店铺知识库"], font=("微软雅黑", 10)).pack(side="left", fill="x", expand=True, padx=15, ipady=3)

        # 8. 更多设置 (折叠区域)
        row8 = tk.Frame(main_frame, bg="white", cursor="hand2")
        row8.pack(fill="x", pady=10)
        
        more_label = tk.Label(row8, text="更多设置", font=("微软雅黑", 10, "bold"), bg="white", width=12, anchor="e", fg="#333")
        more_label.pack(side="left")
        
        arrow_label = tk.Label(row8, text=">", font=("微软雅黑", 10), bg="white", fg="#666")
        arrow_label.pack(side="right", padx=20)
        
        # 更多设置的内容区域
        more_frame = tk.Frame(main_frame, bg="white")
        # 默认不显示
        
        # 切换显示函数
        def toggle_more(event=None):
            if more_frame.winfo_ismapped():
                more_frame.pack_forget()
                arrow_label.config(text=">")
            else:
                more_frame.pack(fill="x", pady=5)
                arrow_label.config(text="v")
        
        row8.bind("<Button-1>", toggle_more)
        more_label.bind("<Button-1>", toggle_more)
        arrow_label.bind("<Button-1>", toggle_more)

        # 8.1 店铺链接
        m_row1 = tk.Frame(more_frame, bg="white")
        m_row1.pack(fill="x", pady=5)
        tk.Label(m_row1, text="店铺链接", font=("微软雅黑", 10), bg="white", width=12, anchor="e", fg="#333").pack(side="left")
        url_var = tk.StringVar(value=getattr(shop, "login_url", ""))
        tk.Entry(m_row1, textvariable=url_var, font=("微软雅黑", 10), bg="white", relief="solid", bd=1, fg="#333").pack(side="left", fill="x", expand=True, padx=(15, 0), ipady=5)
        tk.Label(m_row1, text="0 / 200", bg="white", fg="#999").pack(side="right", padx=5)

        # 8.2 店铺知识 (多行文本)
        m_row2 = tk.Frame(more_frame, bg="white")
        m_row2.pack(fill="x", pady=5)
        tk.Label(m_row2, text="店铺知识", font=("微软雅黑", 10), bg="white", width=12, anchor="ne", fg="#333").pack(side="left", pady=5)
        
        kb_text_frame = tk.Frame(m_row2, bg="white", relief="solid", bd=1)
        kb_text_frame.pack(side="left", fill="x", expand=True, padx=(15, 0))
        
        kb_text = tk.Text(kb_text_frame, font=("微软雅黑", 10), height=4, bd=0, bg="white", fg="#333")
        kb_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 插入店铺知识内容
        notes_content = getattr(shop, "notes", "")
        if notes_content:
            kb_text.insert("1.0", notes_content)

        kb_bottom = tk.Frame(kb_text_frame, bg="white")
        kb_bottom.pack(fill="x", padx=5, pady=2)
        tk.Button(kb_bottom, text="插入图片/视频", font=("微软雅黑", 8), bg="#f0f0f0", relief="flat").pack(side="left")
        tk.Label(kb_bottom, text="0 / 3000", font=("微软雅黑", 8), bg="white", fg="#999").pack(side="right")

        # 8.3 提示词 (多行文本)
        m_row3 = tk.Frame(more_frame, bg="white")
        m_row3.pack(fill="x", pady=5)
        tk.Label(m_row3, text="提示词", font=("微软雅黑", 10), bg="white", width=12, anchor="ne", fg="#333").pack(side="left", pady=5)
        
        prompt_frame = tk.Frame(m_row3, bg="white", relief="solid", bd=1)
        prompt_frame.pack(side="left", fill="x", expand=True, padx=(15, 0))
        
        prompt_text = tk.Text(prompt_frame, font=("微软雅黑", 10), height=4, bd=0, bg="white", fg="#333")
        prompt_text.pack(fill="both", expand=True, padx=5, pady=5)
        prompt_text.insert("1.0", "你是一名专业的电商客服，请根据我提供给你的上下文给出对客户的回复，你只需要输出对客户的回复即可，请勿包含任何其他内容。")
        
        tk.Label(prompt_frame, text="59 / 3000", font=("微软雅黑", 8), bg="white", fg="#999").pack(anchor="e", padx=5, pady=2)

        # 8.4 AI模型
        m_row4 = tk.Frame(more_frame, bg="white")
        m_row4.pack(fill="x", pady=5)
        tk.Label(m_row4, text="AI模型", font=("微软雅黑", 10), bg="white", width=12, anchor="e", fg="#333").pack(side="left")
        
        ai_model_var = tk.StringVar(value="选择AI模型")
        model_cb = ttk.Combobox(m_row4, textvariable=ai_model_var, state="readonly", font=("微软雅黑", 10))
        model_cb['values'] = [
            "Doubao-Seed-1.6 (推荐)", 
            "Deepseek-V3.2", 
            "Gemini-3.0-Pro", 
            "GPT-5", 
            "Qwen-3-plus", 
            "gpt-4o-mini"
        ]
        model_cb.pack(side="left", fill="x", expand=True, padx=(15, 0), ipady=3)

        # 底部按钮
        bottom_bar = tk.Frame(dialog, bg="white", height=60)
        bottom_bar.pack(side="bottom", fill="x")
        tk.Frame(bottom_bar, height=1, bg="#eee").pack(fill="x") # 分割线
        
        btn_box = tk.Frame(bottom_bar, bg="white")
        btn_box.pack(side="right", padx=30, pady=15)
        
        tk.Button(btn_box, text="取消", font=("微软雅黑", 10), bg="white", fg="#666", relief="solid", bd=1, padx=20, pady=5, command=dialog.destroy).pack(side="left", padx=10)
        
        def save():
            s_name = name_var.get().strip()
            p_type = platform_var.get()
            
            if not s_name:
                messagebox.showwarning("提示", "请输入备注名称")
                return
            
            try:
                if shop:
                    shop.shop_name = s_name
                    shop.platform_type = p_type
                    shop.account = account_var.get().strip()
                    shop.password = protect(password_var.get())
                    shop.login_url = url_var.get().strip()
                    shop.notes = kb_text.get("1.0", "end-1c").strip()
                    self.shops.update(shop)
                    self.stats.emit("shop_updated", shop.shop_id)
                else:
                    created = self.shops.create(
                        shop_name=s_name,
                        platform_type=p_type,
                        account=account_var.get().strip(),
                        password=password_var.get(),
                        login_url=url_var.get().strip(),
                        owner_id=self.current_user.user_id,
                        notes=kb_text.get("1.0", "end-1c").strip()
                    )
                    self.stats.emit("shop_created", created.shop_id)
                
                self.refresh_shop_table()
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", str(e))

        tk.Button(btn_box, text="确定", font=("微软雅黑", 10), bg="#2962ff", fg="white", relief="flat", padx=20, pady=5, command=save).pack(side="left")

    def build_product_tab(self):
        top = ttk.Frame(self.product_tab)
        top.pack(fill="x", padx=10, pady=10)

        self.product_keyword_var = tk.StringVar(value="")

        ttk.Label(top, text="关键词").pack(side="left")
        ttk.Entry(top, textvariable=self.product_keyword_var, width=24).pack(side="left", padx=6)
        ttk.Button(top, text="查询", command=self.refresh_product_table).pack(side="left", padx=4)

        ttk.Frame(top).pack(side="left", expand=True, fill="x")

        ttk.Button(top, text="新增", command=self.add_product).pack(side="right", padx=4)
        ttk.Button(top, text="编辑", command=self.edit_product).pack(side="right", padx=4)
        ttk.Button(top, text="删除", command=self.delete_product).pack(side="right", padx=4)
        ttk.Button(top, text="导入CSV", command=self.import_products).pack(side="right", padx=4)
        ttk.Button(top, text="导出CSV", command=self.export_products).pack(side="right", padx=4)

        frame = ttk.Frame(self.product_tab)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ("SKU", "名称", "价格", "库存", "状态", "更新时间")
        self.product_tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            self.product_tree.heading(c, text=c)
            self.product_tree.column(c, width=120, anchor="w")
        self.product_tree.column("名称", width=240)
        self.product_tree.column("更新时间", width=160)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.product_tree.yview)
        self.product_tree.configure(yscrollcommand=sb.set)
        self.product_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.product_tree.bind("<Double-1>", lambda e: self.edit_product())

    def refresh_product_table(self):
        self.product_tree.delete(*self.product_tree.get_children())
        shop_id = self.current_shop_id
        if not shop_id:
            return
        keyword = (self.product_keyword_var.get() or "").strip() or (self.global_search_var.get() or "").strip()
        rows = self.products.list(shop_id=shop_id, keyword=keyword)
        for p in rows:
            ts = p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else ""
            self.product_tree.insert("", "end", iid=p.product_id, values=(p.sku, p.name, f"{p.price:.2f}", str(p.stock), p.status, ts))

    def add_product(self):
        if not self.current_shop_id:
            messagebox.showwarning("提示", "请先在顶部选择一个店铺")
            return
        self._product_form_dialog("新增商品")

    def edit_product(self):
        if not self.current_shop_id:
            messagebox.showwarning("提示", "请先在顶部选择一个店铺")
            return
        sel = self.product_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择一个商品")
            return
        product = self.products.get(sel[0])
        if not product:
            return
        self._product_form_dialog("编辑商品", product)

    def delete_product(self):
        sel = self.product_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择商品")
            return
        if not messagebox.askyesno("确认", "确定删除所选商品吗？"):
            return
        for pid in sel:
            self.products.delete(pid)
            self.stats.emit("product_deleted", pid)
        self.refresh_product_table()
        self.refresh_statistics()

    def _product_form_dialog(self, title, product=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("480x360")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)

        sku_var = tk.StringVar(value=getattr(product, "sku", ""))
        name_var = tk.StringVar(value=getattr(product, "name", ""))
        price_var = tk.StringVar(value=str(getattr(product, "price", 0.0)))
        stock_var = tk.StringVar(value=str(getattr(product, "stock", 0)))
        status_var = tk.StringVar(value=getattr(product, "status", "active"))

        ttk.Label(frame, text="SKU").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=sku_var).grid(row=0, column=1, sticky="ew", pady=8)
        ttk.Label(frame, text="名称").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=name_var).grid(row=1, column=1, sticky="ew", pady=8)
        ttk.Label(frame, text="价格").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=price_var).grid(row=2, column=1, sticky="ew", pady=8)
        ttk.Label(frame, text="库存").grid(row=3, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=stock_var).grid(row=3, column=1, sticky="ew", pady=8)
        ttk.Label(frame, text="状态").grid(row=4, column=0, sticky="w", pady=8)
        ttk.Combobox(frame, textvariable=status_var, state="readonly", values=["active", "inactive"]).grid(row=4, column=1, sticky="ew", pady=8)

        def save():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("提示", "请输入商品名称")
                return
            try:
                price = float(price_var.get())
            except Exception:
                messagebox.showwarning("提示", "价格格式错误")
                return
            try:
                stock = int(stock_var.get())
            except Exception:
                messagebox.showwarning("提示", "库存格式错误")
                return
            if product is None:
                created = self.products.create(
                    shop_id=self.current_shop_id,
                    name=name,
                    price=price,
                    stock=stock,
                    sku=sku_var.get().strip(),
                    status=status_var.get(),
                )
                self.stats.emit("product_created", created.product_id)
            else:
                product.sku = sku_var.get().strip()
                product.name = name
                product.price = price
                product.stock = stock
                product.status = status_var.get()
                self.products.update(product)
                self.stats.emit("product_updated", product.product_id)
            dialog.destroy()
            self.refresh_product_table()
            self.refresh_statistics()

        btns = ttk.Frame(frame)
        btns.grid(row=5, column=0, columnspan=2, pady=18)
        ttk.Button(btns, text="保存", width=14, command=save).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", width=14, command=dialog.destroy).pack(side="left", padx=8)

        frame.grid_columnconfigure(1, weight=1)

    def import_products(self):
        if not self.current_shop_id:
            messagebox.showwarning("提示", "请先选择店铺")
            return
        path = filedialog.askopenfilename(title="选择CSV文件", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        n = 0
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or row.get("名称") or "").strip()
                if not name:
                    continue
                sku = (row.get("sku") or row.get("SKU") or "").strip()
                price = row.get("price") or row.get("价格") or 0
                stock = row.get("stock") or row.get("库存") or 0
                status = (row.get("status") or row.get("状态") or "active").strip() or "active"
                try:
                    price = float(price)
                except Exception:
                    price = 0.0
                try:
                    stock = int(stock)
                except Exception:
                    stock = 0
                self.products.create(self.current_shop_id, name=name, price=price, stock=stock, sku=sku, status=status)
                n += 1
        self.stats.emit("product_import", self.current_shop_id, {"count": n})
        self.refresh_product_table()
        self.refresh_statistics()
        messagebox.showinfo("完成", f"已导入 {n} 条商品")

    def export_products(self):
        if not self.current_shop_id:
            messagebox.showwarning("提示", "请先选择店铺")
            return
        path = filedialog.asksaveasfilename(title="保存CSV文件", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        rows = self.products.list(self.current_shop_id)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["product_id", "shop_id", "sku", "name", "price", "stock", "status", "updated_at"])
            writer.writeheader()
            for p in rows:
                writer.writerow(
                    {
                        "product_id": p.product_id,
                        "shop_id": p.shop_id,
                        "sku": p.sku,
                        "name": p.name,
                        "price": p.price,
                        "stock": p.stock,
                        "status": p.status,
                        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
                    }
                )
        self.stats.emit("product_export", self.current_shop_id, {"count": len(rows)})
        messagebox.showinfo("完成", f"已导出 {len(rows)} 条商品")

    def build_ai_tab(self):
        root = ttk.Frame(self.ai_tab)
        root.pack(fill="both", expand=True)

        left = ttk.Frame(root, width=260)
        left.pack(side="left", fill="y", padx=(10, 6), pady=10)
        left.pack_propagate(False)

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(0, 10))
        ttk.Button(btns, text="新建会话", command=self.new_session).pack(side="left", padx=4)
        ttk.Button(btns, text="关闭会话", command=self.close_session).pack(side="left", padx=4)

        self.session_list = tk.Listbox(left, height=24)
        self.session_list.pack(fill="both", expand=True)
        self.session_list.bind("<<ListboxSelect>>", lambda e: self.on_select_session())

        right = ttk.Frame(root)
        right.pack(side="left", fill="both", expand=True, padx=(6, 10), pady=10)

        self.chat_text = tk.Text(right, height=24, wrap="word", state="disabled")
        chat_scroll = ttk.Scrollbar(right, orient="vertical", command=self.chat_text.yview)
        self.chat_text.configure(yscrollcommand=chat_scroll.set)
        self.chat_text.pack(side="left", fill="both", expand=True)
        chat_scroll.pack(side="right", fill="y")

        bottom = ttk.Frame(self.ai_tab)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        self.chat_input_var = tk.StringVar(value="")
        self.chat_input = ttk.Entry(bottom, textvariable=self.chat_input_var)
        self.chat_input.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(bottom, text="发送", width=10, command=self.send_message).pack(side="left")

        self.refresh_sessions_list()

    def refresh_sessions_list(self):
        self.session_list.delete(0, "end")
        if not self.current_shop_id:
            return
        keyword = (self.global_search_var.get() or "").strip()
        sessions = self.sessions.list(self.current_shop_id)
        for s in sessions:
            name = s.session_id[-6:]
            last = (s.last_message or "").replace("\n", " ")
            if keyword and keyword not in last and keyword not in s.session_id:
                continue
            self.session_list.insert("end", f"{name}  {last[:18]}")
        if self.current_session_id:
            ids = [s.session_id for s in self.sessions.list(self.current_shop_id)]
            if self.current_session_id in ids:
                idx = ids.index(self.current_session_id)
                try:
                    self.session_list.selection_set(idx)
                except Exception:
                    pass

    def _session_ids(self):
        if not self.current_shop_id:
            return []
        return [s.session_id for s in self.sessions.list(self.current_shop_id)]

    def on_select_session(self):
        idxs = self.session_list.curselection()
        if not idxs:
            return
        ids = self._session_ids()
        if not ids:
            return
        idx = idxs[0]
        if idx >= len(ids):
            return
        self.set_current_session_id(ids[idx])
        self.sessions.reset_unread(self.current_session_id)
        self.render_chat(self.current_session_id)

    def render_chat(self, session_id):
        msgs = self.messages.list(session_id, limit=400)
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        for m in msgs:
            ts = m.timestamp.strftime("%H:%M") if m.timestamp else ""
            prefix = "我" if m.sender_type == "user" else ("AI" if m.sender_type == "ai" else m.sender_type)
            self.chat_text.insert("end", f"[{ts}] {prefix}: {m.content}\n")
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def new_session(self):
        if not self.current_shop_id:
            messagebox.showwarning("提示", "请先选择店铺")
            return
        s = self.sessions.create(self.current_shop_id, self.current_user.user_id, platform=self.platform_var.get() if self.platform_var.get() != "全部平台" else "")
        self.set_current_session_id(s.session_id)
        self.stats.emit("session_created", s.session_id)
        self.refresh_sessions_list()
        self.render_chat(self.current_session_id)

    def close_session(self):
        if not self.current_session_id:
            messagebox.showwarning("提示", "请先选择会话")
            return
        self.sessions.set_status(self.current_session_id, "closed")
        self.stats.emit("session_closed", self.current_session_id)
        self.set_current_session_id("")
        self.refresh_sessions_list()
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.configure(state="disabled")

    def send_message(self):
        text = self.chat_input_var.get().strip()
        if not text:
            return
        if not self.current_shop_id:
            messagebox.showwarning("提示", "请先选择店铺")
            return
        if not self.current_session_id:
            self.new_session()

        sid = self.current_session_id
        self.messages.create(sid, "user", self.current_user.user_id, text)
        self.sessions.touch(sid, last_message=text, inc_message=True)
        self.stats.emit("message_user", sid)

        ctx_msgs = self.messages.list(sid, limit=20)
        ctx = "\n".join([f"{m.sender_type}:{m.content}" for m in ctx_msgs[-10:]])
        reply = self.ai.生成回复(text, ctx, None)
        self.messages.create(sid, "ai", "ai", reply)
        self.sessions.touch(sid, last_message=reply, inc_message=True)
        self.stats.emit("message_ai", sid)

        self.chat_input_var.set("")
        self.render_chat(sid)
        self.refresh_sessions_list()
        self.refresh_history_sessions()
        self.refresh_statistics()

    def build_history_tab(self):
        root = ttk.Frame(self.history_tab)
        root.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(root, width=340)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        top = ttk.Frame(left)
        top.pack(fill="x", pady=(0, 10))
        self.history_status_var = tk.StringVar(value="全部")
        ttk.Label(top, text="状态").pack(side="left")
        ttk.Combobox(top, textvariable=self.history_status_var, state="readonly", width=10, values=["全部", "active", "closed", "archived"]).pack(side="left", padx=6)
        ttk.Button(top, text="刷新", command=self.refresh_history_sessions).pack(side="left", padx=6)
        ttk.Button(top, text="导出", command=self.export_history).pack(side="left", padx=6)

        cols = ("会话", "状态", "更新时间", "最后消息")
        self.history_tree = ttk.Treeview(left, columns=cols, show="headings", height=22)
        for c in cols:
            self.history_tree.heading(c, text=c)
            self.history_tree.column(c, width=90, anchor="w")
        self.history_tree.column("会话", width=80)
        self.history_tree.column("更新时间", width=140)
        self.history_tree.column("最后消息", width=240)
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<<TreeviewSelect>>", lambda e: self.on_select_history_session())

        right = ttk.Frame(root)
        right.pack(side="left", fill="both", expand=True)

        self.history_text = tk.Text(right, wrap="word", state="disabled")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.history_text.yview)
        self.history_text.configure(yscrollcommand=sb.set)
        self.history_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.refresh_history_sessions()

    def refresh_history_sessions(self):
        self.history_tree.delete(*self.history_tree.get_children())
        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", "end")
        self.history_text.configure(state="disabled")

        if not self.current_shop_id:
            return
        status = self.history_status_var.get()
        status_filter = "" if status == "全部" else status
        keyword = (self.global_search_var.get() or "").strip()
        sessions = self.sessions.list(self.current_shop_id, status=status_filter)
        for s in sessions:
            if keyword and keyword not in (s.last_message or "") and keyword not in s.session_id:
                continue
            ts = s.updated_at.strftime("%Y-%m-%d %H:%M") if s.updated_at else ""
            self.history_tree.insert("", "end", iid=s.session_id, values=(s.session_id[-6:], s.status, ts, (s.last_message or "")[:22]))

    def on_select_history_session(self):
        sel = self.history_tree.selection()
        if not sel:
            return
        sid = sel[0]
        msgs = self.messages.list(sid, limit=500)
        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", "end")
        for m in msgs:
            ts = m.timestamp.strftime("%Y-%m-%d %H:%M:%S") if m.timestamp else ""
            self.history_text.insert("end", f"[{ts}] {m.sender_type}: {m.content}\n")
        self.history_text.configure(state="disabled")
        self.history_text.see("end")

    def export_history(self):
        sel = self.history_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请选择一个会话")
            return
        sid = sel[0]
        path = filedialog.asksaveasfilename(title="导出聊天记录", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        msgs = self.messages.list(sid, limit=5000)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["session_id", "message_id", "sender_type", "sender_id", "timestamp", "content"])
            writer.writeheader()
            for m in msgs:
                writer.writerow(
                    {
                        "session_id": m.session_id,
                        "message_id": m.message_id,
                        "sender_type": m.sender_type,
                        "sender_id": m.sender_id,
                        "timestamp": m.timestamp.isoformat() if m.timestamp else "",
                        "content": m.content,
                    }
                )
        self.stats.emit("history_export", sid, {"count": len(msgs)})
        messagebox.showinfo("完成", f"已导出 {len(msgs)} 条消息")

    def build_stats_tab(self):
        top = ttk.Frame(self.stats_tab)
        top.pack(fill="x", padx=10, pady=10)
        self.stats_total_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.stats_total_var, font=("Microsoft YaHei", 11)).pack(side="left")
        ttk.Frame(top).pack(side="left", expand=True, fill="x")
        ttk.Button(top, text="刷新", command=self.refresh_statistics).pack(side="right")

        frame = ttk.Frame(self.stats_tab)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ("日期", "消息数")
        self.stats_tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            self.stats_tree.heading(c, text=c)
            self.stats_tree.column(c, width=160, anchor="w")
        self.stats_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.stats_tree.yview)
        self.stats_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh_statistics(self):
        totals = self.stats.totals()
        self.stats_total_var.set(f"店铺 {totals['shops']}  商品 {totals['products']}  会话 {totals['sessions']}  消息 {totals['messages']}")
        self.stats_tree.delete(*self.stats_tree.get_children())
        for r in self.stats.daily_messages(days=14):
            self.stats_tree.insert("", "end", values=(r["day"], r["count"]))

    def build_settings_tab(self):
        root = ttk.Frame(self.settings_tab)
        root.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(root)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        form = ttk.LabelFrame(left, text="基础配置", padding=12)
        form.pack(fill="x")

        self.openai_key_var = tk.StringVar(value="")
        self.openai_model_var = tk.StringVar(value=self.settings.get("openai_model", "gpt-4o-mini"))
        self.openai_temp_var = tk.StringVar(value=self.settings.get("openai_temperature", "0.3"))
        self.selenium_headless_var = tk.IntVar(value=1 if self.settings.get("selenium_headless", "1") not in ("0", "false", "False") else 0)
        self.default_login_url_var = tk.StringVar(value=self.settings.get("default_login_url", ""))

        ttk.Label(form, text="OpenAI Key").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.openai_key_var, show="*").grid(row=0, column=1, sticky="ew", pady=8)
        ttk.Label(form, text="模型").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.openai_model_var).grid(row=1, column=1, sticky="ew", pady=8)
        ttk.Label(form, text="温度").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.openai_temp_var).grid(row=2, column=1, sticky="ew", pady=8)
        ttk.Checkbutton(form, text="Selenium 无头模式", variable=self.selenium_headless_var).grid(row=3, column=1, sticky="w", pady=8)
        ttk.Label(form, text="默认登录URL").grid(row=4, column=0, sticky="w", pady=8)
        ttk.Entry(form, textvariable=self.default_login_url_var).grid(row=4, column=1, sticky="ew", pady=8)

        btns = ttk.Frame(form)
        btns.grid(row=5, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="保存配置", width=14, command=self.save_settings).pack(side="left", padx=8)
        ttk.Button(btns, text="刷新", width=14, command=self.refresh_settings).pack(side="left", padx=8)

        form.grid_columnconfigure(1, weight=1)

        kb_frame = ttk.LabelFrame(left, text="知识库", padding=12)
        kb_frame.pack(fill="both", expand=True, pady=(10, 0))

        self.kb_q_var = tk.StringVar(value="")
        self.kb_a_var = tk.StringVar(value="")
        self.kb_ok_var = tk.IntVar(value=1)
        self.kb_search_var = tk.StringVar(value="")

        ttk.Label(kb_frame, text="问题").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(kb_frame, textvariable=self.kb_q_var).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Label(kb_frame, text="回答").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(kb_frame, textvariable=self.kb_a_var).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Checkbutton(kb_frame, text="标记为正确", variable=self.kb_ok_var).grid(row=2, column=1, sticky="w", pady=6)

        kb_btns = ttk.Frame(kb_frame)
        kb_btns.grid(row=3, column=0, columnspan=2, pady=8)
        ttk.Button(kb_btns, text="写入", width=12, command=self.kb_add).pack(side="left", padx=6)
        ttk.Button(kb_btns, text="今日总结", width=12, command=self.kb_today).pack(side="left", padx=6)

        ttk.Label(kb_frame, text="查询").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(kb_frame, textvariable=self.kb_search_var).grid(row=4, column=1, sticky="ew", pady=6)
        ttk.Button(kb_frame, text="搜索", command=self.kb_search).grid(row=4, column=2, sticky="w", padx=6)

        self.kb_list = tk.Listbox(kb_frame, height=10)
        self.kb_list.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(8, 0))

        kb_frame.grid_columnconfigure(1, weight=1)
        kb_frame.grid_rowconfigure(5, weight=1)

        right = ttk.Frame(root, width=300)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        info = ttk.LabelFrame(right, text="路径信息", padding=12)
        info.pack(fill="both", expand=True)
        self.path_text = tk.Text(info, height=18, wrap="word", state="disabled")
        self.path_text.pack(fill="both", expand=True)

        self.refresh_settings()

    def refresh_settings(self):
        self.openai_model_var.set(self.settings.get("openai_model", "gpt-4o-mini"))
        self.openai_temp_var.set(self.settings.get("openai_temperature", "0.3"))
        self.selenium_headless_var.set(1 if self.settings.get("selenium_headless", "1") not in ("0", "false", "False") else 0)
        self.default_login_url_var.set(self.settings.get("default_login_url", ""))
        self.openai_key_var.set("")

        self.path_text.configure(state="normal")
        self.path_text.delete("1.0", "end")
        self.path_text.insert("end", f"数据目录：{app_data_dir()}\n")
        self.path_text.insert("end", f"数据库：{app_db_path()}\n")
        self.path_text.insert("end", f"日志：{app_log_path()}\n")
        self.path_text.configure(state="disabled")

    def save_settings(self):
        if self.openai_key_var.get().strip():
            self.settings.set_secret("openai_api_key", self.openai_key_var.get().strip())
        self.settings.set("openai_model", self.openai_model_var.get().strip() or "gpt-4o-mini")
        self.settings.set("openai_temperature", self.openai_temp_var.get().strip() or "0.3")
        self.settings.set("selenium_headless", "1" if self.selenium_headless_var.get() else "0")
        self.settings.set("default_login_url", self.default_login_url_var.get().strip())
        self.stats.emit("settings_saved", self.current_user.user_id)
        messagebox.showinfo("完成", "配置已保存")

    def kb_add(self):
        q = self.kb_q_var.get().strip()
        a = self.kb_a_var.get().strip()
        if not q or not a:
            messagebox.showwarning("提示", "请输入问题和回答")
            return
        ok = True if self.kb_ok_var.get() else False
        self.kb.存储问题与回答(q, a, ok)
        self.kb_q_var.set("")
        self.kb_a_var.set("")
        self.kb_list.insert("end", f"写入：{q[:18]} -> {a[:18]}")
        self.stats.emit("kb_add", self.current_user.user_id)

    def kb_search(self):
        q = self.kb_search_var.get().strip()
        self.kb_list.delete(0, "end")
        if not q:
            return
        rows = self.kb.查询相似问题(q)
        for r in rows[:50]:
            flag = "✓" if r.get("is_correct") in (True, 1, "1") else "?"
            self.kb_list.insert("end", f"{flag} {r.get('question','')[:26]} -> {r.get('answer','')[:26]}")

    def kb_today(self):
        s = self.kb.每日学习总结()
        messagebox.showinfo("今日学习总结", f"{s.get('日期')}\n总问题数：{s.get('总问题数')}\n正确回答数：{s.get('正确回答数')}")

    def build_debug_tab(self):
        root = ttk.Frame(self.debug_tab)
        root.pack(fill="both", expand=True, padx=10, pady=10)

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 10))
        ttk.Button(top, text="打开数据目录", command=self.open_data_dir).pack(side="left", padx=4)
        ttk.Button(top, text="打开日志", command=self.open_log_file).pack(side="left", padx=4)
        ttk.Button(top, text="备份数据库", command=self.backup_db).pack(side="left", padx=4)
        ttk.Button(top, text="自检", command=self.self_check).pack(side="left", padx=4)
        ttk.Button(top, text="刷新", command=self.refresh_debug).pack(side="left", padx=4)

        self.debug_text = tk.Text(root, wrap="word", state="disabled")
        sb = ttk.Scrollbar(root, orient="vertical", command=self.debug_text.yview)
        self.debug_text.configure(yscrollcommand=sb.set)
        self.debug_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def refresh_debug(self):
        path = app_log_path()
        text = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-200:]
                text = "".join(lines)
            except Exception:
                text = ""
        if not text:
            text = "暂无日志"
        self.debug_text.configure(state="normal")
        self.debug_text.delete("1.0", "end")
        self.debug_text.insert("end", text)
        self.debug_text.configure(state="disabled")
        self.debug_text.see("end")

    def open_data_dir(self):
        os.startfile(app_data_dir())

    def open_log_file(self):
        path = app_log_path()
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
        os.startfile(path)

    def backup_db(self):
        src = app_db_path()
        if not os.path.exists(src):
            messagebox.showwarning("提示", "数据库不存在")
            return
        dst = filedialog.asksaveasfilename(title="保存备份", defaultextension=".db", filetypes=[("SQLite", "*.db")])
        if not dst:
            return
        with open(src, "rb") as fsrc:
            data = fsrc.read()
        with open(dst, "wb") as fdst:
            fdst.write(data)
        self.stats.emit("db_backup", self.current_user.user_id, {"path": dst})
        messagebox.showinfo("完成", f"已备份到：{dst}")

    def self_check(self):
        totals = self.stats.totals()
        events = self.stats.top_events()
        lines = [
            "自检结果",
            f"店铺：{totals['shops']} 商品：{totals['products']} 会话：{totals['sessions']} 消息：{totals['messages']}",
            "事件统计：",
        ]
        for e in events:
            lines.append(f"{e['event_type']}: {e['count']}")
        messagebox.showinfo("自检", "\n".join(lines[:25]))
        self.stats.emit("self_check", self.current_user.user_id)

    def show_user_center(self):
        messagebox.showinfo("个人中心", f"当前用户：{self.current_user.username}\n角色：{self.current_user.role}")

    def logout(self):
        if messagebox.askyesno("退出登录", "确定要退出登录吗？"):
            self.on_close()
    
    def create_monitored_button(self, parent, text, command, widget_name=None, style="Primary.TButton", **kwargs):
        widget_name = widget_name or text
        def monitored_command():
            self.monitor.record_ui_event(
                event_type="button_click",
                widget_name=widget_name,
                widget_type="Button",
                value=text,
                metadata={"parent": str(parent)}
            )
            try:
                command()
            except Exception as e:
                self.monitor.record_error(
                    error_type="button_command_error",
                    error_message=str(e),
                    metadata={"widget_name": widget_name, "text": text}
                )
                raise
        
        return ttk.Button(parent, text=text, command=monitored_command, style=style, **kwargs)
    
    def create_monitored_entry(self, parent, widget_name, **kwargs):
        def on_change(event):
            value = event.widget.get()
            self.monitor.record_ui_event(
                event_type="entry_change",
                widget_name=widget_name,
                widget_type="Entry",
                value=value,
                metadata={"event": str(event)}
            )
        
        entry = ttk.Entry(parent, **kwargs)
        entry.bind("<KeyRelease>", on_change)
        return entry
    
    def create_monitored_combobox(self, parent, widget_name, **kwargs):
        def on_select(event):
            value = event.widget.get()
            self.monitor.record_ui_event(
                event_type="combobox_select",
                widget_name=widget_name,
                widget_type="ComboBox",
                value=value,
                metadata={"event": str(event)}
            )
        
        combobox = ttk.Combobox(parent, **kwargs)
        combobox.bind("<<ComboboxSelected>>", on_select)
        return combobox
    
    def show_monitoring_dialog(self):
        from tkinter import filedialog, simpledialog
        import os
        
        dialog = tk.Toplevel(self.root)
        dialog.title("应用监控数据导出")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 标题
        tk.Label(dialog, text="应用监控数据导出", font=("微软雅黑", 16, "bold")).pack(pady=(20, 10))
        
        # 事件类型过滤
        tk.Label(dialog, text="事件类型过滤 (留空表示所有类型):", font=("微软雅黑", 10)).pack(anchor="w", padx=30, pady=(10, 5))
        event_type_var = tk.StringVar()
        event_type_entry = ttk.Entry(dialog, textvariable=event_type_var, width=40)
        event_type_entry.pack(padx=30, pady=(0, 10))
        event_type_entry.insert(0, "")
        
        # 数量限制
        tk.Label(dialog, text="最大事件数量:", font=("微软雅黑", 10)).pack(anchor="w", padx=30, pady=(10, 5))
        limit_var = tk.IntVar(value=1000)
        ttk.Entry(dialog, textvariable=limit_var, width=20).pack(padx=30, pady=(0, 10))
        
        # 导出格式
        tk.Label(dialog, text="导出格式:", font=("微软雅黑", 10)).pack(anchor="w", padx=30, pady=(10, 5))
        format_var = tk.StringVar(value="json")
        ttk.Radiobutton(dialog, text="JSON 格式", variable=format_var, value="json").pack(anchor="w", padx=40)
        ttk.Radiobutton(dialog, text="CSV 格式", variable=format_var, value="csv").pack(anchor="w", padx=40)
        
        # 预览按钮
        tk.Label(dialog, text="预览事件统计:", font=("微软雅黑", 10)).pack(anchor="w", padx=30, pady=(10, 5))
        preview_text = tk.Text(dialog, height=8, width=50)
        preview_text.pack(padx=30, pady=(0, 10))
        
        def update_preview():
            try:
                events = self.monitor.export_events(event_type_var.get(), limit=50)
                preview_text.delete("1.0", "end")
                
                if not events:
                    preview_text.insert("1.0", "无事件数据")
                    return
                
                event_counts = {}
                for event in events:
                    event_type = event["event_type"]
                    event_counts[event_type] = event_counts.get(event_type, 0) + 1
                
                preview_text.insert("1.0", f"总事件数: {len(events)}\n\n")
                preview_text.insert("end", "事件类型分布:\n")
                for event_type, count in sorted(event_counts.items(), key=lambda x: x[1], reverse=True):
                    preview_text.insert("end", f"  {event_type}: {count} 个\n")
                
                preview_text.insert("end", f"\n最新事件时间: {events[0]['created_at']}")
            except Exception as e:
                preview_text.delete("1.0", "end")
                preview_text.insert("1.0", f"预览失败: {str(e)}")
        
        ttk.Button(dialog, text="更新预览", command=update_preview).pack(pady=5)
        
        def export_data():
            try:
                filetypes = []
                if format_var.get() == "json":
                    filetypes = [("JSON files", "*.json"), ("All files", "*.*")]
                else:
                    filetypes = [("CSV files", "*.csv"), ("All files", "*.*")]
                
                filename = filedialog.asksaveasfilename(
                    defaultextension=".json" if format_var.get() == "json" else ".csv",
                    filetypes=filetypes,
                    initialdir=os.path.expanduser("~"),
                    title="保存监控数据"
                )
                
                if not filename:
                    return
                
                if format_var.get() == "json":
                    self.monitor.export_to_json(filename, event_type_var.get(), limit_var.get())
                    messagebox.showinfo("导出成功", f"JSON数据已导出到:\n{filename}")
                else:
                    import csv
                    events = self.monitor.export_events(event_type_var.get(), limit_var.get())
                    with open(filename, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(["event_id", "event_type", "entity_id", "created_at", "metadata"])
                        for event in events:
                            writer.writerow([
                                event["event_id"],
                                event["event_type"],
                                event["entity_id"],
                                event["created_at"],
                                str(event["metadata"])
                            ])
                    messagebox.showinfo("导出成功", f"CSV数据已导出到:\n{filename}")
                
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("导出失败", f"导出失败: {str(e)}")
        
        # 导出按钮
        ttk.Button(dialog, text="导出数据", command=export_data, style="Primary.TButton").pack(pady=20)
        
        # 初始预览
        update_preview()
    
    def add_monitoring_menu(self):
        if hasattr(self, "menu_bar"):
            return
        
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)
        
        # 文件菜单
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="导出监控数据...", command=self.show_monitoring_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        
        # 监控菜单
        monitor_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="监控", menu=monitor_menu)
        monitor_menu.add_command(label="启用监控", command=lambda: self.monitor.enable())
        monitor_menu.add_command(label="禁用监控", command=lambda: self.monitor.disable())
        monitor_menu.add_separator()
        monitor_menu.add_command(label="导出监控数据...", command=self.show_monitoring_dialog)
        monitor_menu.add_command(label="查看事件统计", command=lambda: self.show_monitoring_dialog())


def main(conn=None):
    root = tk.Tk()
    connection = conn or connect()
    init_db(connection)
    DesktopApp(root, connection)
    try:
        if not root.winfo_exists():
            return
    except tk.TclError:
        return
    root.mainloop()
