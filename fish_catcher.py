import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime, timedelta, date
import threading
import time
import json
import os
import sys
import calendar
import random
import ctypes

# --- 引入必要的模块 ---
try:
    from PIL import Image, ImageTk
except ImportError:
    root = tk.Tk();
    root.withdraw()
    messagebox.showerror("依赖缺失", "错误：Pillow 库未安装！\n请在终端运行 'pip install Pillow' 来安装。")
    exit()

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame

try:
    from plyer import notification
except ImportError:
    notification = None


# --- 关键辅助函数：获取文件路径 ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_user_data_path(file_name):
    """
    获取用户数据文件的存储路径 (用于 JSON 配置文件).
    - 打包后，此路径将指向 C:\\Users\\<用户名>\\AppData\\Roaming\\FishCatcher
    - 这样做可以使配置文件与程序分离，符合标准软件设计。
    """
    # 获取 AppData/Roaming 目录
    app_data_path = os.getenv('APPDATA')

    # 如果无法获取 APPDATA 目录 (极少见情况)，则退回到程序所在目录
    if not app_data_path:
        if getattr(sys, 'frozen', False):
            app_data_path = os.path.dirname(sys.executable)
        else:
            app_data_path = os.path.dirname(os.path.abspath(__file__))

    # 在 AppData/Roaming 下为我们的应用创建一个专属文件夹
    app_dir = os.path.join(app_data_path, "FishCatcher")

    # 确保这个文件夹存在
    os.makedirs(app_dir, exist_ok=True)

    # 返回最终的文件路径
    return os.path.join(app_dir, file_name)


# --- 使用辅助函数定位文件 ---
IMAGE_PATH = resource_path("doraemon_bg.jpg")
ICON_PATH = resource_path("fish_icon.ico")
# 注意：这里现在会使用新的 get_user_data_path 函数
EVENTS_FILE = get_user_data_path("fish_catcher_events.json")


# ===================================================================
# --- 【重大升级 V5.0】事件类 Event ---
# ===================================================================
class Event:
    def __init__(self, data):
        self.name = data.get("name", "未命名事件")
        self.enabled = data.get("enabled", True)
        self.trigger_type = data.get("trigger", {}).get("type", "date")
        self.trigger_value = data.get("trigger", {}).get("value")

        start_date_str = data.get("start_date")
        if not start_date_str:
            if self.trigger_type == 'date':
                start_date_str = self.trigger_value
            else:
                start_date_str = date.today().strftime("%Y-%m-%d")
        self.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()

        last_triggered_str = data.get("last_triggered_date")
        self.last_triggered_date = datetime.strptime(last_triggered_str,
                                                     "%Y-%m-%d").date() if last_triggered_str else None

        self.repeat_total = int(data.get("repeat", {}).get("total", 1))
        self.times_triggered = int(data.get("repeat", {}).get("triggered", 0))

    def to_dict(self):
        return {
            "name": self.name, "enabled": self.enabled,
            "trigger": {"type": self.trigger_type, "value": self.trigger_value},
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "last_triggered_date": self.last_triggered_date.strftime("%Y-%m-%d") if self.last_triggered_date else None,
            "repeat": {"total": self.repeat_total, "triggered": self.times_triggered}
        }

    def get_occurrences(self, count=2):
        occurrences = []
        from_date = date.today()

        # 如果有上次触发日期，且是今天，那么下一次就从明天开始算
        if self.last_triggered_date and self.last_triggered_date >= from_date:
            from_date = self.last_triggered_date + timedelta(days=1)

        for _ in range(count):
            next_date = self._calculate_next(from_date)
            if next_date:
                occurrences.append(next_date)
                from_date = next_date + timedelta(days=1)
            else:
                break
        return occurrences

    def _calculate_next(self, from_date):
        if self.repeat_total != -1 and self.times_triggered >= self.repeat_total: return None
        if self.trigger_type == "date":
            try:
                event_date = datetime.strptime(self.trigger_value, "%Y-%m-%d").date()
                return event_date if event_date >= from_date and self.times_triggered < self.repeat_total else None
            except (ValueError, TypeError):
                return None
        elif self.trigger_type == "interval":
            try:
                interval = int(self.trigger_value)
                if interval <= 0: return None
                if self.start_date > from_date: return self.start_date
                days_since_start = (from_date - self.start_date).days
                intervals_passed = days_since_start // interval if days_since_start % interval == 0 else (
                                                                                                                     days_since_start // interval) + 1
                return self.start_date + timedelta(days=intervals_passed * interval)
            except (ValueError, TypeError):
                return None
        elif self.trigger_type == "weekly":
            try:
                target_weekdays = sorted([int(d) for d in self.trigger_value])
                if not target_weekdays: return None
                temp_date = from_date
                for _ in range(8):
                    if temp_date.weekday() in target_weekdays: return temp_date
                    temp_date += timedelta(days=1)
            except (ValueError, TypeError):
                return None
        return None

    def trigger(self):
        if self.repeat_total != -1: self.times_triggered += 1
        self.last_triggered_date = date.today()

    def get_rule_text(self):
        if self.trigger_type == "date":
            return f"特定日期: {self.trigger_value}"
        elif self.trigger_type == "interval":
            return f"每 {self.trigger_value} 天"
        elif self.trigger_type == "weekly":
            days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            day_names = [days[int(d)] for d in self.trigger_value]
            return "每周 " + "、".join(day_names)
        return "未知规则"


