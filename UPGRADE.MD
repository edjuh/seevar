# SeeVar Upgrade Guide

## Quick upgrade

For an existing checkout that already lives at `~/seevar`:

```bash
cd ~/seevar
curl -fsSL https://raw.githubusercontent.com/edjuh/seevar/main/upgrade.sh | bash
```

That command:
- fetches the latest `main`
- fast-forwards your checkout
- refreshes Python requirements if `.venv` exists
- runs a syntax check
- leaves your local `config.toml` alone

## Important safety notes

The upgrade helper does **not** overwrite:
- `config.toml`
- untracked local files
- your local observation data

The helper **will stop** if your checkout has local tracked edits. That is deliberate, so it does not trample custom work.

## Before upgrading

Back up these if they matter to you:
- `config.toml`
- any local notes or custom scripts
- any uncommitted code changes
- any local systemd overrides

Recommended backup commands:

```bash
cd ~/seevar
cp config.toml config.toml.backup.$(date +%Y%m%d_%H%M%S)
git status
```

If `git status` shows local changes, either commit them or stash them before upgrading.

## Manual upgrade

If you prefer not to use the helper:

```bash
cd ~/seevar
git fetch origin
git checkout main
git pull --ff-only origin main
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m py_compile $(git ls-files '*.py')
```

## After upgrading

Useful checks:

```bash
~/seevar/.venv/bin/python ~/seevar/core/flight/sim_runner.py --targets 1
```

```bash
systemctl --user status seevar-dashboard
```

```bash
curl http://<seestar-ip>:32323/management/apiversions
```

## Notes for older installs

Some older installs will not already have `scripts/update_seevar.sh`. That is why the root `upgrade.sh` exists and can be fetched directly from GitHub.

For the specific simulation crash:
- changing `simulation_mode` in `config.toml` is **not** enough
- the checkout needs the code update itself
- after upgrading, no extra regeneration step should be needed

## Symlinked Storage

If you move `data` or `catalogs` onto SSD/RAID storage and replace them with symlinks, that is supported.

The repository now ignores both:
- `data/` and `data`
- `catalogs/` and `catalogs`

That distinction matters because Git treats a symlink like a file path, not like a directory.

If you still have local tracked code edits, stash or commit those before upgrading.

## Mission Test Cap

Nightly target count is controlled by two separate layers:

- `data/tonights_plan.json` is the planner output for what is scientifically eligible tonight
- `[mission].max_targets` in `config.toml` is an optional runtime cap applied by the orchestrator

Examples:

```toml
[mission]
max_targets = 0
```

`0` means no orchestrator cap.

```toml
[mission]
max_targets = 1
```

This is useful for test nights where you only want the first planned target executed.
