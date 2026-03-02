#!/usr/bin/env python3
import json, logging, tomllib
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Librarian")

class Librarian:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[2]
        self.data_dir = self.root / "data"
        self.raw_path = self.data_dir / "campaign_targets.json"
        self.master_path = self.data_dir / "targets.json"
        self.plan_path = self.data_dir / "tonights_plan.json"

    def _generate_header(self, obj_text, include_date=False):
        now = datetime.now()
        header = {
            "objective": obj_text,
            "generated_at": now.isoformat(),
            "federation_version": "1.5.0"
        }
        if include_date:
            dark_start = now.replace(hour=20, minute=0, second=0) 
            dark_end = (now + timedelta(days=1)).replace(hour=5, minute=0, second=0)
            header["$date"] = now.strftime("%Y-%m-%d")
            header["$date-dark-period"] = f"{dark_start.strftime('%Y-%m-%dT%H:%M:%S')}Z/{dark_end.strftime('%Y-%m-%dT%H:%M:%S')}Z"
        return header

    def process_lifecycle(self):
        if not self.raw_path.exists():
            logger.error(f"❌ Source missing: {self.raw_path}")
            return

        with open(self.raw_path, 'r') as f:
            raw_data = json.load(f)
        
        # 1. Update Raw Harvest with Objective (In-place)
        raw_data["objective"] = "Raw AAVSO Harvest Data"
        with open(self.raw_path, 'w') as f:
            json.dump(raw_data, f, indent=4)

        target_list = raw_data.get('targets', [])
        unique = {t['star_name'].strip(): t for t in target_list if isinstance(t, dict) and 'star_name' in t}
        master_list = list(unique.values())
        
        # 2. Write Master Catalog
        master_data = {
            "header": self._generate_header("Deduplicated Master Research Catalog"),
            "targets": master_list
        }
        with open(self.master_path, 'w') as f:
            json.dump(master_data, f, indent=4)
        
        # 3. Write Tonights Plan
        plan_data = {
            "header": self._generate_header(f"Tactical Flight Manifest for {datetime.now().strftime('%Y-%m-%d')}", include_date=True),
            "targets": master_list
        }
        with open(self.plan_path, 'w') as f:
            json.dump(plan_data, f, indent=4)

        print("\n" + "="*45)
        print(f"📊 LIBRARIAN AUDIT: DATA STAMPED")
        print(f"  - Master: {len(master_list)} unique stars")
        print(f"  - Plan:   {plan_data['header']['$date']} (with dark-period)")
        print("="*45 + "\n")

if __name__ == "__main__":
    Librarian().process_lifecycle()
