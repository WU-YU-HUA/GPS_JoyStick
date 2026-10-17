"""Read a single Windows location fix without blocking the GUI."""

import json
import os
from pathlib import Path
import subprocess

from iphone_backend import validate_position


def get_computer_position():
    script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Device
$watcher = New-Object System.Device.Location.GeoCoordinateWatcher
try {
    $watcher.Start($false)
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
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
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=35,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("無法取得電腦位置，請確認 Windows 定位服務已開啟，再重試。") from exc
    if result.returncode:
        raise RuntimeError("無法取得電腦位置。請到 Windows「設定 → 隱私權與安全性 → 位置」開啟定位服務並允許桌面應用程式存取位置，再重試。")
    data = json.loads(result.stdout.decode("utf-8-sig"))
    return validate_position(data["latitude"], data["longitude"])
