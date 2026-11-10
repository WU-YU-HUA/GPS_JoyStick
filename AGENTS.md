# Agent 指南

開始修改前先看本檔與 `README.md`。本專案目前只有 PySide6 GUI；除非使用者明確要求，不要新增或恢復 Tk 介面。

## 專案結構

- `pyside_gps.py`：應用程式入口，只負責啟動 UI。
- `ui/schema.py`：畫面區塊、順序、標籤、欄位、方向盤格位、收藏區按鈕設定。
- `ui/pyside_renderer.py`：PySide6 視窗、原生元件、版面、事件綁定與畫面更新。
- `controller/joystick_controller.py`：GUI 與服務之間的操作流程、輸入驗證及狀態協調。
- `controller/movement.py`：鍵盤／方向盤共用的方向狀態與移動計算。
- `services/iphone_backend.py`：iPhone 連線及模擬定位工作。
- `services/pc_location.py`：依作業系統取得電腦位置。
- `services/location_records.py`：收藏地點的讀取、保存及管理。
- `requirements.txt`：執行依賴；`requirements-build.txt` 與 `build.ps1`：Windows 打包依賴及流程。

## 新增或修改畫面元件

1. 修改既有區塊標題、標籤、欄位、方向盤格位或收藏操作設定時，先編輯 `ui/schema.py`。
2. `SCREEN_COMPONENTS` 的 `enabled` 可控制既有區塊顯示；`PYSIDE_COMPONENT_LAYOUT` 管理已支援區塊的位置槽位。設定檔描述畫面資料，不會自行生成任意類型的 Qt 元件。
3. 新增一種區塊或元件時，在 `ui/schema.py` 加設定，並在 `ui/pyside_renderer.py` 加上建立、排版、狀態更新及事件綁定；若有操作流程，放在 `controller/joystick_controller.py`，共用方向計算放在 `controller/movement.py`，系統或裝置 I/O 放在 `services/`。
4. 新增 `RECORD_ACTIONS` 操作時，確認 `handler` 對應的方法存在於 renderer，並由它呼叫 controller；也要更新 disabled/loading 狀態。
5. Qt 元件只能在 GUI 執行緒建立或更新。可能等待定位、USB 或其他 I/O 的工作不可阻塞 GUI event loop；沿用現有背景工作及結果回報模式。

## 修改原則

- 不要把商業流程或系統 I/O 塞進 `ui/schema.py`；schema 僅放設定資料。
- 避免在 renderer 複製移動計算；共用計算放在 `controller/movement.py`。
- 不要覆蓋或刪除使用者的 `config.json`、`record.json`、日誌或其他本機資料。
- 新增執行時套件時更新 `requirements.txt`；新增打包時才需要的套件則更新 `requirements-build.txt`。
- 保持 `pyside_gps.py` 為啟動入口，README 的操作方式與實作一致。
