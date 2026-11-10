"""Tkinter iPhone GPS joystick. Run inside the iphone-gps conda environment."""

import queue
import logging
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

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
    SCREEN_COMPONENTS,
    SECTION_TITLES,
    SPEED_FIELD,
    TK_COMPONENT_LAYOUT,
)

APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1]
)
CONFIG_PATH = APP_DIR / "config.json"
RECORD_PATH = APP_DIR / "record.json"


class JoystickApp:
    def __init__(self, root):
        self.root = root
        self.controller = JoystickController(CONFIG_PATH, RECORD_PATH)
        self.worker = None
        self.events = queue.Queue()
        self.movement = MovementController()
        self.active_navigation = None
        self.connected = False
        self.closing = False
        self.last_confirmed = None
        self.cleanup_error = False
        self.locating = False
        self.location_locked_states = None
        self.computer_position_ready = False
        self.computer_position = None
        self.position = self.controller.position
        self.speed_kmh = self.controller.speed_kmh

        root.title(APP_TITLE)
        root.geometry("740x900")
        root.minsize(700, 820)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.coordinate_vars = {
            "latitude": tk.StringVar(value=f"{self.position[0]:.8f}"),
            "longitude": tk.StringVar(value=f"{self.position[1]:.8f}"),
            "destination_latitude": tk.StringVar(),
            "destination_longitude": tk.StringVar(),
        }
        self.latitude = self.coordinate_vars["latitude"]
        self.longitude = self.coordinate_vars["longitude"]
        self.destination_latitude = self.coordinate_vars["destination_latitude"]
        self.destination_longitude = self.coordinate_vars["destination_longitude"]
        self.status = tk.StringVar(value="尚未連線。請接上 USB、解鎖 iPhone。")
        self.motion = tk.StringVar(value="停止")
        self.mode = tk.StringVar(value="custom")
        self.speed = tk.StringVar(value=f"{self.speed_kmh:g}")
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(TK_COMPONENT_LAYOUT["log"]["rows"]["panel"], weight=1)
        ttk.Label(frame, text=APP_TITLE, font=("Segoe UI", 19, "bold")).grid(
            row=TK_COMPONENT_LAYOUT["settings"]["rows"]["title"],
            column=0, columnspan=2, sticky="w", pady=(0, 6))
        mode_frame = ttk.Frame(frame)
        mode_frame.grid(row=TK_COMPONENT_LAYOUT["settings"]["rows"]["mode"],
                        column=0, columnspan=2, sticky="ew", pady=(0, 12))
        options_frame = ttk.Frame(mode_frame)
        options_frame.pack(side="top", fill="x")
        self.mode_buttons = []
        for value, text in MODE_OPTIONS:
            button = ttk.Radiobutton(options_frame, text=text, value=value, variable=self.mode,
                                     command=self.change_mode)
            button.pack(side="left", padx=(0, 12))
            self.mode_buttons.append(button)
        self.location_button = ttk.Button(options_frame, text=ACTION_LABELS["locate"], command=self.fetch_computer_position)
        self.location_button.pack(side="left")
        self.location_button.configure(state="disabled")
        speed_frame = ttk.Frame(mode_frame)
        speed_frame.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Label(speed_frame, text=f'{SPEED_FIELD["label"]} {SPEED_FIELD["unit"]}').pack(side="left")
        ttk.Entry(speed_frame, textvariable=self.speed, width=8).pack(side="left", padx=8)
        ttk.Button(speed_frame, text=ACTION_LABELS["apply_speed"], command=self.apply_speed).pack(side="left")
        ttk.Label(speed_frame, text="  WASD / 方向鍵").pack(side="left")
        # Both starting-position modes use the same movement worker.
        self.entries = []
        coordinates = ttk.Frame(frame)
        coordinates.grid(row=TK_COMPONENT_LAYOUT["settings"]["rows"]["coordinates"],
                         column=0, columnspan=2, sticky="ew")
        for column, panel_spec in enumerate(COORDINATE_PANELS):
            title = panel_spec["title"]
            variables = [self.coordinate_vars[key] for key in panel_spec["fields"]]
            coordinates.columnconfigure(column, weight=1, uniform="coordinates")
            group = ttk.LabelFrame(coordinates, text=title, padding=8)
            group.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))
            group.columnconfigure(1, weight=1)
            for row, (field_id, variable) in enumerate(zip(panel_spec["fields"], variables)):
                ttk.Label(group, text=COORDINATE_FIELDS[field_id]["label"]).grid(row=row, column=0, padx=(0, 8), pady=4)
                entry = ttk.Entry(group, textvariable=variable, font=("Consolas", 12), width=18)
                entry.grid(row=row, column=1, sticky="ew", pady=4)
                if panel_spec["id"] == "origin":
                    self.entries.append(entry)
            if panel_spec["id"] == "destination":
                self.navigate_button = ttk.Button(group, text=ACTION_LABELS["navigate"], command=self.start_navigation, state="disabled")
                self.navigate_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.button = ttk.Button(frame, text=ACTION_LABELS["connect"], command=self.toggle)
        self.button.grid(row=TK_COMPONENT_LAYOUT["settings"]["rows"]["connect"],
                         column=0, columnspan=2, sticky="ew", pady=(16, 8))
        self.clear_button = ttk.Button(frame, text=ACTION_LABELS["clear"], command=self.clear_location)
        self.clear_button.grid(row=TK_COMPONENT_LAYOUT["settings"]["rows"]["clear"],
                               column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=540).grid(
            row=TK_COMPONENT_LAYOUT["settings"]["rows"]["status"],
            column=0, columnspan=2, sticky="w", pady=6)
        pad = ttk.LabelFrame(frame, text=SECTION_TITLES.get("directions", ""), padding=12)
        pad.grid(row=TK_COMPONENT_LAYOUT["directions"]["rows"]["pad"],
                 column=0, columnspan=2, sticky="ew", pady=10)
        self.direction_labels = {}
        for row, cells in enumerate(DIRECTION_GRID):
            for col, (tk_text, _qt_text, east, north) in enumerate(cells):
                text = tk_text
                pad.columnconfigure(col, weight=1)
                label = tk.Label(pad, text=text, font=("Segoe UI", 12), bg="#eeeeee", padx=8, pady=8)
                label.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
                self.direction_labels[east, north] = label
                label.configure(cursor="hand2")
                if (east, north) == (0, 0):
                    label.bind("<Button-1>", lambda event: self.release_all())
                else:
                    label.bind("<Double-Button-1>",
                               lambda event, e=east, n=north: self.lock_direction(e, n))
        ttk.Label(frame, textvariable=self.motion).grid(
            row=TK_COMPONENT_LAYOUT["directions"]["rows"]["motion"],
            column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="\n".join(MOTION_HELP),
                  wraplength=540).grid(
                      row=TK_COMPONENT_LAYOUT["directions"]["rows"]["help"],
                      column=0, columnspan=2, sticky="w", pady=8)
        self.log = scrolledtext.ScrolledText(frame, height=6, state="disabled", wrap="word")
        self.log.grid(row=TK_COMPONENT_LAYOUT["log"]["rows"]["panel"],
                      column=0, columnspan=2, sticky="nsew")
        records_frame = ttk.LabelFrame(
            frame, text=f'{SECTION_TITLES.get("records", "")} · record.json', padding=8
        )
        records_frame.grid(row=TK_COMPONENT_LAYOUT["records"]["rows"]["panel"],
                           column=0, columnspan=2, sticky="ew", pady=8)
        records_frame.columnconfigure(1, weight=1)
        ttk.Label(records_frame, text=RECORD_COLUMNS[0][1]).grid(row=0, column=0, padx=(0, 8))
        self.record_label = tk.StringVar()
        ttk.Entry(records_frame, textvariable=self.record_label).grid(row=0, column=1, sticky="ew")
        ttk.Button(records_frame, text=ACTION_LABELS["record_current"], command=self.record_current_position).grid(row=0, column=2, padx=(8, 0))
        self.record_tree = ttk.Treeview(records_frame, columns=("label", "latitude", "longitude"), show="headings", height=3, selectmode="browse")
        for column, title in RECORD_COLUMNS:
            self.record_tree.heading(column, text=title)
            self.record_tree.column(column, width=160, minwidth=80)
        self.record_tree.grid(row=1, column=0, columnspan=3, sticky="ew", pady=6)
        scrollbar = ttk.Scrollbar(records_frame, orient="vertical", command=self.record_tree.yview)
        scrollbar.grid(row=1, column=3, sticky="ns")
        self.record_tree.configure(yscrollcommand=scrollbar.set)
        record_actions = ttk.Frame(records_frame)
        record_actions.grid(row=2, column=0, columnspan=3, sticky="ew")
        for action in RECORD_ACTIONS:
            action_id = action["id"]
            button = ttk.Button(
                record_actions,
                text=action["label"],
                command=getattr(self, action["handler"]),
            )
            button.pack(side="left", padx=(0, 6))
            if action_id == "update_record":
                self.update_record_button = button
                button.configure(state="disabled")
        self.record_tree.bind("<<TreeviewSelect>>", self.refresh_record_selection)
        self.record_tree.bind("<Double-1>", lambda event: self.use_record())
        self.records = self.controller.records
        self.reload_records()
        for component_id, component_layout in TK_COMPONENT_LAYOUT.items():
            if SCREEN_COMPONENTS.get(component_id, {}).get("enabled", False):
                continue
            hidden_rows = set(component_layout["rows"].values())
            for child in frame.grid_slaves():
                if int(child.grid_info().get("row", -1)) in hidden_rows:
                    child.grid_remove()
            if component_id == "log":
                frame.rowconfigure(TK_COMPONENT_LAYOUT["log"]["rows"]["panel"], weight=0)
        root.bind("<KeyPress>", self.key_down)
        root.bind("<KeyRelease>", self.key_up)
        root.bind("<FocusOut>", self.on_focus_out)
        root.bind("<Unmap>", lambda event: self.release_keyboard())
        self.write_log(self.controller.load_error or f"啟動時從 {CONFIG_PATH.name} 載入座標。")
        root.after(50, self.poll)

    def write_log(self, text):
        logging.info(text)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def change_mode(self):
        self.computer_position_ready = False
        self.refresh_mode_controls()
        if self.mode.get() == "computer":
            self.fetch_computer_position()

    def apply_speed(self):
        if self.closing:
            return
        self.release_all()
        try:
            speed = self.controller.apply_speed(
                self.speed.get(), self.position, self.last_confirmed, self.worker
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("無法套用速度", str(exc))
            return
        self.speed_kmh = speed
        self.speed.set(f"{speed:g}")
        self.status.set(f"速度已設為 {speed:g} km/h，已保存至 config.json。")
        self.root.focus_set()

    def reload_records(self):
        try:
            records = self.controller.reload_records()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.set(f"無法讀取 record.json：{exc}；原檔保留，請修正後重新讀取。")
            return False
        self.records = records
        self.record_tree.delete(*self.record_tree.get_children())
        for index, record in enumerate(records):
            self.record_tree.insert("", "end", iid=str(index), values=(record["label"] or "（未命名）", f'{record["latitude"]:.8f}', f'{record["longitude"]:.8f}'))
        self.refresh_record_selection()
        return True

    def refresh_record_selection(self, event=None):
        selection = self.record_tree.selection()
        valid = bool(selection) and selection[0] in self.record_tree.get_children()
        self.update_record_button.configure(state="normal" if valid else "disabled")

    def current_record_position(self):
        return self.controller.current_record_position(
            connected=self.connected,
            last_confirmed=self.last_confirmed,
            mode=self.mode.get(),
            computer_position_ready=self.computer_position_ready,
            latitude=self.latitude.get(),
            longitude=self.longitude.get(),
        )

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
            messagebox.showerror("更新地標失敗", str(exc), parent=self.root)
            return
        if self.reload_records():
            self.record_tree.selection_set(str(index))
            self.record_tree.see(str(index))
            self.refresh_record_selection()
        self.status.set("所選地標的經緯度已更新至 record.json，標籤保持不變。")
        self.root.focus_set()

    def selected_record_index(self):
        selection = self.record_tree.selection()
        if not selection:
            self.status.set("請先選取一個收藏地點。")
            return None
        return int(selection[0])

    def edit_record(self):
        if self.closing:
            return
        index = self.selected_record_index()
        if index is None:
            return
        self.release_all()
        original = [dict(record) for record in self.records]
        dialog = tk.Toplevel(self.root)
        dialog.title("編輯收藏地點")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        panel = ttk.Frame(dialog, padding=20)
        panel.pack(fill="both", expand=True)
        variables = {}
        for row, (key, title) in enumerate(RECORD_EDIT_FIELDS):
            ttk.Label(panel, text=title).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            variables[key] = tk.StringVar(value=str(original[index][key]))
            entry = ttk.Entry(panel, textvariable=variables[key], width=32)
            entry.grid(row=row, column=1, pady=6)
            if row == 0:
                entry.focus_set()

        def save():
            try:
                self.records = self.controller.edit_record(
                    index,
                    variables["label"].get(),
                    variables["latitude"].get(),
                    variables["longitude"].get(),
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                messagebox.showerror("儲存失敗", str(exc), parent=dialog)
                return
            dialog.destroy()
            if self.reload_records():
                self.record_tree.selection_set(str(index))
                self.record_tree.see(str(index))
            self.status.set("地點已更新至 record.json。")

        actions = ttk.Frame(panel)
        actions.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="left", padx=8)
        ttk.Button(actions, text="儲存", command=save).pack(side="left")
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.grab_set()

    def delete_record(self):
        if self.closing:
            return
        index = self.selected_record_index()
        if index is None:
            return
        self.release_all()
        record = self.records[index]
        if not messagebox.askyesno("刪除收藏地點", f'確定刪除「{record["label"] or "未命名地點"}」？\n此操作會儲存至 record.json。', parent=self.root):
            return
        try:
            self.records = self.controller.delete_record(index)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("刪除失敗", str(exc), parent=self.root)
            return
        if self.reload_records() and self.records:
            selected = str(min(index, len(self.records) - 1))
            self.record_tree.selection_set(selected)
            self.record_tree.see(selected)
        self.status.set("地點已從 record.json 刪除。")

    def record_current_position(self):
        if self.closing or self.locating or (self.worker and not self.connected):
            return
        self.release_all()
        try:
            position = self.current_record_position()
            self.records = self.controller.add_record(self.record_label.get(), position)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("紀錄失敗", str(exc))
            return
        self.reload_records()
        self.record_tree.selection_set(str(len(self.records) - 1))
        self.record_tree.see(str(len(self.records) - 1))
        self.status.set("地點已加入 record.json。")
        self.record_label.set("")
        self.root.focus_set()

    def use_record(self):
        if self.worker or self.locating or self.closing:
            self.status.set("請先中斷連線，再使用收藏地點。")
            return
        selection = self.record_tree.selection()
        if not selection:
            self.status.set("請先選取一個收藏地點。")
            return
        record = self.records[int(selection[0])]
        self.mode.set("custom")
        self.change_mode()
        self.latitude.set(str(record["latitude"]))
        self.longitude.set(str(record["longitude"]))
        self.status.set(f'已選取 {record["label"] or "未命名地點"}，按連線前往。')
        self.root.focus_set()

    def refresh_mode_controls(self):
        busy = bool(self.worker) or self.locating or self.closing
        self.navigate_button.configure(state="normal" if self.connected and not self.closing else "disabled")
        for button in self.mode_buttons:
            button.configure(state="disabled" if busy else "normal")
        for entry in self.entries:
            entry.configure(state="normal" if not busy and self.mode.get() == "custom" else "disabled")
        self.location_button.configure(state="normal" if not busy and self.mode.get() == "computer" else "disabled")
        if not self.worker:
            ready = self.mode.get() == "custom" or self.computer_position_ready
            self.button.configure(state="normal" if not busy and ready else "disabled",
                                  text=ACTION_LABELS["connect"])
            self.clear_button.configure(state="disabled" if busy else "normal")

    def set_location_controls_locked(self, locked):
        if locked:
            if self.location_locked_states is not None:
                return
            self.location_locked_states = {}
            pending = list(self.root.winfo_children())
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                try:
                    state = widget.cget("state")
                except tk.TclError:
                    continue
                if state not in {"normal", "readonly", "active"}:
                    continue
                try:
                    self.location_locked_states[widget] = state
                    widget.configure(state="disabled")
                except tk.TclError:
                    self.location_locked_states.pop(widget, None)
            return

        if self.location_locked_states is None:
            return
        for widget, state in self.location_locked_states.items():
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        self.location_locked_states = None
        self.refresh_mode_controls()
        self.refresh_record_selection()

    def fetch_computer_position(self):
        if self.worker or self.locating or self.closing or self.mode.get() != "computer":
            return
        self.locating = True
        self.computer_position_ready = False
        self.status.set("正在取得電腦位置…")
        self.refresh_mode_controls()
        self.set_location_controls_locked(True)

        self.controller.start_computer_location(self.events)

    def key_down(self, event):
        if not self.connected or self.closing:
            return
        key = event.keysym.lower()
        if key in KEY_DIRECTIONS:
            if isinstance(self.root.focus_get(), (ttk.Entry, tk.Entry, tk.Text, ttk.Treeview, ttk.Combobox)):
                return
            self.active_navigation = None
            self.movement.key_down(key)
            self.update_direction()
            return "break"

    def key_up(self, event):
        self.movement.key_up(event.keysym.lower())
        self.update_direction()

    def release_all(self):
        self.active_navigation = None
        self.movement.stop()
        self.update_direction()

    def release_keyboard(self):
        """Release physical keys while preserving explicit direction locks."""
        self.movement.release_keys()
        self.update_direction()

    def lock_direction(self, east, north):
        if not self.connected or not self.worker or self.closing:
            return
        self.root.focus_set()
        self.active_navigation = None
        self.movement.lock_direction(east, north)
        self.update_direction()
        return "break"

    def on_focus_out(self, event):
        # Focus transfers between widgets also bubble to the root binding.
        # Leaving the window releases physical keys, but keeps direction locks.
        def check_focus():
            if self.root.focus_get() is None:
                self.release_keyboard()
        self.root.after_idle(check_focus)

    def update_direction(self):
        if self.active_navigation is not None:
            self.motion.set(f"自動前往目的地 · {self.speed_kmh:g} km/h")
            return
        east, north = self.movement.current_direction()
        if self.worker:
            self.worker.direction(east, north)
        state = "方向已鎖定" if self.movement.locked_direction is not None else "移動中"
        self.motion.set(f"{state} · {self.speed_kmh:g} km/h" if east or north else "停止")
        for direction, label in self.direction_labels.items():
            label.configure(bg="#9edfd0" if direction == (east, north) else "#eeeeee")

    def start_navigation(self):
        if not self.connected or not self.worker or self.closing:
            self.status.set("請先連線至現在地，再開始自動前往。")
            return
        try:
            destination = self.controller.validate_destination(
                self.destination_latitude.get(), self.destination_longitude.get()
            )
        except ValueError as exc:
            messagebox.showerror("目的地無效", str(exc), parent=self.root)
            return
        self.release_all()
        self.active_navigation = self.controller.navigate(
            self.worker,
            connected=self.connected,
            closing=self.closing,
            destination=destination,
        )
        for label in self.direction_labels.values():
            label.configure(bg="#eeeeee")
        self.update_direction()
        self.status.set("正在直線前往目的地；到達後會停止。點停止或使用移動鍵可取消。")
        self.root.focus_set()

    def toggle(self):
        if self.closing or self.locating:
            return
        if self.worker:
            self.connected = False
            self.navigate_button.configure(state="disabled")
            self.release_all()
            self.worker.stop()
            self.button.configure(state="disabled", text="正在中斷連線…")
            return
        if self.mode.get() == "computer" and not self.computer_position_ready:
            return
        try:
            position, speed = self.controller.prepare_connection(
                self.latitude.get(), self.longitude.get(), self.speed.get()
            )
        except ValueError as exc:
            messagebox.showerror("座標或速度無效", str(exc))
            return
        self.cleanup_error = False
        self.speed_kmh = speed
        self.last_confirmed = None
        self.worker = self.controller.make_worker(position, self.events, speed_kmh=self.speed_kmh)
        for entry in self.entries:
            entry.configure(state="disabled")
        self.button.configure(state="disabled", text="正在連線…")
        self.clear_button.configure(state="disabled")
        self.refresh_mode_controls()
        self.worker.start()

    def clear_location(self):
        if self.worker or self.closing or self.locating:
            return
        self.release_all()
        self.cleanup_error = False
        self.worker = self.controller.make_worker(self.position, self.events, clear_only=True)
        self.button.configure(state="disabled")
        self.clear_button.configure(state="disabled", text="正在清除，請保持 USB 連接…")
        self.refresh_mode_controls()
        self.worker.start()

    def persist(self):
        # Never save a speculative coordinate that the iPhone did not acknowledge.
        position = self.last_confirmed or self.position
        self.position = self.controller.persist_position(position, self.speed_kmh)
        self.write_log(f"已保存最後位置：{position[0]:.8f}, {position[1]:.8f}")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "computer_position_attempt":
                    attempt, limit = value
                    self.status.set(f"正在取得電腦位置（第 {attempt}/{limit} 次）…")
                elif kind == "computer_position_attempt_error":
                    attempt, limit, reason = value
                    self.write_log(f"電腦定位第 {attempt}/{limit} 次失敗：{reason}")
                elif kind in {"computer_position", "computer_position_error"}:
                    self.locating = False
                    if kind == "computer_position":
                        self.computer_position = value
                        self.latitude.set(f"{value[0]:.8f}")
                        self.longitude.set(f"{value[1]:.8f}")
                        self.computer_position_ready = True
                        self.set_location_controls_locked(False)
                        self.status.set("已取得電腦起點位置。請確認座標，再按連線；連線後可用 WASD／方向鍵移動。")
                    else:
                        self.computer_position_ready = False
                        self.set_location_controls_locked(False)
                        self.mode.set("custom")
                        self.change_mode()
                        self.status.set(
                            f"連續 {value['attempts']} 次無法取得電腦位置，已切回自訂經緯度。"
                        )
                        self.write_log("電腦定位失敗，已切回自訂經緯度。")
                elif kind == "position":
                    self.last_confirmed = self.position = value
                    self.latitude.set(f"{value[0]:.8f}")
                    self.longitude.set(f"{value[1]:.8f}")
                elif kind == "connected":
                    if not self.closing and not self.worker.stop_requested.is_set():
                        self.connected = True
                        self.navigate_button.configure(state="normal")
                        self.status.set(value)
                        self.button.configure(state="normal", text=ACTION_LABELS["disconnect"])
                        self.root.focus_set()
                elif kind == "arrived":
                    if value == self.active_navigation:
                        self.release_all()
                        self.status.set("已到達目的地，移動已停止；連線保留。")
                elif kind == "status":
                    self.status.set(value)
                elif kind == "error":
                    self.cleanup_error = True
                    self.status.set("發生錯誤，詳見下方訊息。")
                    self.write_log(value)
                elif kind == "log":
                    self.write_log(value)
                elif kind == "done":
                    self.connected = False
                    self.release_all()
                    # done follows the worker's last position event, on the same queue.
                    self.worker = None
                    if self.mode.get() == "computer" and self.computer_position_ready:
                        self.latitude.set(f"{self.computer_position[0]:.8f}")
                        self.longitude.set(f"{self.computer_position[1]:.8f}")
                    try:
                        self.persist()
                    except OSError as exc:
                        self.closing = False
                        messagebox.showerror("儲存失敗", f"{exc}\n最後座標仍顯示於畫面，請先記下。")
                    for entry in self.entries:
                        entry.configure(state="normal")
                    self.button.configure(state="normal", text=ACTION_LABELS["connect"])
                    self.clear_button.configure(state="normal", text=ACTION_LABELS["clear"])
                    self.refresh_mode_controls()
                    if self.closing:
                        if self.cleanup_error:
                            messagebox.showwarning("結束前請確認", "發生連線或清除錯誤。請確認手機定位已恢復；"
                                                   "必要時重新啟動程式後按「清除模擬定位」。")
                        self.root.destroy()
                        return
                    if not self.cleanup_error:
                        self.status.set("連線已結束，清除要求已送出。請在 Apple Maps 確認；未恢復可按清除重試。")
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.connected = False
        self.release_all()
        if self.worker:
            self.worker.stop()
            self.button.configure(state="disabled", text="正在保存位置並結束…")
            self.status.set("正在結束連線，請稍候；尚在連線階段時需等待逾時。")
        else:
            try:
                # No session: save the entered starting position for next launch.
                if self.last_confirmed is None:
                    self.position = self.controller.validate_position(
                        self.latitude.get(), self.longitude.get()
                    )
                self.persist()
            except (OSError, ValueError) as exc:
                self.closing = False
                messagebox.showerror("無法保存位置", str(exc))
                return
            self.root.destroy()


def main():
    logging.basicConfig(filename=APP_DIR / "gps.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    root = tk.Tk()
    app = JoystickApp(root)
    if "--self-test" in sys.argv or "--check-device" in sys.argv:
        # Packaged startup smoke check. No USB access, no config changes.
        root.withdraw()
        root.update_idletasks()
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
        import json
        report = {
            "tk": root.tk.call("info", "patchlevel"),
            "config_path": str(CONFIG_PATH),
            "frozen": bool(getattr(sys, "frozen", False)),
            "backend_imports": bool(UserspaceRsdTunnel and LocationSimulation),
        }
        if "--check-device" in sys.argv:
            import asyncio
            from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider

            async def check_device():
                async with UserspaceRsdTunnel(autopair=False, remotepairing_fallback=False) as rsd:
                    async with DvtProvider(rsd) as dvt, LocationSimulation(dvt):
                        return {"udid": rsd.udid, "dvt": True, "location_modified": False}

            report["device"] = asyncio.run(asyncio.wait_for(check_device(), timeout=60))
        report_path = APP_DIR / ("device-check.json" if "--check-device" in sys.argv else "self-test.json")
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        root.destroy()
        return
    root.mainloop()


def launch():
    try:
        main()
    except Exception:
        import traceback
        detail = traceback.format_exc()
        (APP_DIR / "startup-error.log").write_text(detail, encoding="utf-8")
        if "--self-test" not in sys.argv and "--check-device" not in sys.argv:
            messagebox.showerror("程式啟動失敗", f"{detail}\n詳細訊息已寫入 startup-error.log。")
        sys.exit(1)


if __name__ == "__main__":
    launch()
