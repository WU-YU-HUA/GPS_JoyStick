"""PySide6 interface for the iPhone GPS joystick."""

import asyncio
import json
import logging
import queue
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from controller import JoystickController, MovementController
from controller.movement import KEY_DIRECTIONS
from ui.schema import (
    ACTION_LABELS,
    APP_TITLE,
    COORDINATE_FIELDS,
    COORDINATE_PANELS,
    DIRECTION_GRID,
    MODE_OPTIONS,
    MOTION_HELP,
    RECORD_COLUMNS,
    RECORD_EDIT_FIELDS,
    RECORD_ACTIONS,
    PYSIDE_COMPONENT_LAYOUT,
    SCREEN_COMPONENTS,
    SECTION_TITLES,
    SPEED_FIELD,
)


APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1]
)
CONFIG_PATH = APP_DIR / "config.json"
RECORD_PATH = APP_DIR / "record.json"

QT_KEY_NAMES = {
    Qt.Key.Key_W: "w",
    Qt.Key.Key_A: "a",
    Qt.Key.Key_S: "s",
    Qt.Key.Key_D: "d",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Right: "right",
}

def card(title, description=""):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(10)
    heading = QLabel(title)
    heading.setObjectName("cardTitle")
    layout.addWidget(heading)
    if description:
        detail = QLabel(description)
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        layout.addWidget(detail)
    return frame, layout


