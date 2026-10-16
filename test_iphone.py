"""iPhone USB / DVT 最小驗證；請在 conda iphone-gps 環境執行。"""

import argparse
import asyncio
import importlib.metadata
import json
import os
import subprocess
import sys
import traceback


LATITUDE = "35.681236"
LONGITUDE = "139.767125"


class TestFailure(Exception):
    pass


def fail(stage, command, error, next_step):
    print(f"\n失敗階段：{stage}")
    print(f"實際執行 command：{command}")
    print(f"完整錯誤訊息：\n{error}")
    hints = {
        "PermissionError": "Windows 或執行沙箱權限；先看錯誤指出的檔案/操作。",
        "NotTrusted": "手機尚未信任電腦。",
        "Pairing": "USB pairing 或配對記錄問題。",
        "DeveloperMode": "Developer Mode 尚未啟用或重啟確認未完成。",
        "DeveloperDiskImage": "Developer Disk Image 尚未掛載或不可用。",
        "InvalidService": "所需服務不可用；需區分 DDI、Developer Mode 與服務版本。",
        "Tunneld": "工具嘗試使用 tunneld，但 daemon 無法連線；先查自動 tunnel 前面的原始錯誤。",
        "RemoteXPC": "RemoteXPC 連線/握手問題。",
        "NoDevice": "目前 USB 裝置不可見或連線已中斷。",
    }
    cause = next((text for token, text in hints.items() if token.lower() in error.lower()),
                 "目前輸出不足以確認根因；請依原始錯誤與失敗階段繼續排查。")
    if stage == "Developer Mode" and error.strip() == "false":
        cause = "手機回報 Developer Mode 未啟用。"
    print(f"可能原因：{cause}（不能直接推論 iOS 不相容。）")
    print(f"下一個最小排查步驟：{next_step}")
    raise TestFailure


