"""Persistent iPhone location session and coordinate/config helpers."""

import asyncio
import json
import math
import os
import tempfile
import threading
import time
import traceback
from contextlib import AsyncExitStack
from pathlib import Path

SPEED_KMH = 20.0
TICK_SECONDS = 0.1
EARTH_RADIUS_M = 6_371_008.8
DEFAULT_POSITION = (35.681236, 139.767125)


async def clear_location(udid=None):
    """Use a fresh session, as in the separately verified CLI clear flow.

    stopLocationSimulation is fire-and-forget. Returning means the request was
    sent, never that Core Location or Maps has confirmed a real GPS fix.
    """
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

    async with UserspaceRsdTunnel(serial=udid, autopair=False, remotepairing_fallback=False) as rsd:
        async with DvtProvider(rsd) as dvt, LocationSimulation(dvt) as simulation:
            await simulation.clear()
            # Let the no-reply request travel through the userspace transport
            # before tearing it down. This delay is not a GPS confirmation.
            await asyncio.sleep(1)


def validate_position(latitude, longitude):
    latitude, longitude = float(latitude), float(longitude)
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("緯度必須介於 -90 與 90。")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("經度必須介於 -180 與 180。")
    return latitude, longitude


def validate_speed(speed):
    speed = float(speed)
    if not math.isfinite(speed) or not 0.1 <= speed <= 1000:
        raise ValueError("移動速度必須介於 0.1 與 1000 km/h。")
    return speed


def load_speed(path):
    if not path.exists():
        return SPEED_KMH
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return validate_speed(data.get("speed_kmh", SPEED_KMH))


def move_position(latitude, longitude, east, north, seconds, speed_kmh=SPEED_KMH):
    """Great-circle step, normalizing diagonals to the same total speed."""
    length = math.hypot(east, north)
    if not length or seconds <= 0:
        return latitude, longitude
    bearing = math.atan2(east / length, north / length)
    distance = speed_kmh / 3.6 * seconds / EARTH_RADIUS_M
    lat, lon = math.radians(latitude), math.radians(longitude)
    next_lat = math.asin(max(-1.0, min(1.0,
        math.sin(lat) * math.cos(distance)
        + math.cos(lat) * math.sin(distance) * math.cos(bearing))))
    next_lon = lon + math.atan2(
        math.sin(bearing) * math.sin(distance) * math.cos(lat),
        math.cos(distance) - math.sin(lat) * math.sin(next_lat),
    )
    return math.degrees(next_lat), (math.degrees(next_lon) + 180) % 360 - 180


def load_position(path):
    if not path.exists():
        return DEFAULT_POSITION
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return validate_position(data["latitude"], data["longitude"])


