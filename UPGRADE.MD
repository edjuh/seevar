# SeeVar Beta Upgrade Note
# Pre-Alpaca builds -> current 1.9.x checkpoint

This upgrade moves SeeVar from the older TCP-era control path to the current
Alpaca-based architecture.

The main change is:
- hardware control now uses the Seestar's built-in Alpaca driver on port 32323

This is a meaningful architectural upgrade, not a minor patch.
Please read once before upgrading.

---

## What changes

### Control path
Old builds used the earlier sovereign TCP path.
Current builds use Alpaca REST as the primary hardware interface.

### Flight logic
The target execution chain is now standardized as `A1-A12`.

### Postflight logic
The science chain is now being hardened around `P1-P8`.

### Docs and config
Several logic documents and supporting scripts have been updated.
Your existing local config may still work, but it should be reviewed.

---

## Before upgrading

Please make backups of:

- `config.toml`
- any local notes or custom edits
- any uncommitted code changes
- any local service overrides

Recommended backup commands:

```bash
cd ~/seevar
cp config.toml config.toml.backup.$(date +%Y%m%d_%H%M%S)
git status
If git status shows local changes, either commit them or copy them somewhere safe first.

Upgrade steps
1. Stop running services
systemctl --user stop seevar-dashboard.service 2>/dev/null || true
systemctl --user stop seeing-scraper.service 2>/dev/null || true
systemctl --user stop seestar_env_lock.service 2>/dev/null || true
If your installation uses different user service names, stop those instead.

2. Update the repository
cd ~/seevar
git fetch --all
git pull
If you are tracking a specific branch, switch to that first.

3. Refresh the Python environment
cd ~/seevar
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
4. Review config
Check at least:

telescope IP / Seestar IP
observer code
latitude / longitude / elevation
storage paths
weather section
cadence section
any Alpaca-related hardware fields
If a fresh example config is available in the repo, compare yours against it.

5. Verify Alpaca reachability
The new control path depends on Alpaca at port 32323.

Quick check:

curl http://<seestar-ip>:32323/management/apiversions
Expected result:

a small JSON response
no timeout
no connection refusal
If this fails, flight will not work.

6. Re-run the preflight pipeline
~/seevar/.venv/bin/python ~/seevar/core/preflight/audit.py
~/seevar/.venv/bin/python ~/seevar/core/preflight/nightly_planner.py
Optional weather check:

~/seevar/.venv/bin/python ~/seevar/core/preflight/weather.py
7. Run a simulator pass
~/seevar/.venv/bin/python ~/seevar/core/flight/sim_runner.py --targets 1
You should now see the canonical A1-A12 flow in the log.

8. Restart services
systemctl --user daemon-reload
systemctl --user start seevar-dashboard.service 2>/dev/null || true
systemctl --user start seeing-scraper.service 2>/dev/null || true
systemctl --user start seestar_env_lock.service 2>/dev/null || true
What to verify after upgrade
Please verify these specifically:

dashboard loads
weather state updates
nightly planner generates tonights_plan.json
simulator runs cleanly
Alpaca responds on port 32323
no old TCP-only assumptions remain in local scripts
Known differences from older builds
older direct TCP assumptions are no longer the main control path
postflight is stricter about scientific truth than older builds
some internal file names and logic docs have been normalized
this is still beta software; scientific hardening is ongoing
If something breaks
Please report:

the exact command you ran
the relevant traceback or log lines
whether Alpaca on 32323 responds
whether the problem is:
config-related
install-related
simulator-related
live-flight-related
A short pasted log excerpt is more useful than a summary.

Current beta scope
This checkpoint is intended to validate:

Alpaca control path
planner/orchestrator alignment
canonical A1-A12 mission flow
current 1.9.x postflight hardening direction
It is not yet the final science release.
