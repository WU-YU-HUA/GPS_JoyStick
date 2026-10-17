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
2. 選擇起點模式，再點「連線並移動至起點座標」。連線成功後手機會立即模擬到該位置。
   - **自訂經緯度**：手動輸入緯度、經度，預設顯示上次保存的位置。
   - **電腦目前位置**：自動透過 Windows 定位取得起點，取得成功後確認座標再連線；也可按「重新取得位置」。請在 Windows「設定 → 隱私權與安全性 → 位置」開啟定位服務並允許桌面應用程式存取位置。無法取得時會顯示錯誤，不會改用預設位置連線。
3. 設定「速度 km/h」，按「套用速度」儲存並立即生效，兩種模式皆可調整（預設 20，範圍 0.1–1000 km/h）。連線中也可修改；套用時先停止移動，再按住 W／A／S／D 或方向鍵繼續移動。兩鍵組合可斜向移動，總速度與直行相同。
4. 放開按鍵或切換視窗會停止。相反按鍵互相抵消，方向依地理北方，與手機地圖旋轉無關。
5. 中斷連線或關閉視窗，會把最後成功送出的經緯度寫入程式旁的 `config.json`。程式先停止移動、關閉原連線，再建立獨立連線送出 clear。請保持 USB 連接，等待流程完成與視窗自行關閉。
6. 下次啟動讀取保存的座標；點連線才會重新套用到手機。首次預設為東京車站。

位置每約 0.1 秒更新一次。連線延遲過高時會限制單步距離，避免補跳；此時實際速度可能低於設定速度。
GUI 顯示的是最後成功送出的模擬座標，不是讀取手機真實 GPS。請用 Apple Maps 藍點確認效果。

兩種模式共用設定的移動速度與 WASD／方向鍵控制。電腦位置只用於設定起點，連線後不會持續跟隨電腦；斷線完成後可直接再次連線，沿用最近取得的電腦起點。電腦位置變動時可按「重新取得位置」。Windows 定位精確度依電腦與定位環境而異，不一定是 GPS 精度。

`config.json` 保存最後位置與速度，舊版缺少 `speed_kmh` 時預設使用 20 km/h。也可在程式關閉時手動修改：

```json
{
  "latitude": 35.681236,
  "longitude": 139.767125,
  "speed_kmh": 20.0
}
```

## 收藏與選取地點

`config.json` 繼續記錄最後位置；收藏清單獨立保存在 EXE 旁的 `record.json`，不會與最後位置互相覆蓋。

1. 輸入標籤（可留空），按「紀錄現在位置」新增一筆。連線中記錄最後成功送到手機的座標；未連線時記錄畫面上的起點座標。紀錄時會先停止移動。
2. 在清單瀏覽標籤、緯度、經度，可捲動查看更多地點。
3. 未連線時選取地點，按「使用選取地點」或雙擊，會切換至自訂模式並填入座標；再按連線前往。連線中請先中斷再選取起點。
4. 手動編輯 `record.json` 後可按「重新讀取」。輸入標籤或瀏覽清單時，WASD／方向鍵不會控制移動；按紀錄或使用地點後，焦點會回到主視窗。

原有單筆 `{ "latitude": ..., "longitude": ... }` 仍可讀取，顯示為「未命名」。首次新增時保留原資料並轉成以下陣列格式：

```json
[
  {
    "label": "收藏地點",
    "latitude": 53.32143615188298,
    "longitude": -3.8324366386661666
  }
]
```

檔案不存在時會在首次紀錄時建立；格式錯誤時會提示並保留原檔。若要帶走收藏清單，將 `record.json` 與 EXE 一起複製；EXE 本身仍可單獨執行。

## 中斷後位置沒有恢復

clear 呼叫不等待 iOS 回報 GPS 已恢復，所以沒有錯誤不代表真實定位已恢復。
本版改為獨立 clear 連線，並等待短暫傳輸時間；仍須人工確認 Apple Maps 藍點。

