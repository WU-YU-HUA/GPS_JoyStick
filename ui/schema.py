"""Toolkit-neutral screen content shared by the Tk and PySide frontends.

Order and grouping are semantic. Each frontend maps them to its native layout
manager so resizing and platform font metrics remain under that toolkit's control.
"""

APP_TITLE = "iPhone GPS Joystick"

MODE_OPTIONS = (
    ("custom", "自訂經緯度"),
    ("computer", "電腦目前位置"),
)

# Delete a component entry or set enabled=False to hide that shared screen block.
SCREEN_COMPONENTS = {
    "settings": {"type": "section", "title": "起點與速度", "renderer": "settings", "enabled": True},
    "directions": {"type": "section", "title": "移動方向", "renderer": "directions", "enabled": True},
    "records": {"type": "section", "title": "收藏地點", "renderer": "records", "enabled": True},
    "log": {"type": "section", "title": "連線訊息", "renderer": "log", "enabled": True},
}
SECTION_TITLES = {
    component_id: component["title"]
    for component_id, component in SCREEN_COMPONENTS.items()
}

# Logical placements are shared configuration. Each renderer maps these slots
# to its own layout manager; no pixel coordinates are stored here.
TK_COMPONENT_LAYOUT = {
    "settings": {
        "rows": {
            "title": 0,
            "mode": 1,
            "coordinates": 2,
            "connect": 5,
            "clear": 6,
            "status": 7,
        }
    },
    "records": {"rows": {"panel": 4}},
    "directions": {"rows": {"pad": 8, "motion": 9, "help": 10}},
    "log": {"rows": {"panel": 11}},
}
PYSIDE_COMPONENT_LAYOUT = {
    "primary": ("settings", "directions"),
    "secondary": ("records", "log"),
}

COORDINATE_PANELS = (
    {"id": "origin", "title": "現在地", "fields": ("latitude", "longitude")},
    {"id": "destination", "title": "目的地", "fields": ("destination_latitude", "destination_longitude")},
)

COORDINATE_FIELDS = {
    "latitude": {"label": "緯度", "placeholder": "-90 至 90"},
    "longitude": {"label": "經度", "placeholder": "-180 至 180"},
    "destination_latitude": {"label": "緯度", "placeholder": "-90 至 90"},
    "destination_longitude": {"label": "經度", "placeholder": "-180 至 180"},
}

SPEED_FIELD = {"label": "速度", "unit": "km/h"}
RECORD_COLUMNS = (("label", "標籤"), ("latitude", "緯度"), ("longitude", "經度"))
RECORD_EDIT_FIELDS = RECORD_COLUMNS

ACTION_LABELS = {
    "locate": "重新取得位置",
    "apply_speed": "套用速度",
    "navigate": "自動前往目的地",
    "connect": "連線並移動至起點座標",
    "disconnect": "中斷連線並清除模擬定位",
    "clear": "清除模擬定位（恢復真實 GPS）",
    "stop": "停止",
    "record_current": "紀錄現在位置",
    "use_record": "使用選取地點",
    "edit_record": "編輯選取地點",
    "update_record": "更新地標",
    "delete_record": "刪除選取地點",
    "reload_records": "重新讀取",
}

RECORD_ACTIONS = (
    {
        "id": "use_record",
        "type": "button",
        "section": "records",
        "label": ACTION_LABELS["use_record"],
        "handler": "use_record",
    },
    {
        "id": "edit_record",
        "type": "button",
        "section": "records",
        "label": ACTION_LABELS["edit_record"],
        "handler": "edit_record",
    },
    {
        "id": "update_record",
        "type": "button",
        "section": "records",
        "label": ACTION_LABELS["update_record"],
        "handler": "update_record_position",
    },
    {
        "id": "delete_record",
        "type": "button",
        "section": "records",
        "label": ACTION_LABELS["delete_record"],
        "handler": "delete_record",
    },
    {
        "id": "reload_records",
        "type": "button",
        "section": "records",
        "label": ACTION_LABELS["reload_records"],
        "handler": "reload_records",
    },
)

# Each cell is (Tk label, Qt label, east, north); row/column placement is shared.
DIRECTION_GRID = (
    (("WA ↖", "↖", -1, 1), ("W ↑", "↑", 0, 1), ("WD ↗", "↗", 1, 1)),
    (("A ←", "←", -1, 0), ("停止", "停止", 0, 0), ("D →", "→", 1, 0)),
    (("SA ↙", "↙", -1, -1), ("S ↓", "↓", 0, -1), ("SD ↘", "↘", 1, -1)),
)

MOTION_HELP = (
    "按住鍵盤移動，放開停止；雙擊方向可鎖定持續移動。",
    "鎖定後切換視窗／最小化仍會移動；點停止／中斷可解除。",
    "中斷連線／關閉時保存最後位置，並清除手機模擬定位。",
)