# ===================================================================
# --- 主程序窗口类 ---
# ===================================================================
class FishCatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # ... (所有属性初始化保持不变) ...
        self.DOCK_SENSITIVITY = 15;
        self.DOCK_SIZE = 60;
        self.is_docked = False;
        self.dock_widget = None;
        self.last_pos = {};
        self._drag_start_x = 0;
        self._drag_start_y = 0;
        self._was_dragged = False;
        self.in_grace_period = False;
        self._grace_period_timer_id = None;
        self._save_timer_id = None
        self._save_timer_id = None
        self.last_daily_check_date = None # 【新增】记录上次每日检查的日期
        self.random_mottos = [
            # =======================================================
            # === 班主任通用语录 (Head Teacher's Greatest Hits) ===
            # =======================================================
            "[老师专属]我再讲两分钟就下课。",
            "[老师专属]你们是我带过最差的一届。",
            "[老师专属]整个楼道就咱们班最吵！",
            "[老师专属]你不是在为我学，是在为你自己学！",
            "[老师专属]体育老师今天有事，这节课上自习。",
            "[老师专属]等你们上了大学就轻松了。",
            "[老师专属]耽误大家两分钟，宣布个事...",
            "[老师专属]没人举手是吧？那我开始点名了。",
            "[老师专属]等你们走上社会，就会感谢我了。",
            "[老师专属]高考，是你们人生中最后一次不看脸的竞争。",

            # =======================================================
            # === 数学老师专属语录 (Math Teacher Exclusives) ===
            # =======================================================
            "[老师专属]:奇变偶不变，符号看象限。",
            "[老师专属]:这是一道送分题啊同学们！",
            "[老师专属]:好数理化，走遍天下都不怕。",
            "[老师专属]:约吗？不约！通分！",
            "[老师专属]:题我上次就写在黑板这个位置，一模一样！",
            "[老师专属]:数学是思维的体操，不是让你死记硬背的。",
            "[老师专属]:你们的逻辑能力，是我教学生涯的滑铁卢。",

            # =======================================================
            # === 各科通用经典 (Classic Teacherisms - All Subjects) ===
            # =======================================================
            "[老师专属]看我干嘛，我脸上有字啊？看黑板！",
            "[老师专属]这道题，我已经讲过不下八遍了。",
            "[老师专属]好，下面找个同学来回答一下这个问题。",
            "[老师专属]什么迟到？我不想听到任何理由。",
            "[老师专属]明天就要考试了，今天还有人一个字没看。",
            "[老师专属]要善于利用你们的碎片化时间。",
            "[老师专属]都是一个老师教的，怎么差距就这么大呢？",

            # =======================================================
            # === 摸鱼 & 励志语录 (Originals) ===
            # =======================================================
            "加油，摸鱼人！",
            "摸鱼是为了更好地工作。",
            "一杯茶，一包烟，一个bug改一天。",
            "带薪摸鱼，其乐无穷。",
            "今日事，明日议，后日再说。",
            "只要思想不滑坡，办法总比困难多。",
            "种一棵树最好的时间是十年前，其次是现在。",
            "万物皆有裂痕，那是光照进来的地方。",
            "Talk is cheap. Show me the code.",
            "每一个不曾起舞的日子，都是对生命的辜负。",
            "乾坤未定，你我皆是黑马。",
            "人生最大的荣耀不在于从不跌倒，而在于每次跌倒后都能爬起来。",
            "慢慢来，比较快。",
            "熬过最苦的日子，做最酷的自己。",
            "你的日积月累，会成为别人的望尘莫及。",


            # =======================================================
            # === 幽默段子 & 职场智慧 (Jokes & Office Wisdom) ===
            # =======================================================
            "只要我装得够快，工作就追不上我。",
            "上班是会呼吸的痛，它活在我身上所有角落。",
            "我的爱好很广泛：躺着、趴着、侧卧、仰卧。",
            "问：如何快速入睡？ 答：只要想象明天要上班就行了。",
            "客户：“你们这个系统能不能加个‘一键解决所有问题’的按钮？” 我：“可以，但是点了之后会直接提交您的辞职信。”",
            "面试官：“你的期望薪资是多少？” 我：“我的期望是不上班，还给我发钱。”",
            "别跟我谈理想，我的理想是不上班。",
            "我的钱包就像个洋葱，每次打开都让我泪流满面。",
            "我不是懒，我只是对需要耗费体力的事情过敏。",
            "只要我没道德，道德就绑架不了我。",
            "工作是老板的，但命是自己的。",

            # =======================================================
            # === 人生态度 & 躺平哲学 (Life Attitude & Philosophy) ===
            # =======================================================
            "人生建议：及时行乐，爱咋咋地。",
            "允许一切发生，生活才能开始流动。",
            "你必须内心丰富，才能摆脱那些生活表面的相似。",
            "关关难过关关过，前路漫漫亦灿灿。",
            "做个俗人，贪财好色，一身正气。",
            "间歇性踌躇满志，持续性混吃等死。",
            "慢慢来，比较快。",
            "能力以内，尽量周全；能力以外，顺其自然。",
            "生活就是一边崩溃，一边自愈。",
            "佛系人生三大原则：都行，可以，没关系。",
            "工作是老板的，但命是自己的。",
            "上班为了下班，下班为了不上班。",
            "只要我没道德，道德就绑架不了我。",
            "不是工作需要我，而是我需要这份工作。",
            "间歇性踌躇满志，持续性混吃等死。",
            "上班如上坟，摸鱼才是真。",
            "只要我干得够慢，寂寞就追不上我。",
            "万物皆有裂痕，那是光照进来的地方。",
            "生活就是一边崩溃，一边自愈。",
            "闭嘴，是一种修行；沉默，是一种智慧。",
            "能力以内，尽量周全；能力以外，顺其自然。",

            # =======================================================
            # === 国内外名人名句 (Famous Quotes) ===
            # =======================================================
            "我们都在阴沟里，但仍有人仰望星空。 —— 奥斯卡·王尔德",
            "世界上只有一种英雄主义，就是认清生活的真相后依然热爱它。 —— 罗曼·罗兰",
            "Stay hungry, stay foolish. (求知若饥，虚心若愚) —— 史蒂夫·乔布斯",
            "Talk is cheap. Show me the code. —— Linus Torvalds",
            "你所浪费的今天，是昨天逝去的人奢望的明天。 —— 哈佛大学校训",
            "世界上本没有路，走的人多了，也便成了路。 —— 鲁迅",
            "人有悲欢离合，月有阴晴圆缺，此事古难全。 —— 苏轼",
            "天才是1%的灵感加上99%的汗水。 —— 托马斯·爱迪生",
            "The unexamined life is not worth living. (未经审视的人生不值得过) —— 苏格拉底",
            "万物皆有裂痕，那是光照进来的地方。 —— 莱昂纳德·科恩",

            # =======================================================
            # === 程序员专属黑话 (Coder's Humor) ===
            # =======================================================
            "又不是不能用。",
            "在我的电脑上是好的啊！",
            "修复一个bug，产生三个新bug，这是宇宙的守恒定律。",
            "为什么程序员喜欢用暗色主题？因为光是bug就够亮了。",
            "不要动我的代码，它有自己的想法。",
            "面向CV编程，专业代码搬运工。"
        ]
        self.motto_label = None;
        self.MOTTO_REFRESH_INTERVAL = timedelta(seconds=30);
        self.last_motto_update_time = datetime.min
        self.title("摸鱼神器 哆啦A梦版 V4.0");
        self.geometry("450x700")
        # --- 【完美居中解决方案】 ---
        # 定义窗口的期望尺寸
        app_width = 450
        app_height = 700

        # 获取屏幕的尺寸
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # 计算窗口居中时的左上角 x, y 坐标
        x = (screen_width // 2) - (app_width // 2)
        y = (screen_height // 2) - (app_height // 2)

        # 使用 f-string 将尺寸和位置信息合并成一个字符串，一次性设置
        # 格式为 '宽度x高度+x坐标+y坐标'
        self.geometry(f'{app_width}x{app_height}+{x}+{y}')
        # --- 【修改结束】 ---
        self.style = tb.Style(theme='litera');
        self.DORA_BLUE = "#00a0e8";
        self.DORA_WHITE = "#ffffff";
        self.DORA_RED = "#e60012";
        self.TEXT_COLOR = "#333333";
        self.FONT_NORMAL = ("Microsoft YaHei UI", 11);
        self.FONT_BOLD = ("Microsoft YaHei UI", 11, "bold");
        self.FONT_LARGE = ("Microsoft YaHei UI", 28, "bold");
        self.FONT_MEDIUM = ("Microsoft YaHei UI", 16, "bold");
        self.FONT_MOTIVATIONAL = ("Microsoft YaHei UI", 14, "italic")
        try:
            self.iconbitmap(ICON_PATH)
        except tk.TclError:
            print("提示：未找到 fish_icon.ico 图标文件。")
        self.bg_image_pil = None
        try:
            self.bg_image_pil = Image.open(IMAGE_PATH)
        except Exception as e:
            print(f"警告: 加载背景图片失败: {e}")
        self.work_end_time_str = tk.StringVar();
        self.water_reminder_interval = tk.IntVar();
        self.last_reminder_time = time.time();
        self.reminder_enabled = tk.BooleanVar();
        self.payday = tk.IntVar()
        self.event_objects = []
        self.load_data()
        self.event_labels = []

        self.setup_styles()
        self.create_scrollable_area_and_widgets()

        self.work_end_time_str.trace_add("write", self.schedule_save);
        self.water_reminder_interval.trace_add("write", self.schedule_save);
        self.reminder_enabled.trace_add("write", self.schedule_save)
        self.bind_all("<MouseWheel>", self._on_mousewheel);
        self.bind_all("<Button-4>", self._on_mousewheel);
        self.bind_all("<Button-5>", self._on_mousewheel)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.check_and_trigger_events()  # 启动时检查
        self.update_event_display()
        self.after(10, self.update_ui)


    def on_closing(self):
        self.save_data(); self.destroy()

    def load_data(self):
        default_settings = {"payday": 10, "work_end_time": "18:00:00", "reminder_interval": 60,
                            "reminder_enabled": True}
        default_event_data = {"name": "元旦", "enabled": True, "start_date": f"{datetime.now().year + 1}-01-01",
                              "last_triggered_date": None,
                              "trigger": {"type": "date", "value": f"{datetime.now().year + 1}-01-01"},
                              "repeat": {"total": 1, "triggered": 0}}
        default_data = {"events": [default_event_data], "settings": default_settings}
        if not os.path.exists(EVENTS_FILE):
            self.data = default_data
        else:
            try:
                with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                if 'settings' not in self.data: self.data['settings'] = default_settings
            except (json.JSONDecodeError, IOError):
                self.data = default_data
        loaded_settings = self.data.get('settings', default_settings)
        self.payday.set(loaded_settings.get('payday', 10));
        self.work_end_time_str.set(loaded_settings.get('work_end_time', "18:00:00"));
        self.water_reminder_interval.set(loaded_settings.get('reminder_interval', 60));
        self.reminder_enabled.set(loaded_settings.get('reminder_enabled', True))
        events_data_list = self.data.get('events', [default_event_data])
        self.event_objects = [Event(e) for e in events_data_list]

    def save_data(self):
        self.data['events'] = [e.to_dict() for e in self.event_objects]
        self.data['settings'] = {'payday': self.payday.get(), 'work_end_time': self.work_end_time_str.get(),
                                 'reminder_interval': self.water_reminder_interval.get(),
                                 'reminder_enabled': self.reminder_enabled.get()}
        try:
            with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
            print(f"Settings saved at {datetime.now()}")
        except IOError as e:
            print(f"Error saving data: {e}")

    def create_scrollable_area_and_widgets(self):
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0);
        self.scrollbar = tb.Scrollbar(self, orient="vertical", command=self.canvas.yview, bootstyle="info-round");
        self.canvas.pack(side="left", fill="both", expand=True);
        self.scrollbar.pack(side="right", fill="y");
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        if self.bg_image_pil:
            w, h = self.bg_image_pil.size; new_w = 450; new_h = int(
                new_w * h / w); resized_image = self.bg_image_pil.resize((new_w, new_h),
                                                                         Image.Resampling.LANCZOS); self.bg_image_tk = ImageTk.PhotoImage(
                resized_image); self.canvas.create_image(0, 0, image=self.bg_image_tk, anchor="nw")
        else:
            self.canvas.configure(bg=self.DORA_WHITE)
        self.scrollable_frame = tb.Frame(self.canvas);
        self.scrollable_frame.configure(style='TFrame');
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw");
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        time_frame = tb.LabelFrame(self.scrollable_frame, text="📅 当前状态", bootstyle="info");
        time_frame.pack(fill="x", pady=5, padx=10, expand=True, ipady=5);
        self.date_label = tb.Label(time_frame, text="", font=self.FONT_NORMAL, style='Card.TLabel');
        self.date_label.pack();
        self.time_label = tb.Label(time_frame, text="", font=self.FONT_LARGE, foreground=self.DORA_BLUE,
                                   style='Card.TLabel');
        self.time_label.pack()
        work_frame = tb.LabelFrame(self.scrollable_frame, text="🏃 竹蜻蜓启动倒计时", bootstyle="info");
        work_frame.pack(fill="x", pady=10, padx=10, expand=True, ipady=5);
        work_input_frame = tb.Frame(work_frame, style='Card.TFrame');
        work_input_frame.pack(fill="x", padx=10, pady=(5, 0));
        tb.Label(work_input_frame, text="下班时间:", font=self.FONT_NORMAL, style='Card.TLabel').pack(side="left");
        tb.Entry(work_input_frame, textvariable=self.work_end_time_str, width=10, bootstyle="info").pack(side="left",
                                                                                                         padx=5);
        tb.Button(work_input_frame, text="设置发薪日", command=self.set_payday, bootstyle="info-outline",
                  width=10).pack(side="right");
        self.work_countdown_label = tb.Label(work_frame, text="...", style='Highlight.TLabel');
        self.work_countdown_label.pack(pady=(10, 2));
        # 【正确做法】在创建Label时就指定wraplength和justify
        self.motto_label = tb.Label(work_frame, text="...", style='Motivational.TLabel', wraplength=305, justify='left')
        # .pack()只负责布局
        self.motto_label.pack(pady=(0, 5), padx=10, fill='x')
        wealth_frame = tb.LabelFrame(self.scrollable_frame, text="💰 财富百宝箱", bootstyle="info");
        wealth_frame.pack(fill="x", pady=10, padx=10, expand=True, ipady=10);
        self.weekend_countdown_label = tb.Label(wealth_frame, text="距离周末还有...", font=self.FONT_MEDIUM,
                                                style='Card.TLabel', foreground=self.DORA_BLUE);
        self.weekend_countdown_label.pack();
        self.payday_countdown_label = tb.Label(wealth_frame, text="距离发工资还有...", font=self.FONT_MEDIUM,
                                               style='Card.TLabel', foreground=self.DORA_BLUE);
        self.payday_countdown_label.pack(pady=(5, 0))
        event_frame = tb.LabelFrame(self.scrollable_frame, text="🎉 未来时光机", bootstyle="info");
        event_frame.pack(fill="x", pady=10, padx=10, expand=True, ipady=5);
        tb.Button(event_frame, text="管理事件...", command=self.open_event_manager, bootstyle="info-outline").pack(
            pady=5);
        self.events_display_frame = tb.Frame(event_frame, style='Card.TFrame');
        self.events_display_frame.pack(pady=5)
        water_frame = tb.LabelFrame(self.scrollable_frame, text="💧 铜锣烧补给站", bootstyle="info");
        water_frame.pack(fill="x", pady=10, padx=10, expand=True, ipady=5);
        water_control_frame = tb.Frame(water_frame, style='Card.TFrame');
        water_control_frame.pack(fill="x", padx=10, pady=5);
        tb.Checkbutton(water_control_frame, text="开启提醒", variable=self.reminder_enabled,
                       bootstyle="info-round-toggle", style='Card.TCheckbutton').pack(side="left");
        tb.Label(water_control_frame, text="间隔(分):", style='Card.TLabel').pack(side="left", padx=(10, 5));
        tb.Spinbox(water_control_frame, from_=0, to=120, textvariable=self.water_reminder_interval, width=5,
                   bootstyle="info").pack(side="left");
        tb.Button(water_control_frame, text="来一个!", command=lambda: self.send_notification(force=True),
                  bootstyle="warning-outline").pack(side="right")
        about_frame = tb.Frame(self.scrollable_frame);
        about_frame.pack(fill="x", pady=(10, 5), padx=10)
        tb.Button(about_frame, text="关于", command=self.show_about_window, bootstyle="link").pack(side="right")

    def show_about_window(self):
        AboutWindow(self)

    def update_ui(self):
        if not self.is_docked:
            now = datetime.now()
            today = now.date()

            # 【核心修改】每日九点检查逻辑
            # 如果时间是9点以后，并且“今天”还没有执行过每日检查
            if now.hour >= 9 and self.last_daily_check_date != today:
                self.check_and_trigger_events()

            self.date_label.config(text=now.strftime("%Y年%m月%d日 %A"))
            self.time_label.config(text=now.strftime("%H:%M:%S"))
            self.update_work_countdown(now)
            self.update_event_countdown_text(now)
            self.check_position_for_docking()
            self.update_weekend_countdown(now)
            self.update_payday_countdown(now)

        self.check_water_reminder()
        self.after(200, self.update_ui)

    def check_and_trigger_events(self):
        today = date.today()
        triggered_events = []
        for event in self.event_objects:
            if not event.enabled: continue
            next_occurrence = event.get_occurrences(1)
            if next_occurrence and next_occurrence[0] == today:
                if event.last_triggered_date != today:  # 确保今天没有被触发过
                    event.trigger()
                    triggered_events.append(event.name)

        if triggered_events:
            self.save_data()
            messagebox.showinfo("今日事件提醒", f"今天有新事件发生啦！\n\n- " + "\n- ".join(triggered_events),
                                parent=self)
            self.update_event_display()

        # 【核心修改】无论是否触发事件，都标记今天已执行过检查
        self.last_daily_check_date = today

    def open_event_manager(self):
        manager = EventManagerWindow(self); manager.grab_set()

    def update_event_display(self):
        for widget in self.events_display_frame.winfo_children(): widget.destroy()
        self.event_labels.clear()

        # 【修复1】获取当前日期
        today = date.today()
        # 【修复2】将 today 传递给 _calculate_next
        enabled_events = sorted([e for e in self.event_objects if e.enabled],
                                key=lambda x: (x._calculate_next(today) or date.max))

        if not enabled_events:
            tb.Label(self.events_display_frame, text="(还没有添加未来事件哦)", style='Motivational.TLabel').pack()
        else:
            for event in enabled_events:
                label = tb.Label(self.events_display_frame, text="...", font=self.FONT_NORMAL,
                                 foreground=self.DORA_BLUE, style='Card.TLabel')
                label.pack()
                self.event_labels.append(label)

    def update_event_countdown_text(self, now):
        today = now.date()
        # 【核心修改】排序逻辑与 update_event_display 保持一致
        enabled_events = sorted([e for e in self.event_objects if e.enabled],
                                key=lambda x: (x._calculate_next(today) or date.max))

        if len(self.event_labels) != len(enabled_events):
            self.update_event_display()
            # 在某些情况下（如事件被禁用后），需要重新获取排序后的列表
            enabled_events = sorted([e for e in self.event_objects if e.enabled],
                                    key=lambda x: (x._calculate_next(today) or date.max))

        for i, event in enumerate(enabled_events):
            if i >= len(self.event_labels): continue

            # 【核心修改】直接使用 _calculate_next 获取当前或未来的下一次发生日期，用于显示
            # 这会忽略事件今天是否已被触发，确保今日事件全天显示
            next_occurrence = event._calculate_next(today)

            if not next_occurrence:
                # 检查事件是否是因为今天刚刚发生才“结束”的
                if event.last_triggered_date == today:
                    # 如果是，那么全天都应该显示为“今天”
                    text = f"🎉 今天就是 {event.name}！"
                    self.event_labels[i].config(text=text, foreground=self.DORA_RED)
                else:
                    # 否则，事件是真的已经结束了（比如过期的单次事件）
                    text = f"{event.name} (已结束)"
                    self.event_labels[i].config(text=text, foreground="gray")
                continue # 处理完后，跳到下一个事件

            days = (next_occurrence - today).days
            if days == 0:
                text = f"🎉 今天就是 {event.name}！"
            else:
                text = f"距离 {event.name} 还有 {days} 天"

            # 3天内发生的事件用红色突出显示
            self.event_labels[i].config(text=text, foreground=self.DORA_RED if days <= 3 else self.DORA_BLUE)

    # --- (其他所有旧方法保持不变) ---
    def setup_styles(self):
        card_bg = self.DORA_WHITE; self.style.configure('TLabelFrame', background=card_bg, bordercolor=self.DORA_BLUE,
                                                        relief="solid", borderwidth=1); self.style.configure(
            'TLabelFrame.Label', font=self.FONT_BOLD, background=card_bg,
            foreground=self.DORA_BLUE); self.style.configure('Card.TLabel', background=card_bg,
                                                             foreground=self.TEXT_COLOR); self.style.configure(
            'Card.TFrame', background=card_bg); self.style.configure('Card.TCheckbutton',
                                                                     background=card_bg); self.style.configure(
            'Highlight.TLabel', foreground=self.DORA_RED, background=card_bg,
            font=self.FONT_MEDIUM); self.style.configure('Motivational.TLabel', foreground=self.DORA_BLUE,
                                                         background=card_bg, font=self.FONT_MOTIVATIONAL)

    def schedule_save(self, *args):
        if self._save_timer_id: self.after_cancel(self._save_timer_id)
        self._save_timer_id = self.after(500, self.save_data)

    def set_payday(self):
        new_day = simpledialog.askinteger("设置发薪日", "请输入您的发薪日是每月的几号 (1-31):", parent=self, minvalue=1,
                                          maxvalue=31, initialvalue=self.payday.get())
        if new_day is not None: self.payday.set(new_day); self.save_data(); messagebox.showinfo("成功",
                                                                                                f"发薪日已设置为每月 {new_day} 号！"); self.update_payday_countdown(
            datetime.now())

    def update_weekend_countdown(self, now):
        weekday = now.weekday()
        if weekday < 5:
            self.weekend_countdown_label.config(text=f"距离周末还有 {5 - weekday} 天", foreground=self.DORA_BLUE)
        elif weekday == 5:
            self.weekend_countdown_label.config(text="🎉 周末来啦！好好放松！", foreground=self.DORA_RED)
        else:
            self.weekend_countdown_label.config(text="🎉 明天又是新的一周啦！", foreground=self.DORA_RED)

    def update_payday_countdown(self, now):
        payday_num = self.payday.get();
        today_num = now.day
        if today_num == payday_num: self.payday_countdown_label.config(text="🎉 今天发粮！财富到账！",
                                                                       foreground=self.DORA_RED); return
        if today_num < payday_num:
            days_left = payday_num - today_num
        else:
            days_in_month = calendar.monthrange(now.year, now.month)[1]; days_left = (
                                                                                                 days_in_month - today_num) + payday_num
        self.payday_countdown_label.config(text=f"距离发粮还有 {days_left} 天", foreground=self.DORA_BLUE)

    def check_position_for_docking(self):
        if self.in_grace_period or self.state() == 'iconic': return
        screen_w = self.winfo_screenwidth();
        win_x = self.winfo_x();
        win_w = self.winfo_width()
        if win_x < self.DOCK_SENSITIVITY:
            self.dock_app("left")
        elif win_x + win_w > screen_w - self.DOCK_SENSITIVITY:
            self.dock_app("right")

    def dock_app(self, edge):
        if self.is_docked: return
        if self._grace_period_timer_id: self.after_cancel(
            self._grace_period_timer_id); self._grace_period_timer_id = None; self.in_grace_period = False
        self.is_docked = True;
        self.last_pos = {'x': self.winfo_x(), 'y': self.winfo_y()};
        self.withdraw();
        self.create_dock_widget(edge)

    def create_dock_widget(self, edge):
        self.dock_widget = tk.Toplevel(self);
        self.dock_widget.overrideredirect(True);
        self.dock_widget.wm_attributes("-topmost", True);
        transparent_color = '#abcdef';
        self.dock_widget.wm_attributes("-transparentcolor", transparent_color)
        canvas = tk.Canvas(self.dock_widget, bg=transparent_color, width=self.DOCK_SIZE, height=self.DOCK_SIZE,
                           highlightthickness=0);
        canvas.pack();
        padding = 4;
        canvas.create_oval(padding, padding, self.DOCK_SIZE - padding, self.DOCK_SIZE - padding, fill=self.DORA_BLUE,
                           outline=self.DORA_WHITE, width=2);
        canvas.create_text(self.DOCK_SIZE / 2, self.DOCK_SIZE / 2, text="🐟", font=("Segoe UI Emoji", 20),
                           fill=self.DORA_WHITE)
        screen_w = self.winfo_screenwidth();
        y_pos = max(0, self.last_pos['y']);
        x_pos = 0 if edge == "left" else screen_w - self.DOCK_SIZE;
        self.dock_widget.geometry(f'{self.DOCK_SIZE}x{self.DOCK_SIZE}+{x_pos}+{y_pos}')
        canvas.bind("<ButtonPress-1>", self._on_drag_start);
        canvas.bind("<B1-Motion>", self._on_drag_motion);
        canvas.bind("<ButtonRelease-1>", self.undock_app_on_release)

    def undock_app(self, event=None):
        if not self.is_docked: return
        if self.dock_widget: self.dock_widget.destroy(); self.dock_widget = None
        self.is_docked = False;
        self.deiconify();
        self.lift();
        self.focus_force();
        self.geometry(f"+{self.last_pos['x']}+{self.last_pos['y']}")

    def _on_drag_start(self, event):
        self._drag_start_x = event.x; self._drag_start_y = event.y; self._was_dragged = False

    def _on_drag_motion(self, event):
        self._was_dragged = True
        if self.in_grace_period: self.after_cancel(
            self._grace_period_timer_id); self._grace_period_timer_id = None; self.in_grace_period = False
        x = self.dock_widget.winfo_x() - self._drag_start_x + event.x;
        y = self.dock_widget.winfo_y() - self._drag_start_y + event.y;
        self.dock_widget.geometry(f"+{x}+{y}");
        self.last_pos = {'x': x, 'y': y}
        screen_w = self.winfo_screenwidth()
        if x > self.DOCK_SENSITIVITY and x < screen_w - self.DOCK_SIZE - self.DOCK_SENSITIVITY: self.undock_app()

    def undock_app_on_release(self, event):
        if not self._was_dragged: self.undock_app(); self.in_grace_period = True; self._grace_period_timer_id = self.after(
            10000, self.end_grace_period)

    def end_grace_period(self):
        self.in_grace_period = False; self._grace_period_timer_id = None; self.check_position_for_docking()

    def update_work_countdown(self, now):
        motivational_messages = {9: "装上竹蜻蜓，出发！ (ง •̀_•́)ง", 14: "记忆面包有点吃撑了...想睡觉...",
                                 16: "坚持住，任意门就在眼前啦！", 17: "太棒了！下班去吃铜锣烧！ ✨"}
        try:
            end_time_str = self.work_end_time_str.get();
            today_end_time = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {end_time_str}", "%Y-%m-%d %H:%M:%S")
            if now > today_end_time: self.work_countdown_label.config(
                text="🎉 任意门已开启！ 🎉"); self.motto_label.config(text="下班啦！好好休息！"); return
            delta = today_end_time - now;
            h, rem = divmod(delta.seconds, 3600);
            m, s = divmod(rem, 60);
            self.work_countdown_label.config(text=f"{h:02d}:{m:02d}:{s:02d}")
            special_message_found = False
            for trigger_hour, message in motivational_messages.items():
                if now.hour == trigger_hour and 0 <= now.minute < 10: self.motto_label.config(
                    text=message); special_message_found = True; break
            if not special_message_found:
                if (now - self.last_motto_update_time) > self.MOTTO_REFRESH_INTERVAL: self.motto_label.config(
                    text=random.choice(self.random_mottos)); self.last_motto_update_time = now
        except (ValueError, tk.TclError):
            self.work_countdown_label.config(text="时间格式不对哦~"); self.motto_label.config(
                text="请检查下班时间格式 (HH:MM:SS)")

    def check_water_reminder(self):
        if not self.reminder_enabled.get(): return
        try:
            interval_minutes = self.water_reminder_interval.get()
            if interval_minutes <= 0: return
            interval_seconds = interval_minutes * 60
        except (ValueError, tk.TclError):
            return
        if (
                time.time() - self.last_reminder_time) > interval_seconds: self.last_reminder_time = time.time(); self.send_notification(
            is_burst=True)

    def send_notification(self, force=False, is_burst=False):
        if force:
            try:
                if self.water_reminder_interval.get() <= 0: messagebox.showwarning("输入无效", "提醒间隔必须大于0分钟！",
                                                                                   parent=self); return
            except (ValueError, tk.TclError):
                messagebox.showwarning("输入无效", "提醒间隔必须是有效的数字！", parent=self); return
            self.last_reminder_time = time.time()

        def _send():
            title = '百宝袋提醒您';
            message = '是时候补充一个铜锣烧啦！(起来喝水~)'
            if is_burst and notification:
                for i in range(10):
                    try:
                        notification.notify(title=f"{title} ({i + 1}/10)", message=message, app_name='Doraemon Catcher',
                                            timeout=10)
                    except Exception as e:
                        print(f"发送通知失败: {e}"); messagebox.showinfo(title, message); break
                    time.sleep(3)
            else:
                try:
                    if notification:
                        notification.notify(title=title, message=message, app_name='Doraemon Catcher', timeout=10)
                    else:
                        messagebox.showinfo(title, message)
                except Exception as e:
                    print(f"发送通知失败: {e}"); messagebox.showinfo(title, message)

        threading.Thread(target=_send, daemon=True).start()

    def _on_mousewheel(self, event):
        if self.is_docked: return
        if hasattr(event, 'delta') and event.delta != 0:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")


# ===================================================================
# --- 【重大升级 V5.1】事件管理窗口 EventManagerWindow ---
# ===================================================================
class EventManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("事件管理");
        self.geometry("650x450");
        self.resizable(False, False)

        frame = tb.Frame(self, padding="10");
        frame.pack(expand=True, fill="both")
        cols = ("启用", "事件名称", "规则", "最近两次发生", "剩余次数")
        self.tree = tb.Treeview(frame, columns=cols, show="headings", height=10, bootstyle="info")
        for col in cols: self.tree.heading(col, text=col)
        self.tree.column("启用", width=50, anchor="center")
        self.tree.column("事件名称", width=120)
        self.tree.column("规则", width=150)
        self.tree.column("最近两次发生", width=180, anchor="center")
        self.tree.column("剩余次数", width=80, anchor="center")
        self.tree.pack(expand=True, fill="both")
        self.tree.bind("<Double-1>", self.edit_event)

        btn_frame = tb.Frame(frame, padding=(0, 10, 0, 0));
        btn_frame.pack(fill="x")
        tb.Button(btn_frame, text="添加", command=self.add_event, bootstyle="success").pack(side="left", padx=5)
        tb.Button(btn_frame, text="编辑", command=self.edit_event, bootstyle="warning").pack(side="left", padx=5)
        tb.Button(btn_frame, text="删除", command=self.delete_event, bootstyle="danger").pack(side="left", padx=5)
        self.toggle_button = tb.Button(btn_frame, text="切换启用/禁用", command=self.toggle_event_enabled,
                                       bootstyle="secondary")
        self.toggle_button.pack(side="left", padx=5)

        bottom_frame = tb.Frame(frame, padding=(0, 10, 0, 0));
        bottom_frame.pack(side="bottom", fill="x")
        tb.Button(bottom_frame, text="关闭", command=self.on_close, bootstyle="primary").pack(side="right")

        # 【核心修改】绑定选择事件，以实时更新按钮状态
        self.tree.bind("<<TreeviewSelect>>", self.update_toggle_button_state)

        self.populate_tree()

    def populate_tree(self):
        # 保存当前选中的项
        selected_iid = self.tree.focus()

        for i in self.tree.get_children(): self.tree.delete(i)
        for idx, event in enumerate(self.parent.event_objects):
            occurrences = event.get_occurrences(2)
            next_dates_str = "、".join([d.strftime("%y-%m-%d") for d in occurrences]) if occurrences else "N/A"
            remaining = "∞" if event.repeat_total == -1 else max(0, event.repeat_total - event.times_triggered)

            tag = "enabled" if event.enabled else "disabled"
            self.tree.insert("", "end", iid=idx, values=(
                "✔" if event.enabled else "✘", event.name, event.get_rule_text(), next_dates_str, remaining
            ), tags=(tag,))

        self.tree.tag_configure("enabled", foreground="black")
        self.tree.tag_configure("disabled", foreground="gray")

        # 恢复选中状态
        if selected_iid and self.tree.exists(selected_iid):
            self.tree.selection_set(selected_iid)
            self.tree.focus(selected_iid)

        self.update_toggle_button_state()  # 刷新后也更新一次按钮状态

    def update_toggle_button_state(self, event=None):
        """【新增】根据当前选择项更新按钮颜色"""
        selected_iid = self.tree.focus()
        if not selected_iid:
            self.toggle_button.config(bootstyle="secondary")  # 未选中时为灰色
            return

        idx = int(selected_iid)
        if idx < len(self.parent.event_objects):
            event_obj = self.parent.event_objects[idx]
            if event_obj.enabled:
                self.toggle_button.config(bootstyle="success")  # 启用时为绿色
            else:
                self.toggle_button.config(bootstyle="secondary")  # 禁用时为灰色

    def add_event(self):
        EventEditorWindow(self, callback=self.on_event_saved)

    def edit_event(self, event_info=None):
        selected_iid = self.tree.focus()
        if not selected_iid: messagebox.showwarning("提示", "请先选择一个事件进行编辑。", parent=self); return
        idx = int(selected_iid);
        event_obj = self.parent.event_objects[idx]
        EventEditorWindow(self, event_to_edit=event_obj, index=idx, callback=self.on_event_saved)

    def on_event_saved(self, event_obj, index):
        if index is None:
            self.parent.event_objects.append(event_obj)
        else:
            self.parent.event_objects[index] = event_obj
        self.populate_tree()

    def delete_event(self):
        selected_iid = self.tree.focus()
        if not selected_iid: messagebox.showwarning("提示", "请先选择一个要删除的事件。", parent=self); return
        if messagebox.askyesno("确认删除", "确定要删除选中的事件吗？此操作无法撤销。", parent=self):
            del self.parent.event_objects[int(selected_iid)];
            self.populate_tree()

    def toggle_event_enabled(self):
        selected_iid = self.tree.focus()
        if not selected_iid: messagebox.showwarning("提示", "请先选择一个要切换状态的事件。", parent=self); return
        idx = int(selected_iid)
        self.parent.event_objects[idx].enabled = not self.parent.event_objects[idx].enabled
        self.populate_tree()

    def on_close(self):
        self.parent.save_data(); self.parent.update_event_display(); self.destroy()


# ===================================================================
# --- 【重大升级 V5.0】事件编辑器窗口 EventEditorWindow ---
# ===================================================================
class EventEditorWindow(tk.Toplevel):
    def __init__(self, parent, event_to_edit=None, index=None, callback=None):
        super().__init__(parent)
        self.parent = parent;
        self.event_to_edit = event_to_edit;
        self.index = index;
        self.callback = callback
        self.title("添加/编辑事件");
        self.geometry("450x500");
        self.resizable(False, False)
        main_frame = ScrolledFrame(self, autohide=True);
        main_frame.pack(fill="both", expand=True)
        base_info_frame = tb.LabelFrame(main_frame, text="基本信息", padding=10);
        base_info_frame.pack(fill="x", padx=10, pady=5);
        tb.Label(base_info_frame, text="事件名称:").grid(row=0, column=0, sticky="w", pady=2);
        self.name_var = tk.StringVar();
        self.name_entry = tb.Entry(base_info_frame, textvariable=self.name_var, bootstyle="info");
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=5);
        self.enabled_var = tk.BooleanVar(value=True);
        tb.Checkbutton(base_info_frame, text="启用此事件", variable=self.enabled_var,
                       bootstyle="info-round-toggle").grid(row=1, column=0, columnspan=2, sticky="w", pady=5);
        base_info_frame.columnconfigure(1, weight=1)
        trigger_frame = tb.LabelFrame(main_frame, text="触发规则", padding=10);
        trigger_frame.pack(fill="x", padx=10, pady=5);
        tb.Label(trigger_frame, text="类型:").grid(row=0, column=0, sticky="w", pady=2);
        self.type_var = tk.StringVar();
        self.type_combo = tb.Combobox(trigger_frame, textvariable=self.type_var,
                                      values=["特定日期", "按天循环", "按周循环"], state="readonly", bootstyle="info");
        self.type_combo.grid(row=0, column=1, sticky="ew", padx=5);
        self.type_combo.bind("<<ComboboxSelected>>", self._on_type_change);
        self.options_frame = tb.Frame(trigger_frame);
        self.options_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5);
        self._create_options_frames();
        trigger_frame.columnconfigure(1, weight=1)
        repeat_frame = tb.LabelFrame(main_frame, text="重复设置", padding=10);
        repeat_frame.pack(fill="x", padx=10, pady=5);
        tb.Label(repeat_frame, text="起始日期:").grid(row=0, column=0, sticky="w", pady=2);
        self.start_date_var = tk.StringVar(value=date.today().strftime("%Y-%m-%d"));
        tb.Entry(repeat_frame, textvariable=self.start_date_var, bootstyle="info").grid(row=0, column=1, sticky="ew",
                                                                                        padx=5);
        tb.Label(repeat_frame, text="重复次数:").grid(row=1, column=0, sticky="w", pady=2);
        self.repeat_var = tk.IntVar(value=1);
        self.repeat_spinbox = tb.Spinbox(repeat_frame, from_=1, to=999, textvariable=self.repeat_var, bootstyle="info");
        self.repeat_spinbox.grid(row=1, column=1, sticky="ew", padx=5);
        self.infinite_var = tk.BooleanVar();
        tb.Checkbutton(repeat_frame, text="无限循环 (∞)", variable=self.infinite_var, command=self._toggle_infinite,
                       bootstyle="info").grid(row=2, column=1, sticky="w", pady=5);
        repeat_frame.columnconfigure(1, weight=1)
        control_frame = tb.Frame(main_frame, padding=10);
        control_frame.pack(fill="x", side="bottom");
        tb.Button(control_frame, text="保存", command=self.save_event, bootstyle="success").pack(side="right", padx=5);
        tb.Button(control_frame, text="取消", command=self.destroy, bootstyle="secondary").pack(side="right")
        self.load_event_data()

    def _create_options_frames(self):
        self.date_frame = tb.Frame(self.options_frame);
        tb.Label(self.date_frame, text="日期 (YYYY-MM-DD):").pack(side="left");
        self.date_val_var = tk.StringVar();
        tb.Entry(self.date_frame, textvariable=self.date_val_var, bootstyle="info").pack(side="left", fill="x",
                                                                                         expand=True, padx=5)
        self.interval_frame = tb.Frame(self.options_frame);
        tb.Label(self.interval_frame, text="每隔").pack(side="left");
        self.interval_val_var = tk.IntVar(value=7);
        tb.Spinbox(self.interval_frame, from_=1, to=365, textvariable=self.interval_val_var, bootstyle="info").pack(
            side="left", padx=5);
        tb.Label(self.interval_frame, text="天").pack(side="left")
        self.weekly_frame = tb.Frame(self.options_frame);
        self.weekday_vars = [tk.BooleanVar() for _ in range(7)];
        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
        for i, day in enumerate(days): tb.Checkbutton(self.weekly_frame, text=day, variable=self.weekday_vars[i],
                                                      bootstyle="info").pack(side="left", padx=2, expand=True)

    def _on_type_change(self, event=None):
        self.date_frame.pack_forget();
        self.interval_frame.pack_forget();
        self.weekly_frame.pack_forget()
        selected_type = self.type_var.get()
        if selected_type == "特定日期":
            self.date_frame.pack(fill="x"); self.infinite_var.set(False); self.repeat_var.set(
                1); self.repeat_spinbox.config(state="normal")
        elif selected_type == "按天循环":
            self.interval_frame.pack(fill="x")
        elif selected_type == "按周循环":
            self.weekly_frame.pack(fill="x")

    def _toggle_infinite(self):
        is_infinite = self.infinite_var.get()
        self.repeat_spinbox.config(state="disabled" if is_infinite else "normal")
        if not is_infinite and self.repeat_var.get() < 1: self.repeat_var.set(1)

    def load_event_data(self):
        if not self.event_to_edit: self.type_combo.set("特定日期"); self._on_type_change(); return
        e = self.event_to_edit;
        self.name_var.set(e.name);
        self.enabled_var.set(e.enabled);
        self.start_date_var.set(e.start_date.strftime("%Y-%m-%d"))
        if e.repeat_total == -1:
            self.infinite_var.set(True)
        else:
            self.repeat_var.set(e.repeat_total)
        self._toggle_infinite()
        type_map = {"date": "特定日期", "interval": "按天循环", "weekly": "按周循环"};
        self.type_combo.set(type_map.get(e.trigger_type, "特定日期"))
        if e.trigger_type == "date":
            self.date_val_var.set(e.trigger_value)
        elif e.trigger_type == "interval":
            self.interval_val_var.set(int(e.trigger_value))
        elif e.trigger_type == "weekly":
            for i, var in enumerate(self.weekday_vars):
                if str(i) in e.trigger_value: var.set(True)
        self._on_type_change()

    def save_event(self):
        name = self.name_var.get().strip()
        if not name: messagebox.showerror("错误", "事件名称不能为空。", parent=self); return
        type_map_rev = {"特定日期": "date", "按天循环": "interval", "按周循环": "weekly"};
        trigger_type = type_map_rev[self.type_var.get()];
        trigger_value = None
        if trigger_type == "date":
            try:
                datetime.strptime(self.date_val_var.get(), "%Y-%m-%d"); trigger_value = self.date_val_var.get()
            except ValueError:
                messagebox.showerror("错误", "日期格式不正确 (应为 YYYY-MM-DD)。", parent=self); return
        elif trigger_type == "interval":
            val = self.interval_val_var.get()
            if val <= 0: messagebox.showerror("错误", "间隔天数必须大于0。", parent=self); return
            trigger_value = str(val)
        elif trigger_type == "weekly":
            selected_days = [str(i) for i, var in enumerate(self.weekday_vars) if var.get()]
            if not selected_days: messagebox.showerror("错误", "请至少选择一个星期几。", parent=self); return
            trigger_value = selected_days

        repeat_total = -1 if self.infinite_var.get() else self.repeat_var.get()
        start_date = self.start_date_var.get()

        if self.event_to_edit:
            self.event_to_edit.name = name;
            self.event_to_edit.enabled = self.enabled_var.get();
            self.event_to_edit.start_date = datetime.strptime(start_date, "%Y-%m-%d").date();
            self.event_to_edit.trigger_type = trigger_type;
            self.event_to_edit.trigger_value = trigger_value;
            self.event_to_edit.repeat_total = repeat_total
            if self.callback: self.callback(self.event_to_edit, self.index)
        else:
            event_data = {"name": name, "enabled": self.enabled_var.get(), "start_date": start_date,
                          "trigger": {"type": trigger_type, "value": trigger_value},
                          "repeat": {"total": repeat_total, "triggered": 0}, "last_triggered_date": None}
            if self.callback: self.callback(Event(event_data), None)
        self.destroy()


