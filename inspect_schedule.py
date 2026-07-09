import json

data = json.load(open("data/synthetic/optimized_schedule.json"))
sections = list(data["section_precedence"].items())

print(f"Total sections: {len(sections)}\n")
for name, occupants in sections[:3]:
    print(f"{name}  ({len(occupants)} trains)")
    for o in occupants[:6]:
        print("  ", o)
    print()