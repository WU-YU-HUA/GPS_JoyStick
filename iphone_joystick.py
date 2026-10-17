"""Tkinter iPhone GPS joystick. Run inside the iphone-gps conda environment."""

import queue
import logging
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from iphone_backend import (
    DEFAULT_POSITION, SPEED_KMH, IPhoneWorker, load_position, load_speed,
    save_position, validate_position, validate_speed,
)
from pc_location import get_computer_position
from location_records import append_record, load_records

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
RECORD_PATH = APP_DIR / "record.json"


class JoystickApp:
    def __init__(self, root):
        self.root = root
        self.worker = None
        self.events = queue.Queue()
        self.keys = set()
        self.connected = False
        self.closing = False
        self.last_confirmed = None
        self.cleanup_error = False
        self.locating = False
        self.computer_position_ready = False
        self.computer_position = None
        load_error = None
        self.speed_kmh = SPEED_KMH
        try:
            self.position = load_position(CONFIG_PATH)
            self.speed_kmh = load_speed(CONFIG_PATH)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.position = DEFAULT_POSITION
            load_error = f"讀取 config.json 失敗：{exc}\n目前顯示預設東京座標，連線前請確認。"

        root.title("iPhone GPS Joystick")
        root.geometry("740x900")
        root.minsize(700, 820)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.latitude = tk.StringVar(value=f"{self.position[0]:.8f}")
        self.longitude = tk.StringVar(value=f"{self.position[1]:.8f}")
        self.status = tk.StringVar(value="尚未連線。請接上 USB、解鎖 iPhone。")
        self.motion = tk.StringVar(value="停止")
        self.mode = tk.StringVar(value="custom")
        self.speed = tk.StringVar(value=f"{self.speed_kmh:g}")
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(9, weight=1)
        ttk.Label(frame, text="iPhone GPS Joystick", font=("Segoe UI", 19, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        mode_frame = ttk.Frame(frame)
        mode_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        options_frame = ttk.Frame(mode_frame)
        options_frame.pack(side="top", fill="x")
        self.mode_buttons = []
        for text, value in [("自訂經緯度", "custom"), ("電腦目前位置", "computer")]:
            button = ttk.Radiobutton(options_frame, text=text, value=value, variable=self.mode,
                                     command=self.change_mode)
            button.pack(side="left", padx=(0, 12))
            self.mode_buttons.append(button)
        self.location_button = ttk.Button(options_frame, text="重新取得位置", command=self.fetch_computer_position)
        self.location_button.pack(side="left")
        self.location_button.configure(state="disabled")
        speed_frame = ttk.Frame(mode_frame)
        speed_frame.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Label(speed_frame, text="速度 km/h").pack(side="left")
        ttk.Entry(speed_frame, textvariable=self.speed, width=8).pack(side="left", padx=8)
        ttk.Button(speed_frame, text="套用速度", command=self.apply_speed).pack(side="left")
        ttk.Label(speed_frame, text="  WASD / 方向鍵").pack(side="left")
        ttk.Label(frame, text="起點座標（電腦位置由 Windows 定位提供，可能有誤差）").grid(
            row=11, column=0, columnspan=2, sticky="w")
        # Both starting-position modes use the same movement worker.
        self.entries = []
        for row, label, variable in [(2, "緯度 Latitude", self.latitude), (3, "經度 Longitude", self.longitude)]:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 20), pady=6)
            entry = ttk.Entry(frame, textvariable=variable, font=("Consolas", 13))
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            self.entries.append(entry)
        self.button = ttk.Button(frame, text="連線並移動至輸入座標", command=self.toggle)
        self.button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(16, 8))
        self.clear_button = ttk.Button(frame, text="清除模擬定位（恢復真實 GPS）", command=self.clear_location)
        self.clear_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=540).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=6)
        pad = ttk.LabelFrame(frame, text="移動方向", padding=12)
        pad.grid(row=7, column=0, columnspan=2, sticky="ew", pady=10)
        self.direction_labels = {}
        for row, cells in enumerate([
            [("WA ↖", -1, 1), ("W ↑", 0, 1), ("WD ↗", 1, 1)],
            [("A ←", -1, 0), ("停止", 0, 0), ("D →", 1, 0)],
            [("SA ↙", -1, -1), ("S ↓", 0, -1), ("SD ↘", 1, -1)],
        ]):
            for col, (text, east, north) in enumerate(cells):
                pad.columnconfigure(col, weight=1)
                label = tk.Label(pad, text=text, font=("Segoe UI", 12), bg="#eeeeee", padx=8, pady=8)
                label.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
                self.direction_labels[east, north] = label
        ttk.Label(frame, textvariable=self.motion).grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="按住移動，放開停止；切離視窗停止。斜向速度相同。\n"
                  "中斷連線／關閉時保存最後位置，並清除手機模擬定位。",
                  wraplength=540).grid(row=9, column=0, columnspan=2, sticky="w", pady=8)
        self.log = scrolledtext.ScrolledText(frame, height=6, state="disabled", wrap="word")
        self.log.grid(row=10, column=0, columnspan=2, sticky="nsew")
        frame.rowconfigure(9, weight=0)
        frame.rowconfigure(10, weight=1)
        for child in frame.winfo_children():
            row = int(child.grid_info().get("row", 0))
            if row >= 4:
                child.grid_configure(row=row + 1)
        frame.rowconfigure(10, weight=0)
        frame.rowconfigure(11, weight=1)
        records_frame = ttk.LabelFrame(frame, text="收藏地點 · record.json", padding=8)
        records_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)
        records_frame.columnconfigure(1, weight=1)
        ttk.Label(records_frame, text="標籤").grid(row=0, column=0, padx=(0, 8))
        self.record_label = tk.StringVar()
        ttk.Entry(records_frame, textvariable=self.record_label).grid(row=0, column=1, sticky="ew")
        ttk.Button(records_frame, text="紀錄現在位置", command=self.record_current_position).grid(row=0, column=2, padx=(8, 0))
        self.record_tree = ttk.Treeview(records_frame, columns=("label", "latitude", "longitude"), show="headings", height=3, selectmode="browse")
        for column, title in [("label", "標籤"), ("latitude", "緯度"), ("longitude", "經度")]:
            self.record_tree.heading(column, text=title)
            self.record_tree.column(column, width=160, minwidth=80)
        self.record_tree.grid(row=1, column=0, columnspan=3, sticky="ew", pady=6)
        scrollbar = ttk.Scrollbar(records_frame, orient="vertical", command=self.record_tree.yview)
        scrollbar.grid(row=1, column=3, sticky="ns")
        self.record_tree.configure(yscrollcommand=scrollbar.set)
        ttk.Button(records_frame, text="使用選取地點", command=self.use_record).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Button(records_frame, text="重新讀取", command=self.reload_records).grid(row=2, column=2, sticky="e")
        self.record_tree.bind("<Double-1>", lambda event: self.use_record())
        self.records = []
        self.reload_records()
        root.bind("<KeyPress>", self.key_down)
        root.bind("<KeyRelease>", self.key_up)
        root.bind("<FocusOut>", lambda event: self.release_all())
        root.bind("<Unmap>", lambda event: self.release_all())
        self.write_log(load_error or f"啟動時從 {CONFIG_PATH.name} 載入座標。")
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
            speed = validate_speed(self.speed.get())
            save_position(CONFIG_PATH, self.last_confirmed or self.position, speed)
        except (ValueError, OSError) as exc:
            messagebox.showerror("無法套用速度", str(exc))
            return
        self.speed_kmh = speed
        if self.worker:
            self.worker.set_speed(speed)
        self.speed.set(f"{speed:g}")
        self.status.set(f"速度已設為 {speed:g} km/h，已保存至 config.json。")
        self.root.focus_set()

    def reload_records(self):
        try:
            records = load_records(RECORD_PATH)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.set(f"無法讀取 record.json：{exc}；原檔保留，請修正後重新讀取。")
            return False
        self.records = records
        self.record_tree.delete(*self.record_tree.get_children())
        for index, record in enumerate(records):
            self.record_tree.insert("", "end", iid=str(index), values=(record["label"] or "（未命名）", f'{record["latitude"]:.8f}', f'{record["longitude"]:.8f}'))
        return True

    def record_current_position(self):
        if self.closing or self.locating or (self.worker and not self.connected):
            return
        self.release_all()
        try:
            if self.connected:
                if self.last_confirmed is None:
                    raise ValueError("尚未收到手機確認的座標。")
                position = self.last_confirmed
            else:
                if self.mode.get() == "computer" and not self.computer_position_ready:
                    raise ValueError("請先取得電腦位置。")
                position = validate_position(self.latitude.get(), self.longitude.get())
            append_record(RECORD_PATH, self.record_label.get(), position)
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
        for button in self.mode_buttons:
            button.configure(state="disabled" if busy else "normal")
        for entry in self.entries:
            entry.configure(state="normal" if not busy and self.mode.get() == "custom" else "disabled")
        self.location_button.configure(state="normal" if not busy and self.mode.get() == "computer" else "disabled")
        if not self.worker:
            ready = self.mode.get() == "custom" or self.computer_position_ready
            self.button.configure(state="normal" if not busy and ready else "disabled",
                                  text="連線並移動至起點座標")
            self.clear_button.configure(state="disabled" if busy else "normal")

    def fetch_computer_position(self):
        if self.worker or self.locating or self.closing or self.mode.get() != "computer":
            return
        self.locating = True
        self.computer_position_ready = False
        self.status.set("正在取得電腦位置，最多約 35 秒…")
        self.refresh_mode_controls()

        def locate():
            try:
                self.events.put(("computer_position", get_computer_position()))
            except Exception as exc:
                self.events.put(("computer_position_error", str(exc)))

        threading.Thread(target=locate, name="computer-location", daemon=True).start()

    def key_down(self, event):
        if not self.connected or self.closing:
            return
        if event.keysym.lower() in {"w", "a", "s", "d", "up", "left", "down", "right"}:
            if isinstance(self.root.focus_get(), (ttk.Entry, tk.Entry, tk.Text, ttk.Treeview, ttk.Combobox)):
                return
            self.keys.add(event.keysym.lower())
            self.update_direction()
            return "break"

    def key_up(self, event):
        self.keys.discard(event.keysym.lower())
        self.update_direction()

    def release_all(self):
        self.keys.clear()
        self.update_direction()

    def update_direction(self):
        east = int(bool(self.keys & {"d", "right"})) - int(bool(self.keys & {"a", "left"}))
        north = int(bool(self.keys & {"w", "up"})) - int(bool(self.keys & {"s", "down"}))
        if self.worker:
            self.worker.direction(east, north)
        self.motion.set(f"移動中 · {self.speed_kmh:g} km/h" if east or north else "停止")
        for direction, label in self.direction_labels.items():
            label.configure(bg="#9edfd0" if direction == (east, north) else "#eeeeee")

    def toggle(self):
        if self.closing or self.locating:
            return
        if self.worker:
            self.connected = False
            self.release_all()
            self.worker.stop()
            self.button.configure(state="disabled", text="正在中斷連線…")
            return
        if self.mode.get() == "computer" and not self.computer_position_ready:
            return
        try:
            position = validate_position(self.latitude.get(), self.longitude.get())
            speed = validate_speed(self.speed.get())
        except ValueError as exc:
            messagebox.showerror("座標或速度無效", str(exc))
            return
        self.cleanup_error = False
        self.speed_kmh = speed
        self.last_confirmed = None
        self.worker = IPhoneWorker(position, self.events, speed_kmh=self.speed_kmh)
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
        self.worker = IPhoneWorker(self.position, self.events, clear_only=True)
        self.button.configure(state="disabled")
        self.clear_button.configure(state="disabled", text="正在清除，請保持 USB 連接…")
        self.refresh_mode_controls()
        self.worker.start()

    def persist(self):
        # Never save a speculative coordinate that the iPhone did not acknowledge.
        position = self.last_confirmed or self.position
        save_position(CONFIG_PATH, position, self.speed_kmh)
        self.write_log(f"已保存最後位置：{position[0]:.8f}, {position[1]:.8f}")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind in {"computer_position", "computer_position_error"}:
                    self.locating = False
                    if kind == "computer_position":
                        self.computer_position = value
                        self.latitude.set(f"{value[0]:.8f}")
                        self.longitude.set(f"{value[1]:.8f}")
                        self.computer_position_ready = True
                        self.status.set("已取得電腦起點位置。請確認座標，再按連線；連線後可用 WASD／方向鍵移動。")
                    else:
                        self.status.set(value)
                        self.write_log(value)
                    self.refresh_mode_controls()
                elif kind == "position":
                    self.last_confirmed = self.position = value
                    self.latitude.set(f"{value[0]:.8f}")
                    self.longitude.set(f"{value[1]:.8f}")
                elif kind == "connected":
                    if not self.closing and not self.worker.stop_requested.is_set():
                        self.connected = True
                        self.status.set(value)
                        self.button.configure(state="normal", text="中斷連線並清除模擬定位")
                        self.root.focus_set()
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
                    self.button.configure(state="normal", text="連線並移動至輸入座標")
                    self.clear_button.configure(state="normal", text="清除模擬定位（恢復真實 GPS）")
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
                    self.position = validate_position(self.latitude.get(), self.longitude.get())
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


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        detail = traceback.format_exc()
        (APP_DIR / "startup-error.log").write_text(detail, encoding="utf-8")
        if "--self-test" not in sys.argv and "--check-device" not in sys.argv:
            messagebox.showerror("程式啟動失敗", f"{detail}\n詳細訊息已寫入 startup-error.log。")
        sys.exit(1)
