"""Shared application operations used by both native GUI frontends."""

import threading
import time

from services.iphone_backend import (
    DEFAULT_POSITION,
    SPEED_KMH,
    IPhoneWorker,
    load_position,
    load_speed,
    save_position,
    validate_position,
    validate_speed,
)
from services.location_records import append_record, load_records, save_records
from services.pc_location import get_computer_position

COMPUTER_LOCATION_MAX_ATTEMPTS = 5


class JoystickController:
    """Toolkit-independent state and use cases for the joystick application.

    Tk and Qt own their widgets, event loops, and visual feedback. Both delegate
    settings, coordinate validation, record CRUD, and worker setup to this class.
    """

    def __init__(self, config_path, record_path):
        self.config_path = config_path
        self.record_path = record_path
        self.load_error = None
        self.position = DEFAULT_POSITION
        self.speed_kmh = SPEED_KMH
        self.records = []
        try:
            position = load_position(config_path)
            speed_kmh = load_speed(config_path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.load_error = (
                f"讀取 config.json 失敗：{exc}\n"
                "目前顯示預設東京座標，連線前請確認。"
            )
        else:
            self.position = position
            self.speed_kmh = speed_kmh

    def apply_speed(self, speed_text, position, last_confirmed, worker=None):
        speed = validate_speed(speed_text)
        saved_position = last_confirmed or position
        save_position(self.config_path, saved_position, speed)
        if worker:
            worker.set_speed(speed)
        self.position = saved_position
        self.speed_kmh = speed
        return speed

    @staticmethod
    def prepare_connection(latitude, longitude, speed_text):
        position = validate_position(latitude, longitude)
        speed = validate_speed(speed_text)
        return position, speed

    @staticmethod
    def validate_position(latitude, longitude):
        return validate_position(latitude, longitude)

    def persist_position(self, position, speed_kmh):
        position = validate_position(*position)
        speed_kmh = validate_speed(speed_kmh)
        save_position(self.config_path, position, speed_kmh)
        self.position = position
        self.speed_kmh = speed_kmh
        return position

    def reload_records(self):
        self.records = load_records(self.record_path)
        return self.records

    def current_record_position(
        self,
        *,
        connected,
        last_confirmed,
        mode,
        computer_position_ready,
        latitude,
        longitude,
    ):
        if connected:
            if last_confirmed is None:
                raise ValueError("尚未收到手機確認的座標。")
            return last_confirmed
        if mode == "computer" and not computer_position_ready:
            raise ValueError("請先取得電腦位置。")
        return validate_position(latitude, longitude)

    def add_record(self, label, position):
        append_record(self.record_path, label, position)
        return self.reload_records()

    def update_record_position(self, index, position):
        records = [dict(record) for record in self.records]
        latitude, longitude = validate_position(*position)
        records[index].update(latitude=latitude, longitude=longitude)
        save_records(self.record_path, records, expected=self.records)
        return self.reload_records()

    def edit_record(self, index, label, latitude, longitude):
        latitude, longitude = validate_position(latitude, longitude)
        records = [dict(record) for record in self.records]
        records[index] = dict(
            label=label.strip(), latitude=latitude, longitude=longitude
        )
        save_records(self.record_path, records, expected=self.records)
        return self.reload_records()

    def delete_record(self, index):
        records = [dict(record) for record in self.records]
        del records[index]
        save_records(self.record_path, records, expected=self.records)
        return self.reload_records()

    @staticmethod
    def make_worker(position, events, *, speed_kmh=SPEED_KMH, clear_only=False):
        return IPhoneWorker(
            position,
            events,
            speed_kmh=speed_kmh,
            clear_only=clear_only,
        )

    @staticmethod
    def start_computer_location(events):
        def locate():
            errors = []
            for attempt in range(1, COMPUTER_LOCATION_MAX_ATTEMPTS + 1):
                events.put(("computer_position_attempt", (attempt, COMPUTER_LOCATION_MAX_ATTEMPTS)))
                try:
                    position = get_computer_position()
                except Exception as exc:
                    reason = str(exc).strip() or repr(exc)
                    errors.append(reason)
                    events.put((
                        "computer_position_attempt_error",
                        (attempt, COMPUTER_LOCATION_MAX_ATTEMPTS, reason),
                    ))
                    if attempt < COMPUTER_LOCATION_MAX_ATTEMPTS:
                        time.sleep(0.5)
                else:
                    events.put(("computer_position", position))
                    return

            events.put((
                "computer_position_error",
                {"attempts": COMPUTER_LOCATION_MAX_ATTEMPTS, "errors": errors},
            ))

        thread = threading.Thread(target=locate, name="computer-location", daemon=True)
        thread.start()
        return thread

    @staticmethod
    def validate_destination(latitude, longitude):
        return validate_position(latitude, longitude)

    @staticmethod
    def navigate(worker, *, connected, closing, destination):
        if not connected or not worker or closing:
            raise RuntimeError("請先連線至現在地，再開始自動前往。")
        return worker.navigate(*destination)
