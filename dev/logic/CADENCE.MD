# 🕰️ SEEVAR CADENCE LOGIC

> **Objective:** Ensure science-grade sampling of variable stars by
> adhering to AAVSO cadence requirements.
> **Version:** 2.0.0 (Praw)
> **Path:** `logic/CADENCE.md`

Cadence table (short form): `AAVSO_LOGIC.MD` § Cadence Rules.
Implementation: `core/preflight/audit.py`, `core/preflight/ledger_manager.py`.

---

## 📐 1. The Sampling Rule

To capture a scientifically valid light curve, the scheduler must sample
at **1/20th of the target's period**.

| Variable Type | Period Range | Recommended Cadence | Derivation |
|---------------|-------------|--------------------:|------------|
| Mira | 200–500d | Every 5–10 days | P / 20 ≈ 10d |
| Semi-Regular (SR) | 100–200d | Every 3–5 days | P / 20 ≈ 5d |
| Fast SR | < 100d | Every 1–3 days | P / 20 ≈ 2d |
| CV / UG / RR | < 1d–few days | Every 1 day | Alert Corps cadence |

For targets with a known period in the catalog, the exact cadence is
`recommended_cadence_days` from the federation catalog entry. The type
lookup above is the fallback. Default fallback: 3 days.

---

## 🔄 2. The Scheduling Workflow

`audit.py` iterates the federation catalog and marks each target:

1. **Last Observed** — read `last_success` from `data/ledger.json`
   for the target key (`NAME.upper().replace(" ", "_")`).
2. **Cadence Delta** — `now - last_success` in days.
3. **Priority Gate:**
   - `cadence_delta >= recommended_cadence` → target is **CRITICAL**
     (`cadence_due = True`) — include in tonight's plan.
   - `cadence_delta < recommended_cadence` → target is **DEFERRED**
     (`cadence_due = False`) — skip tonight.
4. **Altitude Gate** — `nightly_planner.py` further filters to targets
   above 30° during the astronomical dark window for Haarlem.

Within the flight loop, `orchestrator.py` additionally applies
meridian-aware scoring to sequence CRITICAL targets optimally.
See `AAVSO_LOGIC.MD` and `API_PROTOCOL.MD` for scoring detail.

---

## 🛠️ 3. Flight Integration

For every target cleared by cadence, horizon, weather, and timing logic,
`core/flight/orchestrator.py` executes the current `A1-A12` flight chain through
`core/flight/pilot.py` and `core/flight/fsm.py`.

Flight captures raw FITS custody into:

```text
data/local_buffer/{TARGET}_{TS}_Raw.fits
```

The active transport is described in `ALPACA_BRIDGE.MD` and `API_PROTOCOL.MD`.
Older direct-TCP examples are historical and must not override current flight
law.

On success, `data/ledger.json` is updated with `last_success` timestamp,
resetting the cadence clock for that target.
