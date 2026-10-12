"""
RailMind - train priority lookup.

Reads data/synthetic/train_priorities.json, a map of train number -> priority.
Values may be 1/2/3 or the names "Premium"/"Express"/"Passenger".
Returns normalised ints: 1 = Premium, 2 = Express, 3 = Passenger.
Trains missing from the file are simply absent from the result.
"""

import json

from src.simulator.schedule_simulator import SYNTHETIC_DIR

PRIORITY_PATH = SYNTHETIC_DIR / "train_priorities.json"
PRIORITY_NAMES = {1: "Premium", 2: "Express", 3: "Passenger"}
_BY_NAME = {v.lower(): k for k, v in PRIORITY_NAMES.items()}


def load_priorities() -> dict:
    if not PRIORITY_PATH.exists():
        return {}
    with open(PRIORITY_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for train, value in raw.items():
        if isinstance(value, str) and value.strip().lower() in _BY_NAME:
            value = _BY_NAME[value.strip().lower()]
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value in PRIORITY_NAMES:
            out[str(train)] = value
    return out