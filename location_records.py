"""Saved destinations, compatible with the original single-record file."""
import json
import os
from pathlib import Path
import tempfile

from iphone_backend import validate_position


def load_records(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("record.json 必須是地點物件或地點陣列。")
    records = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("label", ""), str):
            raise ValueError("地點格式錯誤，label 必須是文字。")
        latitude, longitude = validate_position(item["latitude"], item["longitude"])
        records.append(dict(label=item.get("label", ""), latitude=latitude, longitude=longitude))
    return records


def append_record(path, label, position):
    records = load_records(path)
    latitude, longitude = validate_position(*position)
    records.append(dict(label=label.strip(), latitude=latitude, longitude=longitude))
    save_records(path, records)
    return records


def save_records(path, records, expected=None):
    """Validate before replacing the file; reject edits based on an old list."""
    if expected is not None and load_records(path) != expected:
        raise ValueError("record.json 已變更，請按「重新讀取」後再編輯或刪除。")
    validated = []
    for record in records:
        latitude, longitude = validate_position(record["latitude"], record["longitude"])
        if not isinstance(record["label"], str):
            raise ValueError("標籤必須是文字。")
        validated.append(dict(label=record["label"].strip(), latitude=latitude, longitude=longitude))
    fd, temporary = tempfile.mkstemp(prefix=".records-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
