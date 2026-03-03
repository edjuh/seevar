#!/usr/bin/env python3
import json
from pathlib import Path

def migrate():
    data_path = Path("~/seestar_organizer/data/targets.json").expanduser().resolve()
    if not data_path.exists():
        print("❌ Master Catalog not found.")
        return

    with open(data_path, 'r') as f:
        targets = json.load(f)

    updated_count = 0
    for t in targets:
        # Standardize the Name Key
        if 'star_name' in t and 'name' not in t:
            t['name'] = t.pop('star_name')
            updated_count += 1
        
        # Ensure priority is boolean
        if 'priority' not in t:
            t['priority'] = False

    with open(data_path, 'w') as f:
        json.dump(targets, f, indent=4)
    
    print(f"✅ Migration Complete: Standardized {updated_count} targets on RAID.")

if __name__ == "__main__":
    migrate()
