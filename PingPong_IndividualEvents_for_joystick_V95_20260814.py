# ================================================
# 乒乓球单项比赛计分程序 - PingPang_IndividualEvents_for_joystick_V95_Qt_20260814.py
# 功能：实时记录和显示选手的比赛分数和获胜局数
# 支持：键盘快捷键操作、游戏手柄输入
# ================================================
# 版权所有 © 2026 北京市市政工程设计研究总院有限公司
# 开发者：姜恒
# 开发日期：2026年8月
# 版本：V912_Qt_20260806
# ================================================

# 导入PySide6库，用于创建图形用户界面
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QDialog, QLineEdit,
    QFileDialog, QGridLayout, QVBoxLayout,
)
# 导入Qt核心模块：事件过滤器、定时器、常量
from PySide6.QtCore import Qt, QTimer, QEvent, QObject
# 导入Qt图形模块：字体、字体度量、图标、快捷键
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QShortcut, QKeySequence
# 导入pygame库，用于游戏手柄支持
import pygame
import warnings
import sys
import os
import json
import copy
from datetime import datetime
warnings.filterwarnings("ignore")  # 如果警告来自 Python 的 warnings 模块

# ================================================
# 配置文件：Config_IndividualEvents.json
# ================================================
CONFIG_FILE_NAME = "Config_IndividualEvents.json"

# 程序默认配置（首次运行无配置文件时按此生成）
DEFAULT_CONFIG = {
    "player_a_name": "选手A",
    "player_b_name": "选手B",
    "joystick_buttons": {
        "left_add_score":       {"type": "hat",    "value": 1},
        "left_subtract_score":  {"type": "hat",    "value": -1},
        "right_add_score":      {"type": "button", "value": 3},
        "right_subtract_score": {"type": "button", "value": 0},
        "new_over":             {"type": "button", "value": 1},
        "change_ends":          {"type": "button", "value": 2}
    }
}