class DirectionButton(QPushButton):
    """A direction pad button that supports hold and double-click lock."""

    def __init__(self, text, direction, window):
        super().__init__(text, window)
        self.direction = direction
        self.joystick_window = window
        self.setObjectName("directionButton")
        self.setMinimumSize(82, 62)
        self.setProperty("active", False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.joystick_window.begin_mouse_direction(self.direction)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.joystick_window.release_mouse_direction()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.joystick_window.lock_direction(*self.direction)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class JoystickWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.controller = JoystickController(CONFIG_PATH, RECORD_PATH)
        self.events = queue.Queue()
        self.worker = None
        self.movement = MovementController()
        self.active_navigation = None
        self.connected = False
        self.closing = False
        self.allow_close = False
        self.cleanup_error = False
        self.locating = False
        self.location_controls_locked = False
        self.computer_position_ready = False
        self.computer_position = None
        self.last_confirmed = None
        self.records = self.controller.records
        self.position = self.controller.position
        self.speed_kmh = self.controller.speed_kmh
        self.load_error = self.controller.load_error

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1000, 760)
        self.resize(1160, 860)
        self.setStyleSheet(STYLE)
        self._build_ui()
        self.reload_records()
        self.write_log(self.load_error or f"啟動時從 {CONFIG_PATH.name} 載入座標。")

        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll_events)
        self.timer.start()
        app = QApplication.instance()
        if app:
            app.focusChanged.connect(self.on_focus_changed)

    def _build_ui(self):
        outer = QWidget()
        self.setCentralWidget(outer)
        page = QVBoxLayout(outer)
        page.setContentsMargins(24, 20, 24, 18)
        page.setSpacing(16)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        subtitle = QLabel("設定起點、管理收藏地點，並用鍵盤或方向鍵控制移動")
        subtitle.setObjectName("muted")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch(1)
        self.connection_badge = QLabel("尚未連線")
        self.connection_badge.setObjectName("statusBadge")
        header.addWidget(self.connection_badge, alignment=Qt.AlignmentFlag.AlignTop)
        page.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page.addWidget(scroll, 1)
        columns = QWidget()
        scroll.setWidget(columns)
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 8, 0)
        columns_layout.setSpacing(16)
        left = QVBoxLayout()
        right = QVBoxLayout()
        left.setSpacing(14)
        right.setSpacing(14)
        columns_layout.addLayout(left, 11)
        columns_layout.addLayout(right, 10)

        renderers = {
            "settings": self._build_start_card,
            "directions": self._build_joystick_card,
            "records": self._build_records_card,
            "log": self._build_log_card,
        }
        self.component_frames = {}
        for area, parent_layout in (("primary", left), ("secondary", right)):
            for component_id in PYSIDE_COMPONENT_LAYOUT[area]:
                component_spec = SCREEN_COMPONENTS.get(component_id, {})
                renderer_name = component_spec.get("renderer", component_id)
                self.component_frames[component_id] = renderers[renderer_name](parent_layout)
        for component_id, frame in self.component_frames.items():
            if not SCREEN_COMPONENTS.get(component_id, {}).get("enabled", False):
                frame.hide()

        footer = QLabel(
            "中斷或關閉時會保存最後成功送出的座標並送出清除要求；"
            "請在 Apple Maps 確認真實定位是否恢復。"
        )
        footer.setObjectName("footer")
        footer.setWordWrap(True)
        page.addWidget(footer)

    def _build_start_card(self, parent_layout):
        frame, layout = card(
            SECTION_TITLES.get("settings", ""),
            "電腦位置使用作業系統定位服務；連線後可用 WASD、方向鍵或下方方向盤移動。",
        )
        parent_layout.addWidget(frame)

        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        mode_widgets = {}
        for mode_id, label in MODE_OPTIONS:
            button = QRadioButton(label)
            mode_widgets[mode_id] = button
        self.custom_mode = mode_widgets["custom"]
        self.computer_mode = mode_widgets["computer"]
        self.custom_mode.setChecked(True)
        self.mode_group.addButton(self.custom_mode, 0)
        self.mode_group.addButton(self.computer_mode, 1)
        self.custom_mode.toggled.connect(self.change_mode)
        self.computer_mode.toggled.connect(self.change_mode)
        mode_row.addWidget(self.custom_mode)
        mode_row.addWidget(self.computer_mode)
        mode_row.addStretch(1)
        self.locate_button = QPushButton(ACTION_LABELS["locate"])
        self.locate_button.setObjectName("secondaryButton")
        self.locate_button.clicked.connect(self.fetch_computer_position)
        mode_row.addWidget(self.locate_button)
        layout.addLayout(mode_row)

        coordinate_row = QHBoxLayout()
        coordinate_row.setSpacing(10)
        self.coordinate_edits = {}
        for panel_spec in COORDINATE_PANELS:
            coordinate_panel, panel_layout = self._coordinate_panel(panel_spec["title"])
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            for row, field_id in enumerate(panel_spec["fields"]):
                field_spec = COORDINATE_FIELDS[field_id]
                grid.addWidget(QLabel(field_spec["label"]), row, 0)
                initial = ""
                if field_id == "latitude":
                    initial = f"{self.position[0]:.8f}"
                elif field_id == "longitude":
                    initial = f"{self.position[1]:.8f}"
                entry = QLineEdit(initial)
                entry.setPlaceholderText(field_spec["placeholder"])
                self.coordinate_edits[field_id] = entry
                grid.addWidget(entry, row, 1)
            grid.setColumnStretch(1, 1)
            panel_layout.addLayout(grid)
            if panel_spec["id"] == "destination":
                self.navigate_button = QPushButton(ACTION_LABELS["navigate"])
                self.navigate_button.setObjectName("secondaryButton")
                self.navigate_button.setEnabled(False)
                self.navigate_button.clicked.connect(self.start_navigation)
                panel_layout.addWidget(self.navigate_button)
            coordinate_row.addWidget(coordinate_panel, 1)
        self.latitude_edit = self.coordinate_edits["latitude"]
        self.longitude_edit = self.coordinate_edits["longitude"]
        self.destination_latitude_edit = self.coordinate_edits["destination_latitude"]
        self.destination_longitude_edit = self.coordinate_edits["destination_longitude"]
        layout.addLayout(coordinate_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel(SPEED_FIELD["label"]))
        self.speed_edit = QLineEdit(f"{self.speed_kmh:g}")
        self.speed_edit.setMaximumWidth(120)
        self.speed_edit.setPlaceholderText("km/h")
        speed_row.addWidget(self.speed_edit)
        speed_row.addWidget(QLabel(SPEED_FIELD["unit"]))
        self.apply_speed_button = QPushButton(ACTION_LABELS["apply_speed"])
        self.apply_speed_button.setObjectName("secondaryButton")
        self.apply_speed_button.clicked.connect(self.apply_speed)
        speed_row.addWidget(self.apply_speed_button)
        speed_row.addStretch(1)
        layout.addLayout(speed_row)

        self.action_button = QPushButton(ACTION_LABELS["connect"])
        self.action_button.setObjectName("primaryButton")
        self.action_button.clicked.connect(self.toggle_connection)
        layout.addWidget(self.action_button)
        self.clear_button = QPushButton(ACTION_LABELS["clear"])
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self.clear_location)
        layout.addWidget(self.clear_button)

        self.status_label = QLabel("尚未連線。請接上 USB、解鎖 iPhone。")
        self.status_label.setObjectName("statusText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return frame

    @staticmethod
    def _coordinate_panel(title):
        panel = QFrame()
        panel.setObjectName("coordinatePanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(11, 10, 11, 11)
        panel_layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("coordinateTitle")
        panel_layout.addWidget(heading)
        return panel, panel_layout

    def _build_joystick_card(self, parent_layout):
        frame, layout = card(
            SECTION_TITLES.get("directions", ""),
            "按住方向鍵移動，放開即停止；雙擊方向可鎖定。切離視窗會放開鍵盤移動。",
        )
        parent_layout.addWidget(frame)
        pad = QGridLayout()
        pad.setHorizontalSpacing(8)
        pad.setVerticalSpacing(8)
        self.direction_buttons = {}
        for row, cells in enumerate(DIRECTION_GRID):
            for column, (text, east, north) in enumerate(cells):
                direction = (east, north)
                if direction == (0, 0):
                    button = QPushButton(ACTION_LABELS["stop"])
                    button.setObjectName("stopButton")
                    button.setMinimumSize(82, 62)
                    button.clicked.connect(self.release_all)
                else:
                    button = DirectionButton(text, direction, self)
                    button.setToolTip("按住移動，雙擊鎖定方向")
                    self.direction_buttons[direction] = button
                pad.addWidget(button, row, column)
        for column in range(3):
            pad.setColumnStretch(column, 1)
        layout.addLayout(pad)
        self.motion_label = QLabel("停止")
        self.motion_label.setObjectName("motionLabel")
        self.motion_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.motion_label)
        note = QLabel("\n".join(MOTION_HELP) + "\n斜向移動的總速度與直行相同。移動方向依地理北方。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        return frame

    def _build_records_card(self, parent_layout):
        frame, layout = card(
            SECTION_TITLES.get("records", ""),
            "收藏資料保存在程式旁的 record.json。選取後可帶入座標或編輯地點。",
        )
        parent_layout.addWidget(frame, 1)
        add_row = QHBoxLayout()
        self.record_label_edit = QLineEdit()
        self.record_label_edit.setPlaceholderText("地點標籤（可留空）")
        add_row.addWidget(self.record_label_edit, 1)
        self.record_button = QPushButton(ACTION_LABELS["record_current"])
        self.record_button.setObjectName("secondaryButton")
        self.record_button.clicked.connect(self.record_current_position)
        add_row.addWidget(self.record_button)
        layout.addLayout(add_row)

        self.record_table = QTableWidget(0, 3)
        self.record_table.setHorizontalHeaderLabels([label for _column, label in RECORD_COLUMNS])
        self.record_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.record_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.record_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.record_table.setAlternatingRowColors(True)
        self.record_table.setMinimumHeight(235)
        self.record_table.verticalHeader().setVisible(False)
        header = self.record_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.record_table.itemSelectionChanged.connect(self.refresh_record_selection)
        self.record_table.cellDoubleClicked.connect(lambda _row, _col: self.use_record())
        layout.addWidget(self.record_table)

        actions = QGridLayout()
        action_buttons = {}
        for action in RECORD_ACTIONS:
            button = QPushButton(action["label"])
            button.clicked.connect(getattr(self, action["handler"]))
            action_buttons[action["id"]] = button
        self.use_record_button = action_buttons["use_record"]
        self.edit_record_button = action_buttons["edit_record"]
        self.update_record_button = action_buttons["update_record"]
        self.delete_record_button = action_buttons["delete_record"]
        self.reload_records_button = action_buttons["reload_records"]
        for index, action in enumerate(RECORD_ACTIONS):
            button = action_buttons[action["id"]]
            button.setObjectName("secondaryButton")
            actions.addWidget(button, index // 3, index % 3)
        layout.addLayout(actions)
        return frame

    def _build_log_card(self, parent_layout):
        frame, layout = card(SECTION_TITLES.get("log", ""), "完整錯誤內容也會寫入程式旁的 gps.log。")
        parent_layout.addWidget(frame)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        self.log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.log_view)
        return frame

    def write_log(self, message):
        logging.info(message)
        self.log_view.append(message)

    def set_status(self, message, *, connected=None):
        self.status_label.setText(message)
        if connected is True:
            self.connection_badge.setText("已連線")
            self.connection_badge.setProperty("connected", True)
        elif connected is False:
            self.connection_badge.setText("尚未連線")
            self.connection_badge.setProperty("connected", False)
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def is_busy(self):
        return bool(self.worker or self.locating or self.closing)

    def set_location_controls_locked(self, locked):
        if locked == self.location_controls_locked:
            return
        self.location_controls_locked = locked
        self.centralWidget().setEnabled(not locked)

    def change_mode(self, _checked=False):
        if not hasattr(self, "computer_mode"):
            return
        self.computer_position_ready = False
        self.refresh_controls()
        if self.computer_mode.isChecked():
            self.fetch_computer_position()

    def refresh_controls(self):
        busy = self.is_busy()
        computer = self.computer_mode.isChecked()
        self.custom_mode.setEnabled(not busy)
        self.computer_mode.setEnabled(not busy)
        self.latitude_edit.setEnabled(not busy and not computer)
        self.longitude_edit.setEnabled(not busy and not computer)
        self.navigate_button.setEnabled(self.connected and not self.closing)
        self.locate_button.setEnabled(not busy and computer)
        self.speed_edit.setEnabled(not self.closing)
        self.apply_speed_button.setEnabled(not self.closing and not self.locating)

        if self.worker:
            if self.connected:
                self.action_button.setText(ACTION_LABELS["disconnect"])
                self.action_button.setEnabled(True)
            elif self.worker.stop_requested.is_set():
                self.action_button.setText("正在中斷連線並清除…")
                self.action_button.setEnabled(False)
            else:
                label = "正在清除，請保持 USB 連接…" if self.worker.clear_only else "正在連線…"
                self.action_button.setText(label)
                self.action_button.setEnabled(False)
        else:
            ready = not computer or self.computer_position_ready
            self.action_button.setText(ACTION_LABELS["connect"])
            self.action_button.setEnabled(not busy and ready)
        self.clear_button.setEnabled(not busy)
        self.clear_button.setText(ACTION_LABELS["clear"])
        self.record_button.setEnabled(not self.closing and not self.locating and not (self.worker and not self.connected))
        can_edit_records = not self.closing and not self.locating and not (self.worker and not self.connected)
        self.use_record_button.setEnabled(not busy)
        self.edit_record_button.setEnabled(can_edit_records and self.selected_record_index_or_none() is not None)
        self.delete_record_button.setEnabled(can_edit_records and self.selected_record_index_or_none() is not None)
        self.reload_records_button.setEnabled(not self.closing and not self.locating)
        self.update_record_button.setEnabled(can_edit_records and self.selected_record_index_or_none() is not None)

    def apply_speed(self):
        if self.closing:
            return
        self.release_all()
        try:
            speed = self.controller.apply_speed(
                self.speed_edit.text(), self.position, self.last_confirmed, self.worker
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "無法套用速度", str(exc))
            return
        self.speed_kmh = speed
        self.speed_edit.setText(f"{speed:g}")
        self.set_status(f"速度已設為 {speed:g} km/h，已保存至 config.json。")
        self.setFocus()

    def start_navigation(self):
        if not self.connected or not self.worker or self.closing:
            self.set_status("請先連線至現在地，再開始自動前往。")
            return
        try:
            destination = self.controller.validate_destination(
                self.destination_latitude_edit.text(),
                self.destination_longitude_edit.text(),
            )
        except ValueError as exc:
            QMessageBox.critical(self, "目的地無效", str(exc))
            return
        self.release_all()
        self.active_navigation = self.controller.navigate(
            self.worker,
            connected=self.connected,
            closing=self.closing,
            destination=destination,
        )
        self.update_direction()
        self.set_status("正在直線前往目的地；到達後會停止。點停止或使用移動鍵可取消。")
        self.setFocus()

    def reload_records(self):
        try:
            records = self.controller.reload_records()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.set_status(f"無法讀取 record.json：{exc}；原檔保留，請修正後重新讀取。")
            self.write_log(f"讀取收藏失敗：{exc}")
            return False
        self.records = records
        self.record_table.setRowCount(0)
        for record in records:
            row = self.record_table.rowCount()
            self.record_table.insertRow(row)
            values = (
                record["label"] or "（未命名）",
                f'{record["latitude"]:.8f}',
                f'{record["longitude"]:.8f}',
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.record_table.setItem(row, column, item)
        self.refresh_controls()
        return True

    def selected_record_index_or_none(self):
        rows = self.record_table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def selected_record_index(self):
        index = self.selected_record_index_or_none()
        if index is None:
            self.set_status("請先選取一個收藏地點。")
        return index

    def refresh_record_selection(self):
        self.refresh_controls()

    def current_record_position(self):
        return self.controller.current_record_position(
            connected=self.connected,
            last_confirmed=self.last_confirmed,
            mode="computer" if self.computer_mode.isChecked() else "custom",
            computer_position_ready=self.computer_position_ready,
            latitude=self.latitude_edit.text(),
            longitude=self.longitude_edit.text(),
        )

    def record_current_position(self):
        if self.closing or self.locating or (self.worker and not self.connected):
            return
        self.release_all()
        try:
            position = self.current_record_position()
            self.records = self.controller.add_record(self.record_label_edit.text(), position)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "紀錄失敗", str(exc))
            return
        if self.reload_records():
            self.record_table.selectRow(len(self.records) - 1)
            self.record_table.scrollToBottom()
        self.set_status("地點已加入 record.json。")
        self.record_label_edit.clear()
        self.setFocus()

    def use_record(self):
        if self.worker or self.locating or self.closing:
            self.set_status("請先中斷連線，再使用收藏地點。")
            return
        index = self.selected_record_index()
        if index is None:
            return
        record = self.records[index]
        self.custom_mode.setChecked(True)
        self.latitude_edit.setText(f'{record["latitude"]:.8f}')
        self.longitude_edit.setText(f'{record["longitude"]:.8f}')
        self.set_status(f'已選取 {record["label"] or "未命名地點"}，按連線前往。')
        self.setFocus()

    def update_record_position(self):
        if self.closing or self.locating or (self.worker and not self.connected):
            return
        index = self.selected_record_index()
        if index is None:
            return
        self.release_all()
        try:
            position = self.current_record_position()
            self.records = self.controller.update_record_position(index, position)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "更新地標失敗", str(exc))
            return
        if self.reload_records():
            self.record_table.selectRow(index)
            self.record_table.scrollToItem(self.record_table.item(index, 0))
        self.set_status("所選地標的經緯度已更新至 record.json，標籤保持不變。")
        self.setFocus()

    def edit_record(self):
        if self.closing or self.locating or (self.worker and not self.connected):
            return
        index = self.selected_record_index()
        if index is None:
            return
        self.release_all()
        original = [dict(record) for record in self.records]
        record = original[index]
        dialog = QDialog(self)
        dialog.setWindowTitle("編輯收藏地點")
        dialog.setMinimumWidth(390)
        form = QFormLayout(dialog)
        label_edit = QLineEdit(record["label"])
        latitude_edit = QLineEdit(str(record["latitude"]))
        longitude_edit = QLineEdit(str(record["longitude"]))
        edit_fields = dict(RECORD_EDIT_FIELDS)
        form.addRow(edit_fields["label"], label_edit)
        form.addRow(edit_fields["latitude"], latitude_edit)
        form.addRow(edit_fields["longitude"], longitude_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        form.addRow(buttons)
        label_edit.setFocus()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.records = self.controller.edit_record(
                index,
                label_edit.text(),
                latitude_edit.text(),
                longitude_edit.text(),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "儲存失敗", str(exc))
            return
        if self.reload_records():
            self.record_table.selectRow(index)
            self.record_table.scrollToItem(self.record_table.item(index, 0))
        self.set_status("地點已更新至 record.json。")

    def delete_record(self):
        if self.closing or self.locating or (self.worker and not self.connected):
            return
        index = self.selected_record_index()
        if index is None:
            return
        self.release_all()
        record = self.records[index]
        answer = QMessageBox.question(
            self,
            "刪除收藏地點",
            f'確定刪除「{record["label"] or "未命名地點"}」？\n此操作會儲存至 record.json。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.records = self.controller.delete_record(index)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "刪除失敗", str(exc))
            return
        if self.reload_records() and self.records:
            selected = min(index, len(self.records) - 1)
            self.record_table.selectRow(selected)
            self.record_table.scrollToItem(self.record_table.item(selected, 0))
        self.set_status("地點已從 record.json 刪除。")

    def fetch_computer_position(self):
        if self.worker or self.locating or self.closing or not self.computer_mode.isChecked():
            return
        self.locating = True
        self.computer_position_ready = False
        self.set_status("正在取得電腦位置…")
        self.refresh_controls()
        self.set_location_controls_locked(True)

        self.controller.start_computer_location(self.events)

    def toggle_connection(self):
        if self.closing or self.locating:
            return
        if self.worker:
            if not self.connected:
                return
            self.connected = False
            self.release_all()
            self.worker.stop()
            self.action_button.setEnabled(False)
            self.action_button.setText("正在中斷連線…")
            self.set_status("移動已停止，正在關閉連線並清除模擬定位…", connected=False)
            self.refresh_controls()
            return
        if self.computer_mode.isChecked() and not self.computer_position_ready:
            return
        try:
            position, speed = self.controller.prepare_connection(
                self.latitude_edit.text(),
                self.longitude_edit.text(),
                self.speed_edit.text(),
            )
        except ValueError as exc:
            QMessageBox.critical(self, "座標或速度無效", str(exc))
            return
        self.cleanup_error = False
        self.speed_kmh = speed
        self.last_confirmed = None
        self.worker = self.controller.make_worker(position, self.events, speed_kmh=speed)
        self.refresh_controls()
        self.set_status("正在連線 iPhone…")
        self.worker.start()

    def clear_location(self):
        if self.worker or self.closing or self.locating:
            return
        self.release_all()
        self.cleanup_error = False
        self.worker = self.controller.make_worker(self.position, self.events, clear_only=True)
        self.refresh_controls()
        self.set_status("正在重新連線並清除模擬定位…")
        self.worker.start()

    def persist(self):
        position = self.last_confirmed or self.position
        self.position = self.controller.persist_position(position, self.speed_kmh)
        self.write_log(f"已保存最後位置：{position[0]:.8f}, {position[1]:.8f}")

    def poll_events(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "computer_position_attempt":
                attempt, limit = value
                self.set_status(f"正在取得電腦位置（第 {attempt}/{limit} 次）…")
            elif kind == "computer_position_attempt_error":
                attempt, limit, reason = value
                self.write_log(f"電腦定位第 {attempt}/{limit} 次失敗：{reason}")
            elif kind in {"computer_position", "computer_position_error"}:
                self.locating = False
                if kind == "computer_position":
                    self.computer_position = value
                    self.latitude_edit.setText(f"{value[0]:.8f}")
                    self.longitude_edit.setText(f"{value[1]:.8f}")
                    self.computer_position_ready = True
                    self.set_location_controls_locked(False)
                    self.set_status(
                        "已取得電腦起點位置。請確認座標，再按連線；"
                        "連線後可用 WASD／方向鍵移動。"
                    )
                else:
                    self.computer_position_ready = False
                    self.set_location_controls_locked(False)
                    self.custom_mode.setChecked(True)
                    self.refresh_controls()
                    self.set_status(
                        f"連續 {value['attempts']} 次無法取得電腦位置，已切回自訂經緯度。"
                    )
                    self.write_log("電腦定位失敗，已切回自訂經緯度。")
                self.refresh_controls()
            elif kind == "position":
                self.last_confirmed = self.position = value
                self.latitude_edit.setText(f"{value[0]:.8f}")
                self.longitude_edit.setText(f"{value[1]:.8f}")
            elif kind == "connected":
                if not self.closing and self.worker and not self.worker.stop_requested.is_set():
                    self.connected = True
                    self.set_status(value, connected=True)
                    self.refresh_controls()
                    self.activateWindow()
                    self.setFocus()
            elif kind == "arrived":
                if value == self.active_navigation:
                    self.release_all()
                    self.set_status("已到達目的地，移動已停止；連線保留。", connected=True)
            elif kind == "status":
                self.set_status(value)
            elif kind == "error":
                self.cleanup_error = True
                self.set_status("發生錯誤，詳見下方訊息。")
                self.write_log(value)
            elif kind == "log":
                self.write_log(value)
            elif kind == "done":
                self.connected = False
                self.release_all()
                self.active_navigation = None
                self.worker = None
                if self.computer_mode.isChecked() and self.computer_position_ready:
                    self.latitude_edit.setText(f"{self.computer_position[0]:.8f}")
                    self.longitude_edit.setText(f"{self.computer_position[1]:.8f}")
                try:
                    self.persist()
                except OSError as exc:
                    QMessageBox.critical(
                        self, "儲存失敗", f"{exc}\n最後座標仍顯示於畫面，請先記下。"
                    )
                    self.closing = False
                self.refresh_controls()
                if self.closing:
                    if self.cleanup_error:
                        QMessageBox.warning(
                            self,
                            "結束前請確認",
                            "發生連線或清除錯誤。請確認手機定位已恢復；"
                            "必要時重新啟動程式後按「清除模擬定位」。",
                        )
                    self.allow_close = True
                    self.close()
                    return
                if not self.cleanup_error:
                    self.set_status(
                        "連線已結束，清除要求已送出。請在 Apple Maps 確認；"
                        "未恢復可按清除重試。",
                        connected=False,
                    )

    def current_direction(self):
        return self.movement.current_direction()

    def update_direction(self):
        if self.active_navigation is not None:
            self.motion_label.setText(f"自動前往目的地 · {self.speed_kmh:g} km/h")
            for button in self.direction_buttons.values():
                button.setProperty("active", False)
                button.style().unpolish(button)
                button.style().polish(button)
            return
        east, north = self.current_direction()
        if self.worker:
            self.worker.direction(east, north)
        moving = east != 0 or north != 0
        if self.movement.locked_direction is not None and moving:
            text = f"方向已鎖定 · {self.speed_kmh:g} km/h"
        elif moving:
            text = f"移動中 · {self.speed_kmh:g} km/h"
        else:
            text = "停止"
        self.motion_label.setText(text)
        for direction, button in self.direction_buttons.items():
            active = moving and direction == (east, north)
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def begin_mouse_direction(self, direction):
        if not self.connected or self.closing:
            return
        self.active_navigation = None
        self.movement.begin_mouse_direction(direction)
        self.update_direction()

    def release_mouse_direction(self):
        self.movement.release_mouse_direction()
        self.update_direction()

    def lock_direction(self, east, north):
        if not self.connected or not self.worker or self.closing:
            return
        self.active_navigation = None
        self.movement.lock_direction(east, north)
        self.update_direction()

    def release_keyboard(self):
        self.movement.release_keys()
        self.update_direction()

    def release_all(self):
        self.movement.stop()
        self.active_navigation = None
        self.update_direction()

    def _is_text_or_list_focus(self):
        widget = QApplication.focusWidget()
        return isinstance(widget, (QLineEdit, QTextEdit, QAbstractItemView))

    def keyPressEvent(self, event: QKeyEvent):
        key_name = QT_KEY_NAMES.get(event.key())
        if key_name in KEY_DIRECTIONS and self.connected and not self.closing:
            if self._is_text_or_list_focus():
                super().keyPressEvent(event)
                return
            self.active_navigation = None
            self.movement.key_down(key_name)
            self.update_direction()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        key_name = QT_KEY_NAMES.get(event.key())
        if key_name in KEY_DIRECTIONS:
            self.movement.key_up(key_name)
            self.update_direction()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def on_focus_changed(self, _old, new):
        if isinstance(new, (QLineEdit, QTextEdit, QAbstractItemView)):
            self.release_keyboard()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowDeactivate:
            self.release_keyboard()
        super().changeEvent(event)

    def closeEvent(self, event: QCloseEvent):
        if self.allow_close:
            event.accept()
            return
        if self.worker:
            if not self.closing:
                self.closing = True
                self.connected = False
                self.release_all()
                self.worker.stop()
                self.set_status("正在結束連線，請稍候；尚在連線階段時需等待逾時。", connected=False)
                self.refresh_controls()
            event.ignore()
            return
        try:
            if self.last_confirmed is None:
                self.position = self.controller.validate_position(
                    self.latitude_edit.text(), self.longitude_edit.text()
                )
            self.persist()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "無法保存位置", str(exc))
            event.ignore()
            return
        event.accept()


STYLE = """
QMainWindow, QWidget { background: #f2f5fa; color: #17243a; font-family: 'Segoe UI'; font-size: 10pt; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#card { background: #ffffff; border: 1px solid #e1e7f0; border-radius: 14px; }
QFrame#coordinatePanel { background: #f7f9fc; border: 1px solid #e5eaf1; border-radius: 10px; }
QLabel#appTitle { font-size: 23pt; font-weight: 700; color: #14233b; }
QLabel#cardTitle { font-size: 13pt; font-weight: 650; color: #1b2d49; }
QLabel#coordinateTitle { font-size: 11pt; font-weight: 650; color: #415571; }
QLabel#muted, QLabel#footer { color: #65748b; }
QLabel#footer { padding: 2px 4px; }
QLabel#statusBadge { background: #e8edf5; color: #52627a; padding: 7px 13px; border-radius: 12px; font-weight: 650; }
QLabel#statusBadge[connected="true"] { background: #d9f5e8; color: #08744b; }
QLabel#statusText { background: #f5f7fb; border: 1px solid #e7ecf3; border-radius: 9px; padding: 9px 11px; color: #40536d; }
QLabel#motionLabel { font-size: 12pt; font-weight: 650; color: #3e526e; padding: 4px; }
QLineEdit { background: #ffffff; border: 1px solid #cfd8e5; border-radius: 8px; padding: 9px 10px; selection-background-color: #bcd5ff; }
QLineEdit:focus { border: 1px solid #5886d9; }
QLineEdit:disabled { background: #f0f3f7; color: #79869a; }
QPushButton { background: #ffffff; border: 1px solid #d5deea; border-radius: 8px; padding: 9px 12px; color: #30435e; }
QPushButton:hover { background: #f2f6fc; border-color: #9eb3d1; }
QPushButton:disabled { background: #edf0f4; color: #98a2b1; border-color: #e1e5eb; }
QPushButton#primaryButton { background: #2767d4; color: #ffffff; border: 0; font-weight: 650; padding: 12px; }
QPushButton#primaryButton:hover { background: #1d58bd; }
QPushButton#primaryButton:disabled { background: #b7c8e4; color: #f7f9fc; }
QPushButton#secondaryButton { padding: 8px 10px; }
QPushButton#directionButton { background: #edf2f8; border: 1px solid #dce4ee; font-size: 20pt; font-weight: 600; color: #405674; }
QPushButton#directionButton:hover { background: #e1ebf8; border-color: #a9bdd9; }
QPushButton#directionButton[active="true"] { background: #bdebdc; color: #126c52; border-color: #79c9ab; }
QPushButton#stopButton { background: #fff2ed; color: #a53b27; border: 1px solid #f5d1c7; font-weight: 650; }
QPushButton#stopButton:hover { background: #ffe4db; }
QTableWidget { background: #ffffff; alternate-background-color: #f7f9fc; border: 1px solid #e0e6ef; border-radius: 8px; gridline-color: #eef1f5; selection-background-color: #dce9ff; selection-color: #183e78; }
QHeaderView::section { background: #f4f7fb; color: #586a83; border: 0; border-bottom: 1px solid #e0e6ef; padding: 8px; font-weight: 650; }
QTextEdit { background: #17253b; color: #dbe7f8; border: 0; border-radius: 8px; padding: 8px; font-family: Consolas, monospace; font-size: 9pt; }
QRadioButton { spacing: 6px; }
QRadioButton::indicator { width: 15px; height: 15px; }
QDialog { background: #f2f5fa; }
QDialogButtonBox QPushButton { min-width: 84px; }
"""


def run_self_test(check_device=False):
    from PySide6 import __version__ as pyside_version
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

    report = {
        "pyside6": pyside_version,
        "config_path": str(CONFIG_PATH),
        "frozen": bool(getattr(sys, "frozen", False)),
        "backend_imports": bool(UserspaceRsdTunnel and LocationSimulation),
    }
    if check_device:
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider

        async def check():
            async with UserspaceRsdTunnel(autopair=False, remotepairing_fallback=False) as rsd:
                async with DvtProvider(rsd) as dvt, LocationSimulation(dvt):
                    return {"udid": rsd.udid, "dvt": True, "location_modified": False}

        report["device"] = asyncio.run(asyncio.wait_for(check(), timeout=60))
    report_path = APP_DIR / ("device-check.json" if check_device else "self-test.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main():
    logging.basicConfig(
        filename=APP_DIR / "gps.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    if "--self-test" in sys.argv or "--check-device" in sys.argv:
        run_self_test(check_device="--check-device" in sys.argv)
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")
    window = JoystickWindow()
    window.show()
    return app.exec()


def launch():
    try:
        return main()
    except Exception:
        detail = traceback.format_exc()
        (APP_DIR / "startup-error.log").write_text(detail, encoding="utf-8")
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "程式啟動失敗", f"{detail}\n詳細訊息已寫入 startup-error.log。")
        except Exception:
            sys.stderr.write(detail)
        return 1


if __name__ == "__main__":
    raise SystemExit(launch())
