# ================================================
# 乒乓球团体比赛计分程序 - PingPang_TeamEvents_for_joystick_V95_Qt_20260806.py
# 功能：实时记录和显示选手的比赛分数和获胜局数
# 支持：键盘快捷键操作、全屏模式切换、游戏手柄输入
# ================================================
# 版权所有 © 2026 北京市市政工程设计研究总院有限公司
# 开发者：姜恒
# 开发日期：2026年8月
# ================================================
# 本版本说明：由 tkinter 版迁移至 PySide6(Qt6)。
#   相比 tkinter 版，PySide6 的 QFileDialog 使用 Windows 系统原生文件对话框，
#   在全屏模式下浏览/取消历史计分文件均正常、顺畅，不再需要"退出全屏再恢复"的补丁。
# ================================================

# 导入PySide6库，用于创建图形用户界面
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QDialog, QRadioButton,
    QButtonGroup, QLineEdit, QMessageBox, QFileDialog, QFrame, QGridLayout,
    QVBoxLayout, QHBoxLayout,
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


class _HistoryFileError(Exception):
    """历史计分数据文件解析错误（如缺少"赛制信息"行，无法按赛制解析）。"""
    pass


# ================================================
# 配置文件：Config_TeamEvents.json
# ================================================
CONFIG_FILE_NAME = "Config_TeamEvents.json"

