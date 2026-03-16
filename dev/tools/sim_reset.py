#!/usr/bin/env python3
"""
Filename: tools/sim_reset.py
Version:  2.0.0
Objective: Reset ledger entries for targets in tonights_plan.json to
           PENDING so the simulation has targets to fly.
           Usage: python3 tools/sim_reset.py [N]
           N = number of targets to reset (default: all in plan)
"""
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEDGER_FILE  = PROJECT_ROOT / "data" / "ledger.json"
PLAN_FILE    = PROJECT_ROOT / "data" / "tonights_plan.json"

n = int(sys.argv[1]) if len(sys.argv) > 1 else None

# Load plan targets
plan_raw = json.loads(PLAN_FILE.read_text())
targets  = plan_raw.get("targets", []) if isinstance(plan_raw, dict) else plan_raw

if not targets:
    print("❌ No targets in tonights_plan.json — run nightly_planner.py first.")
    sys.exit(1)

if n:
    targets = targets[:n]

# Load ledger
data    = json.loads(LEDGER_FILE.read_text())
entries = data.get("entries", {})
reset   = 0

for t in targets:
    name = t.get("name", "")
    if not name:
        continue
    if name not in entries:
        entries[name] = {
            "status": "PENDING", "last_success": None,
            "attempts": 0, "priority": "NORMAL"
        }
    else:
        entries[name]["last_success"] = None
        entries[name]["status"]       = "PENDING"
    print(f"  RESET → {name}")
    reset += 1

data["entries"] = entries
LEDGER_FILE.write_text(json.dumps(data, indent=4))
print(f"\n✅ {reset} ledger entries reset to PENDING.")
print(f"   Run: python3 core/flight/sim_runner.py --targets {reset}")