1. 保持手機解鎖、USB 連接，確認其他定位程式已停止。不要先拔線再中斷。
2. 按 GUI 的「清除模擬定位（恢復真實 GPS）」；沒有連線時也能重新連接並清除。
3. 在 Apple Maps 點「目前位置」，等待重新定位；必要時重新開啟 Maps。
4. 若仍無恢復，保留視窗下方完整錯誤與程式旁的 `gps.log`。

強制終止程式或拔線可能使清除來不及執行。請重新連接後用清除按鈕重試。
設定檔保留的是最後模擬位置，即使手機已恢復真實位置，設定檔也不會改成真實 GPS。

## PyInstaller 打包 Windows EXE

### 給 Agent 的打包要求

- 一律執行根目錄的 `build.ps1`，使用 `--noconsole --onefile --collect-all pytun_pmd3`。
- 輸出必須是根目錄的單一 `iPhoneGPSJoystick.exe`，取代舊 EXE，不使用需要 `_internal` 的資料夾版本。
- 打包結束後移除本次產生的建置目錄、暫存 spec、驗證副本及診斷產物；不要刪除原始碼、既有 spec、`config.json`、`record.json` 或使用者日誌。
- 保留使用者既有經緯度、速度及收藏，不要以範例設定覆蓋。設定與收藏不嵌入 EXE，執行時在 EXE 旁讀寫。
- 驗證單檔 EXE 可啟動並匯入連線套件；若執行環境的沙箱限制暫存檔讀取，應在允許的沙箱外環境驗證。未做實機測試時請明確說明。

本版打包成單一 `iPhoneGPSJoystick.exe`，輸出在專案根目錄；只需複製這個 EXE 即可執行，不需要攜帶 `_internal`。Git repository 不包含 EXE。

在 Windows 的 iphone-gps 環境執行：

```powershell
conda activate iphone-gps
python -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

執行原則僅針對本次建置子程序，不修改系統設定。
腳本會使用以下打包選項，另透過 `--workpath` 與 `--specpath` 將中間產物放入獨立暫存資料夾，結束後自動刪除。原始碼與既有的 `config.json` 會保留。

```powershell
python -m PyInstaller --clean --noconfirm --noconsole --onefile --collect-all pytun_pmd3 --name iPhoneGPSJoystick --distpath . iphone_joystick.py
```

上面是直接打包指令，會留下預設的 `build` 資料夾與產生的 `iPhoneGPSJoystick.spec`；需要自動清理時請執行 `build.ps1`。
`--collect-all pytun_pmd3` 會收集連線所需的 `wintun.dll` 等依賴，避免 EXE 初始化時缺少 DLL。

輸出結構：

```text
iPhoneGPSJoystick.exe
```

雙擊 EXE 啟動，不需要安裝 Python 或 conda；仍需要 Apple USB 驅動、手機信任與開發者模式。
單檔 EXE 啟動時會將內含依賴解壓到系統暫存目錄，首次啟動可能較慢。
請放在可寫入的位置。執行時會在 EXE 旁讀寫 `config.json`（最後位置）與 `gps.log`；這些檔案不必隨 EXE 分發。沒有設定檔時會使用預設座標。
正常使用不需要系統管理員，也不需要手動啟動 tunneld。

打包後可先做不連手機的啟動檢查：

```powershell
.\iPhoneGPSJoystick.exe --self-test
```

成功會在 EXE 旁產生 `self-test.json`，包含 Tk 版本、config 路徑及後端匯入檢查結果。
此檢查不改定位，也不能取代 EXE 的實機移動與 clear 人工驗證。

若要用 EXE 檢查實機開發者連線（不設定／清除定位）：

```powershell
.\iPhoneGPSJoystick.exe --check-device
```

成功會產生 `device-check.json`。啟動失敗則查看 EXE 旁的 `startup-error.log`。

錯誤會在 GUI 下方列出失敗階段與完整 traceback。不要同時執行多個定位程式。