def get_base_dir():
    """返回程序数据所在目录（脚本或 exe 所在目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_config_path():
    """返回配置文件路径（脚本或 exe 所在目录）"""
    return os.path.join(get_base_dir(), CONFIG_FILE_NAME)


# ================================================
# 相对布局辅助类
# 功能：在 PySide6 中实现 tkinter.place(relx, rely, relwidth, relheight)
#       的相对坐标布局语义。父控件尺寸变化（resizeEvent）时自动重新计算。
# ================================================
class RelativePlacer:
    """按相对坐标放置子控件：relx/rely/relwidth/relheight 与 tkinter.place 语义一致"""

    def __init__(self, parent):
        self._parent = parent
        self._items = []  # 保存 (控件, relx, rely, relw, relh)
        self._batch = 0   # 批处理深度：>0 时 place() 只登记不立即 apply

    def place(self, widget, relx, rely, relw, relh):
        """登记一个控件及其相对位置；非批处理模式下立即应用一次"""
        self._items.append((widget, relx, rely, relw, relh))
        if self._batch == 0:
            self.apply()

    def begin_batch(self):
        """进入批处理：期间的 place() 只登记，end_batch() 时统一 apply 一次"""
        self._batch += 1

    def end_batch(self):
        """结束批处理：最外层结束时统一 apply 一次"""
        if self._batch > 0:
            self._batch -= 1
        if self._batch == 0:
            self.apply()

    def apply(self):
        """根据父控件当前尺寸重新计算所有子控件的位置和大小"""
        pw, ph = self._parent.width(), self._parent.height()
        if pw <= 0 or ph <= 0:
            return
        for widget, relx, rely, relw, relh in self._items:
            widget.setGeometry(
                int(pw * relx), int(ph * rely),
                int(pw * relw), int(ph * relh))


class PlacedMixin:
    """提供相对布局能力：resizeEvent 时重新计算所有子控件位置"""

    def init_placer(self):
        self.placer = RelativePlacer(self)

    def place(self, widget, relx, rely, relw, relh):
        """按相对坐标放置子控件（等价于 tkinter 的 widget.place）"""
        self.placer.place(widget, relx, rely, relw, relh)

    def begin_batch(self):
        """进入批处理布局（期间 place 只登记，end_batch 统一重排）"""
        self.placer.begin_batch()

    def end_batch(self):
        self.placer.end_batch()

    def resizeEvent(self, event):
        if hasattr(self, "placer"):
            self.placer.apply()
        super().resizeEvent(event)


# ================================================
# 主窗口（继承相对布局能力）
# ================================================
class MainWidget(PlacedMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.init_placer()

    def closeEvent(self, event):
        """窗口关闭（如 Alt+F4）时走统一的退出流程，避免直接销毁窗口"""
        app_ref = getattr(self, 'app_ref', None)
        if app_ref is not None:
            event.ignore()
            app_ref.on_closing()
        else:
            super().closeEvent(event)


# ================================================
# 全屏对话框（比赛结果窗口，继承相对布局能力）
# ================================================
class PlacedDialog(PlacedMixin, QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_placer()


# ================================================
# 吞掉 ESC 键的事件过滤器
# 功能：防止 QDialog 默认按 ESC 关闭窗口。
#       原 tkinter 版在设置选手弹窗中按 ESC 无任何效果（grab_set 屏蔽了根窗口绑定），
#       这里保持一致：设置选手弹窗按 ESC 不关闭、不退出。
# ================================================
class _EscapeSwallowFilter(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            return True  # 吞掉 ESC，不交给 QDialog 处理
        return False


# ================================================
# 版权弹窗事件过滤器
# 功能：任意按键或鼠标点击取消自动关闭；
#       吞掉 ESC，防止 QDialog 默认按 ESC 关闭（原 tkinter 版按 ESC 只取消自动关闭）
# ================================================
class _CopyrightEventFilter(QObject):
    def __init__(self, cancel_cb):
        super().__init__()
        self._cancel = cancel_cb

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True  # 吞掉 ESC，避免 QDialog 默认关闭
            self._cancel()
        elif t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            self._cancel()
        return False


# ================================================
# 主类：PingPongScoringApp
# 功能：实现乒乓球比赛计分的完整功能
# ================================================
class PingPongScoringApp:
    # ================================================
    # 初始化方法
    # 参数：root - PySide6主窗口对象
    # ================================================
    def __init__(self, root):
        # 保存主窗口对象引用
        self.root = root
        # 设置窗口标题\图标
        self.root.setWindowTitle("乒乓球比赛计分程序")
        try:
            if getattr(sys, 'frozen', False):
                icon_path = os.path.join(sys._MEIPASS, 'IndividualEvents.ico')
            else:
                icon_path = 'IndividualEvents.ico'
            self.root.setWindowIcon(QIcon(icon_path))
            QApplication.instance().setWindowIcon(QIcon(icon_path))
        except:
            pass
        # 获取当前屏幕的分辨率（在创建控件前先取得，用于预缩放主窗口与自适应字号）
        screen = QApplication.primaryScreen()
        self.screen_width = screen.geometry().width()    # 屏幕宽度
        self.screen_height = screen.geometry().height()  # 屏幕高度

        # 主窗口先保持隐藏并预设为屏幕尺寸：Qt 中若父窗口已显示，之后创建的子控件
        # 会被标记为"显式隐藏"而始终不显示（导致全屏黑屏）。
        # 因此在创建全部控件期间保持主窗口隐藏，控件创建完成后统一进入全屏。
        self.root.resize(self.screen_width, self.screen_height)
        # 设置主窗口背景颜色为黑色
        self.root.setStyleSheet("background-color: black;")

        # 加载配置文件（不存在时按默认值自动创建）
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.load_config()

        # 初始化选手名称变量（从配置文件读取）
        self.player_a_name = self.config["player_a_name"]  # 选手A名称
        self.player_b_name = self.config["player_b_name"]  # 选手B名称

        # 初始化比分变量
        self.score_a = 0  # 当前比赛选手A的得分
        self.score_b = 0  # 当前比赛选手B的得分

        # 初始化获胜局数变量
        self.wins_a = 0  # 当前比赛选手A的获胜局数
        self.wins_b = 0  # 当前比赛选手B的获胜局数

        # 计分文件路径（初始为None，首次保存时生成文件名）
        self.current_score_file = None

        # 游戏手柄对象（初始化为None）
        self.joystick = None
        # 程序运行标志
        self.running = True
        # 退出流程防重复标志
        self._closing = False
        # 模态弹窗深度计数：>0 时 run_gamepad_input 直接返回、不泵取 SDL 事件。
        # 原因：QTimer.stop() 只能阻止后续触发，已进入事件队列的定时器事件仍会在
        # 弹窗 exec() 的嵌套事件循环里被派发，此时 pygame.event.get() 的 SDL 窗口
        # 消息泵会干扰 Qt 模态对话框，导致 exec() 立刻返回（结果窗口偶发一闪即关）。
        # 采用计数方式支持模态弹窗的嵌套调用（结果窗口→历史对话框→提示框）。
        self._dialog_open = False
        self._dialog_depth = 0

        # 游戏手柄轮询定时器（30ms，约33Hz；打开模态弹窗时暂停，与原 wait_window 阻塞行为一致）
        self.gamepad_timer = QTimer(self.root)
        # 精确定时器：默认 CoarseTimer 约有5%抖动，会导致按键响应忽快忽慢
        self.gamepad_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.gamepad_timer.setInterval(30)
        self.gamepad_timer.timeout.connect(self.run_gamepad_input)

        # 手柄按钮映射表（只构建一次，避免每次轮询 tick 内重复创建列表）
        self._joystick_mappings = [
            ("left_add_score",       self.add_score_a),
            ("left_subtract_score",  self.subtract_score_a),
            ("right_add_score",      self.add_score_b),
            ("right_subtract_score", self.subtract_score_b),
            ("new_over",             self.win_a_or_b),
            ("change_ends",          self.change_ends),
        ]

        # 手柄热插拔检测定时器（每2秒检测一次，比赛现场插拔手柄也能立即生效）
        self.hotplug_timer = QTimer(self.root)
        self.hotplug_timer.setInterval(2000)
        self.hotplug_timer.timeout.connect(self._check_joystick_hotplug)

        # 调用UI设置方法
        self.setup_ui()
        # 全部控件创建完成后首次进入全屏：
        # 父窗口首次 show 会自动显示在其创建时已存在的所有子控件（不会黑屏）。
        # 主窗口必须先去掉边框（FramelessWindowHint）：Windows 上带边框的顶层窗口
        # 执行 showFullScreen() 时不会真正铺满屏幕（frame 内缩约8像素），导致任务栏仍可见。
        self.root.setWindowFlags(
            self.root.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.root.showFullScreen()
        # 调用游戏手柄初始化方法
        self.init_gamepad()
        # 绑定ESC键用于退出程序
        self._bind_key("Escape", self.on_closing)
        # 绑定Ctrl+C用于退出程序
        self._bind_key("Ctrl+C", self.on_closing)
        # 绑定窗口关闭事件
        self.root.app_ref = self

    # ---------- 键盘快捷键绑定辅助方法 ----------
    def _bind_key(self, key, callback, parent=None):
        """把快捷键绑定到指定窗口（默认主窗口）。Qt 的 WindowShortcut 上下文：
        仅当该窗口获得焦点时生效——因此模态对话框（如结果窗口）内的快捷键
        必须绑定到对话框本身，否则对话框 exec() 期间主窗口失焦、快捷键不响应。"""
        sc = QShortcut(self.root if parent is None else parent)
        sc.setKey(QKeySequence(key))
        sc.activated.connect(callback)

    # ---------- 模态弹窗期间暂停/恢复手柄轮询 ----------
    def _pause_gamepad(self):
        """打开模态弹窗前暂停手柄轮询（可嵌套调用），避免弹窗期间误触发
        （与原 tkinter wait_window 阻塞行为一致）。同时置位 _dialog_open 标志：
        即使已有定时器事件进入队列、在 exec() 的嵌套事件循环里被派发，
        run_gamepad_input 也会直接返回，绝不在弹窗事件循环内泵取 SDL 消息。"""
        self._dialog_depth += 1
        self._dialog_open = True
        if getattr(self, 'gamepad_timer', None) is not None:
            self.gamepad_timer.stop()

    def _resume_gamepad(self):
        """模态弹窗关闭后恢复手柄轮询（可嵌套调用，仅最外层弹窗关闭时真正恢复）"""
        if self._dialog_depth > 0:
            self._dialog_depth -= 1
        if self._dialog_depth == 0:
            self._dialog_open = False
            if getattr(self, 'gamepad_timer', None) is not None:
                self.gamepad_timer.start()

    # ---------- 通用控件创建辅助方法 ----------
    def _make_label(self, parent, text, family, size, color='white', bg='black', bold=False, align=Qt.AlignmentFlag.AlignCenter):
        """创建与 tkinter 版外观一致的标签：指定底色、文字颜色、对齐方式。
        color 与 bg 同时传 None 时不设置样式，使用系统原生默认配色（用于常规弹窗）。"""
        label = QLabel(text, parent)
        font = QFont(family)
        font.setPointSize(size)
        font.setBold(bold)
        label.setFont(font)
        if color is not None and bg is not None:
            label.setStyleSheet(f"color: {color}; background-color: {bg};")
        label.setAlignment(align)
        return label

    def _make_button(self, parent, text, command, bordered=False):
        """创建与 tkinter 版外观一致的按钮：黑底灰字、灰色边框。
        默认 bordered=False 采用细边框（1px），与比赛结果窗口按钮风格统一；
        bordered=True 对应原版的 highlightthickness=3（3px高亮边框）"""
        border = "3px solid #555555" if bordered else "1px solid #555555"
        btn = QPushButton(text, parent)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: black;"
            f"  color: #555555;"
            f"  border: {border};"
            f"}}")
        btn.clicked.connect(command)
        return btn

    def _fill_with(self, frame, widget):
        """让 widget 填满 frame（等价于 pack(side=..., fill=BOTH, expand=True)）
        注意：必须在 addWidget 时给拉伸系数 1，否则 QBoxLayout 只给控件 sizeHint
        大小（如 100x30），多出的空间不会分配，导致标签没有撑满框架、黑屏看不到字。"""
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(widget, 1)

    # ---------- 配置文件 ----------
    def load_config(self):
        """加载配置文件。文件不存在或损坏时用默认值新建/重写。"""
        path = get_config_path()
        loaded = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except (json.JSONDecodeError, OSError):
                loaded = {}
        if not isinstance(loaded, dict):
            loaded = {}
        # 与默认值合并，缺失键用默认值补齐
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        for key in DEFAULT_CONFIG:
            if key in loaded:
                self.config[key] = loaded[key]
        # 补齐 joystick_buttons 中缺失的功能项
        if not isinstance(self.config["joystick_buttons"], dict):
            self.config["joystick_buttons"] = copy.deepcopy(DEFAULT_CONFIG["joystick_buttons"])
        for key in DEFAULT_CONFIG["joystick_buttons"]:
            if key not in self.config["joystick_buttons"]:
                self.config["joystick_buttons"][key] = copy.deepcopy(DEFAULT_CONFIG["joystick_buttons"][key])
        self.save_config()

    def save_config(self):
        """把当前配置写回文件。"""
        try:
            with open(get_config_path(), "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except OSError:
            pass

    # ================================================
    # 精确填满框架的自适应字体大小计算方法
    # 功能：用 QFontMetrics 精确测量指定文字在参考字号下的
    #       实际像素尺寸，反算出填满显示区域所需的字体大小，
    #       确保数字在宽度或高度上占满框架
    # 参数：relw - 框架相对宽度, relh - 框架相对高度,
    #       text - 要显示的文本, family - 字体名称,
    #       ref_size - 测量用的参考字号
    # ================================================
    def _calc_fill_font_size(self, relw, relh, text, family="Arial", ref_size=100):
        fw = int(self.screen_width * relw)
        fh = int(self.screen_height * relh)
        f = QFont(family)
        f.setPointSize(ref_size)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(text)
        th = fm.lineSpacing()
        scale = min(fw / tw, fh / th)
        return max(1, int(ref_size * scale))

    # ================================================
    # 选手名称自适应字号计算方法
    # 功能：根据两文本内容和显示区域的尺寸，
    #       计算出一个统一的字号，优先填满高度（85%），
    #       若较宽的名称超出框架宽度则等比缩小
    # 参数：name_a - 选手A名称, name_b - 选手B名称
    # ================================================
    def _calc_font_size(self, relw, relh, name_a, name_b):
        fw = int(self.screen_width * relw)
        fh = int(self.screen_height * relh)
        family = "黑体"
        # 以高度为基准，填满框架高度
        ref_font = QFont(family)
        ref_font.setPointSize(100)
        ref_h = QFontMetrics(ref_font).lineSpacing()
        font_size = max(1, int(fh / ref_h * 100))
        # 检查较宽的名称是否超出框架宽度
        font = QFont(family)
        font.setPointSize(font_size)
        fm = QFontMetrics(font)
        max_w = max(fm.horizontalAdvance(name_a), fm.horizontalAdvance(name_b))
        if max_w > fw:
            font_size = max(1, int(font_size * fw / max_w))
        return font_size

    # ================================================
    # 设置用户界面方法
    # 功能：创建所有UI元素并布局
    # ================================================
    def setup_ui(self):
        # 批量布局：创建期间只登记控件，全部创建完成后统一重排一次，
        # 避免每次 place() 都全量重排所有子控件（O(n^2)）。
        self.root.begin_batch()
        # 预计算得分和获胜局数的填满框架字号
        score_fill_size = self._calc_fill_font_size(0.41, 0.80, "99")#使用99这个最大二位数进行测试，计算出最大字号
        win_fill_size = self._calc_fill_font_size(0.07, 0.20, "4")#使用4这个最大局数进行测试，计算出最大字号
        # 预计算选手名称共用自适应字号
        player_font_size = self._calc_font_size(0.50, 0.20, self.player_a_name, self.player_b_name)

        # ====================左半边区域====================
        ## NO1 创建左边选手名称显示框架
        self.left_player_frame = QWidget(self.root)
        self.left_player_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左上角开始，宽度50%，高度20%
        self.root.place(self.left_player_frame, 0, 0, 0.50, 0.20)
        ### 创建左边选手名称标签，自适应字号填满框架高度，白字（原版 pack(side=BOTTOM)）
        self.left_player_label = self._make_label(
            self.left_player_frame, self.player_a_name, "黑体", player_font_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        ### 标签充满整个框架
        self._fill_with(self.left_player_frame, self.left_player_label)

        ## NO2 创建左边得分显示框架
        self.left_score_display_frame = QWidget(self.root)
        self.left_score_display_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距，上边距，宽度41%，高度80%
        self.root.place(self.left_score_display_frame, 0.00, 0.20, 0.41, 0.80)
        ### 创建左边得分标签，使用Arial字体，字号score_fill_size号，黑底白字，两位数显示（原版 pack(side=RIGHT)）
        self.left_score_label = self._make_label(
            self.left_score_display_frame, f"{self.score_a:02d}", "Arial", score_fill_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ### 标签靠右显示，充满整个框架
        self._fill_with(self.left_score_display_frame, self.left_score_label)

        ## NO3 创建左边获胜局数显示框架
        self.left_wins_frame = QWidget(self.root)
        self.left_wins_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距，上边距，宽度7%，高度20%
        self.root.place(self.left_wins_frame, 0.41, 0.20, 0.07, 0.20)
        ### 创建左边获胜局数标签，使用Arial字体，字号win_fill_size号，白字（原版 pack(side=RIGHT)）
        self.left_wins_label = self._make_label(
            self.left_wins_frame, f"{self.wins_a}", "Arial", win_fill_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ### 标签靠右显示，充满整个框架
        self._fill_with(self.left_wins_frame, self.left_wins_label)

        # ====================中间局数分隔符区域====================
        ## NO4 创建中间":"分隔符框架
        self.middle_colon_frame = QWidget(self.root)
        self.middle_colon_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：水平居中偏左2%，上边距，宽度4%，高度20%
        self.root.place(self.middle_colon_frame, 0.5 - 0.02, 0.20, 0.04, 0.20)
        ### 创建分隔符标签，使用Arial字体，字号自适应填满框架（原版 pack(side=TOP)）
        middle_colon_fill_size = self._calc_fill_font_size(0.04, 0.20, ":")
        self.middle_colon_label = self._make_label(
            self.middle_colon_frame, ":", "Arial", middle_colon_fill_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        ### 标签靠顶部显示，充满整个框架
        self._fill_with(self.middle_colon_frame, self.middle_colon_label)

        # ====================左边操作按钮====================
        ## NO5 创建左边"加分"按钮
        self.add_score_a_button = self._make_button(
            self.root, "加分<w>", self.add_score_a)
        ### 设置按钮位置：左边距，上边距，宽度6%，高度3%
        self.root.place(self.add_score_a_button, 0.41, 0.60, 0.06, 0.03)
        ### 绑定快捷键W到加分功能
        self._bind_key("W", self.add_score_a)

        ## NO6 创建左边"减分"按钮
        self.subtract_score_a_button = self._make_button(
            self.root, "减分<s>", self.subtract_score_a)
        ### 设置按钮位置：左边距，上边距，宽度6%，高度3%
        self.root.place(self.subtract_score_a_button, 0.41, 0.65, 0.06, 0.03)
        ### 绑定快捷键S到减分功能
        self._bind_key("S", self.subtract_score_a)

        # ====================右半边区域====================
        ## NO7 创建右边选手名称显示框架
        self.right_player_frame = QWidget(self.root)
        self.right_player_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距50%，上边距，宽度50%，高度20%
        self.root.place(self.right_player_frame, 0.50, 0, 0.50, 0.20)
        ### 创建右边选手名称标签，自适应字号填满框架高度，白字（原版 pack(side=BOTTOM)）
        self.right_player_label = self._make_label(
            self.right_player_frame, self.player_b_name, "黑体", player_font_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        ### 标签充满整个框架
        self._fill_with(self.right_player_frame, self.right_player_label)

        ## NO8 创建比分分隔符":"框架
        self.score_colon_frame = QWidget(self.root)
        self.score_colon_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：水平居中偏左3%，上边距，宽度6%，高度37%
        self.root.place(self.score_colon_frame, 0.5 - 0.03, 0.40, 0.06, 0.37)
        colon_fill_size = self._calc_fill_font_size(0.06, 0.37, ":")
        ### 创建比分分隔符标签，使用Arial字体，字号自适应，黑底白字（原版 pack(side=TOP)）
        self.score_colon_label = self._make_label(
            self.score_colon_frame, ":", "Arial", colon_fill_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        ### 标签靠顶部显示，充满整个框架
        self._fill_with(self.score_colon_frame, self.score_colon_label)

        ## NO9 创建右边得分显示框架
        self.right_score_display_frame = QWidget(self.root)
        self.right_score_display_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距59%，上边距，宽度41%，高度80%
        self.root.place(self.right_score_display_frame, 0.59, 0.20, 0.41, 0.80)
        ### 创建右边得分标签，使用Arial字体，字号score_fill_size号，黑底白字，两位数显示（原版 pack(side=LEFT)）
        self.right_score_label = self._make_label(
            self.right_score_display_frame, f"{self.score_b:02d}", "Arial", score_fill_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ### 标签靠左显示，充满整个框架
        self._fill_with(self.right_score_display_frame, self.right_score_label)

        ## NO10 创建右边获胜局数显示框架
        self.right_wins_frame = QWidget(self.root)
        self.right_wins_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距52%，上边距，宽度7%，高度20%
        self.root.place(self.right_wins_frame, 0.52, 0.20, 0.07, 0.20)
        ### 创建右边获胜局数标签，使用Arial字体，字号win_fill_size号，白字（原版 pack(side=LEFT)）
        self.right_wins_label = self._make_label(
            self.right_wins_frame, f"{self.wins_b}", "Arial", win_fill_size,
            'white', 'black', align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ### 标签靠左显示，充满整个框架
        self._fill_with(self.right_wins_frame, self.right_wins_label)

        # ====================右边操作按钮====================
        ## NO11 创建右边"加分"按钮
        self.add_score_b_button = self._make_button(
            self.root, "加分<o>", self.add_score_b)
        ### 设置按钮位置：左边距，上边距，宽度6%，高度3%
        self.root.place(self.add_score_b_button, 0.53, 0.60, 0.06, 0.03)
        ### 绑定快捷键O到加分功能
        self._bind_key("O", self.add_score_b)

        ## NO12 创建右边"减分"按钮
        self.subtract_score_b_button = self._make_button(
            self.root, "减分<l>", self.subtract_score_b)
        ### 设置按钮位置：左边距，上边距，宽度6%，高度3%
        self.root.place(self.subtract_score_b_button, 0.53, 0.65, 0.06, 0.03)
        ### 绑定快捷键L到减分功能
        self._bind_key("L", self.subtract_score_b)

        # ====================中间按钮区域====================
        ## NO13 创建"设置选手"按钮
        self.set_player_button = self._make_button(
            self.root, "设置选手<v>", self.set_player)
        ### 设置按钮位置：水平居中偏左3%，上边距，宽度6%，高度3%
        self.root.place(self.set_player_button, 0.5 - 0.03, 0.79, 0.06, 0.03)
        ### 绑定快捷键V到"设置选手"功能
        self._bind_key("V", self.set_player)

        ## NO14 创建"本局结束"按钮
        self.new_over_button = self._make_button(
            self.root, "本局结束<b>", self.win_a_or_b)
        ### 设置按钮位置：水平居中偏左3%，上边距，宽度6%，高度3%
        self.root.place(self.new_over_button, 0.5 - 0.03, 0.84, 0.06, 0.03)
        ### 绑定快捷键B到"本局结束"功能
        self._bind_key("B", self.win_a_or_b)

        ## NO15 创建"交换场地"按钮
        self.switch_button = self._make_button(
            self.root, "交换场地<n>", self.change_ends)
        ### 设置按钮位置：水平居中偏左3%，上边距，宽度6%，高度3%
        self.root.place(self.switch_button, 0.5 - 0.03, 0.89, 0.06, 0.03)
        ### 绑定快捷键N到交换场地功能
        self._bind_key("N", self.change_ends)

        ## NO16 创建"比赛结果"按钮
        self.result_button = self._make_button(
            self.root, "比赛结果<m>", self.show_match_result)
        ### 设置按钮位置：水平居中偏左3%，上边距，宽度6%，高度3%
        self.root.place(self.result_button, 0.5 - 0.03, 0.94, 0.06, 0.03)
        ### 绑定快捷键R到比赛结果功能
        self._bind_key("M", self.show_match_result)
        # 全部控件登记完成，统一重排一次
        self.root.end_batch()

    # ================================================
    # 游戏手柄初始化方法
    # 功能：初始化pygame和游戏手柄子系统，
    #       检测并连接手柄设备
    # ================================================
    def init_gamepad(self):
        # 只初始化用得到的手柄与事件队列子系统，避免 pygame.init() 顺带初始化
        # 混音器（音频）等用不到的模块：混音器初始化较慢，且无声卡时可能拖慢启动。
        # display.init() 仅建立事件队列，不会真的弹出窗口（开窗口要 set_mode 才发生）。
        pygame.display.init()
        pygame.joystick.init()
        self._connect_joystick()
        # 启动手柄热插拔检测（每2秒检测一次，现场插拔手柄也能立即生效）
        self.hotplug_timer.start()

    def _connect_joystick(self):
        """检测并连接第一个游戏手柄；未连接则置 None（仍可使用键盘操作）"""
        try:
            joystick_count = pygame.joystick.get_count()
        except pygame.error:
            self.joystick = None
            return
        if joystick_count > 0:
            try:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
                print(f"游戏手柄已连接: {self.joystick.get_name()} (共检测到 {joystick_count} 个手柄)")
            except pygame.error:
                self.joystick = None
        else:
            self.joystick = None
            print("未检测到游戏手柄，请使用键盘操作")

    def _check_joystick_hotplug(self):
        """定时检测手柄热插拔：新插入即连接，拔出即断开"""
        try:
            count = pygame.joystick.get_count()
        except pygame.error:
            return
        if count > 0:
            if self.joystick is None:
                self._connect_joystick()
        else:
            if self.joystick is not None:
                self.joystick = None
                print("游戏手柄已断开，请使用键盘操作")

    # ================================================
    # 游戏手柄输入处理方法
    # 功能：轮询处理游戏手柄按钮按下事件，
    #       根据配置文件中的按钮映射执行对应的计分操作
    # ================================================
    def run_gamepad_input(self):
        # 模态弹窗打开期间直接返回：绝不在弹窗 exec() 的嵌套事件循环内调用
        # pygame.event.get()，否则 SDL 的窗口消息泵会干扰 Qt 模态对话框，
        # 导致弹窗 exec() 偶发立刻返回（结果窗口一闪即关）。
        if self._dialog_open:
            return
        buttons = self.config["joystick_buttons"]
        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:
                for key, action in self._joystick_mappings:
                    if buttons[key].get("type") == "button" and buttons[key].get("value") == event.button:
                        action()
                        break
            elif event.type == pygame.JOYHATMOTION:
                hat_x, hat_y = event.value
                for key, action in self._joystick_mappings:
                    if buttons[key].get("type") == "hat" and buttons[key].get("value") == hat_y:
                        action()
                        break

    # ================================================
    # 选手A加分方法
    # 功能：将选手A当前得分加1并更新显示（加分前校验比分是否合法）
    # ================================================
    #加分：不加逻辑判断加分是否合理，这部分交给裁判。仅在保存比分的时候判断一下比分是否符合规则。
    def add_score_a(self):
        self._adjust_score('A', +1)

    # ================================================
    # 选手A减分方法
    # 功能：将选手A当前得分减1并更新显示（减分前校验比分是否合法）
    # ================================================
    #减分：不加逻辑判断减分是否合理，这部分交给裁判。仅在保存比分的时候判断一下比分是否符合规则。
    def subtract_score_a(self):
        self._adjust_score('A', -1)

    # ================================================
    # 选手B加分方法
    # 功能：将选手B当前得分加1并更新显示（加分前校验比分是否合法）
    # ================================================
    def add_score_b(self):
        self._adjust_score('B', +1)

    # ================================================
    # 选手B减分方法
    # 功能：将选手B当前得分减1并更新显示（减分前校验比分是否合法）
    # ================================================
    def subtract_score_b(self):
        self._adjust_score('B', -1)

    # ================================================
    # 通用计分调整方法
    # 功能：加分/减分的公共实现，消除四个加减分方法的重复代码
    # ================================================
    def _adjust_score(self, side, delta):
        """side: 'A' 或 'B'；delta: +1（加分）或 -1（减分）。
        校验规则与原四个加减分方法完全一致：
        加分——当前比分已是合法结果则不再加；
        减分——当前与减后均为合法结果则不再减；
        仅通过 is_valid_ongoing_score 校验后方更新比分并刷新显示。"""
        if side == 'A':
            score = self.score_a
            other = self.score_b
            label = self.left_score_label
            next_a, next_b = score + delta, other
        else:
            score = self.score_b
            other = self.score_a
            label = self.right_score_label
            next_a, next_b = other, score + delta

        if delta > 0:
            if self.is_valid_result(self.score_a, self.score_b):
                return
        else:
            if self.is_valid_result(self.score_a, self.score_b) and self.is_valid_result(next_a, next_b):
                return

        if self.is_valid_ongoing_score(next_a, next_b):
            new_score = score + delta
            if side == 'A':
                self.score_a = new_score
            else:
                self.score_b = new_score
            label.setText(f"{new_score:02d}")

    # ================================================
    # 本局结束方法
    # 功能：记录本局获胜方，更新局分、保存比分并重新开局
    # ================================================
    def win_a_or_b(self):
        if self.is_valid_result(self.score_a, self.score_b):
            #更新局分
            if self.score_a > self.score_b:
                #对局数量不做限制，愿意打几局就打几局。
                self.wins_a += 1
                self.left_wins_label.setText(f"{self.wins_a}")
            elif self.score_a < self.score_b:
                self.wins_b += 1
                self.right_wins_label.setText(f"{self.wins_b}")
            #保存当前小分和大分
            self.save_scores()
            # self.save_wins()
            #清除小分，重新开局
            self.score_a = 0
            self.left_score_label.setText(f"{self.score_a:02d}")
            self.score_b = 0
            self.right_score_label.setText(f"{self.score_b:02d}")

    # ================================================
    # 交换场地方法(选手、大小比分，都要换)
    # 功能：随着双方交换场地，记分牌上的选手姓名、得分和获胜局数，都要交换
    # ================================================
    def change_ends(self):
        #交换选手
        self.player_a_name, self.player_b_name = self.player_b_name, self.player_a_name
        self.left_player_label.setText(self.player_a_name)
        self.right_player_label.setText(self.player_b_name)
        #交换小分
        self.score_a, self.score_b = self.score_b, self.score_a
        self.left_score_label.setText(f"{self.score_a:02d}")
        self.right_score_label.setText(f"{self.score_b:02d}")
        #交换局分
        self.wins_a, self.wins_b = self.wins_b, self.wins_a
        self.left_wins_label.setText(f"{self.wins_a}")
        self.right_wins_label.setText(f"{self.wins_b}")

    # ================================================
    # 设置选手方法
    # 功能：弹出设置选手对话框，输入选手A/B姓名
    # ================================================
    def set_player(self):
        self.set_player_window = QDialog(self.root)
        self.set_player_window.setWindowTitle("设置选手")
        # 用浅色窗口底色覆盖主窗口的黑底样式，避免弹窗继承主窗口的黑色背景。
        # 关键：主窗口的 setStyleSheet("background-color: black;") 是 * 全局规则，
        # 会级联到本弹窗及其全部子控件；只写 "QDialog{...}" 只能覆盖弹窗本身，
        # 子控件（标签、输入框、按钮等）仍会命中黑底规则。
        # 因此这里同时覆盖 QDialog 本身及其全部后代子控件：白底黑字，保持常规 Windows 外观。
        self.set_player_window.setStyleSheet(
            "QDialog, QDialog * { background-color: white; color: black; }")
        window_width = 400
        window_height = 150
        x = (self.screen_width // 2) - (window_width // 2)
        y = (self.screen_height // 2) - (window_height // 2)
        self.set_player_window.setFixedSize(window_width, window_height)
        self.set_player_window.move(x, y)
        self.set_player_window.setModal(True)
        # 安装事件过滤器：吞掉 ESC，保持与 tkinter 版一致（设置选手弹窗按 ESC 不关闭）
        self.set_player_window.installEventFilter(_EscapeSwallowFilter(self.set_player_window))

        main_layout = QVBoxLayout(self.set_player_window)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(10)

        # 选手A/B姓名输入行（两行网格）
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        lb_player_a = QLabel("选手A：", self.set_player_window)
        lb_player_a.setFont(QFont("黑体", 14))
        grid.addWidget(lb_player_a, 0, 0)
        self.player_a_entry = QLineEdit(self.player_a_name, self.set_player_window)
        self.player_a_entry.setFont(QFont("黑体", 14))
        grid.addWidget(self.player_a_entry, 0, 1)

        lb_player_b = QLabel("选手B：", self.set_player_window)
        lb_player_b.setFont(QFont("黑体", 14))
        grid.addWidget(lb_player_b, 1, 0)
        self.player_b_entry = QLineEdit(self.player_b_name, self.set_player_window)
        self.player_b_entry.setFont(QFont("黑体", 14))
        grid.addWidget(self.player_b_entry, 1, 1)

        grid.setColumnStretch(1, 1)
        main_layout.addLayout(grid)

        # 确定按钮
        self.set_player_window.confirm_button = QPushButton("确定", self.set_player_window)
        self.set_player_window.confirm_button.setFont(QFont("黑体", 14))
        self.set_player_window.confirm_button.clicked.connect(self.confirm_player_names)
        main_layout.addWidget(
            self.set_player_window.confirm_button,
            alignment=Qt.AlignmentFlag.AlignCenter)

        # 模态弹窗期间暂停手柄轮询（与原 tkinter wait_window 阻塞行为一致）
        self._pause_gamepad()
        self.set_player_window.exec()
        self._resume_gamepad()

    # ================================================
    # 确认设置选手方法
    # 功能：读取输入框的选手姓名，保存配置，清零积分并新建计分文件
    # ================================================
    def confirm_player_names(self):
        player_a = self.player_a_entry.text()
        player_b = self.player_b_entry.text()
        # if not {self.player_a_name,self.player_b_name} == {player_a,player_b}:
        #保存上一对选手大分
        if self.wins_a or self.wins_b:
            self.save_wins()
        self.player_a_name = player_a
        self.player_b_name = player_b
        # 更新配置文件中的选手姓名
        self.config["player_a_name"] = self.player_a_name
        self.config["player_b_name"] = self.player_b_name
        self.save_config()
        player_font_size = self._calc_font_size(0.5, 0.2, self.player_a_name, self.player_b_name)
        self.left_player_label.setText(self.player_a_name)
        self.left_player_label.setFont(QFont("黑体", player_font_size))
        self.right_player_label.setText(self.player_b_name)
        self.right_player_label.setFont(QFont("黑体", player_font_size))

        # 新建计分文件（文件名+日期+时间）
        now = datetime.now()
        filename = os.path.join(get_base_dir(), f"Score_IndividualEvents_{self.player_a_name}_{self.player_b_name}_{now.strftime('%Y%m%d_%H%M%S')}.txt")
        self.current_score_file = filename

        #各种积分清零
        self.score_a = 0
        self.score_b = 0
        self.wins_a = 0
        self.wins_b = 0
        self.left_score_label.setText(f"{self.score_a:02d}")
        self.right_score_label.setText(f"{self.score_b:02d}")
        self.left_wins_label.setText(f"{self.wins_a}")
        self.right_wins_label.setText(f"{self.wins_b}")

        self.set_player_window.accept()

    # ================================================
    # 判断一局11分制乒乓球比赛的【过程中】出现的比分是否合法
    # 功能：校验比分是否合理，包含负分、分差、11分规则、10平后领先2分规则
    # ================================================
    def is_valid_ongoing_score(self, a: int, b: int) -> bool:
        """
        判断乒乓球11分制比赛过程中的实时比分是否合法
        """
        if a < 0 or b < 0:
            return False

        max_score = max(a, b)
        min_score = min(a, b)

        # 规则1: 比分不超过11时，任何比分都合法（11平及之前的任意比分均可出现）
        if max_score <= 11:
            return True
        # 规则2: 超过11分后，分差须不超过2分（10平后须领先2分，如 12:11、13:12 等）
        return min_score >= max_score - 2

    # ================================================
    # 判断一局11分制乒乓球比赛的【最终结果】比分是否合法
    # 功能：校验比分是否合理，包含负分、分差、11分规则、10平后领先2分规则
    # ================================================
    def is_valid_result(self, a: int, b: int) -> bool:
        """
        判断一局11分制乒乓球比赛的最终比分结果是否符合规则。

        参数:
            a: 选手A的得分
            b: 选手B的得分

        返回:
            如果比分合法则返回True，否则返回False。
        """
        # 1. 比分不能为负数
        if a < 0 or b < 0:
            # self.show_info("提示", "分数应大于0，请改正。")
            return False

        max_score = max(a, b)
        diff = abs(a-b)

        # 一方获胜，分至少为11
        if max_score >= 11 and diff >= 2:#本条件可能出现15:12这种比分。但是有is_valid_ongoing_score（）把关，就出现不了了。
            return True
        else:
            # self.show_info("提示", "此局未结束，请检查。")
            return False

    # ================================================
    # 保存本场比赛小分方法
    # 功能：将本局比分记录保存到文件
    # ================================================
    def _ensure_score_file(self):
        """确保当前计分文件已创建；未创建时按日期时间生成新文件名"""
        if self.current_score_file is None:
            now = datetime.now()
            self.current_score_file = os.path.join(
                get_base_dir(),
                f"Score_IndividualEvents_{self.player_a_name}_{self.player_b_name}_{now.strftime('%Y%m%d_%H%M%S')}.txt")
        return self.current_score_file

    def save_scores(self):
        #判断比分是否合理，已经在self.win_a_or_b()
        self._ensure_score_file()
        with open(self.current_score_file, "a") as file:
            file.write(f"保存小分,{self.player_a_name}:{self.player_b_name},{self.score_a}:{self.score_b}\n")

    # ================================================
    # 保存本场比赛大分方法
    # 功能：将选手局分（大分）记录保存到文件
    # ================================================
    def save_wins(self):
        self._ensure_score_file()
        with open(self.current_score_file, "a") as file:
            file.write(f"保存大分,{self.player_a_name}:{self.player_b_name},{self.wins_a}:{self.wins_b}\n")

    # ---------- 解析计分文件 ----------
    def _parse_score_file(self, filepath):
        """解析计分文件，返回 (player_a, player_b, wins_a, wins_b, small_scores)
        若文件不存在或为空，player_a 返回 None"""
        lines = None
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    lines = f.readlines()
                break
            except (UnicodeDecodeError, FileNotFoundError):
                continue
        if lines is None:
            return None, None, 0, 0, []

        if not lines:
            return None, None, 0, 0, []

        # 用字典记录每位选手的各局小分
        # key: 选手名, value: 该选手各局得分的列表（按行序排列）
        player_scores = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("保存小分"):
                parts = line.split(',')
                if len(parts) >= 3:
                    score_part = parts[2].strip()
                    name_part = parts[1].strip()
                    try:
                        sa_str, sb_str = score_part.split(':')
                        pa, pb = name_part.split(':')
                        pa = pa.strip()
                        pb = pb.strip()
                        sa = int(sa_str)
                        sb = int(sb_str)
                        # 把每局的得分记到对应选手名下
                        player_scores.setdefault(pa, []).append(sa)
                        player_scores.setdefault(pb, []).append(sb)
                    except:
                        pass

        if not player_scores:
            return None, None, 0, 0, []

        # 取出两位选手名（保持首次出现的顺序）和各自的分数列表
        names = list(player_scores.keys())
        if len(names) < 2:
            return None, None, 0, 0, []

        player_a = names[0]
        player_b = names[1]
        scores_a = player_scores[player_a]
        scores_b = player_scores[player_b]

        # 组装小分列表：每局为 (A分, B分)
        small_scores = list(zip(scores_a, scores_b))

        # 大分完全从小分计算：每局小分中分数高的一方赢得该局
        wins_a = sum(1 for sa, sb in small_scores if sa > sb)
        wins_b = sum(1 for sa, sb in small_scores if sb > sa)

        return player_a, player_b, wins_a, wins_b, small_scores

    # ---------- 比赛结果全屏展示 ----------
    def show_match_result(self, filepath=None):
        """全屏显示比赛结果，黑底白字，包含大分、局数和小分（两行：A分/B分）
        若传入 filepath，则显示指定文件的历史数据；
        若未传入 filepath，则使用当前计分文件。
        所有数据一律从文件读取，大分从小分计算，不触碰内存变量。
        仅显示已完成的局，当前未打完的局不显示。"""
        # 按钮点击时 QPushButton.clicked 信号会传入 checked (bool)，
        # 非字符串参数统一视为"未指定文件"
        if not isinstance(filepath, str):
            filepath = None
        if filepath is None:
            filepath = self.current_score_file

        if filepath is None:
            # 尚未进行任何比赛：显示当前对手，大分和小分全为0
            player_a = self.player_a_name
            player_b = self.player_b_name
            wins_a, wins_b = 0, 0
            small_scores = [(0, 0)]
        else:
            player_a, player_b, wins_a, wins_b, small_scores = self._parse_score_file(filepath)

            if player_a is None:
                # 计分文件不存在：显示当前对手，大分和小分全为0
                player_a = self.player_a_name
                player_b = self.player_b_name

            if not small_scores:
                # 文件中没有局分记录：补充一局0:0
                player_a = self.player_a_name
                player_b = self.player_b_name
                wins_a, wins_b = 0, 0
                small_scores = [(0, 0)]

        self._create_result_window(player_a, player_b, wins_a, wins_b, small_scores, filepath)

    # ---------- 创建结果展示窗口 ----------
    def _create_result_window(self, player_a, player_b, wins_a, wins_b, small_scores, filepath):
        """全屏显示比赛结果，黑底白字，包含大分、局数和小分（两行：A分/B分）"""

        n = len(small_scores)   # 实际局数（最多7局）
        if n > 7:
            n = 7
            small_scores = small_scores[-7:]

        # 创建全屏窗口
        result_win = PlacedDialog(self.root)
        result_win.setWindowTitle("比赛结果")
        # 去掉窗口边框（无边框窗口）：Qt 在 Windows 上对带边框的 QDialog 执行
        # showFullScreen() 时，会把对话框框架居中，导致客户区整体左移约8像素——
        # 左侧内容（如选手名的首字）被裁掉，右侧露出8像素空隙。
        # 设为无边框后，客户区才能精确对齐屏幕 (0,0)，铺满整个屏幕。
        result_win.setWindowFlags(
            result_win.windowFlags() | Qt.WindowType.FramelessWindowHint)
        result_win.setStyleSheet("background-color: black;")
        result_win.setModal(True)

        # ---------- 1. 顶部大比分区域（0~40%高度） ----------
        top_relh = 0.40
        #选手字体大小测算和显示
        labels_top_player_font_size = self._calc_font_size(0.35, top_relh, player_a, player_b)
        lb_player_a = self._make_label(result_win, player_a, "黑体", labels_top_player_font_size, 'white', 'black')
        result_win.place(lb_player_a, 0.00, 0.00, 0.35, top_relh)
        lb_player_b = self._make_label(result_win, player_b, "黑体", labels_top_player_font_size, 'white', 'black')
        result_win.place(lb_player_b, 0.65, 0.00, 0.35, top_relh)
        #局分字体大小测算和显示
        labels_top_win_font_size = self._calc_font_size(0.12, top_relh, str(wins_a), str(wins_b))
        lb_wins_a = self._make_label(result_win, str(wins_a), "黑体", labels_top_win_font_size, 'white', 'black')
        result_win.place(lb_wins_a, 0.35, 0.00, 0.12, top_relh)
        lb_wins_b = self._make_label(result_win, str(wins_b), "黑体", labels_top_win_font_size, 'white', 'black')
        result_win.place(lb_wins_b, 0.53, 0.00, 0.12, top_relh)
        #冒号字体大小测算和显示
        labels_top_colon_font_size = self._calc_fill_font_size(0.06, top_relh, ":")
        lb_colon = self._make_label(result_win, ":", "Arial", labels_top_colon_font_size, 'white', 'black')
        result_win.place(lb_colon, 0.47, 0.00, 0.06, top_relh)

        # 关闭按钮 + 历史数据按钮（右上角）
        history_btn = self._make_button(
            result_win, "历史数据<h>", lambda: self._show_history_dialog(result_win),
            bordered=False)
        result_win.place(history_btn, 0.82, 0.01, 0.06, 0.03)
        ### 绑定快捷键H到"历史数据"功能（绑定到结果窗口本身：模态对话框期间主窗口
        ### 失焦，绑定到主窗口的快捷键不会响应；且需传入 result_win 以便刷新同一窗口）
        self._bind_key("H", lambda: self._show_history_dialog(result_win), parent=result_win)

        close_btn = self._make_button(
            result_win, "返回<r>", result_win.accept, bordered=False)
        result_win.place(close_btn, 0.93, 0.01, 0.06, 0.03)
        ### 绑定快捷键R到"返回"功能
        self._bind_key("R", result_win.accept, parent=result_win)

        # ---------- 2. 左侧下方选手名（宽度30%，60%~80% 和 80%~100%） ----------
        left_name_font_size = self._calc_font_size(0.20, 0.30, player_a, player_b)
        lb_a = self._make_label(result_win, player_a, "宋体", left_name_font_size, 'white', 'black')
        result_win.place(lb_a, 0.0, 0.60, 0.30, 0.20)

        lb_b = self._make_label(result_win, player_b, "宋体", left_name_font_size, 'white', 'black')
        result_win.place(lb_b, 0.0, 0.80, 0.30, 0.20)

        # ---------- 3. 右侧局数标签（70%宽度，14%高度） ----------
        frame_round = QWidget(result_win)
        frame_round.setStyleSheet("background-color: black;")
        result_win.place(frame_round, 0.30, 0.46, 0.70, 0.14)
        grid_round = QGridLayout(frame_round)
        grid_round.setContentsMargins(0, 0, 0, 0)
        self._fill_round_labels(grid_round, n)

        # ---------- 4. 右侧小分显示（70%宽度，50%高度） ----------
        frame_scores = QWidget(result_win)
        frame_scores.setStyleSheet("background-color: black;")
        result_win.place(frame_scores, 0.30, 0.60, 0.70, 0.40)
        grid_scores = QGridLayout(frame_scores)
        grid_scores.setContentsMargins(0, 0, 0, 0)
        self._fill_score_grid(grid_scores, small_scores, n)

        # ---- 保存动态控件的引用，供 _refresh_result_window 更新 ----
        result_win._top_player_a = lb_player_a
        result_win._top_player_b = lb_player_b
        result_win._top_wins_a = lb_wins_a
        result_win._top_wins_b = lb_wins_b
        result_win._left_player_a = lb_a
        result_win._left_player_b = lb_b
        result_win._grid_round = grid_round
        result_win._grid_scores = grid_scores

        # ESC键关闭：QDialog 默认按 ESC 触发 reject，等效于原版的 ESC 销毁窗口

        # 模态弹窗期间暂停手柄轮询（与原 tkinter wait_window 阻塞行为一致）
        self._pause_gamepad()
        result_win.showFullScreen()
        result_win.activateWindow()
        result_win.exec()
        self._resume_gamepad()

    # ---------- 填充局数标签 ----------
    def _fill_round_labels(self, grid_round, n):
        """在 grid_round(QGridLayout) 中重新创建第1局~第n局的标签"""
        # 先清除旧内容
        while grid_round.count():
            item = grid_round.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # 先清除所有旧列的权重（最多支持7列），防止历史数据刷新时
        # 上一次显示的列权重残留，导致分数列与局数标签列不对齐
        for i in range(7):
            grid_round.setColumnStretch(i, 1 if i < n else 0)
        grid_round.setRowStretch(0, 1)
        grid_round.setSpacing(4)

        round_font_size = self._calc_fill_font_size(0.70 * 1.0 / 7, 0.14, "第5局", family="宋体")

        for i in range(n):
            lb = self._make_label(
                grid_round.parentWidget(),
                f"第{i+1}局",
                "宋体", min(round_font_size, 100),
                'white', 'black')
            grid_round.addWidget(lb, 0, i)

    # ---------- 填充小分网格 ----------
    def _fill_score_grid(self, grid_scores, small_scores, n):
        """在 grid_scores(QGridLayout) 中重新创建两行小分（A分/B分）"""
        # 先清除旧内容
        while grid_scores.count():
            item = grid_scores.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # 先清除所有旧列的权重（最多支持7列），防止历史数据刷新时
        # 上一次显示的列权重残留，导致分数列与局数标签列不对齐
        for i in range(7):
            grid_scores.setColumnStretch(i, 1 if i < n else 0)
        for r in range(2):
            grid_scores.setRowStretch(r, 1)
        grid_scores.setSpacing(4)

        cell_width = 0.70 / n
        cell_height = 0.40 / 2
        score_font_size = self._calc_fill_font_size(cell_width, cell_height, "99", family="宋体")

        # 每局中，输掉该局的选手的该局小分用灰色显示（黑底上可读的中灰）
        LOSER_COLOR = '#A0A0A0'

        # A小分
        for i in range(n):
            if i < len(small_scores):
                text = str(small_scores[i][0])
                sa, sb = small_scores[i]
                color = LOSER_COLOR if sb > sa else 'white'
            else:
                text = "-"
                color = 'white'
            lb = self._make_label(
                grid_scores.parentWidget(), text, "Arial", score_font_size,
                color, 'black')
            grid_scores.addWidget(lb, 0, i)

        # B小分
        for i in range(n):
            if i < len(small_scores):
                text = str(small_scores[i][1])
                sa, sb = small_scores[i]
                color = LOSER_COLOR if sa > sb else 'white'
            else:
                text = "-"
                color = 'white'
            lb = self._make_label(
                grid_scores.parentWidget(), text, "Arial", score_font_size,
                color, 'black')
            grid_scores.addWidget(lb, 1, i)

    # ---------- 刷新结果窗口内容（用于查看历史数据，不改变程序状态） ----------
    def _refresh_result_window(self, result_win, player_a, player_b, wins_a, wins_b, small_scores):
        """在不销毁窗口的前提下，用新数据更新结果窗口的全部动态内容"""
        n = len(small_scores)
        if n > 7:
            n = 7
            small_scores = small_scores[-7:]

        top_relh = 0.40

        # 更新顶部选手名
        font_size = self._calc_font_size(0.35, top_relh, player_a, player_b)
        result_win._top_player_a.setText(player_a)
        result_win._top_player_a.setFont(QFont("黑体", font_size))
        result_win._top_player_b.setText(player_b)
        result_win._top_player_b.setFont(QFont("黑体", font_size))

        # 更新顶部大分
        win_font_size = self._calc_font_size(0.12, top_relh, str(wins_a), str(wins_b))
        result_win._top_wins_a.setText(str(wins_a))
        result_win._top_wins_a.setFont(QFont("黑体", win_font_size))
        result_win._top_wins_b.setText(str(wins_b))
        result_win._top_wins_b.setFont(QFont("黑体", win_font_size))

        # 更新左侧选手名
        left_font_size = self._calc_font_size(0.20, 0.30, player_a, player_b)
        result_win._left_player_a.setText(player_a)
        result_win._left_player_a.setFont(QFont("宋体", left_font_size))
        result_win._left_player_b.setText(player_b)
        result_win._left_player_b.setFont(QFont("宋体", left_font_size))

        # 重建局数标签和小分网格
        self._fill_round_labels(result_win._grid_round, n)
        self._fill_score_grid(result_win._grid_scores, small_scores, n)

    # ---------- 历史数据浏览 ----------
    def _show_history_dialog(self, current_result_win=None):
        """弹出文件浏览对话框，让用户指定计分文件，然后将历史数据刷新到当前结果窗口。
        历史数据的展示仅为临时查看，不会改变程序当前设置的选手、大分和小分。
        PySide6 版说明：QFileDialog 使用 Windows 系统原生文件对话框，
        在全屏模式下浏览/取消均正常，不再需要 tkinter 版"退出全屏再恢复"的补丁。"""
        parent = current_result_win if current_result_win is not None else self.root
        # 模态弹窗（结果窗口）打开期间手柄轮询已暂停；这里再暂停一层，
        # 覆盖"没有结果窗口而直接调用"的边界情况，保证 QFileDialog 原生对话框期间
        # 不会泵取 SDL 消息（QFileDialog 自带的嵌套事件循环里不应调用 pygame.event.get()）。
        self._pause_gamepad()
        try:
            while True:
                chosen_path, _ = QFileDialog.getOpenFileName(
                    parent,
                    "选择历史比赛数据文件",
                    ".",
                    "计分文件 (Score_IndividualEvents_*.txt);;文本文件 (*.txt);;所有文件 (*.*)")

                if not chosen_path:
                    return  # 用户取消了选择

                # 验证文件名：用"_"分割，第二个词必须是"IndividualEvents"
                basename = os.path.basename(chosen_path)
                parts = basename.split('_')
                if len(parts) < 2 or parts[1] != "IndividualEvents":
                    self.show_info("提示", "所选文件不是本程序的计分文件，请重新选择。", parent)
                    continue

                # 读取选中文件
                pa, pb, wa, wb, ss = self._parse_score_file(chosen_path)
                if pa is None or not ss:
                    self.show_info("提示", "无法读取选中的文件或文件中没有局分记录。", parent)
                    return

                # 将历史数据刷新到当前结果窗口（不关闭窗口，不改变程序状态）
                if current_result_win is not None:
                    self._refresh_result_window(current_result_win, pa, pb, wa, wb, ss)
                else:
                    self._create_result_window(pa, pb, wa, wb, ss, chosen_path)
                return
        finally:
            self._resume_gamepad()

    # ---------- 版权及退出 ----------
    def show_copyright(self, is_exit=False):
        copyright_window = QDialog(self.root)
        copyright_window.setWindowTitle("版权信息")
        # 用浅色窗口底色覆盖主窗口的黑底样式，避免弹窗继承主窗口的黑色背景。
        # 关键：主窗口的 setStyleSheet("background-color: black;") 是 * 全局规则，
        # 会级联到本弹窗及其全部子控件；只写 "QDialog{...}" 只能覆盖弹窗本身，
        # 子控件（标签、按钮等）仍会命中黑底规则。
        # 因此这里同时覆盖 QDialog 本身及其全部后代子控件：白底黑字，保持常规 Windows 外观。
        copyright_window.setStyleSheet(
            "QDialog, QDialog * { background-color: white; color: black; }")

        window_width = 550
        window_height = 300
        x = (self.screen_width // 2) - (window_width // 2)
        y = (self.screen_height // 2) - (window_height // 2)
        copyright_window.setFixedSize(window_width, window_height)
        copyright_window.move(x, y)
        copyright_window.setModal(True)

        text = "版权所有 © 2026 北京市政总院乒协\n\n开发者：姜恒 jiangheng010@qq.com\n\n开发日期：2026年7月\n\n程序版本：V20260802\n\n在不修改代码的前提下，本程序可免费使用"

        label = self._make_label(copyright_window, text, "黑体", 14, None, None)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        close_btn = QPushButton("关闭", copyright_window)
        close_btn.setFont(QFont("黑体", 12))
        close_btn.clicked.connect(copyright_window.accept)

        layout = QVBoxLayout(copyright_window)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.addWidget(label, 1)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # 2秒后自动关闭；期间任意按键/点击则取消自动关闭，需手动关闭窗口
        auto_close_timer = QTimer(copyright_window)
        auto_close_timer.setSingleShot(True)
        auto_close_timer.timeout.connect(copyright_window.accept)
        auto_close_timer.start(2000)

        def cancel_auto_close():
            if auto_close_timer.isActive():
                auto_close_timer.stop()

        # 安装事件过滤器：任意按键/点击取消自动关闭；吞掉 ESC 防止直接关闭（与原版行为一致）
        filter_obj = _CopyrightEventFilter(cancel_auto_close)
        copyright_window._filter_obj = filter_obj  # 保存引用，防止被垃圾回收
        copyright_window.installEventFilter(filter_obj)
        close_btn.installEventFilter(filter_obj)
        label.installEventFilter(filter_obj)

        # 模态弹窗期间暂停手柄轮询（与原 tkinter wait_window 阻塞行为一致）
        self._pause_gamepad()
        copyright_window.exec()
        self._resume_gamepad()

        self.root.activateWindow()

    # ---------- 自定义提示对话框 ----------
    def show_info(self, title: str, message: str, parent=None):
        """显示一个自定义的提示对话框，确保按钮居中。常规Windows配色（白底黑字）。"""
        if parent is None:
            parent = self.root
        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        # 覆盖主窗口的黑底样式：白底黑字，保持常规 Windows 外观
        dialog.setStyleSheet(
            "QDialog, QDialog * { background-color: white; color: black; }")
        dialog.setModal(True)

        # 主体框架，加内边距
        frm = QWidget(dialog)
        frm_layout = QVBoxLayout(frm)
        frm_layout.setContentsMargins(30, 20, 30, 20)
        frm_layout.setSpacing(15)

        # 提示文字
        lbl = QLabel(message, frm)
        lbl.setFont(QFont("Microsoft YaHei", 12))
        lbl.setWordWrap(True)
        frm_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        # 确定按钮（居中）
        btn = QPushButton("确定", frm)
        btn.setFont(QFont("Microsoft YaHei", 10))
        btn.setFixedWidth(100)
        btn.clicked.connect(dialog.accept)
        btn.setDefault(True)
        frm_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(frm)

        # 3秒后自动关闭（不点击确定时）
        auto_close_timer = QTimer(dialog)
        auto_close_timer.setSingleShot(True)
        auto_close_timer.timeout.connect(dialog.accept)
        auto_close_timer.start(3000)

        # 等窗口尺寸计算完毕后再居中
        dialog.adjustSize()
        pc = parent.frameGeometry().center()
        dialog.move(pc.x() - dialog.width() // 2, pc.y() - dialog.height() // 2)

        btn.setFocus()

        # 模态弹窗期间暂停手柄轮询（与原 tkinter wait_window 阻塞行为一致）
        self._pause_gamepad()
        dialog.exec()
        self._resume_gamepad()

    def on_closing(self):
        # 关闭前处理当前局的小分与大分，防止关闭程序导致数据丢失。
        # 小分符合比赛结果（一方≥11且领先≥2）→ 完整一局：保存小分、更新大分并保存、小分清零；
        # 小分不符合比赛结果 → 该局未完成：保存小分、不清零、不更新大分、仅保存现有大分。
        # 防止重复触发（ESC、Ctrl+C、Alt+F4 可能连续触发）
        if self._closing:
            return
        self._closing = True

        # 退出前暂停手柄轮询
        self._pause_gamepad()

        max_score = max(self.score_a, self.score_b)
        diff = abs(self.score_a - self.score_b)
        if max_score >= 11 and diff >= 2:
            # 完整一局，更新大分
            if self.score_a > self.score_b:
                self.wins_a += 1
            else:
                self.wins_b += 1
            self.save_scores()
            self.save_wins()
            self.score_a = 0
            self.score_b = 0
        else:
            # 该局未完成
            if self.score_a or self.score_b:
                self.save_scores()
            if self.wins_a or self.wins_b:
                self.save_wins()
        self.root.hide()
        self.show_copyright(is_exit=True)
        self.running = False
        QApplication.instance().quit()

# ================================================
# 程序主入口
# ================================================
if __name__ == "__main__":
    # 创建Qt应用
    app = QApplication(sys.argv)
    app.setApplicationName("乒乓球比赛计分程序")
    # 创建主窗口（默认隐藏，避免创建时的默认小窗口闪现）
    root = MainWidget()
    # 创建计分应用对象（内部会进入全屏模式并创建全部控件）
    scoring_app = PingPongScoringApp(root)
    # 启动游戏手柄轮询定时器（30ms，约33Hz）
    scoring_app.gamepad_timer.start(30)
    # 主事件循环：Qt 自动处理界面刷新、键盘快捷键、对话框与手柄轮询
    code = app.exec()
    pygame.quit()
    sys.exit(code)
