"""Read one operating-system location fix without blocking the GUI."""

import sys

from .iphone_backend import validate_position

LOCATION_ATTEMPT_TIMEOUT_SECONDS = 20


def get_computer_position():
    """Dispatch to the active operating system's location provider."""
    if sys.platform == "win32":
        return _get_windows_position()
    if sys.platform == "darwin":
        return _get_macos_position(timeout=LOCATION_ATTEMPT_TIMEOUT_SECONDS)
    raise RuntimeError("目前位置支援 Windows 與 macOS；此作業系統尚未提供定位服務整合。")


def _get_windows_position():
    import json
    import os
    import subprocess
    from pathlib import Path

    script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Device
$watcher = New-Object System.Device.Location.GeoCoordinateWatcher
try {
    $watcher.Start($false)
    $deadline = [DateTime]::UtcNow.AddSeconds(17)
    while ($watcher.Position.Location.IsUnknown) {
        if ($watcher.Permission -eq 'Denied') { throw 'Windows location permission denied.' }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Windows location timed out or is unavailable.' }
        Start-Sleep -Milliseconds 200
    }
    $location = $watcher.Position.Location
    @{latitude=$location.Latitude; longitude=$location.Longitude} | ConvertTo-Json -Compress
} finally {
    $watcher.Stop()
    $watcher.Dispose()
}
"""
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=LOCATION_ATTEMPT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("無法取得電腦位置，請確認 Windows 定位服務已開啟，再重試。") from exc
    if result.returncode:
        raise RuntimeError("無法取得電腦位置。請到 Windows「設定 → 隱私權與安全性 → 位置」開啟定位服務並允許桌面應用程式存取位置，再重試。")
    data = json.loads(result.stdout.decode("utf-8-sig"))
    return validate_position(data["latitude"], data["longitude"])


def _get_macos_position(timeout=LOCATION_ATTEMPT_TIMEOUT_SECONDS):
    import time

    try:
        import CoreLocation
        from Foundation import NSDate, NSRunLoop
    except ImportError as exc:
        raise RuntimeError(
            "macOS 取位需要 PyObjC。請在目前的 Python 環境執行："
            "python -m pip install -r requirements.txt"
        ) from exc

    if not CoreLocation.CLLocationManager.locationServicesEnabled():
        raise RuntimeError("macOS 定位服務尚未開啟，請到「系統設定 → 隱私權與安全性 → 定位服務」啟用。")

    manager = CoreLocation.CLLocationManager.alloc().init()
    try:
        authorization = int(manager.authorizationStatus())
        not_determined = getattr(CoreLocation, "kCLAuthorizationStatusNotDetermined", 0)
        denied = getattr(CoreLocation, "kCLAuthorizationStatusDenied", 2)
        restricted = getattr(CoreLocation, "kCLAuthorizationStatusRestricted", 1)
        if authorization == denied:
            raise RuntimeError("macOS 尚未允許此 Python／終端機使用定位，請到「系統設定 → 隱私權與安全性 → 定位服務」授權。")
        if authorization == restricted:
            raise RuntimeError("此 macOS 帳號或裝置受到限制，無法使用定位服務。")
        if authorization == not_determined:
            try:
                manager.requestWhenInUseAuthorization()
            except Exception as exc:
                raise RuntimeError(
                    "macOS 無法顯示定位授權。請確認目前使用的 Python／終端機具有定位權限。"
                ) from exc

        manager.startUpdatingLocation()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            authorization = int(manager.authorizationStatus())
            if authorization in (denied, restricted):
                raise RuntimeError("macOS 未授權此 Python／終端機使用定位，請在系統設定中允許定位服務。")

            location = manager.location()
            if location is not None and location.horizontalAccuracy() >= 0:
                timestamp = location.timestamp()
                if -120 <= timestamp.timeIntervalSinceNow() <= 5:
                    coordinate = location.coordinate()
                    return validate_position(coordinate.latitude, coordinate.longitude)

            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))

        raise RuntimeError(
            "macOS 定位逾時或尚無位置資料。請開啟定位服務並允許目前的 Python／終端機存取位置後重試。"
        )
    finally:
        manager.stopUpdatingLocation()

