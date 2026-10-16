# iPhone GPS Joystick（Windows）

## 取得專案

```powershell
git clone https://github.com/WU-YU-HUA/GPS_JoyStick.git
cd GPS_JoyStick
Copy-Item config.example.json config.json
```

`config.json` 記錄本機最後位置，不提交到 Git。EXE、`_internal`、`build`、`dist`、日誌與診斷檔也不提交。
首次下載請依下方步驟啟動原始碼，或自行打包 EXE。

## 首次啟用

1. 使用可傳輸資料的 USB-C 線連接 iPhone，解鎖並選擇「信任這部電腦」。
2. Windows 必須可辨識 Apple iPhone / Apple Mobile Device USB Device；缺少驅動時安裝官方 Apple Devices。
3. iPhone：設定 → 隱私權與安全性 → 開發者模式；開啟後依提示重啟並確認。
4. 建立獨立 conda 環境（已建立者跳過）：

```powershell
conda create -n iphone-gps python=3.12 pip -y
```

在專案資料夾的 PowerShell 執行：

```powershell
conda activate iphone-gps
python -m pip install -r requirements.txt
python iphone_joystick.py
```

Tkinter 隨此 conda Python 提供，不需要另外 pip 安裝。

## 日常啟動與操作

```powershell
conda activate iphone-gps
python iphone_joystick.py
```

1. USB 連接 iPhone，解鎖並信任電腦，保持開發者模式開啟。
2. 輸入緯度、經度，點「連線並移動至輸入座標」。連線成功後手機會立即模擬到該位置。
3. GUI 取得焦點時，按住 W／A／S／D 移動；兩鍵組合可斜向移動，總速度同樣是 20 km/h。
4. 放開按鍵或切換視窗會停止。相反按鍵互相抵消，方向依地理北方，與手機地圖旋轉無關。
5. 中斷連線或關閉視窗，會把最後成功送出的經緯度寫入程式旁的 `config.json`。程式先停止移動、關閉原連線，再建立獨立連線送出 clear。請保持 USB 連接，等待流程完成與視窗自行關閉。
6. 下次啟動讀取保存的座標；點連線才會重新套用到手機。首次預設為東京車站。

位置每約 0.1 秒更新一次。連線延遲過高時會限制單步距離，避免補跳；此時實際速度可能低於 20 km/h。
GUI 顯示的是最後成功送出的模擬座標，不是讀取手機真實 GPS。請用 Apple Maps 藍點確認效果。

## 中斷後位置沒有恢復

clear 呼叫不等待 iOS 回報 GPS 已恢復，所以沒有錯誤不代表真實定位已恢復。
本版改為獨立 clear 連線，並等待短暫傳輸時間；仍須人工確認 Apple Maps 藍點。

1. 保持手機解鎖、USB 連接，確認其他定位程式已停止。不要先拔線再中斷。
2. 按 GUI 的「清除模擬定位（恢復真實 GPS）」；沒有連線時也能重新連接並清除。
3. 在 Apple Maps 點「目前位置」，等待重新定位；必要時重新開啟 Maps。
4. 若仍無恢復，保留視窗下方完整錯誤與程式旁的 `gps.log`。
5. 原始碼環境也可獨立執行：

```powershell
python test_iphone.py clear
```

強制終止程式或拔線可能使清除來不及執行。請重新連接後用清除按鈕重試。
設定檔保留的是最後模擬位置，即使手機已恢復真實位置，設定檔也不會改成真實 GPS。

## PyInstaller 打包 Windows EXE

本機若已將產生的 EXE 移到專案根目錄，可直接雙擊 `iPhoneGPSJoystick.exe`；Git repository 不包含此檔。
根目錄的 `_internal` 必須保留在 EXE 旁；此版本使用根目錄現有的 `config.json`。
以下建置指令重新打包時，仍輸出到 `dist/iPhoneGPSJoystick/`。

在 Windows 的 iphone-gps 環境執行：

```powershell
conda activate iphone-gps
python -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

執行原則僅針對本次建置子程序，不修改系統設定。
腳本會執行 `python -m PyInstaller --noconfirm iphone_joystick.spec`，再放入 README 與初始 config。
重建時會保留輸出資料夾既有的 `config.json`，避免覆寫最後位置。

輸出結構：

```text
dist/
  iPhoneGPSJoystick/
    iPhoneGPSJoystick.exe
    _internal/
    config.json
    README.md
```

雙擊 EXE 啟動，不需要安裝 Python 或 conda；仍需要 Apple USB 驅動、手機信任與開發者模式。
**必須複製整個 iPhoneGPSJoystick 資料夾**，不要只複製 EXE；`_internal` 是執行必要元件。
請放在可寫入的位置。打包後 `config.json` 與 `gps.log` 均位於 EXE 旁，不在 `_internal` 或暫存目錄。
正常使用不需要系統管理員，也不需要手動啟動 tunneld。

打包後可先做不連手機的啟動檢查：

```powershell
.\dist\iPhoneGPSJoystick\iPhoneGPSJoystick.exe --self-test
```

成功會在 EXE 旁產生 `self-test.json`，包含 Tk 版本、config 路徑及後端匯入檢查結果。
此檢查不改定位，也不能取代 EXE 的實機移動與 clear 人工驗證。

若要用 EXE 檢查實機開發者連線（不設定／清除定位）：

```powershell
.\dist\iPhoneGPSJoystick\iPhoneGPSJoystick.exe --check-device
```

成功會產生 `device-check.json`。啟動失敗則查看 EXE 旁的 `startup-error.log`。

## 連線檢查與原先的最小驗證

```powershell
python test_iphone.py check
python test_iphone.py run
python -m unittest test_joystick -v
```

錯誤會在 GUI 下方列出失敗階段與完整 traceback。不要同時執行多個定位程式。
`check` 不改定位；`run` 設定東京並請你確認 Apple Maps，接著 clear 並確認恢復。
離線單元測試不連手機。