# ===================================================================
# --- 【新增】关于窗口 AboutWindow ---
# ===================================================================
class AboutWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent);
        self.title("关于 摸鱼神器");
        self.geometry("350x220");
        self.resizable(False, False);
        self.transient(parent)
        frame = tb.Frame(self, padding=20);
        frame.pack(fill="both", expand=True)
        tb.Label(frame, text="摸鱼神器 哆啦A梦版", font=("Microsoft YaHei UI", 16, "bold"), bootstyle="primary").pack(
            pady=(0, 10))
        tb.Label(frame, text="版本: 4.0", bootstyle="secondary").pack()
        tb.Label(frame, text="作者: 小猫不吃鱼$-$", bootstyle="secondary").pack()
        tb.Separator(frame, bootstyle="info").pack(fill="x", pady=15)
        statement = "本软件为开源学习项目，源代码仅供学习和交流使用。严禁用于任何商业目的或非法用途。使用者需自行承担使用本软件所带来的一切风险。"
        tb.Label(frame, text=statement, wraplength=300, justify="left", bootstyle="dark").pack(pady=5)
        tb.Button(frame, text="好的", command=self.destroy, bootstyle="info").pack(pady=(15, 0))


if __name__ == "__main__":
    my_app_id = 'my.company.product.fishcatcher.v4'
    try:
        # 调用Windows Shell API来设置当前进程的AppID
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(my_app_id)
    except AttributeError:
        # 如果在非Windows系统上运行，或者出现其他问题，就忽略这个错误。
        print("非Windows平台，或设置AppID失败，将跳过此步骤。")
    # --- 【修改结束】 ---

    app = FishCatcherApp()
    app.mainloop()