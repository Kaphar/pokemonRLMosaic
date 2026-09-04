"""Convert v2/event.json to a clean milestone format.

Run this once:
    python skill_lab/convert_events.py

Reads:  v2/event.json
Writes: skill_lab/milestones.json
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = PROJECT_ROOT / "v2"
INPUT_PATH = V2_DIR / "events.json"
OUTPUT_PATH = PROJECT_ROOT / "skill_lab" / "milestones.json"


def parse_event_key(key: str) -> dict | None:
    """Parse event key like '0xD817-5' into address and bit.

    Format: 0xADDRESS-BIT
    Example: 0xD817-5 means address 0xD817, bit 5
    """
    key = key.strip()

    # Remove "0x" prefix if present
    if key.lower().startswith("0x"):
        key = key[2:]

    # Split on dash: "D817-5" -> address="D817", bit="5"
    if "-" in key:
        addr_str, bit_str = key.split("-", 1)
        try:
            address = int(addr_str, 16)
            bit = int(bit_str)
            mask = 1 << bit
            return {
                "address": address,
                "bit": bit,
                "mask": mask,
            }
        except ValueError:
            return None

    # No dash: just an address, check whole byte
    try:
        address = int(key, 16)
        return {
            "address": address,
            "bit": None,
            "mask": 0xFF,
        }
    except ValueError:
        return None


def main():
    if not INPUT_PATH.exists():
        print(f"ERROR: {INPUT_PATH} not found")
        sys.exit(1)

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Handle nested or flat structure
    events = raw_data.get("events", raw_data)

    milestones = []
    skipped = 0

    for key, value in events.items():
        parsed = parse_event_key(key)
        if parsed is None:
            skipped += 1
            print(f"  [SKIP] Could not parse: {key}")
            continue

        milestones.append({
            "name": key,
            "address": parsed["address"],
            "bit": parsed["bit"],
            "mask": parsed["mask"],
            "original_value": value,
        })

    output = {
        "source": str(INPUT_PATH),
        "total_milestones": len(milestones),
        "milestones": milestones,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"Converted {len(milestones)} milestones -> {OUTPUT_PATH}")
    if skipped > 0:
        print(f"Skipped {skipped} unparseable entries")


if __name__ == "__main__":
    main()