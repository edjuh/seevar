By mapping the inputs and outputs of the Python scripts you just uploaded, the linear execution order for Phase 1 (The Data Funnel) reveals itself:

state_flusher.py: Sweeps the board clean. Resets data/system_state.json to IDLE so the dashboard isn't showing ghost data from a previous run.

aavso_fetcher.py (Step 1): Reaches out to the AAVSO, applies the physics constraints (MAG <= 15, DEC >= -7.62), and generates catalogs/campaign_targets.json.

chart_fetcher.py (Step 2): Reads the master haul and pulls down the required 90' FOV photometry charts into catalogs/reference_stars/.

librarian.py: Acts as the gatekeeper. It cross-references the targets against the downloaded charts and outputs the definitive catalogs/federation_catalog.json.

nightly_planner.py: Reads the federated catalog, calculates real-time Alt/Az against your Haarlem GPS coordinates, enforces the 30° limit, and generates the initial data/tonights_plan.json.

ledger_manager.py: The final triage. It checks the historical data/ledger.json, applies the 3-day sovereign cadence rule, and permanently filters data/tonights_plan.json down to only the targets that are strictly 'DUE'.
