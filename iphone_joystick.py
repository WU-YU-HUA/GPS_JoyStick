"""Tkinter iPhone GPS joystick. Run inside the iphone-gps conda environment."""

import queue
import logging
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from iphone_backend import (
    DEFAULT_POSITION, IPhoneWorker, load_position, save_position, validate_position,
)

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"


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
        load_error = None
        try:
            self.position = load_position(CONFIG_PATH)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.position = DEFAULT_POSITION
            load_error = f"讀取 config.json 失敗：{exc}\n目前顯示預設東京座標，連線前請確認。"

        root.title("iPhone GPS Joystick")
        root.geometry("650x640")
        root.minsize(580, 580)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.latitude = tk.StringVar(value=f"{self.position[0]:.8f}")
        self.longitude = tk.StringVar(value=f"{self.position[1]:.8f}")
        self.status = tk.StringVar(value="尚未連線。請接上 USB、解鎖 iPhone。")
        self.motion = tk.StringVar(value="停止")
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(9, weight=1)
        ttk.Label(frame, text="iPhone GPS Joystick", font=("Segoe UI", 19, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(frame, text="固定 20 km/h  ·  USB 連線  ·  WASD 八方向").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 20))
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

    def key_down(self, event):
        if not self.connected or self.closing:
            return
        if event.keysym.lower() in "wasd" and len(event.keysym) == 1:
            if isinstance(self.root.focus_get(), (ttk.Entry, tk.Entry, tk.Text)):
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
        east = int("d" in self.keys) - int("a" in self.keys)
        north = int("w" in self.keys) - int("s" in self.keys)
        if self.worker:
            self.worker.direction(east, north)
        self.motion.set("移動中 · 20 km/h" if east or north else "停止")
        for direction, label in self.direction_labels.items():
            label.configure(bg="#9edfd0" if direction == (east, north) else "#eeeeee")

    def toggle(self):
        if self.worker:
            self.connected = False
            self.release_all()
            self.worker.stop()
            self.button.configure(state="disabled", text="正在中斷連線…")
            return
        try:
            position = validate_position(self.latitude.get(), self.longitude.get())
        except ValueError as exc:
            messagebox.showerror("座標無效", str(exc))
            return
        self.cleanup_error = False
        self.last_confirmed = None
        self.worker = IPhoneWorker(position, self.events)
        for entry in self.entries:
            entry.configure(state="disabled")
        self.button.configure(state="disabled", text="正在連線…")
        self.clear_button.configure(state="disabled")
        self.worker.start()

    def clear_location(self):
        if self.worker or self.closing:
            return
        self.release_all()
        self.cleanup_error = False
        self.worker = IPhoneWorker(self.position, self.events, clear_only=True)
        self.button.configure(state="disabled")
        self.clear_button.configure(state="disabled", text="正在清除，請保持 USB 連接…")
        self.worker.start()

    def persist(self):
        # Never save a speculative coordinate that the iPhone did not acknowledge.
        position = self.last_confirmed or self.position
        save_position(CONFIG_PATH, position)
        self.write_log(f"已保存最後位置：{position[0]:.8f}, {position[1]:.8f}")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "position":
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
                    try:
                        self.persist()
                    except OSError as exc:
                        self.closing = False
                        messagebox.showerror("儲存失敗", f"{exc}\n最後座標仍顯示於畫面，請先記下。")
                    for entry in self.entries:
                        entry.configure(state="normal")
                    self.button.configure(state="normal", text="連線並移動至輸入座標")
                    self.clear_button.configure(state="normal", text="清除模擬定位（恢復真實 GPS）")
                    if self.closing:
                        if self.cleanup_error:
                            messagebox.showwarning("結束前請確認", "發生連線或清除錯誤。請確認手機定位已恢復；"
                                                   "必要時執行 python test_iphone.py clear。")
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
