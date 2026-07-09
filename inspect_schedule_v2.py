"""
RailMind - Schedule Inspector (v2)

Cross-references the optimized schedule with the section configs so you can
actually verify: (1) headway/capacity rules are respected, (2) higher
priority trains are getting preference.
"""

import json

with open("data/synthetic/section_configs.json", "r", encoding="utf-8") as f:
    config = json.load(f)

with open("data/synthetic/optimized_schedule.json", "r", encoding="utf-8") as f:
    schedule = json.load(f)

# train_number -> priority_label
priority_lookup = {t["train_number"]: t.get("priority_label", "?") for t in config["trains"]}

# section name -> {line_type, headway_minutes, capacity}
section_info = {}
for s in config["block_sections"]:
    name = f"{s['from_station']} -> {s['to_station']}"
    section_info[name] = {
        "line_type": s["line_type"],
        "headway_minutes": s["headway_minutes"],
        "capacity": 2 if s["line_type"] == "double" else 1,
    }

print(f"Total sections: {len(schedule['section_precedence'])}\n")

for name, occupants in schedule["section_precedence"].items():
    info = section_info.get(name, {})
    print(f"{name}  [{info.get('line_type')}-line, capacity={info.get('capacity')}, "
          f"headway={info.get('headway_minutes')}min]  ({len(occupants)} trains)")

    for o in occupants[:8]:
        label = priority_lookup.get(o["train_number"], "?")
        print(f"    entry={o['entry_min']:<6}  train={o['train_number']:<8} priority={label}")

    # simple spacing check for single-line (capacity=1) sections only —
    # consecutive entries must be >= duration+headway apart
    if info.get("capacity") == 1 and len(occupants) > 1:
        gaps = [occupants[i + 1]["entry_min"] - occupants[i]["entry_min"] for i in range(len(occupants) - 1)]
        min_gap = min(gaps) if gaps else None
        print(f"    -> min gap between consecutive trains: {min_gap} min "
              f"(headway requirement: {info.get('headway_minutes')} min + transit time)")
    print()