def cli(stage, args, *, interactive=False):
    command = [sys.executable, "-m", "pymobiledevice3", "--no-color", *args]
    display = subprocess.list2cmdline(command)
    print(f"\n[{stage}]\n> {display}", flush=True)
    env = os.environ.copy()
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NO_COLOR="1")
    if interactive:
        # 保留 stdin 供官方 set 指令的「Press ENTER to exit」使用。
        # 逐字轉送 stdout，確保沒有換行的提示也能立即顯示。
        output = []
        with subprocess.Popen(
            command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", bufsize=0,
        ) as process:
            try:
                while char := process.stdout.read(1):
                    print(char, end="", flush=True)
                    output.append(char)
                code = process.wait()
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                raise
        output = "".join(output)
    else:
        try:
            result = subprocess.run(
                command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or b""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            fail(stage, display, output + "\nTimeoutExpired: 超過 120 秒。",
                 "確認手機已解鎖、信任電腦，再單獨重跑上列 command；不要跳到下一階段。")
        output, code = result.stdout, result.returncode
        print(output, end="" if output.endswith("\n") else "\n")
    if code:
        fail(stage, display, output or f"程序結束碼：{code}",
             "先辨識錯誤屬於權限、Trust、Developer Mode、DDI、Tunnel/RemoteXPC 或 DVT；保留完整輸出。")
    return output


async def pairing(udid):
    from pymobiledevice3.lockdown import create_using_usbmux

    # 建立連線時就會驗證 pairing；不可再次呼叫 validate_pairing，
    # 否則同一連線重複 StartSession 會回報 SessionActive。
    async with await create_using_usbmux(serial=udid, autopair=False) as device:
        if not device.session_id:
            raise RuntimeError("沒有有效 pairing session；請解鎖手機並確認信任。")
        print("Pairing session：有效")


def check(requested_udid):
    print(f"Python：{sys.executable}")
    print(f"Conda 環境：{os.environ.get('CONDA_DEFAULT_ENV', '未啟用')}")
    try:
        version = importlib.metadata.version("pymobiledevice3")
    except importlib.metadata.PackageNotFoundError:
        fail("Python 環境", "python -m pip show pymobiledevice3", traceback.format_exc(),
             "conda activate iphone-gps，然後 python -m pip install -r requirements.txt")
    print(f"pymobiledevice3：{version}（本程式依 11.32.0 驗證）")
    cli("確認 USB 指令", ["usbmux", "list", "--help"])
    raw = cli("USB 列舉（不連接 lockdown）", ["usbmux", "list", "--usb", "--simple"])
    try:
        udids = json.loads(raw)
        if not isinstance(udids, list) or any(not isinstance(u, str) for u in udids):
            raise ValueError("預期 USB UDID 字串陣列")
    except (ValueError, TypeError):
        fail("USB 列舉輸出解析", "usbmux list --usb --simple", raw,
             "確認目前版本的 usbmux list --help 與原始輸出格式。")
    if not udids or (requested_udid and requested_udid not in udids):
        fail("USB 裝置列舉", "usbmux list --usb --simple", raw,
             "先檢查裝置管理員的 Apple USB 裝置/驅動與 Apple Devices 程序，再確認 USB 線與 Trust。")
    if not requested_udid and len(udids) != 1:
        fail("USB 裝置選擇", "usbmux list --usb --simple", raw,
             "使用 --udid 指定其中一台手機。")
    udid = requested_udid or udids[0]
    print(f"選定 USB UDID：{udid}")
    cli("USB 裝置名稱與 iOS", ["usbmux", "list", "--usb"])
    try:
        asyncio.run(pairing(udid))
    except Exception:
        fail("USB pairing", "Python API: create_using_usbmux(autopair=False)",
             traceback.format_exc(), "保持手機解鎖並確認信任；勿直接 unpair。先排查現有 pairing 與快取權限。")
    raw = cli("Developer Mode", ["amfi", "developer-mode-status", "--udid", udid])
    try:
        enabled = json.loads(raw)
    except ValueError:
        fail("Developer Mode 輸出解析", "amfi developer-mode-status", raw,
             "檢查上述完整輸出及目前版本 help。")
    if enabled is not True:
        fail("Developer Mode", "amfi developer-mode-status", raw,
             "iPhone：設定 → 隱私權與安全性 → 開發者模式；開啟、依提示重啟並確認，再解鎖重跑。")
    print("\n連線檢查通過；尚未驗證 Developer Services、GPS 或 clear。")
    return udid


def location(action, udid):
    base = ["developer", "dvt", "simulate-location", action]
    cli(f"確認 {action} syntax", [*base, "--help"])
    args = [*base, "--udid", udid]
    if action == "set":
        print("\n請打開 Apple Maps，點定位按鈕，先確認原本藍點。")
        input("準備好後按 Enter，開始設定東京車站座標：")
        print("指令執行後請觀察藍點；確認結果後，才在 Press ENTER to exit 提示按 Enter。")
        args += ["--", LATITUDE, LONGITUDE]
    cli(f"DVT simulate-location {action}（自動 tunnel）", args, interactive=action == "set")
    print(f"\n{action} 指令正常結束；這不代表 Apple Maps 已驗證成功。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["check", "set", "clear", "run"], default="check")
    parser.add_argument("--udid", help="多台手機時指定 USB UDID")
    args = parser.parse_args()
    if args.action == "clear":
        # 救援清除不可被 Developer Mode 前置檢查擋住。
        location("clear", args.udid) if args.udid else clear_default()
        print("請在 Apple Maps 點定位按鈕，確認藍點恢復真實位置。")
        return
    udid = check(args.udid)
    if args.action == "check":
        return
    if args.action == "set":
        location("set", udid)
        print("測完請執行：python test_iphone.py clear --udid " + udid)
        return
    try:
        location("set", udid)
        moved = input("Apple Maps 藍點有移到東京車站附近嗎？[y/N]：").strip().lower() == "y"
    finally:
        # 設定失敗或中斷也嘗試清除；清除失敗會完整呈現。
        print("\n現在執行獨立 clear 指令。")
        location("clear", udid)
    restored = input("Apple Maps 點定位按鈕後，藍點有恢復真實位置嗎？[y/N]：").strip().lower() == "y"
    if not moved or not restored:
        fail("Apple Maps 人工驗證", "set → Apple Maps → clear → Apple Maps",
             f"東京藍點確認：{moved}；真實定位恢復確認：{restored}",
             "先確認 Apple Maps 定位權限、定位按鈕與上述 DVT 輸出；不可宣告整體測試通過。")
    print("\n完整驗證通過：USB、pairing、Developer Mode、DVT 設定，以及你確認的東京藍點與 clear 後真實定位。")


def clear_default():
    # 未指定 UDID 時沿用官方 CLI 的預設 USB 裝置選擇。
    base = ["developer", "dvt", "simulate-location", "clear"]
    cli("確認 clear syntax", [*base, "--help"])
    cli("DVT clear（預設 USB 裝置）", base)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except TestFailure:
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("\n測試中斷，不能宣告成功。若曾設定位置，請執行 python test_iphone.py clear。")
        sys.exit(130)