def save_position(path, position, speed_kmh=SPEED_KMH):
    latitude, longitude = validate_position(*position)
    speed_kmh = validate_speed(speed_kmh)
    # Atomic replace keeps the old config intact if writing is interrupted.
    fd, temporary = tempfile.mkstemp(prefix=".gps-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"latitude": latitude, "longitude": longitude, "speed_kmh": speed_kmh}, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class IPhoneWorker(threading.Thread):
    """Own all asyncio/device resources on one background thread; never call Tk."""

    def __init__(self, position, events, *, clear_only=False, speed_kmh=SPEED_KMH):
        super().__init__(name="iphone-location", daemon=False)
        self.position = validate_position(*position)
        self.events = events
        self.stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._direction = (0, 0)
        self._speed_kmh = validate_speed(speed_kmh)
        self.stage = "初始化"
        self.clear_only = clear_only

    def direction(self, east, north):
        with self._lock:
            self._direction = (east, north)

    def stop(self):
        self.direction(0, 0)
        self.stop_requested.set()

    def set_speed(self, speed_kmh):
        speed_kmh = validate_speed(speed_kmh)
        with self._lock:
            self._speed_kmh = speed_kmh

    def publish(self, kind, value):
        self.events.put((kind, value))

    def run(self):
        try:
            if self.clear_only:
                self.stage = "獨立 clear / tunnel / DVT"
                self.publish("status", "正在重新連線並清除模擬定位…")
                asyncio.run(asyncio.wait_for(clear_location(), timeout=70))
                self.publish("log", "獨立 clear 要求已送出；請在手機點目前位置，確認真實定位。")
            else:
                asyncio.run(self._session())
        except Exception:
            self.publish("error", f"失敗階段：{self.stage}\n{traceback.format_exc()}")
        finally:
            self.publish("done", self.position)

    async def _session(self):
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
        from pymobiledevice3.usbmux import list_devices

        stack = AsyncExitStack()
        simulation = None
        attempted_set = False
        udid = None
        try:
            self.stage = "USB 裝置列舉"
            self.publish("status", "正在檢查 USB iPhone…")
            devices = await asyncio.wait_for(list_devices(), timeout=15)
            devices = [d for d in devices if d.connection_type == "USB"]
            if len(devices) != 1:
                raise RuntimeError(f"偵測到 {len(devices)} 台 USB 裝置，請只連接一台 iPhone。")
            udid = devices[0].serial
            self.stage = "USB pairing / Developer Mode"
            async with await asyncio.wait_for(
                create_using_usbmux(serial=udid, autopair=False), timeout=20,
            ) as lockdown:
                if not lockdown.session_id:
                    raise RuntimeError("配對無效，請解鎖 iPhone 並信任這部電腦。")
                if not await asyncio.wait_for(lockdown.get_developer_mode_status(), timeout=10):
                    raise RuntimeError("請先開啟 iPhone 開發者模式並完成重新啟動確認。")
                self.publish("log", f"USB / pairing 通過，UDID：{udid}")
            if self.stop_requested.is_set():
                return
            self.stage = "Userspace tunnel / RemoteXPC"
            self.publish("status", "正在建立 iPhone 開發者連線…")
            tunnel = UserspaceRsdTunnel(
                serial=udid, autopair=False, remotepairing_fallback=False,
            )
            rsd = await asyncio.wait_for(stack.enter_async_context(tunnel), timeout=45)
            self.stage = "DVT"
            dvt = await asyncio.wait_for(stack.enter_async_context(DvtProvider(rsd)), timeout=20)
            simulation = await asyncio.wait_for(stack.enter_async_context(LocationSimulation(dvt)), timeout=15)
            if self.stop_requested.is_set():
                return
            self.stage = "初始模擬座標設定"
            attempted_set = True
            await asyncio.wait_for(simulation.set(*self.position), timeout=8)
            self.publish("position", self.position)
            self.publish("connected", "已連線，WASD 可移動；請用 Apple Maps 確認藍點。")
            last_tick = time.monotonic()
            while not self.stop_requested.is_set():
                await asyncio.sleep(TICK_SECONDS)
                now = time.monotonic()
                # Do not catch up with a large jump after a stall.
                elapsed = min(now - last_tick, 0.25)
                last_tick = now
                with self._lock:
                    east, north = self._direction
                    speed_kmh = self._speed_kmh
                if self.stop_requested.is_set():
                    break
                if tunnel.rsd is None:
                    self.stage = "USB / tunnel 連線中斷"
                    raise ConnectionError("iPhone tunnel 已關閉，請確認 USB 連接並重新連線。")
                if not (east or north):
                    continue
                next_position = move_position(*self.position, east, north, elapsed, speed_kmh)
                self.stage = "DVT 移動座標更新"
                await asyncio.wait_for(simulation.set(*next_position), timeout=8)
                self.position = next_position  # Only commit acknowledged coordinates.
                self.publish("position", self.position)
        finally:
            closed = False
            try:
                await asyncio.wait_for(stack.aclose(), timeout=15)
                closed = True
            except Exception:
                self.publish("error", "關閉 Developer Services / tunnel 時發生錯誤：\n" + traceback.format_exc())
            if attempted_set:
                if not closed:
                    self.publish("error", "舊連線未正常關閉，不能安全重建 clear 連線。請結束程式後單獨執行 clear。")
                else:
                    self.publish("status", "移動已停止，正在用獨立連線清除模擬定位…")
                    try:
                        await asyncio.wait_for(clear_location(udid), timeout=70)
                        self.publish("log", "獨立 clear 要求已送出；尚需在 Apple Maps 確認真實定位。")
                    except Exception:
                        self.publish("error", "失敗階段：獨立 clear / tunnel / DVT。\n"
                                     "請保持 USB 連接並解鎖手機，再按「清除模擬定位」重試。\n"
                                     + traceback.format_exc())
