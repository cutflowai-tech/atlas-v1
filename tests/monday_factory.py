"""Synthetic Monday activity-log builders for runtime tests. No real names or IDs."""

import json
from datetime import datetime, timezone

BOARD = "5091110326"
STATUS = "project_status"
EDITOR = "dropdown_mm1emgt8"
VIDEO_TYPE = "dropdown_mm062ga0"
ETA = "date"
ISSUES = "dropdown_mm3tyk8g"
SHARED = "99154021"


def ticks(moment: str) -> str:
    parsed = datetime.fromisoformat(moment.replace("Z", "+00:00")).astimezone(timezone.utc)
    return str(int(parsed.timestamp()) * 10_000_000 + parsed.microsecond * 10)


def _log(log_id, item, column, moment, previous, value, user=SHARED, column_type="color", undo=False):
    data = {"pulse_id": int(item), "board_id": int(BOARD), "column_id": column, "column_type": column_type,
            "previous_value": previous, "value": value, "is_undo_action": undo or None, "pulse_name": "SYNTHETIC"}
    return {"id": log_id, "event": "update_column_value", "entity": "pulse", "user_id": user, "account_id": "1",
            "created_at": ticks(moment), "data": json.dumps(data)}


def status(log_id, item, moment, before, after, user=SHARED, undo=False):
    label = lambda text: None if text is None else {"label": {"text": text, "index": 0}}
    return _log(log_id, item, STATUS, moment, label(before), label(after), user, undo=undo)


def dropdown(log_id, item, column, moment, ids, names=None, previous=None):
    names = names or [f"label-{value}" for value in ids]
    value = {"chosenValues": [{"id": value, "name": name} for value, name in zip(ids, names)]} if ids else None
    return _log(log_id, item, column, moment, previous, value, column_type="dropdown")


def editor(log_id, item, moment, ids):
    return dropdown(log_id, item, EDITOR, moment, ids)


VIDEO_TYPE_NAMES = {4: "Class A", 5: "Class B", 8: "Class A+", 10: "2*", 16: "Ai"}


def video_type(log_id, item, moment, ids, names=None):
    return dropdown(log_id, item, VIDEO_TYPE, moment, ids, names or [VIDEO_TYPE_NAMES.get(value, f"label-{value}") for value in ids])


def eta(log_id, item, moment, date, time):
    return _log(log_id, item, ETA, moment, None, {"date": date, "time": time, "icon": None}, column_type="date")


def payload(*logs):
    return {"boards": [{"activity_logs": list(logs)}]}
