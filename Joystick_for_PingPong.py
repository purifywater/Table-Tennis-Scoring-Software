# ================================================
# 手柄按键配置程序 - Config_Joystick_IndividualEvents.py
# 功能：为单项/团体两个计分程序配置游戏手柄的六个功能按键，
#       配置完成后同时写入 Config_IndividualEvents.json 和
#       Config_TeamEvents.json 的手柄部分（各文件其它字段保持不变）
# 六个功能：左侧加分、左侧减分、右侧加分、右侧减分、本局结束、交换场地
# 支持：手柄按钮、方向键(上/下) 两种按键来源（与计分程序支持的范围一致）
# ================================================
# 开发者：姜恒
# 开发日期：2026年8月
# ================================================

import sys
import json
import os
import copy

import pygame
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QDialog,
    QMessageBox,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont, QGuiApplication

# ================================================
# 手柄按键默认配置（与两个计分程序的 DEFAULT_CONFIG 保持一致）
# ================================================
DEFAULT_JOYSTICK_BUTTONS = {
    "left_add_score":       {"type": "hat",    "value": 1},
    "left_subtract_score":  {"type": "hat",    "value": -1},
    "right_add_score":      {"type": "button", "value": 3},
    "right_subtract_score": {"type": "button", "value": 0},
    "new_over":             {"type": "button", "value": 1},
    "change_ends":          {"type": "button", "value": 2}
}

# ================================================
# 需要写入手柄配置的计分程序配置文件
# 每个文件保留自己的非手柄字段（选手姓名、赛制、队伍等）
# ================================================
CONFIG_FILES = [
    {
        "filename": "Config_IndividualEvents.json",
        "defaults": {
            "player_a_name": "选手A",
            "player_b_name": "选手B",
            "joystick_buttons": copy.deepcopy(DEFAULT_JOYSTICK_BUTTONS),
        },
    },
    {
        "filename": "Config_TeamEvents.json",
        "defaults": {
            "match_format": "五场三胜制",
            "match_type": "男单",
            "team_a_name": "队伍A",
            "team_b_name": "队伍B",
            "player_a_name": "选手A",
            "player_b_name": "选手B",
            "joystick_buttons": copy.deepcopy(DEFAULT_JOYSTICK_BUTTONS),
        },
    },
]

# 六个功能及其中文显示名称
FUNCTIONS = [
    ("left_add_score", "左侧加分"),
    ("left_subtract_score", "左侧减分"),
    ("right_add_score", "右侧加分"),
    ("right_subtract_score", "右侧减分"),
    ("new_over", "本局结束"),
    ("change_ends", "交换场地"),
]

FUNCTION_LABELS = dict(FUNCTIONS)


def get_config_path(filename):
    """返回指定配置文件路径（脚本或 exe 所在目录）"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def get_icon_path():
    """返回程序图标文件路径（脚本或 exe 所在目录）"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "IndividualEvents.ico")


class JoystickConfigApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("乒乓球计分手柄按键配置")
        self.setWindowIcon(QIcon(get_icon_path()))

        self.configs = {}          # 各配置文件内容（默认值+已存字段）
        self.joystick_buttons = {} # 正在编辑的六个功能键映射
        self.load_all_configs()
        self.joystick_buttons = copy.deepcopy(self.configs[CONFIG_FILES[0]["filename"]]["joystick_buttons"])

        # 初始化手柄
        pygame.init()
        pygame.joystick.init()
        self.joystick = None
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
        else:
            return  # 无手柄时由 main() 提示错误并退出

        self.waiting_key = None   # 正在等待按键的功能 key，None 表示当前不在等待状态
        self.armed = False        # 是否已松开所有按键，允许捕获（避免按住状态被误捕获）

        self.setup_ui()
        self.refresh_rows()

        # 轮询捕获手柄按键
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    # ---------- 读取所有配置文件（保留各文件非手柄字段） ----------
    def load_all_configs(self):
        for entry in CONFIG_FILES:
            filename = entry["filename"]
            cfg = copy.deepcopy(entry["defaults"])
            path = get_config_path(filename)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for key in entry["defaults"]:
                            if key in data:
                                cfg[key] = data[key]
                except (json.JSONDecodeError, OSError):
                    pass
            # 确保 joystick_buttons 六个功能项完整
            if not isinstance(cfg.get("joystick_buttons"), dict):
                cfg["joystick_buttons"] = copy.deepcopy(DEFAULT_JOYSTICK_BUTTONS)
            for k in DEFAULT_JOYSTICK_BUTTONS:
                if k not in cfg["joystick_buttons"]:
                    cfg["joystick_buttons"][k] = copy.deepcopy(DEFAULT_JOYSTICK_BUTTONS[k])
            self.configs[filename] = cfg

    # ---------- UI ----------
    @staticmethod
    def cjk_width(widget, n):
        """以全角字符宽度为单位的固定宽度（近似 tkinter 的字符宽度）"""
        return n * widget.fontMetrics().horizontalAdvance("中")

    def setup_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(22, 20, 22, 20)
        root_layout.setSpacing(12)

        # 手柄信息
        info = (
            f"手柄名称：{self.joystick.get_name()}\n"
            # f"按钮数量：{self.joystick.get_numbuttons()}　"
            # f"方向键数量：{self.joystick.get_numhats()}　"
            # f"摇杆数量：{self.joystick.get_numaxes()}"
        )
        self.info_label = QLabel(info)
        self.info_label.setFont(QFont("宋体", 11))
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("color: #444444;")
        root_layout.addWidget(self.info_label)

        # 状态栏
        self.status_label = QLabel("点击【配置】按钮，然后按下手柄上的按键")
        self.status_label.setFont(QFont("宋体", 12))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status("点击【配置】按钮，然后按下手柄上的按键")
        root_layout.addWidget(self.status_label)

        # 功能行
        self.row_widgets = {}
        rows_container = QWidget()
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(13)
        root_layout.addWidget(rows_container)

        for key, label_text in FUNCTIONS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(14)

            name_lbl = QLabel(f"{label_text}：")
            name_lbl.setFont(QFont("宋体", 14))
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            name_lbl.setFixedWidth(self.cjk_width(name_lbl, 6))  # ≈ tkinter width=10
            row_layout.addWidget(name_lbl)

            binding_lbl = QLabel("")
            binding_lbl.setFont(QFont("宋体", 14))
            binding_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            binding_lbl.setMinimumWidth(self.cjk_width(binding_lbl, 10))  # ≈ tkinter width=16
            binding_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row_layout.addWidget(binding_lbl)

            btn = QPushButton("配置")
            btn.setFont(QFont("宋体", 12))
            btn.setFixedWidth(self.cjk_width(btn, 5) + 16)  # ≈ tkinter width=6
            btn.clicked.connect(lambda checked=False, k=key: self.on_config_click(k))
            row_layout.addWidget(btn)

            rows_layout.addWidget(row)
            self.row_widgets[key] = {"binding": binding_lbl, "config_btn": btn}

        # 底部按钮
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(22)
        bottom_layout.addStretch(1)

        btn_default = QPushButton("恢复默认")
        btn_default.setFont(QFont("宋体", 12))
        btn_default.setFixedWidth(self.cjk_width(btn_default, 6))  # ≈ tkinter width=10
        btn_default.clicked.connect(self.reset_default)
        bottom_layout.addWidget(btn_default)

        btn_save = QPushButton("保存")
        btn_save.setFont(QFont("宋体", 12))
        btn_save.setFixedWidth(self.cjk_width(btn_save, 6))
        btn_save.clicked.connect(self.save_config)
        bottom_layout.addWidget(btn_save)

        btn_quit = QPushButton("退出")
        btn_quit.setFont(QFont("宋体", 12))
        btn_quit.setFixedWidth(self.cjk_width(btn_quit, 6))
        btn_quit.clicked.connect(self.quit)
        bottom_layout.addWidget(btn_quit)

        bottom_layout.addStretch(1)
        root_layout.addWidget(bottom)

        # 固定窗口大小（窗口不可拉伸）并居中
        # 宽度随内容（手柄名称长度）自然计算后放大 8%（在放大 20% 基础上缩窄 10%）；
        # 高度由下方各控件间距撑起
        self.adjustSize()
        self.setFixedSize(int(self.size().width() * 1.08),
                          self.size().height())
        self.center_window()

    def refresh_rows(self):
        """把配置刷新到各功能行显示"""
        for key, widget in self.row_widgets.items():
            widget["binding"].setText(self.binding_text(self.joystick_buttons[key]))
            widget["binding"].setStyleSheet("color: black;")

    def center_window(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    # ---------- 按钮名称映射（常见手柄的按钮编号 → 名称）----------
    # Xbox / Nintendo 布局: 0=A, 1=B, 2=X, 3=Y
    # PlayStation 布局:   0=✕, 1=○, 2=□, 3=△
    BUTTON_NAMES = {
        0: "A", 1: "B", 2: "X", 3: "Y",
        4: "LB", 5: "RB", 6: "Back", 7: "Start",
        8: "左摇杆按下", 9: "右摇杆按下",
        10: "Guide", 11: "Share",
    }

    # ---------- 绑定显示文本 ----------
    @staticmethod
    def binding_text(binding):
        t = binding.get("type")
        v = binding.get("value")
        if t == "hat":
            if v == 1:
                return "方向键(上)"
            if v == -1:
                return "方向键(下)"
            return f"方向键(值{v})"
        name = JoystickConfigApp.BUTTON_NAMES.get(v)
        if name:
            return f"按钮{name}"
        return f"按钮{v}"

    # ---------- 等待按键 ----------
    def on_config_click(self, key):
        if self.waiting_key == key:
            self.cancel_waiting()
        else:
            self.start_waiting(key)

    def start_waiting(self, key):
        self.waiting_key = key
        self.armed = False  # 需要先松开所有按键，再等待新的按下
        self.set_status(f"请按下【{FUNCTION_LABELS[key]}】对应的按键，按 Esc 取消")
        for k, widget in self.row_widgets.items():
            if k == key:
                widget["binding"].setText("等待按键...")
                widget["binding"].setStyleSheet("color: orange;")
                widget["config_btn"].setText("取消")
            else:
                widget["config_btn"].setEnabled(False)

    def cancel_waiting(self):
        if self.waiting_key is not None:
            self.waiting_key = None
            self.armed = False
            self.set_status("已取消", color="red")
            self.refresh_rows()
            for k, widget in self.row_widgets.items():
                widget["config_btn"].setText("配置")
                widget["config_btn"].setEnabled(True)

    def set_status(self, text, color="green"):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")

    # ---------- 捕获按键 ----------
    def poll(self):
        if self.waiting_key is not None and self.joystick is not None:
            # 先判断是否已松开所有按键（避免按住状态被误捕获）
            pressed = False
            for i in range(self.joystick.get_numbuttons()):
                if self.joystick.get_button(i):
                    pressed = True
                    break
            hat_off = False
            for i in range(self.joystick.get_numhats()):
                x, y = self.joystick.get_hat(i)
                if x != 0 or y != 0:
                    hat_off = True
                    break
            if not pressed and not hat_off:
                self.armed = True

            if self.armed:
                captured = False
                for i in range(self.joystick.get_numbuttons()):
                    if self.joystick.get_button(i):
                        self.capture({"type": "button", "value": i})
                        captured = True
                        break
                if not captured:
                    for i in range(self.joystick.get_numhats()):
                        x, y = self.joystick.get_hat(i)
                        if y != 0:   # 计分程序只支持方向键上/下（y 轴）
                            self.capture({"type": "hat", "value": y})
                            break

    def capture(self, binding):
        key = self.waiting_key
        if key is None:
            return
        self.joystick_buttons[key] = binding
        self.finish_waiting()
        self.set_status(f"【{FUNCTION_LABELS[key]}】绑定为：{self.binding_text(binding)}")

    def finish_waiting(self):
        self.waiting_key = None
        self.armed = False
        self.refresh_rows()
        for k, widget in self.row_widgets.items():
            widget["config_btn"].setText("配置")
            widget["config_btn"].setEnabled(True)

    # ---------- 恢复默认 ----------
    def reset_default(self):
        if self.show_custom_dialog("恢复默认", "确定要恢复默认按键配置吗？", confirm=True):
            self.waiting_key = None
            self.armed = False
            self.joystick_buttons = copy.deepcopy(DEFAULT_JOYSTICK_BUTTONS)
            self.refresh_rows()
            for k, widget in self.row_widgets.items():
                widget["config_btn"].setText("配置")
                widget["config_btn"].setEnabled(True)
            self.write_config(show_dialog=False)
            self.set_status("已恢复默认配置并保存")

    # ---------- 自定义提示对话框（按钮居中） ----------
    def show_custom_dialog(self, title, message, is_error=False, confirm=False):
        """显示按钮居中的自定义对话框。
        confirm=False: 单个"确定"按钮
        confirm=True:  "确定"+"取消"两个按钮，返回 True/False"""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setWindowIcon(QIcon(get_icon_path()))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        fg_color = "#cc0000" if is_error else "#333333"

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)

        msg_label = QLabel(message)
        msg_label.setFont(QFont("宋体", 12))
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setStyleSheet(f"color: {fg_color};")
        layout.addWidget(msg_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        # 普通大小按钮：不设为醒目的默认按钮，也不随窗口变宽而拉伸
        ok_btn = QPushButton("确定")
        ok_btn.setFont(QFont("宋体", 12))
        ok_btn.setAutoDefault(True)
        ok_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        ok_btn.setFocus()

        if confirm:
            cancel_btn = QPushButton("取消")
            cancel_btn.setFont(QFont("宋体", 12))
            cancel_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            cancel_btn.clicked.connect(dlg.reject)
            btn_layout.addWidget(cancel_btn)

            ok_btn.clicked.connect(dlg.accept)
            btn_layout.addWidget(ok_btn)
        else:
            ok_btn.clicked.connect(dlg.accept)
            btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

        # 居中于父窗口
        dlg.adjustSize()
        dlg.move(self.x() + (self.width() - dlg.width()) // 2,
                 self.y() + (self.height() - dlg.height()) // 2)

        result = dlg.exec()
        return result == QDialog.DialogCode.Accepted

    # ---------- 保存（同时写入两个配置文件的手柄部分） ----------
    def write_config(self, show_dialog=True):
        ok = True
        first_error = None
        for entry in CONFIG_FILES:
            filename = entry["filename"]
            # 基于该文件已有内容（或默认值）构造完整配置，仅更新手柄部分
            cfg = copy.deepcopy(entry["defaults"])
            if filename in self.configs:
                for key in entry["defaults"]:
                    if key in self.configs[filename]:
                        cfg[key] = copy.deepcopy(self.configs[filename][key])
            cfg["joystick_buttons"] = copy.deepcopy(self.joystick_buttons)
            path = get_config_path(filename)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=4)
            except OSError as e:
                ok = False
                if show_dialog:
                    first_error = (path, e)
                else:
                    self.set_status(f"保存失败：{e}", color="red")
        if show_dialog:
            if first_error:
                path, e = first_error
                self.show_custom_dialog("保存失败",
                    f"无法写入配置文件：\n{path}\n{e}", is_error=True)
            elif ok:
                self.show_custom_dialog("保存成功",
                    "配置已写入：\n"
                    + "\n".join(entry["filename"] for entry in CONFIG_FILES))
        return ok

    def find_all_conflicts(self):
        """检查所有功能之间是否有重复按键，返回重复的按键列表"""
        conflicts = []
        seen = {}  # binding_tuple -> (function_key, label)
        for key, label_text in FUNCTIONS:
            binding = self.joystick_buttons.get(key)
            if binding is None:
                continue
            binding_tuple = (binding["type"], binding["value"])
            if binding_tuple in seen:
                other_label = seen[binding_tuple][1]
                conflicts.append((label_text, other_label, self.binding_text(binding)))
            else:
                seen[binding_tuple] = (key, label_text)
        return conflicts

    def save_config(self):
        # 先检查重复按键
        conflicts = self.find_all_conflicts()
        if conflicts:
            msg = "以下按键存在重复使用，请修正后重新保存：\n"
            for label1, label2, btn_text in conflicts:
                msg += f"\n【{label1}】和【{label2}】都绑定了 {btn_text}"
            self.show_custom_dialog("按键重复", msg, is_error=True)
            return
        self.write_config(show_dialog=True)

    def quit(self):
        self.close()

    # ---------- 事件处理 ----------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_waiting()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = JoystickConfigApp()
    if window.joystick is None:
        QMessageBox.critical(None, "错误", "未检测到游戏手柄，请连接手柄后重试。")
        pygame.quit()
        return 0
    window.show()
    code = app.exec()
    pygame.quit()
    return code


if __name__ == "__main__":
    sys.exit(main())