# 程序默认配置（首次运行无配置文件时按此生成）
DEFAULT_CONFIG = {
    "match_format": "五场三胜制",      # 赛制
    "match_type": "男单",              # 比赛类型
    "team_a_name": "队伍A",            # 队伍A名称
    "team_b_name": "队伍B",            # 队伍B名称
    "player_a_name": "选手A",          # 选手A姓名
    "player_b_name": "选手B",          # 选手B姓名
    "games_per_match": "三局二胜",     # 每场局数：三局二胜/五局三胜/七局四胜
    "joystick_buttons": {              # 手柄配置
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


def read_text_auto_encoding(filepath):
    """以 utf-8 → gbk → gb18030 的顺序尝试读取文本文件，返回全部内容。
    计分数据文件写端使用系统默认编码（中文 Windows 下为 GBK），
    读取时先试 UTF-8 可兼容外部编辑器保存的 UTF-8 文件、以及跨电脑拷贝的文件；
    三种编码均失败时抛出 OSError，由调用方的 try/except 处理。"""
    encodings = ("utf-8", "gbk", "gb18030")
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    raise OSError(f"无法以 {', '.join(encodings)} 读取文件: {filepath}")


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

    def place(self, widget, relx, rely, relw, relh):
        """登记一个控件及其相对位置并立即应用一次"""
        self._items.append((widget, relx, rely, relw, relh))
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
#       原 tkinter 版在设置弹窗中按 ESC 无任何效果（grab_set 屏蔽了根窗口绑定），
#       这里保持一致：设置弹窗按 ESC 不关闭、不退出。
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
                icon_path = os.path.join(sys._MEIPASS, 'TeamEvents.ico')
            else:
                icon_path = 'TeamEvents.ico'
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

        # 初始化队伍名称变量（从配置文件读取）
        self.team_a_name = self.config["team_a_name"]  # 队伍A名称
        self.team_b_name = self.config["team_b_name"]  # 队伍B名称

        # 初始化选手名称变量（从配置文件读取）
        self.player_a_name = self.config["player_a_name"]  # 选手A名称
        self.player_b_name = self.config["player_b_name"]  # 选手B名称

        # 初始化比分变量
        self.score_a = 0  # 当前比赛选手A的得分
        self.score_b = 0  # 当前比赛选手B的得分

        # 初始化获胜局数变量
        self.wins_a = 0  # 当前比赛选手A的获胜局数
        self.wins_b = 0  # 当前比赛选手B的获胜局数

        # 初始化队伍大分变量
        self.team_score_a = 0  # 队伍A的团队大分
        self.team_score_b = 0  # 队伍B的团队大分

        # 计分文件路径（初始为None，首次保存时生成文件名）
        self.current_score_file = None

        # 比赛赛制（从配置文件读取）
        # 兼容旧版：若配置里存的是显示文本"十五局八胜制"，统一转成内部常量"15局8胜制"
        self.match_format = self.config["match_format"]
        if self.match_format == "十五局八胜制":
            self.match_format = "15局8胜制"

        # 每场局数（从配置文件读取）：三局二胜/五局三胜/七局四胜
        self.games_per_match = self.config["games_per_match"]

        # 比赛类型（从配置文件读取）
        self.match_type = self.config["match_type"]

        # 游戏手柄对象（初始化为None）
        self.joystick = None

        # 程序运行标志
        self.running = True
        # 退出流程防重复标志
        self._closing = False
        # 模态弹窗标志：为 True 时 run_gamepad_input 直接返回、不泵取 SDL 事件。
        # 原因：QTimer.stop() 只能阻止后续触发，已进入事件队列的定时器事件仍会在
        # 弹窗 exec() 的嵌套事件循环里被派发，此时 pygame.event.get() 的 SDL 窗口
        # 消息泵会干扰 Qt 模态对话框，导致 exec() 立刻返回（结果窗口偶发一闪即关）。
        self._dialog_open = False

        # 游戏手柄轮询定时器（30ms，约33Hz；打开模态弹窗时暂停，与原 wait_window 阻塞行为一致）
        self.gamepad_timer = QTimer(self.root)
        self.gamepad_timer.setInterval(30)
        self.gamepad_timer.timeout.connect(self.run_gamepad_input)

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
    def _bind_key(self, key, callback):
        """把快捷键绑定到主窗口（Qt 的 WindowShortcut 上下文：主窗口获得焦点时生效）"""
        sc = QShortcut(self.root)
        sc.setKey(QKeySequence(key))
        sc.activated.connect(callback)

    # ---------- 模态弹窗期间暂停/恢复手柄轮询 ----------
    def _pause_gamepad(self):
        """打开模态弹窗前暂停手柄轮询，避免弹窗期间误触发（与原 tkinter wait_window 阻塞行为一致）。
        同时置位 _dialog_open 标志：即使已有定时器事件进入队列、在 exec() 的嵌套事件循环
        里被派发，run_gamepad_input 也会直接返回，绝不在弹窗事件循环内泵取 SDL 消息。"""
        self._dialog_open = True
        if getattr(self, 'gamepad_timer', None) is not None:
            self.gamepad_timer.stop()

    def _resume_gamepad(self):
        """模态弹窗关闭后恢复手柄轮询"""
        self._dialog_open = False
        if getattr(self, 'gamepad_timer', None) is not None:
            self.gamepad_timer.start()

    # ---------- 按钮组取值/赋值辅助方法 ----------
    def _checked_text(self, group):
        """返回按钮组当前选中项的文本"""
        btn = group.checkedButton()
        return btn.text() if btn is not None else ""

    def _set_group_text(self, group, text):
        """按文本选中按钮组中的某一项"""
        for btn in group.buttons():
            if btn.text() == text:
                btn.setChecked(True)
                break

    # ---------- 通用控件创建辅助方法 ----------
    def _make_label(self, parent, text, family, size, color='white', bg='black', bold=False):
        """创建与 tkinter 版外观一致的标签：指定底色、文字颜色、居中显示。
        color 与 bg 同时传 None 时不设置样式，使用系统原生默认配色（用于常规弹窗）。"""
        label = QLabel(text, parent)
        font = QFont(family)
        font.setPointSize(size)
        font.setBold(bold)
        label.setFont(font)
        if color is not None and bg is not None:
            label.setStyleSheet(f"color: {color}; background-color: {bg};")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
    # 队伍名称、选手名称自适应字号计算方法
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
        # 预计算得分和获胜局数的填满框架字号
        ##队伍分字号
        team_score_font_size = self._calc_fill_font_size(0.07, 0.15, "[8]")
        ##当前局小分得分字号
        score_fill_size = self._calc_fill_font_size(0.41, 0.80, "99")#使用99这个最大二位数进行测试，计算出最大字号
        ##当前场大分（局分）字号
        win_fill_size = self._calc_fill_font_size(0.07, 0.20, "4")#最多七局四胜制，使用4这个最大局数进行测试，计算出最大字号
        # 预计算队伍名称共用自适应字号
        team_font_size = self._calc_font_size(0.41, 0.15, self.team_a_name, self.team_b_name)
        # 预计算选手名称共用自适应字号
        player_font_size = self._calc_font_size(0.5, 0.15, self.player_a_name, self.player_b_name)

        # ====================左半边区域====================
        ## NO1 创建左边队伍名称显示框架
        self.left_team_frame = QWidget(self.root)
        self.left_team_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左上角开始，宽度，高度
        self.root.place(self.left_team_frame, 0, 0, 0.41, 0.15)
        ### 创建左边队伍名称标签，自适应字号填满框架高度，白字
        self.left_team_label = self._make_label(
            self.left_team_frame, self.team_a_name, "黑体", team_font_size,
            'white', 'black')
        ### 标签靠底部显示，充满整个框架
        self._fill_with(self.left_team_frame, self.left_team_label)

        ## NO2 创建左边队伍大分标签，靠右显示，黄色醒目
        self.left_team_score_frame = QWidget(self.root)
        self.left_team_score_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左上角开始，宽度，高度
        self.root.place(self.left_team_score_frame, 0.41, 0, 0.07, 0.15)
        self.left_team_score_label = self._make_label(
            self.left_team_score_frame, f"[{self.team_score_a}]", "黑体", team_score_font_size,
            '#FFD700', 'black')
        self._fill_with(self.left_team_score_frame, self.left_team_score_label)

        ## NO20 创建左边选手名称显示框架
        self.left_player_frame = QWidget(self.root)
        self.left_player_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左上角开始，宽度，高度
        self.root.place(self.left_player_frame, 0, 0.15, 0.50, 0.15)
        ### 创建左边选手名称标签，自适应字号填满框架高度，白字
        self.left_player_label = self._make_label(
            self.left_player_frame, self.player_a_name, "黑体", player_font_size,
            'white', 'black')
        ### 标签靠底部显示，充满整个框架
        self._fill_with(self.left_player_frame, self.left_player_label)

        ## NO2 创建左边得分显示框架
        self.left_score_display_frame = QWidget(self.root)
        self.left_score_display_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距，上边距，宽度，高度
        self.root.place(self.left_score_display_frame, 0.00, 0.30, 0.41, 0.70)
        ### 创建左边得分标签，使用Arial字体，字号score_fill_size，黑底白字，两位数显示
        self.left_score_label = self._make_label(
            self.left_score_display_frame, f"{self.score_a:02d}", "Arial", score_fill_size,
            'white', 'black')
        ### 标签靠右显示，充满整个框架
        self._fill_with(self.left_score_display_frame, self.left_score_label)

        ## NO3 创建左边获胜局数显示框架
        self.left_wins_frame = QWidget(self.root)
        self.left_wins_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距，上边距，宽度，高度
        self.root.place(self.left_wins_frame, 0.41, 0.30, 0.07, 0.20)
        ### 创建左边获胜局数标签，使用Arial字体，字号win_fill_size，白字
        self.left_wins_label = self._make_label(
            self.left_wins_frame, f"{self.wins_a}", "Arial", win_fill_size,
            'white', 'black')
        ### 标签靠右显示，充满整个框架
        self._fill_with(self.left_wins_frame, self.left_wins_label)

        # ====================中间局数分隔符区域====================
        ## NO4 创建中间":"分隔符框架
        self.middle_colon_frame = QWidget(self.root)
        self.middle_colon_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：水平居中偏左3%，上边距，宽度6%，高度
        self.root.place(self.middle_colon_frame, 0.5 - 0.02, 0.30, 0.04, 0.20)
        ### 创建分隔符标签，使用Arial字体135号，黑底白字
        self.middle_colon_label = self._make_label(
            self.middle_colon_frame, ":", "Arial", 135,
            'white', 'black')
        ### 标签靠顶部显示，充满整个框架
        self._fill_with(self.middle_colon_frame, self.middle_colon_label)

        # ====================左边操作按钮====================
        ## NO5 创建左边"加分"按钮
        self.add_score_a_button = self._make_button(
            self.root, "加分<w>", self.add_score_a)
        ### 设置按钮位置：与右侧减分按钮成镜像（右边缘距中线 = 右侧减分左边缘距中线）
        self.root.place(self.add_score_a_button, 0.41, 0.60, 0.06, 0.03)
        ### 绑定快捷键W到加分功能
        self._bind_key("W", self.add_score_a)

        ## NO6 创建左边"减分"按钮
        self.subtract_score_a_button = self._make_button(
            self.root, "减分<s>", self.subtract_score_a)
        ### 设置按钮位置：与右侧加分按钮成镜像（右边缘距中线 = 右侧加分左边缘距中线）
        self.root.place(self.subtract_score_a_button, 0.41, 0.65, 0.06, 0.03)
        ### 绑定快捷键S到减分功能
        self._bind_key("S", self.subtract_score_a)

        # ====================右半边区域====================
        ## NO2 创建右边队伍大分标签，黄色醒目
        self.right_team_score_frame = QWidget(self.root)
        self.right_team_score_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左上角开始，宽度，高度
        self.root.place(self.right_team_score_frame, 0.52, 0, 0.07, 0.15)
        self.right_team_score_label = self._make_label(
            self.right_team_score_frame, f"[{self.team_score_b}]", "黑体", team_score_font_size,
            '#FFD700', 'black')
        self._fill_with(self.right_team_score_frame, self.right_team_score_label)

        ## NO8 创建右边队伍名称显示框架
        self.right_team_frame = QWidget(self.root)
        self.right_team_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距，上边距，宽度，高度
        self.root.place(self.right_team_frame, 0.59, 0, 0.41, 0.15)
        ### 创建右边队伍名称标签，自适应字号填满框架高度，白字
        self.right_team_label = self._make_label(
            self.right_team_frame, self.team_b_name, "黑体", team_font_size,
            'white', 'black')
        ### 标签靠底部显示，充满整个框架
        self._fill_with(self.right_team_frame, self.right_team_label)

        ## NO21 创建右边选手名称显示框架
        self.right_player_frame = QWidget(self.root)
        self.right_player_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距，上边距，宽度，高度
        self.root.place(self.right_player_frame, 0.50, 0.15, 0.50, 0.15)
        ### 创建右边选手名称标签，自适应字号填满框架高度，白字
        self.right_player_label = self._make_label(
            self.right_player_frame, self.player_b_name, "黑体", player_font_size,
            'white', 'black')
        ### 标签靠底部显示，充满整个框架
        self._fill_with(self.right_player_frame, self.right_player_label)

        # ====================比分分隔符区域====================
        ## NO9 创建比分分隔符":"框架
        self.score_colon_frame = QWidget(self.root)
        self.score_colon_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：水平居中偏左3%，上边距32%，宽度6%，高度40%
        self.root.place(self.score_colon_frame, 0.5 - 0.03, 0.50, 0.06, 0.27)
        colon_fill_size = self._calc_fill_font_size(0.06, 0.27, ":")
        ### 创建比分分隔符标签，使用Arial字体337号，黑底白字
        self.score_colon_label = self._make_label(
            self.score_colon_frame, ":", "Arial", colon_fill_size,
            'white', 'black')
        ### 标签靠顶部显示，充满整个框架
        self._fill_with(self.score_colon_frame, self.score_colon_label)

        ## NO10 创建右边得分显示框架
        self.right_score_display_frame = QWidget(self.root)
        self.right_score_display_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距，上边距，宽度，高度
        self.root.place(self.right_score_display_frame, 0.59, 0.30, 0.41, 0.70)
        ### 创建右边得分标签，使用Arial字体，字号score_fill_size号，黑底白字，两位数显示
        self.right_score_label = self._make_label(
            self.right_score_display_frame, f"{self.score_b:02d}", "Arial", score_fill_size,
            'white', 'black')
        ### 标签靠左显示，充满整个框架
        self._fill_with(self.right_score_display_frame, self.right_score_label)

        ## NO11 创建右边获胜局数显示框架
        self.right_wins_frame = QWidget(self.root)
        self.right_wins_frame.setStyleSheet("background-color: black;")
        ### 设置框架位置：左边距53%，上边距4%，宽度13%，高度18%
        self.root.place(self.right_wins_frame, 0.52, 0.30, 0.07, 0.20)
        ### 创建右边获胜局数标签，使用Arial字体，字号win_fill_size号，黑底白字
        self.right_wins_label = self._make_label(
            self.right_wins_frame, f"{self.wins_b}", "Arial", win_fill_size,
            'white', 'black')
        ### 标签靠左显示，充满整个框架
        self._fill_with(self.right_wins_frame, self.right_wins_label)

        # ====================右边操作按钮====================
        ## NO12 创建右边"加分"按钮
        self.add_score_b_button = self._make_button(
            self.root, "加分<o>", self.add_score_b)
        ### 设置按钮位置：左边距，上边距，宽度，高度
        self.root.place(self.add_score_b_button, 0.53, 0.60, 0.06, 0.03)
        ### 绑定快捷键O到加分功能
        self._bind_key("O", self.add_score_b)

        ## NO13 创建右边"减分"按钮
        self.subtract_score_b_button = self._make_button(
            self.root, "减分<l>", self.subtract_score_b)
        ### 设置按钮位置：左边距，上边距，宽度，高度
        self.root.place(self.subtract_score_b_button, 0.53, 0.65, 0.06, 0.03)
        ### 绑定快捷键L到减分功能
        self._bind_key("L", self.subtract_score_b)

        # ====================中间按钮区域====================
        ## NO16 创建"设置"按钮（弹窗统一设置赛制、比赛类型、队伍选手）
        self.set_button = self._make_button(
            self.root, "设置<v>", self.open_settings)
        ### 设置按钮位置：水平居中偏左3%，上边距，宽度，高度
        self.root.place(self.set_button, 0.5 - 0.03, 0.78, 0.06, 0.03)
        ### 绑定快捷键V到"设置"功能
        self._bind_key("V", self.open_settings)

        ## NO18 创建"本局结束"按钮
        self.new_over_button = self._make_button(
            self.root, "本局结束<b>", self.win_a_or_b)
        ### 设置按钮位置：水平居中偏左3%，上边距，宽度，高度
        self.root.place(self.new_over_button, 0.5 - 0.03, 0.82, 0.06, 0.03)
        ### 绑定快捷键B到"本局结束"功能
        self._bind_key("B", self.win_a_or_b)

        ## NO19 创建"交换场地"按钮
        self.switch_button = self._make_button(
            self.root, "交换场地<n>", self.change_ends)
        ### 设置按钮位置：水平居中偏左3%，上边距，宽度，高度
        self.root.place(self.switch_button, 0.5 - 0.03, 0.86, 0.06, 0.03)
        ### 绑定快捷键N到交换场地功能
        self._bind_key("N", self.change_ends)

        #创建"比赛结果"按钮
        self.result_button = self._make_button(
            self.root, "比赛结果<m>", self.show_match_result)
        self.root.place(self.result_button, 0.5 - 0.03, 0.90, 0.06, 0.03)
        self._bind_key("M", self.show_match_result)

    # ================================================
    # 游戏手柄初始化方法
    # 功能：初始化pygame和游戏手柄子系统，
    #       检测并连接手柄设备
    # ================================================
    def init_gamepad(self):
        # 初始化pygame库
        pygame.init()
        # 初始化游戏手柄子系统
        pygame.joystick.init()

        # 检测连接的手柄数量
        joystick_count = pygame.joystick.get_count()
        if joystick_count > 0:
            # 连接检测到的第一个游戏手柄
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print(f"游戏手柄已连接: {self.joystick.get_name()} (共检测到 {joystick_count} 个手柄)")
        else:
            # 未检测到手柄，设为None（仍可使用键盘操作）
            self.joystick = None
            print("未检测到游戏手柄，请使用键盘操作")

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
        mappings = [
            ("left_add_score", self.add_score_a),
            ("left_subtract_score", self.subtract_score_a),
            ("right_add_score", self.add_score_b),
            ("right_subtract_score", self.subtract_score_b),
            ("new_over", self.win_a_or_b),
            ("change_ends", self.change_ends),
        ]
        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:
                for key, action in mappings:
                    if buttons[key].get("type") == "button" and buttons[key].get("value") == event.button:
                        action()
                        break
            elif event.type == pygame.JOYHATMOTION:
                hat_x, hat_y = event.value
                for key, action in mappings:
                    if buttons[key].get("type") == "hat" and buttons[key].get("value") == hat_y:
                        action()
                        break

    # ================================================
    # 选手A加分方法
    # 功能：将选手A当前得分加1并更新显示（加分前校验比分是否合法）
    # ================================================
    def add_score_a(self):
        if self.is_valid_result(self.score_a,self.score_b):
            return
        if self.is_valid_ongoing_score(self.score_a + 1, self.score_b):
            self.score_a += 1
            self.left_score_label.setText(f"{self.score_a:02d}")

    # ================================================
    # 选手A减分方法
    # 功能：将选手A当前得分减1（不小于0）并更新显示（减分前校验比分是否合法）
    # ================================================
    def subtract_score_a(self):
        if self.is_valid_result(self.score_a,self.score_b) and self.is_valid_result(self.score_a-1,self.score_b):
            return
        if self.is_valid_ongoing_score(self.score_a - 1, self.score_b):
            self.score_a -= 1
            self.left_score_label.setText(f"{self.score_a:02d}")

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

        # 规则1: 11平之前（max_score < 10），任何比分都合法
        if max_score <= 11:
            return True
        # 规则2: max_score > 11，进入11分后的阶段
        else:
            if min_score <= max_score and min_score >= max_score-2:
                return True
            # else:
            #     messagebox.showinfo("提示", "分数应大于0，请改正。")
            #     return False
        return False

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
            # messagebox.showinfo("提示", "分数应大于0，请改正。")
            return False

        max_score = max(a, b)
        diff = abs(a-b)

        # 一方获胜，分至少为11
        if max_score >= 11 and diff >= 2:#本条件可能出现15:12这种比分。但是有is_valid_ongoing_score（）把关，就出现不了了。
            return True
        else:
            # messagebox.showinfo("提示", "此局未结束，请检查。")
            return False

    # ================================================
    # 根据比分判断选手A还是选手B本局获胜方法
    # 功能：记录本局获胜方，更新局分和队伍大分并重置小分
    # ================================================
    def win_a_or_b(self):
        # 使用 is_valid_result 判断比分是否合理
        if self.is_valid_result(self.score_a, self.score_b):
            #判断哪一方获胜，更新局分
            if self.score_a > self.score_b:
                # 选手A获胜局数加1（不超过4）
                if self.wins_a < 4:
                    self.wins_a += 1
                    self.left_wins_label.setText(f"{self.wins_a}")
            elif self.score_a < self.score_b:
                # 选手B获胜局数加1（不超过4）
                if self.wins_b < 4:
                    self.wins_b += 1
                    self.right_wins_label.setText(f"{self.wins_b}")

            # 更新队伍大分：仅"十五局八胜制"按局计分（每局结束更新队伍大分）；
            # "五场三胜制"按场计分，不在此处更新，待本场获胜局数达标时自动结算
            if self.match_format == "15局8胜制":
                if self.score_a > self.score_b:
                    self.team_score_a += 1
                else:
                    self.team_score_b += 1
                self._update_team_score_display()
            # 队伍是否获胜由现场裁判判定，程序不弹窗、不判断

            # 保存本局比分记录
            self.save_scores()

            # 重置选手A得分
            self.score_a = 0
            self.left_score_label.setText(f"{self.score_a:02d}")
            # 重置选手B得分
            self.score_b = 0
            self.right_score_label.setText(f"{self.score_b:02d}")

            # "五场三胜制"按场计分：本场某方局分达到"每场局数"要求时，判定本场结束，
            # 先弹确认窗口提示胜方，点击"确定"后再结算（给胜方队伍加分、清零本场局分小分）
            if self.match_format == "五场三胜制":
                target = self._get_games_target()
                if self.wins_a >= target or self.wins_b >= target:
                    self._confirm_finalize_match()

    # ================================================
    # 本场结束确认方法（五场三胜制）
    # 功能：判定本场结束后，先弹确认窗口提示胜方队伍与选手，点击"确定"后再结算本场，
    #       给胜方队伍加分并清零本场局分、小分；点击"取消"则暂不结算，保持当前状态。
    #       当本场某方局分达到"每场局数"要求时，由 win_a_or_b 调用。
    # ================================================
    def _confirm_finalize_match(self):
        if self.wins_a > self.wins_b:
            winner_team = self.team_a_name
            winner_player = self.player_a_name
        else:
            winner_team = self.team_b_name
            winner_player = self.player_b_name

        box = QMessageBox(self.root)
        box.setWindowTitle("本场结束确认")
        box.setText(
            f"本场结束，胜方：{winner_team}（选手：{winner_player}）\n\n"
            f"本场局分 {self.team_a_name}{self.wins_a}:{self.wins_b}{self.team_b_name}\n\n"
            f"点击「确定」后 {winner_team}加 1 分，并清零本场局分。")
        # 覆盖主窗口黑底样式，保证弹窗白底黑字可读
        box.setStyleSheet("QMessageBox, QMessageBox * { background-color: white; color: black; }")
        ok_btn = box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(ok_btn)
        box.exec()
        if box.clickedButton() is ok_btn:
            self._finalize_match()

    # ================================================
    # 本场结束自动结算方法
    # 功能：保存本场比赛大分（局分），统计进入队伍大分，保存队伍大分，然后清零大分。
    #       当本场某方局分达到"每场局数"要求时，由 _confirm_finalize_match 在确认后调用
    # ================================================
    def _finalize_match(self):
        # 保存本场比赛大分（局分）：仅当本场有过获胜局时才保存
        if self.wins_a or self.wins_b:
            self.save_wins()
        # 统计进入队伍大分（五场三胜制按场计分）
        if self.wins_a or self.wins_b:
            self._finalize_match_team_score()
        # 保存队伍大分
        if self.team_score_a or self.team_score_b:
            self.save_team_score()
        # 强制刷新显示，让用户看到更新后的队伍大分
        self.root.repaint()

        # 清零局分
        self.wins_a = 0
        self.wins_b = 0
        self.left_wins_label.setText(f"{self.wins_a}")
        self.right_wins_label.setText(f"{self.wins_b}")
        # 清零小分
        self.score_a = 0
        self.score_b = 0
        self.left_score_label.setText(f"{self.score_a:02d}")
        self.right_score_label.setText(f"{self.score_b:02d}")

    # ================================================
    # 每场局数目标获取方法
    # 功能：根据"每场局数"设置返回本场获胜所需局数
    #       （三局二胜=2、五局三胜=3、七局四胜=4），未知设置时按五局三胜处理
    # ================================================
    def _get_games_target(self):
        targets = {"三局二胜": 2, "五局三胜": 3, "七局四胜": 4}
        return targets.get(self.games_per_match, 3)

    # ================================================
    # 选手B加分方法
    # 功能：将选手B当前得分加1并更新显示（加分前校验比分是否合法）
    # ================================================
    def add_score_b(self):
        if self.is_valid_result(self.score_a,self.score_b):
            return
        if self.is_valid_ongoing_score(self.score_a, self.score_b + 1):
            self.score_b += 1
            self.right_score_label.setText(f"{self.score_b:02d}")

    # ================================================
    # 选手B减分方法
    # 功能：将选手B当前得分减1（不小于0）并更新显示（减分前校验比分是否合法）
    # ================================================
    def subtract_score_b(self):
        if self.is_valid_result(self.score_a,self.score_b) and self.is_valid_result(self.score_a,self.score_b-1):
            return
        if self.is_valid_ongoing_score(self.score_a, self.score_b - 1):
            self.score_b -= 1
            self.right_score_label.setText(f"{self.score_b:02d}")

    # ================================================
    # 交换场地方法(队伍、选手、大小比分，都要换)
    # 功能：随着双方交换场地，记分牌上的队伍名称、选手姓名、得分和获胜局数，都要交换
    # ================================================
    def change_ends(self):
        # 交换队伍名称
        self.team_a_name, self.team_b_name = self.team_b_name, self.team_a_name
        # 更新队伍名称显示
        self.left_team_label.setText(self.team_a_name)
        self.right_team_label.setText(self.team_b_name)

        # 交换选手名称
        self.player_a_name, self.player_b_name = self.player_b_name, self.player_a_name
        # 更新选手名称显示
        self.left_player_label.setText(self.player_a_name)
        self.right_player_label.setText(self.player_b_name)

        # 交换当前得分
        self.score_a, self.score_b = self.score_b, self.score_a
        # 更新得分显示
        self.left_score_label.setText(f"{self.score_a:02d}")
        self.right_score_label.setText(f"{self.score_b:02d}")

        # 交换获胜局数
        self.wins_a, self.wins_b = self.wins_b, self.wins_a
        # 更新获胜局数显示
        self.left_wins_label.setText(f"{self.wins_a}")
        self.right_wins_label.setText(f"{self.wins_b}")

        # 交换队伍大分
        self.team_score_a, self.team_score_b = self.team_score_b, self.team_score_a
        # 更新队伍大分显示
        self._update_team_score_display()

    # ================================================
    # 更新队伍大分显示方法
    # 功能：更新界面上的队伍大分标签
    # ================================================
    def _update_team_score_display(self):
        self.left_team_score_label.setText(f"[{self.team_score_a}]")
        self.right_team_score_label.setText(f"[{self.team_score_b}]")

    # ================================================
    # 结算一场比赛的队伍大分方法
    # 功能：五场三胜制按场计分，仅在整场比赛结束（换选手/换队伍/程序退出）时，
    #       根据局分领先的选手判定该场获胜方，其所在队伍加1分。
    #       本方法只负责加分结算，调用方须先确认本场已有获胜局（wins_a 或 wins_b 非0）
    # ================================================
    def _finalize_match_team_score(self):
        if self.match_format != "五场三胜制":
            return
        if self.wins_a > self.wins_b:
            self.team_score_a += 1
        else:
            self.team_score_b += 1
        self._update_team_score_display()

    # ================================================
    # 统一设置方法
    # 功能：弹窗统一设置赛制、比赛类型、队伍选手
    # ================================================
    def open_settings(self):
        self.settings_window = QDialog(self.root)
        self.settings_window.setWindowTitle("比赛设置")
        # 用浅色窗口底色覆盖主窗口的黑底样式，避免弹窗继承主窗口的黑色背景。
        # 关键：主窗口的 setStyleSheet("background-color: black;") 是 * 全局规则，
        # 会级联到本弹窗及其全部子控件；只写 "QDialog{...}" 只能覆盖弹窗本身，
        # 子控件（标签、单选框、输入框、容器等）仍会命中黑底规则。
        # 因此这里同时覆盖 QDialog 本身及其全部后代子控件：白底黑字，保持常规 Windows 外观。
        # 注意：对单选框设置样式后，必须同时显式声明 ::indicator 子控件的选中/未选中外观，
        # 否则选中态的小圆点不会绘制（这正是“选中的单选框消失”的原因）。
        self.settings_window.setStyleSheet(
            "QDialog, QDialog * { background-color: white; color: black; }"
            "QDialog *:disabled { color: #909090; }"
            "QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px;"
            " border: 1px solid #808080; background-color: white; }"
            "QRadioButton::indicator:checked { border: 1px solid #0078d4;"
            " background-color: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,"
            " stop: 0 #0078d4, stop: 0.4 #0078d4, stop: 0.5 white, stop: 1 white); }"
            "QRadioButton::indicator:disabled { border: 1px solid #c0c0c0; background-color: #f0f0f0; }"
            "QRadioButton::indicator:checked:disabled { border: 1px solid #909090;"
            " background-color: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,"
            " stop: 0 #909090, stop: 0.4 #909090, stop: 0.5 white, stop: 1 white); }")

        window_width = 420
        window_height = 520

        x = (self.screen_width // 2) - (window_width // 2)
        y = (self.screen_height // 2) - (window_height // 2)

        self.settings_window.setFixedSize(window_width, window_height)
        self.settings_window.move(x, y)
        self.settings_window.setModal(True)
        # 安装事件过滤器：吞掉 ESC，保持与 tkinter 版一致（设置弹窗按 ESC 不关闭）
        self.settings_window.installEventFilter(_EscapeSwallowFilter(self.settings_window))

        main_layout = QVBoxLayout(self.settings_window)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(6)

        # ========== 1. 赛制选择 ==========
        lbl_format_title = self._make_label(
            self.settings_window, "赛制选择：", "黑体", 12, None, None, bold=True)
        main_layout.addWidget(lbl_format_title, alignment=Qt.AlignmentFlag.AlignLeft)

        self.format_group = QButtonGroup(self.settings_window)
        frame_format = QWidget(self.settings_window)
        main_layout.addWidget(frame_format)
        fmt_layout = QVBoxLayout(frame_format)
        fmt_layout.setContentsMargins(10, 0, 0, 0)
        fmt_layout.setSpacing(4)

        rb_format1 = QRadioButton("五场三胜制", frame_format)
        rb_format1.setFont(QFont("黑体", 11))
        self.format_group.addButton(rb_format1)
        rb_format1.setChecked(self.match_format == "五场三胜制")
        fmt_layout.addWidget(rb_format1)

        # ---------- 每场局数选择（五场三胜制下每场的局数，与五场三胜制联动） ----------
        # 整体作为一个缩进块（标题与三个单选项都再向内缩进，形成层级关系）
        frame_games_section = QWidget(frame_format)
        fmt_layout.addWidget(frame_games_section)
        games_section_layout = QVBoxLayout(frame_games_section)
        games_section_layout.setContentsMargins(20, 0, 0, 0)
        games_section_layout.setSpacing(4)

        self.lbl_games_title = self._make_label(
            frame_games_section, "每场局数：", "黑体", 11, None, None)
        self.lbl_games_title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        games_section_layout.addWidget(self.lbl_games_title)

        # 每场局数始终保持一个有效选中值（配置异常时回退为"五局三胜"）
        if self.games_per_match not in ("三局二胜", "五局三胜", "七局四胜"):
            self.games_per_match = "五局三胜"
        self.games_group = QButtonGroup(self.settings_window)
        self.games_radios = []      # 保存每场局数单选项，供联动变灰/恢复
        frame_games = QWidget(frame_games_section)
        games_section_layout.addWidget(frame_games)
        games_layout = QHBoxLayout(frame_games)
        games_layout.setContentsMargins(30, 0, 0, 0)
        games_layout.setSpacing(15)
        games_options = ["三局二胜", "五局三胜", "七局四胜"]
        for g in games_options:
            rb = QRadioButton(g, frame_games)
            rb.setFont(QFont("黑体", 11))
            self.games_group.addButton(rb)
            rb.setChecked(self.games_per_match == g)
            games_layout.addWidget(rb)
            self.games_radios.append(rb)

        rb_format2 = QRadioButton("十五局八胜制", frame_format)
        rb_format2.setFont(QFont("黑体", 11))
        self.format_group.addButton(rb_format2)
        rb_format2.setChecked(self.match_format == "15局8胜制")
        fmt_layout.addWidget(rb_format2)

        # 比赛进行中禁止修改赛制：赛制信息必须在比赛开始前确定，
        # 只能在所有比分均为 0（尚未开始比赛）时修改。
        # 每场局数区域由 _update_games_section 一并禁用。
        if self._is_match_in_progress():
            rb_format1.setEnabled(False)
            rb_format2.setEnabled(False)

        # 赛制单选变化时联动更新"每场局数"区域
        self.format_group.buttonClicked.connect(lambda _btn: self._on_format_change())

        # 分隔线：赛制区域与比赛类型区域之间
        sep1 = QFrame(self.settings_window)
        sep1.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(sep1)

        # ========== 2. 比赛类型选择 ==========
        lbl_type_title = self._make_label(
            self.settings_window, "比赛类型：", "黑体", 12, None, None, bold=True)
        main_layout.addWidget(lbl_type_title, alignment=Qt.AlignmentFlag.AlignLeft)

        self.type_group = QButtonGroup(self.settings_window)
        frame_type = QWidget(self.settings_window)
        main_layout.addWidget(frame_type)
        type_layout = QHBoxLayout(frame_type)
        type_layout.setContentsMargins(10, 0, 0, 0)
        type_layout.setSpacing(15)
        types = ["男单", "男双", "女单", "女双", "混双"]
        for t in types:
            rb = QRadioButton(t, frame_type)
            rb.setFont(QFont("黑体", 11))
            self.type_group.addButton(rb)
            rb.setChecked(self.match_type == t)
            type_layout.addWidget(rb)

        # 分隔线：比赛类型区域与队伍选手区域之间
        sep2 = QFrame(self.settings_window)
        sep2.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(sep2)

        # ========== 3. 队伍选手输入 ==========
        lbl_team_title = self._make_label(
            self.settings_window, "队伍及选手信息：", "黑体", 12, None, None, bold=True)
        main_layout.addWidget(lbl_team_title, alignment=Qt.AlignmentFlag.AlignLeft)

        frame_input = QWidget(self.settings_window)
        main_layout.addWidget(frame_input, 1)
        grid = QGridLayout(frame_input)
        grid.setContentsMargins(10, 0, 10, 0)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(6)

        # 标签和输入框
        lbl_team_a = self._make_label(frame_input, "队伍A：", "黑体", 11, None, None)
        lbl_team_a.setAlignment(Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(lbl_team_a, 0, 0)
        entry_team_a = QLineEdit(self.team_a_name, frame_input)
        entry_team_a.setFont(QFont("黑体", 11))
        grid.addWidget(entry_team_a, 0, 1)

        lbl_player_a = self._make_label(frame_input, "选手A：", "黑体", 11, None, None)
        lbl_player_a.setAlignment(Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(lbl_player_a, 1, 0)
        entry_player_a = QLineEdit(self.player_a_name, frame_input)
        entry_player_a.setFont(QFont("黑体", 11))
        grid.addWidget(entry_player_a, 1, 1)

        lbl_team_b = self._make_label(frame_input, "队伍B：", "黑体", 11, None, None)
        lbl_team_b.setAlignment(Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(lbl_team_b, 2, 0)
        entry_team_b = QLineEdit(self.team_b_name, frame_input)
        entry_team_b.setFont(QFont("黑体", 11))
        grid.addWidget(entry_team_b, 2, 1)

        lbl_player_b = self._make_label(frame_input, "选手B：", "黑体", 11, None, None)
        lbl_player_b.setAlignment(Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(lbl_player_b, 3, 0)
        entry_player_b = QLineEdit(self.player_b_name, frame_input)
        entry_player_b.setFont(QFont("黑体", 11))
        grid.addWidget(entry_player_b, 3, 1)

        grid.setColumnStretch(1, 1)

        # 确定按钮
        btn_confirm = QPushButton("确定", self.settings_window)
        btn_confirm.setFont(QFont("黑体", 12))
        btn_confirm.clicked.connect(lambda: self.confirm_settings(
            entry_team_a.text(), entry_team_b.text(),
            entry_player_a.text(), entry_player_b.text()))
        main_layout.addWidget(btn_confirm, alignment=Qt.AlignmentFlag.AlignCenter)

        # 按当前赛制初始化"每场局数"区域的启用/禁用状态
        self._update_games_section()

        # 模态弹窗期间暂停手柄轮询（与原 tkinter wait_window 阻塞行为一致）
        self._pause_gamepad()
        self.settings_window.exec()
        self._resume_gamepad()

    # ---------- 赛制与每场局数联动 ----------
    def _on_format_change(self):
        """赛制单选变化时，联动更新"每场局数"区域"""
        self._update_games_section()

    def _update_games_section(self):
        """根据赛制联动"每场局数"区域的启用状态：
        五场三胜制 → 每场局数可选；
        15局8胜制 → 每场局数禁用（系统原生置灰，选中项保持不变）。
        比赛进行中 → 整个赛制区（含每场局数）都禁用，赛制信息必须在比赛开始前确定。
        每场局数始终保留一个选中值，不会全部取消选中。"""
        # 注意：这里比较的是单选框的显示文本"十五局八胜制"，而不是内部常量"15局8胜制"
        disabled = (self._checked_text(self.format_group) == "十五局八胜制"
                    or self._is_match_in_progress())
        self.lbl_games_title.setEnabled(not disabled)
        for rb in self.games_radios:
            rb.setEnabled(not disabled)

    # ================================================
    # 比赛是否进行中判断方法
    # 功能：小分、局分、队伍大分任一非零即视为比赛进行中。
    #       比赛进行中禁止修改赛制（含每场局数），赛制信息必须在比赛开始前确定。
    # ================================================
    def _is_match_in_progress(self):
        return bool(self.score_a or self.score_b
                    or self.wins_a or self.wins_b
                    or self.team_score_a or self.team_score_b)

    # ================================================
    # 确认设置方法
    # 功能：确认赛制、比赛类型、队伍选手的变更
    # ================================================
    def confirm_settings(self, team_a, team_b, player_a, player_b):
        # 验证输入不为空
        if not (team_a and team_b and player_a and player_b):
            self.settings_window.accept()
            return

        # 判断赛制是否变化
        # 单选框显示的是"十五局八胜制"，而程序内部统一用"15局8胜制"表示，
        # 取回后先转成内部常量，保证与计分逻辑、配置文件一致。
        new_format = self._checked_text(self.format_group)
        if new_format == "十五局八胜制":
            new_format = "15局8胜制"
        format_changed = new_format != self.match_format

        # 判断比赛类型是否变化
        new_type = self._checked_text(self.type_group)
        type_changed = new_type != self.match_type

        # 判断每场局数是否变化
        new_games = self._checked_text(self.games_group)
        games_changed = new_games != self.games_per_match

        # 判断队伍名称是否变化（顺序互换不算变化）
        current_teams = {self.team_a_name, self.team_b_name}
        new_teams = {team_a, team_b}
        team_changed = current_teams != new_teams

        # 判断选手名称是否变化（选手姓名顺序变化也视为换选手，如 张三/李四 换成 李四/张三）
        player_changed = (self.player_a_name, self.player_b_name) != (player_a, player_b)

        # 赛制变化处理：比赛进行中（小分/局分/队伍大分任一非零）禁止修改赛制，
        # 只能在比赛开始前修改。设置弹窗中赛制单选在比赛进行中已被禁用，
        # 此处为兜底防护，防止绕过 UI 直接触发。
        if format_changed and not team_changed and self._is_match_in_progress():
            QMessageBox.information(
                self.settings_window,
                "无法修改赛制",
                "比赛进行中不能修改赛制，请在比赛开始前进行赛制设置。")
            # 恢复原赛制单选，其余设置照常应用，所有积分保持不变
            # _set_group_text 需要单选框的显示文本，先把内部常量转回显示文本
            restore_text = "十五局八胜制" if self.match_format == "15局8胜制" else self.match_format
            self._set_group_text(self.format_group, restore_text)
            new_format = self.match_format
            format_changed = False

        # 队伍名称变化：整场团体赛结束，保存最后一场局分和最终队伍大分，然后重新开始
        if team_changed:
            # 结算最后一场比赛的队伍大分（五场三胜制按场计分）
            if self.wins_a or self.wins_b:
                self._finalize_match_team_score()
            # 保存最后一场比赛的局分
            if self.wins_a or self.wins_b:
                self.save_wins()
            # 保存最终队伍大分（该团体赛计分文件中的最后一次）
            if self.team_score_a or self.team_score_b:
                self.save_team_score()
            self.team_score_a = 0
            self.team_score_b = 0
            self.wins_a = 0
            self.wins_b = 0
            self.score_a = 0
            self.score_b = 0
            # 新建计分文件（文件开头写入赛制信息头）
            now = datetime.now()
            filename = os.path.join(get_base_dir(), f"Score_TeamEvents_{team_a}_{team_b}_{now.strftime('%Y%m%d_%H%M%S')}.txt")
            self.current_score_file = filename
            self._ensure_score_file()
        elif format_changed:
            # 赛制变化（仅在比赛未开始时可修改）：直接切换赛制，
            # 此时尚无任何比分记录，队伍大分保持 0:0，无需重算
            self.match_format = new_format
        elif player_changed:
            # 换选手：队伍不变，结算本场队伍大分（五场三胜制），保留队伍大分，
            # 保存该场次局分，然后清零局分和小分重新开局
            if self.wins_a or self.wins_b:
                self._finalize_match_team_score()
                self.save_wins()
            self.wins_a = 0
            self.wins_b = 0
            self.score_a = 0
            self.score_b = 0
        # 比赛类型变化：不影响任何计分（队伍大分、选手局分、小分都保持不变）
        # else: 都没变→保持所有积分不变

        # 更新赛制变量
        self.match_format = new_format
        # 更新每场局数变量（每场局数始终保留一个选中值，直接保存）
        self.games_per_match = new_games

        # 赛制或每场局数变化后，同步更新计分文件开头的赛制信息，
        # 保证读取端按新赛制解析小分
        if format_changed or games_changed:
            self._update_header_format()
        # 更新比赛类型变量
        self.match_type = new_type
        # 更新队伍名称变量
        self.team_a_name = team_a
        self.team_b_name = team_b
        # 更新选手名称变量
        self.player_a_name = player_a
        self.player_b_name = player_b

        # 重新计算字号并更新队伍名称显示
        team_font_size = self._calc_font_size(0.41, 0.15, self.team_a_name, self.team_b_name)
        self.left_team_label.setText(self.team_a_name)
        self.left_team_label.setFont(QFont("黑体", team_font_size))
        self.right_team_label.setText(self.team_b_name)
        self.right_team_label.setFont(QFont("黑体", team_font_size))
        # 重新计算字号并更新选手名称显示
        player_font_size = self._calc_font_size(0.5, 0.15, self.player_a_name, self.player_b_name)
        self.left_player_label.setText(self.player_a_name)
        self.left_player_label.setFont(QFont("黑体", player_font_size))
        self.right_player_label.setText(self.player_b_name)
        self.right_player_label.setFont(QFont("黑体", player_font_size))

        # 更新所有显示标签
        self._update_team_score_display()
        self.left_score_label.setText(f"{self.score_a:02d}")
        self.right_score_label.setText(f"{self.score_b:02d}")
        self.left_wins_label.setText(f"{self.wins_a}")
        self.right_wins_label.setText(f"{self.wins_b}")

        # 将赛制、每场局数、比赛类型、队伍名称、选手姓名写入配置文件
        self.config["match_format"] = self.match_format
        self.config["games_per_match"] = self.games_per_match
        self.config["match_type"] = self.match_type
        self.config["team_a_name"] = self.team_a_name
        self.config["team_b_name"] = self.team_b_name
        self.config["player_a_name"] = self.player_a_name
        self.config["player_b_name"] = self.player_b_name
        self.save_config()

        self.settings_window.accept()

    # ================================================
    # 确保计分文件已创建方法
    # 功能：首次保存时生成文件名，并在文件开头写入赛制信息行。
    #       文件已存在且非空时（如换队伍后新建的文件）不再重复写头。
    #       返回当前计分文件路径。
    # ================================================
    def _ensure_score_file(self):
        if self.current_score_file is None:
            now = datetime.now()
            filename = os.path.join(get_base_dir(), f"Score_TeamEvents_{self.team_a_name}_{self.team_b_name}_{now.strftime('%Y%m%d_%H%M%S')}.txt")
            self.current_score_file = filename
        # 文件不存在或为空（新建）时写入赛制信息头
        if not os.path.exists(self.current_score_file) or os.path.getsize(self.current_score_file) == 0:
            with open(self.current_score_file, "a") as file:
                file.write(self._make_header_line())
        return self.current_score_file

    # ================================================
    # 赛制信息头生成方法
    # 功能：生成计分文件开头的赛制信息行。
    #       五场三胜制额外保存每场局数；15局8胜制无每场局数。
    #       读取端据此选择小分的解析规则。
    # ================================================
    def _make_header_line(self):
        if self.match_format == "五场三胜制":
            return f"赛制信息,{self.match_format},每场局数:{self.games_per_match}\n"
        return f"赛制信息,{self.match_format}\n"

    # ================================================
    # 更新计分文件头赛制信息方法
    # 功能：赛制或每场局数变化后，同步更新计分文件开头的赛制信息行，
    #       保证读取端按新赛制解析小分，与重新计算的队伍大分一致。
    #       赛制变化只在设置确认时发生，频率很低，直接改写整个文件。
    # ================================================
    def _update_header_format(self):
        if self.current_score_file is None:
            return
        try:
            lines = read_text_auto_encoding(self.current_score_file).split("\n")
        except OSError:
            return
        new_header = self._make_header_line().rstrip("\n")
        if lines and lines[0].startswith("赛制信息"):
            lines[0] = new_header
        else:
            lines.insert(0, new_header)
        try:
            with open(self.current_score_file, "w") as f:
                f.write("\n".join(lines))
        except OSError:
            pass

    # ================================================
    # 保存本场比赛小分方法
    # 功能：将本局比分记录保存到文件（首次保存时新建计分文件并写入赛制信息头）
    # ================================================
    def save_scores(self):
        # 以追加模式打开计分文件
        with open(self._ensure_score_file(), "a") as file:
            # 写入比分记录，格式：保存小分,队伍A-选手A:队伍B-选手B,得分A:得分B,类型:比赛类型
            file.write(f"保存小分,{self.team_a_name}-{self.player_a_name}:{self.team_b_name}-{self.player_b_name},{self.score_a}:{self.score_b},类型:{self.match_type}\n")

    # ================================================
    # 保存本场比赛大分方法（选手局分和队伍大分）
    # 功能：将选手局分和队伍大分记录保存到文件
    # ================================================
    def save_wins(self):
        # 以追加模式打开计分文件
        with open(self._ensure_score_file(), "a") as file:
            # 写入该场次选手局分记录（一场比赛仅记录一次，换选手时保存），格式：保存大分,队伍A-选手A:队伍B-选手B,局分A:局分B,类型:比赛类型
            file.write(f"保存大分,{self.team_a_name}-{self.player_a_name}:{self.team_b_name}-{self.player_b_name},{self.wins_a}:{self.wins_b},类型:{self.match_type}\n")

    # ================================================
    # 保存队伍大分方法
    # 功能：将队伍大分记录保存到文件
    # 说明：整个团体赛计分文件中仅在最后保存一次队伍大分，
    #       在队伍更换时或程序退出时调用
    # ================================================
    def save_team_score(self):
        # 以追加模式打开计分文件
        with open(self._ensure_score_file(), "a") as file:
            # 写入队伍大分记录
            file.write(f"保存队伍大分,{self.team_a_name}:{self.team_b_name},{self.team_score_a}:{self.team_score_b}\n")

    # ---------- 从文件名解析队伍名称 ----------
    def _parse_team_names_from_filename(self, filepath):
        """从计分文件名解析两队名称。
        文件名格式：score_队伍A_队伍B_YYYYMMDD_HHMMSS.txt
        队伍名不含下划线，最后两段为日期与时间戳。
        解析失败时返回当前设置的两队名称。"""
        if filepath is None:
            return self.team_a_name, self.team_b_name
        basename = os.path.basename(filepath)
        if basename.lower().endswith(".txt"):
            basename = basename[:-4]
        parts = basename.split('_')
        if len(parts) >= 5 and parts[0] == "score":
            return parts[1], parts[2]
        return self.team_a_name, self.team_b_name

    # ---------- 解析团体赛计分文件 ----------
    def _parse_team_file(self, filepath):
        """解析团体赛计分文件，返回 (team_a, team_b, matches, match_format, games_per_match)。
        matches：每场 (比赛类型, A选手, A局分, B选手, B局分)。
        以"保存小分"记录为依据整理每场的结果：把连续的"保存小分"记录归并为一场，
        统计每场中双方获胜的局数作为该场的局分（大分）。
        这样既能展示已结束的场次，也能展示正在进行的场次的当前局分。

        解析规则：
          1) 文件必须包含"赛制信息"行，缺失时抛出 _HistoryFileError（不兼容旧版无赛制文件）；
          2) 仅读取"保存小分"开头的行，"保存大分""保存队伍大分"等行一律忽略，
             不作为场次结束信号，也不读取其中的数据；
          3) 场次是否结束仅由"保存小分"数据结合赛制判定：
             - 比赛类型与双方选手组成的场次标识发生变化 → 当前场结束；
             - 五场三胜制下，一方局分达到"每场局数"目标 → 当前场结束；
             - 文件末尾 → 关闭最后一个场次。
          4) 队伍大分不在此解析，由调用方按赛制从场次数据重新计算。"""
        # 第一步：读取文件全部行（文件不存在/打不开 → 返回空结果，保持原行为）
        try:
            lines = read_text_auto_encoding(filepath).split("\n")
        except (FileNotFoundError, OSError, TypeError):
            return (self.team_a_name, self.team_b_name, [],
                    self.match_format, self.games_per_match)

        # 第二步：预扫描"赛制信息"行。赛制决定后续"场次是否结束"的判定规则，
        # 必须先于"保存小分"解析确定；文件没有该行 → 直接报错，不兼容旧版无赛制文件。
        file_format = None
        file_games = None
        for line in lines:
            if line.strip().startswith("赛制信息"):
                # 赛制信息,五场三胜制,每场局数:五局三胜
                # （15局8胜制无每场局数；兼容旧版显示文本"十五局八胜制"）
                parts = line.split(',')
                if len(parts) >= 2:
                    fmt = parts[1].strip()
                    if fmt == "十五局八胜制":
                        fmt = "15局8胜制"
                    if fmt in ("五场三胜制", "15局8胜制"):
                        file_format = fmt
                if len(parts) >= 3 and parts[2].strip().startswith("每场局数:"):
                    gpm = parts[2].strip()[len("每场局数:"):].strip()
                    if gpm in ("三局二胜", "五局三胜", "七局四胜"):
                        file_games = gpm
                break
        if file_format is None:
            raise _HistoryFileError("数据文件缺少'赛制信息'行，无法解析。")

        # 第三步：仅解析"保存小分"行，其余行（含"保存大分""保存队伍大分"）一律忽略
        team_a = self.team_a_name
        team_b = self.team_b_name
        matches = []        # 每场 (比赛类型, A选手, A局分, B选手, B局分)
        cur_match = None     # 当前正在归并的一场: [match_type, pa, wa, pb, wb]
        cur_identity = None  # 当前场的标识 (match_type, pa, pb)

        for line in lines:
            line = line.strip()
            if not line:  # 去掉为空的空行
                continue
            if not line.startswith("保存小分"):
                # "保存大分""保存队伍大分"及空行/其他行：一律忽略，
                # 不作为场次结束信号，也不读取其中的数据
                continue
            parts = line.split(',')
            if len(parts) < 3:
                continue
            try:
                name_part = parts[1].strip()
                score_part = parts[2].strip()
                match_type = ""
                if len(parts) >= 4 and parts[3].strip().startswith("类型:"):
                    match_type = parts[3].strip()[len("类型:"):].strip()
                # name_part格式：队伍A-选手A:队伍B-选手B（左右队伍可能互换）
                name_pairs = name_part.split(':')
                if len(name_pairs) < 2:
                    continue
                pa_full = name_pairs[0].strip()  # 左侧 队伍-选手
                pb_full = name_pairs[1].strip()  # 右侧 队伍-选手
                left_team = pa_full.split('-', 1)[0].strip()
                # 首次出现时从记录中提取两队名称
                if not matches and cur_match is None:
                    if '-' in pa_full:
                        team_a = pa_full.split('-', 1)[0].strip()
                    if '-' in pb_full:
                        team_b = pb_full.split('-', 1)[0].strip()
                # 提取选手名（去掉队伍名-前缀）
                pa_name = pa_full.split('-', 1)[1] if '-' in pa_full else pa_full
                pb_name = pb_full.split('-', 1)[1] if '-' in pb_full else pb_full
                # 按队伍名把左右对应到 team_a/team_b（左右顺序不固定）
                sa, sb = score_part.split(':')
                sa, sb = int(sa), int(sb)
                if left_team == team_a:
                    player_a_side, player_b_side = pa_name, pb_name
                    a_won = sa > sb
                elif left_team == team_b:
                    player_a_side, player_b_side = pb_name, pa_name
                    a_won = sb > sa
                else:
                    # 队伍名与当前两支队伍都不匹配，跳过该行
                    continue
                # 场次标识：比赛类型 + 双方选手（已按队伍归位，与左右无关）
                identity = (match_type, player_a_side, player_b_side)
                # 判定一：场次标识变化 → 当前场结束，开始新场
                if cur_match is not None and identity != cur_identity:
                    matches.append(tuple(cur_match))
                    cur_match = None
                if cur_match is None:
                    cur_match = [match_type, player_a_side, 0, player_b_side, 0]
                    cur_identity = identity
                # 累计本场局分（cur_match = [类型, A选手, A局分, B选手, B局分]）
                if a_won:
                    cur_match[2] += 1
                else:
                    cur_match[4] += 1
                # 判定二（五场三胜制）：一方局分达到每场局数目标 → 本场结束，
                # 后续记录属下一场（同队同选手连续打两场时也能正确分场）
                if file_format == "五场三胜制":
                    target = {"三局二胜": 2, "五局三胜": 3, "七局四胜": 4}.get(file_games, 3)
                    if cur_match[2] >= target or cur_match[4] >= target:
                        matches.append(tuple(cur_match))
                        cur_match = None
                        cur_identity = None
            except Exception:
                continue

        # 文件结束时关闭最后一个场次
        if cur_match is not None:
            matches.append(tuple(cur_match))

        # 文件中没有任何"保存小分"记录时，退回从文件名解析两队名称
        if not matches:
            team_a, team_b = self._parse_team_names_from_filename(filepath)

        return team_a, team_b, matches, file_format, file_games

    # ---------- 历史赛制辅助 ----------
    def _recompute_team_score(self, matches, file_format, file_games):
        """按当时的赛制从"保存小分"场次数据计算队伍大分。
        五场三胜制按场计分：一方局分达到"每场局数"目标的场次计1分（与 _finalize_match_team_score 一致），
        未结束的场次不计分；十五局八胜制按局计分：累计双方获胜局数。"""
        ta = tb = 0
        if file_format == "15局8胜制":
            for _t, _pa, wa, _pb, wb in matches:
                ta += wa
                tb += wb
        else:
            target = {"三局二胜": 2, "五局三胜": 3, "七局四胜": 4}.get(file_games, 3)
            for _t, _pa, wa, _pb, wb in matches:
                if wa >= target:
                    ta += 1
                elif wb >= target:
                    tb += 1
        return ta, tb

    # ---------- 比赛结果全屏展示 ----------
    def show_match_result(self, filepath=None):
        """全屏显示比赛结果，黑底白字：上半队伍名与大分，左下队伍名，
           右下按场次展示五行明细（比赛类型/双方选手/双方局分），每列一场比赛。
           若传入 filepath，则显示指定文件的历史数据；
           若未传入 filepath，则使用当前计分文件。
           不论当前比赛情况如何，均可进入结果窗口；有几场数据展示几场，
           没有任何结果时展示一场 0:0。"""
        # 按钮点击时 QPushButton.clicked 信号会传入 checked (bool)，
        # 非字符串参数统一视为"未指定文件"
        if not isinstance(filepath, str):
            filepath = None
        if filepath is None:
            filepath = self.current_score_file

        if filepath is None:
            # 尚未进行任何比赛：显示当前队伍，无场次数据
            team_a, team_b, matches = \
                self.team_a_name, self.team_b_name, []
            file_format = file_games = None
        else:
            try:
                team_a, team_b, matches, file_format, file_games = \
                    self._parse_team_file(filepath)
            except _HistoryFileError as e:
                # 数据文件缺少"赛制信息"行等解析错误：提示后不打开结果窗口
                QMessageBox.information(None, "提示", str(e))
                return

        self._create_result_window(team_a, team_b, matches, file_format, file_games)

    # ---------- 创建比赛结果窗口 ----------
    def _create_result_window(self, team_a, team_b, matches,
                              file_format=None, file_games=None):
        """全屏显示比赛结果，黑底白字：上半队伍名与大分，左下队伍名，
           右下按场次展示五行明细（比赛类型/双方选手/双方局分），每列一场比赛。
           file_format/file_games 为该结果所用的赛制（历史文件从"赛制信息"记录读取），
           为 None 时表示当前比赛，赛制用当前程序设置。
           队伍大分：一律按当时的赛制从"保存小分"场次数据重新计算得出，
           不使用文件中的"保存大分""保存队伍大分"记录，也不使用程序内存中的队伍大分。"""
        n = len(matches)   # 有几场数据展示几场
        if n > 5:
            QMessageBox.information(None, "提示", "计分文件出错，请检查。场次数大于5场")
            return
        if n == 0:
            # 没有任何结果：展示一场 0:0（由当前比赛分析得出：一场未打 → 双方各0分）
            matches = [(self.match_type, self.player_a_name, 0, self.player_b_name, 0)]
            n = 1

        # 创建全屏窗口
        result_win = PlacedDialog(self.root)
        result_win.setWindowTitle("比赛结果")
        # 去掉窗口边框（无边框窗口）：Qt 在 Windows 上对带边框的 QDialog 执行
        # showFullScreen() 时，会把对话框框架居中，导致客户区整体左移约8像素——
        # 左侧内容（如队伍名的首字）被裁掉，右侧露出8像素空隙。
        # 设为无边框后，客户区才能精确对齐屏幕 (0,0)，铺满整个屏幕。
        result_win.setWindowFlags(
            result_win.windowFlags() | Qt.WindowType.FramelessWindowHint)
        result_win.setStyleSheet("background-color: black;")
        result_win.setModal(True)

        # ---------- 1. 顶部队伍大分区域（0~40%高度） ----------
        top_relh = 0.40
        # 队伍名称字体大小测算和显示
        labels_top_team_font_size = self._calc_font_size(0.35, top_relh, team_a, team_b)
        lb_team_a = self._make_label(result_win, team_a, "黑体", labels_top_team_font_size, 'white', 'black')
        result_win.place(lb_team_a, 0.00, 0.00, 0.35, top_relh)
        lb_team_b = self._make_label(result_win, team_b, "黑体", labels_top_team_font_size, 'white', 'black')
        result_win.place(lb_team_b, 0.65, 0.00, 0.35, top_relh)

        # 队伍大分字体大小测算和显示
        # 队伍大分一律按当时的赛制从"保存小分"场次数据重新计算得出，
        # 不使用文件中的"保存大分""保存队伍大分"记录，也不使用程序内存中的队伍大分
        team_score_display = self._recompute_team_score(matches, file_format, file_games)
        labels_top_ts_font_size = self._calc_font_size(0.12, top_relh, str(team_score_display[0]), str(team_score_display[1]))
        lb_ts_a = self._make_label(result_win, str(team_score_display[0]), "黑体", labels_top_ts_font_size, 'white', 'black')
        result_win.place(lb_ts_a, 0.35, 0.00, 0.12, top_relh)
        lb_ts_b = self._make_label(result_win, str(team_score_display[1]), "黑体", labels_top_ts_font_size, 'white', 'black')
        result_win.place(lb_ts_b, 0.53, 0.00, 0.12, top_relh)
        # 冒号字体大小测算和显示
        labels_top_colon_font_size = self._calc_fill_font_size(0.06, top_relh, ":")
        lb_colon = self._make_label(result_win, ":", "Arial", labels_top_colon_font_size, 'white', 'black')
        result_win.place(lb_colon, 0.47, 0.00, 0.06, top_relh)

        # 历史数据按钮 + 返回按钮（右上角）
        history_btn = self._make_button(
            result_win, "历史数据<h>", lambda: self._show_history_dialog(result_win),
            bordered=False)
        result_win.place(history_btn, 0.84, 0.01, 0.06, 0.03)
        ### 绑定快捷键H到"历史数据"功能（绑定到结果窗口本身：模态对话框期间主窗口
        ### 失焦，绑定到主窗口的快捷键不会响应；且需传入 result_win 以便刷新同一窗口）
        QShortcut(QKeySequence("H"), result_win).activated.connect(lambda: self._show_history_dialog(result_win))

        close_btn = self._make_button(
            result_win, "返回<r>", result_win.accept, bordered=False)
        result_win.place(close_btn, 0.94, 0.01, 0.06, 0.03)
        ### 绑定快捷键R到"返回"功能
        QShortcut(QKeySequence("R"), result_win).activated.connect(result_win.accept)
        
        # ---------- 2. 左侧下方队伍名（宽度30%，60%~80% 和 80%~100%） ----------
        left_name_font_size = self._calc_font_size(0.20, 0.30, team_a, team_b)
        lb_a = self._make_label(result_win, team_a, "宋体", left_name_font_size, 'white', 'black')
        result_win.place(lb_a, 0.0, 0.60, 0.30, 0.20)

        lb_b = self._make_label(result_win, team_b, "宋体", left_name_font_size, 'white', 'black')
        result_win.place(lb_b, 0.0, 0.80, 0.30, 0.20)

        # ---------- 3. 右侧场次明细（70%宽度，5行×n列，每列一场比赛） ----------
        # 五行内容：第1行比赛类型、第2行A队选手、第3行A选手局分、第4行B选手局分、第5行B队选手
        frame_detail = QWidget(result_win)
        frame_detail.setStyleSheet("background-color: black;")
        result_win.place(frame_detail, 0.30, 0.46, 0.70, 0.54)
        grid_detail = QGridLayout(frame_detail)
        grid_detail.setContentsMargins(0, 0, 0, 0)
        self._fill_detail_grid(grid_detail, matches, n)

        # 保存动态控件的引用，供 _refresh_result_window 更新
        result_win._top_team_a = lb_team_a
        result_win._top_team_b = lb_team_b
        result_win._top_ts_a = lb_ts_a
        result_win._top_ts_b = lb_ts_b
        result_win._left_team_a = lb_a
        result_win._left_team_b = lb_b
        result_win._frame_detail = frame_detail
        result_win._grid_detail = grid_detail

        # ESC键关闭：QDialog 默认按 ESC 触发 reject，等效于原版的 ESC 销毁窗口

        # 模态弹窗期间暂停手柄轮询（与原 tkinter wait_window 阻塞行为一致）
        self._pause_gamepad()
        result_win.showFullScreen()
        result_win.exec()
        self._resume_gamepad()

    # ---------- 填充右侧场次明细网格 ----------
    def _fill_detail_grid(self, grid, matches, n):
        """在 grid(QGridLayout) 中重新创建 5行×n列 的场次明细（每列一场比赛）。
        五行内容：第1行比赛类型、第2行A队选手、第3行A选手局分、第4行B选手局分、第5行B队选手"""
        # 先清除旧内容
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # 先清除所有旧列的权重（最多支持5列），防止历史数据刷新时
        # 上一次显示的列权重残留，导致分数列与标签列不对齐
        for i in range(5):
            grid.setColumnStretch(i, 1 if i < n else 0)
        for r in range(5):
            grid.setRowStretch(r, 1)
        grid.setSpacing(4)

        # 计算字体大小（基于每个格子的尺寸）
        cell_width = 0.70 / n
        cell_height = 0.54 / 5
        score_font_size = self._calc_fill_font_size(cell_width, cell_height, "99", family="宋体")
        name_font_size = self._calc_fill_font_size(cell_width, cell_height, "第X队选手名", family="宋体")

        for i in range(n):
            mtype, pa, wa, pb, wb = matches[i]
            # 判定本场负者：局分较少的一方为负者，其局分用灰色显示；
            # 局分相同（如比赛进行中、未分胜负）时无负者，双方均正常显示
            if wa > wb:
                color_wa, color_wb = 'white', '#888888'
            elif wb > wa:
                color_wa, color_wb = '#888888', 'white'
            else:
                color_wa = color_wb = 'white'
            # 第1行：比赛类型
            grid.addWidget(self._make_label(grid.parentWidget(), mtype, "宋体", name_font_size, '#888888', 'black'), 0, i)
            # 第2行：A队选手
            grid.addWidget(self._make_label(grid.parentWidget(), pa, "宋体", name_font_size, 'white', 'black'), 1, i)
            # 第3行：A选手局分
            grid.addWidget(self._make_label(grid.parentWidget(), str(wa), "Arial", score_font_size, color_wa, 'black'), 2, i)
            # 第4行：B选手局分
            grid.addWidget(self._make_label(grid.parentWidget(), str(wb), "Arial", score_font_size, color_wb, 'black'), 3, i)
            # 第5行：B队选手
            grid.addWidget(self._make_label(grid.parentWidget(), pb, "宋体", name_font_size, 'white', 'black'), 4, i)

    # ---------- 刷新比赛结果窗口内容（用于查看历史数据，不改变程序状态） ----------
    def _refresh_result_window(self, result_win, team_a, team_b, matches,
                               file_format=None, file_games=None):
        """在不销毁窗口的前提下，用新数据更新结果窗口的全部动态内容。
        file_format/file_games 为历史文件的赛制（None 表示当前比赛，用当前程序设置）。
        队伍大分一律按当时的赛制从"保存小分"场次数据重新计算得出。"""
        n = len(matches)   # 有几场数据展示几场
        if n > 5:
            n = 5
            matches = matches[-5:]
        if n == 0:
            # 没有任何结果：展示一场 0:0（由当前比赛分析得出：一场未打 → 双方各0分）
            matches = [(self.match_type, self.player_a_name, 0, self.player_b_name, 0)]
            n = 1

        top_relh = 0.40

        # 更新顶部队伍名
        font_size = self._calc_font_size(0.35, top_relh, team_a, team_b)
        result_win._top_team_a.setText(team_a)
        result_win._top_team_a.setFont(QFont("黑体", font_size))
        result_win._top_team_b.setText(team_b)
        result_win._top_team_b.setFont(QFont("黑体", font_size))

        # 更新顶部队伍大分（一律按当时的赛制从"保存小分"场次数据重新计算得出，
        # 不使用文件中的"保存大分""保存队伍大分"记录，也不使用程序内存中的队伍大分）
        team_score_display = self._recompute_team_score(matches, file_format, file_games)
        ts_font_size = self._calc_font_size(0.12, top_relh, str(team_score_display[0]), str(team_score_display[1]))
        result_win._top_ts_a.setText(str(team_score_display[0]))
        result_win._top_ts_a.setFont(QFont("黑体", ts_font_size))
        result_win._top_ts_b.setText(str(team_score_display[1]))
        result_win._top_ts_b.setFont(QFont("黑体", ts_font_size))

        # 更新左侧队伍名
        left_font_size = self._calc_font_size(0.20, 0.30, team_a, team_b)
        result_win._left_team_a.setText(team_a)
        result_win._left_team_a.setFont(QFont("宋体", left_font_size))
        result_win._left_team_b.setText(team_b)
        result_win._left_team_b.setFont(QFont("宋体", left_font_size))

        # 重建右侧场次明细网格
        self._fill_detail_grid(result_win._grid_detail, matches, n)

    # ---------- 历史数据浏览 ----------
    def _show_history_dialog(self, current_result_win=None):
        """弹出文件浏览对话框，让用户指定计分文件，然后将历史数据刷新到当前结果窗口。
        历史数据的展示仅为临时查看，不会改变程序当前设置的队伍、选手、大分和小分。
        PySide6 版说明：QFileDialog 使用 Windows 系统原生文件对话框，
        在全屏模式下浏览/取消均正常，不再需要 tkinter 版"退出全屏再恢复"的补丁。"""
        while True:
            chosen_path, _ = QFileDialog.getOpenFileName(
                current_result_win if current_result_win is not None else self.root,
                "选择历史比赛数据文件",
                ".",
                "计分文件 (Score_TeamEvents_*.txt);;文本文件 (*.txt);;所有文件 (*.*)")

            if not chosen_path:
                return  # 用户取消了选择

            # 验证文件名：以"Score_TeamEvents_"开头（团体赛计分文件）
            basename = os.path.basename(chosen_path)
            if not basename.startswith("Score_TeamEvents"):
                QMessageBox.information(
                    None, "提示", "所选文件不是本程序的团体赛计分文件，请重新选择。")
                continue

            # 读取选中文件（按文件自身的赛制信息解析，返回 file_format/file_games）
            try:
                team_a, team_b, matches, file_format, file_games = \
                    self._parse_team_file(chosen_path)
            except _HistoryFileError as e:
                # 数据文件缺少"赛制信息"行等解析错误：提示后留在文件选择循环，让用户重选
                QMessageBox.information(None, "提示", str(e))
                continue
            if not matches:
                QMessageBox.information(
                    None, "提示", "无法读取选中的文件或文件中没有比赛记录。")
                continue

            # 将历史数据刷新到当前结果窗口（不关闭窗口，不改变程序状态）
            if current_result_win is not None:
                self._refresh_result_window(
                    current_result_win, team_a, team_b, matches,
                    file_format, file_games)
            else:
                self._create_result_window(
                    team_a, team_b, matches, file_format, file_games)
            return

    # ================================================
    # 显示版权信息弹窗
    # 功能：创建版权信息弹窗，2秒后自动关闭，
    #       期间若有按键操作则取消自动关闭，
    #       需要用户手动关闭窗口
    # 参数：is_exit - 是否为退出时显示
    # ================================================
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

    # ================================================
    # 窗口关闭处理方法
    # 功能：先保存选手局分和队伍大分，然后隐藏主窗口，显示版权信息，最后退出程序
    # ================================================
    def on_closing(self):
        # 防止重复触发（ESC、Ctrl+C、Alt+F4 可能连续触发）
        if self._closing:
            return
        self._closing = True

        # 退出前暂停手柄轮询
        self._pause_gamepad()

        # 退出前结算最后一场比赛的队伍大分（五场三胜制按场计分）
        if self.wins_a or self.wins_b:
            self._finalize_match_team_score()
        # 退出前保存最终队伍大分
        if self.team_score_a or self.team_score_b:
            self.save_team_score()
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
