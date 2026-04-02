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

## 🛠️ 3. Diamond Sequence Integration

For every target cleared by cadence and altitude logic, the hardware
executes the **Diamond Sequence** via `core/flight/pilot.py`:

1. **Clear** — `iscope_stop_view` on port 4700 — abort any active session.
2. **Slew** — `scope_sync [ra_hours, dec_deg]` on port 4700.
3. **Settle** — 8 second post-slew wait.
4. **Expose** — `iscope_start_view {"mode": "star"}` on port 4700.
5. **Capture** — read frame_id 21 from binary stream on port 4801 —
   raw uint16 Bayer GRBG, 2160×3840.
6. **Stamp** — `sovereign_stamp()` writes AAVSO-compliant FITS header.
7. **Store** — `write_fits()` → `data/local_buffer/{TARGET}_{TS}_Raw.fits`.
8. **Stop** — `iscope_stop_view` to end session.

On success, `data/ledger.json` is updated with `last_success` timestamp,
resetting the cadence clock for that target.
