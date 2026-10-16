"""Offline tests: no iPhone connection or simulated location changes."""

import math
import queue
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from iphone_backend import (
    EARTH_RADIUS_M, IPhoneWorker, load_position, move_position,
    save_position, validate_position,
)


def distance(a, b):
    lat1, lat2 = map(math.radians, (a[0], b[0]))
    dlat = lat2 - lat1
    dlon = math.radians(b[1] - a[1])
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(haversine))


class PositionTests(unittest.TestCase):
    def test_all_eight_directions_have_same_speed(self):
        start = (25.0, 121.0)
        for east, north in ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)):
            with self.subTest(east=east, north=north):
                end = move_position(*start, east, north, 1)
                self.assertAlmostEqual(distance(start, end), 20 / 3.6, places=6)
                if east:
                    self.assertEqual(math.copysign(1, end[1] - start[1]), east)
                if north:
                    self.assertEqual(math.copysign(1, end[0] - start[0]), north)

    def test_stop_and_dateline(self):
        self.assertEqual(move_position(25, 121, 0, 0, 1), (25, 121))
        result = move_position(0, 179.99999, 1, 0, 1)
        self.assertLess(result[1], 0)
        validate_position(*result)

    def test_invalid_coordinates(self):
        for position in [(91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))]:
            with self.assertRaises(ValueError):
                validate_position(*position)

    def test_config_roundtrip_and_failed_replace_preserves_old_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            original = (25.123456789, 121.987654321)
            save_position(path, original)
            self.assertEqual(load_position(path), original)
            with patch("iphone_backend.os.replace", side_effect=OSError("read only")):
                with self.assertRaises(OSError):
                    save_position(path, (35, 139))
            self.assertEqual(load_position(path), original)
            self.assertEqual(list(Path(folder).iterdir()), [path])


class WorkerTests(unittest.TestCase):
    def exercise_worker(self, fail_move=False, fail_clear=False):
        events = queue.Queue()
        worker = IPhoneWorker((25, 121), events)
        worker.direction(1, 1)
        sent = []
        cleared = []
        closed = []

        class Context:
            def __init__(self, *args, **kwargs):
                self.session_id = "fake"
                self.rsd = self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                closed.append(type(self).__name__)

            async def get_developer_mode_status(self):
                return True

        class Simulation(Context):
            async def set(self, latitude, longitude):
                if sent and fail_move:
                    raise ConnectionError("test USB disconnect")
                sent.append((latitude, longitude))
                if len(sent) >= 3:
                    worker.stop()

            async def clear(self):
                cleared.append(True)

        async def devices():
            return [types.SimpleNamespace(connection_type="USB", serial="fake")]

        async def lockdown(**kwargs):
            return Context()

        async def independent_clear(udid=None):
            self.assertEqual(len(closed), 4, "old session must be closed before independent clear")
            if fail_clear:
                raise ConnectionError("test clear failure")
            cleared.append(True)

        with (
            patch("pymobiledevice3.usbmux.list_devices", devices),
            patch("pymobiledevice3.lockdown.create_using_usbmux", lockdown),
            patch("pymobiledevice3.remote.userspace_tunnel.UserspaceRsdTunnel", Context),
            patch("pymobiledevice3.services.dvt.instruments.dvt_provider.DvtProvider", Context),
            patch("pymobiledevice3.services.dvt.instruments.location_simulation.LocationSimulation", Simulation),
            patch("iphone_backend.clear_location", independent_clear),
        ):
            worker.start()
            worker.join(timeout=5)
            if worker.is_alive():
                worker.stop()
                worker.join(timeout=5)
                self.fail("worker did not stop")
        messages = []
        while not events.empty():
            messages.append(events.get_nowait())
        self.assertEqual(cleared, [] if fail_clear else [True])
        self.assertEqual(len(closed), 4)
        self.assertEqual(messages[-1][0], "done")
        return sent, messages

    def test_persistent_session_updates_then_clears(self):
        sent, messages = self.exercise_worker()
        self.assertEqual(len(sent), 3)
        self.assertGreater(sent[-1][0], sent[0][0])
        self.assertGreater(sent[-1][1], sent[0][1])
        self.assertEqual(messages[-1][1], sent[-1])
        self.assertFalse(any(kind == "error" for kind, _ in messages))

    def test_failed_update_keeps_last_acknowledged_position(self):
        sent, messages = self.exercise_worker(fail_move=True)
        self.assertEqual(sent, [(25, 121)])
        self.assertEqual(messages[-1][1], (25, 121))
        self.assertTrue(any(kind == "error" and "test USB disconnect" in value for kind, value in messages))

    def test_clear_failure_is_visible_and_position_is_preserved(self):
        sent, messages = self.exercise_worker(fail_clear=True)
        self.assertEqual(messages[-1][1], sent[-1])
        self.assertTrue(any(kind == "error" and "test clear failure" in value for kind, value in messages))
        self.assertFalse(any(kind == "log" and "要求已送出" in value for kind, value in messages))

    def test_manual_clear_does_not_set_position(self):
        calls = []

        async def clear(udid=None):
            calls.append(udid)

        events = queue.Queue()
        worker = IPhoneWorker((25, 121), events, clear_only=True)
        with patch("iphone_backend.clear_location", clear):
            worker.start()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, [None])
        messages = list(events.queue)
        self.assertFalse(any(kind in ("position", "connected", "error") for kind, _ in messages))
        self.assertEqual(messages[-1], ("done", (25.0, 121.0)))


if __name__ == "__main__":
    unittest.main()
