# SeeVar Dev Tools

- `reports/`: AAVSO/BAA staging, submission probes, and campaign pulls.
- `horizon/`: Horizon-mask audits, editor, installers, and panorama packaging.
- `telescope/`: Live telescope diagnostics, PEM-auth probes, SSH probes, pre-alignment, RPC, SSC schedule injection, and widefield solve helpers.
- `ops/`: Cleanup and session triage tools that do not steer hardware.

SSC schedule injection:
`python dev/tools/telescope/inject_ssc_schedule.py --device 1 --payload data/ssc_payload.json --dry-run`
Remove `--dry-run` to replace the target scope scheduler; add `--start` only when ready to run.

Seestar app view-plan export:
`python dev/tools/telescope/build_seestar_view_plan.py --payload data/ssc_payload.json --output /tmp/view_plan.json`

The confirmed firmware file is `/home/pi/.ZWO/view_plan.json`; it is current/history state for Seestar app Plan mode. Firmware logs also reference `/home/pi/.ZWO/plan.json`, but no ground-truth sample has been captured yet. The exporter defaults to JNOW coordinates because ASIAIR/Seestar plan execution appears to operate in current epoch, while SeeVar/AAVSO inputs are J2000.
