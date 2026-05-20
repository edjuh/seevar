# Seestar SSH Access

Objective: define the safe SeeVar use of optional SSH access on owned Seestar scopes.

## Scope

SSH is for diagnostics and controlled file exchange only. SeeVar should keep normal
flight control on Alpaca/RPC paths unless a specific tool states otherwise.

## Useful Paths

| Path | Purpose |
| --- | --- |
| `/home/pi/.ZWO/view_plan.json` | App-side plan/session state. Candidate for app-compatible plan export. |
| `/home/pi/.ZWO/userData.db3` | ZWO app state database. Inspect read-only unless format is understood. |
| `/usr/local/astrometry/data/` | Onboard Astrometry.net Tycho index files. Useful for local solve inventory. |
| `/boot/Image/MyWorks/` | User media/FITS products exposed by the scope. |
| `/oem/zwo/iqfiles/` | Camera/image-quality profiles. Read-only reference. |

## Tooling

`dev/tools/telescope/seestar_ssh_probe.py` performs a read-only health and inventory probe:

```bash
python3 dev/tools/telescope/seestar_ssh_probe.py --user pi
python3 dev/tools/telescope/seestar_ssh_probe.py --user ed --json
python3 dev/tools/telescope/seestar_ssh_probe.py --host 192.168.178.251
```

The probe reports OS/kernel, MAC/IP state, storage, `.ZWO` files, `view_plan.json`
summary, and onboard astrometry indexes.

## Seestar Proxy

`seestar-proxy` is installed on the DEV RPI as `/home/ed/bin/seestar-proxy`.
It is configured as user-systemd services with discovery disabled and non-standard
ports, so it does not hijack normal Seestar app discovery.

| Scope | Service | Dashboard | Control | Imaging |
| --- | --- | --- | --- | --- |
| Wilhelmina | `seestar-proxy@wilhelmina.service` | `http://192.168.178.57:14090` | `192.168.178.57:14700` | `192.168.178.57:14800` |
| Anna | `seestar-proxy@anna.service` | `http://192.168.178.57:24090` | `192.168.178.57:24700` | `192.168.178.57:24800` |

```bash
systemctl --user start seestar-proxy@anna.service
systemctl --user stop seestar-proxy@anna.service
systemctl --user status seestar-proxy@anna.service
```

Use the proxy for diagnostics, protocol recording, and multi-client testing. Keep
SeeVar production flight paths on Alpaca/RPC until proxy behavior has been tested.

## APK PEM

The Seestar app `3.1.2` / firmware `7.32` PEM is stored on the DEV RPI only:

```bash
/home/ed/.config/seestar/seestar_3.1.2.pem
```

Permissions must remain `0600`. Do not commit PEM files; `.gitignore` blocks
`*.pem`.

`seestar-tool` is installed on the DEV RPI as `/usr/bin/seestar-tool`. It is
GUI/TUI-only, so diagnostics are interactive:

```bash
seestar-tool --tui
```

Use the Diagnostics tab with scope IP and PEM path. Treat this as a manual
interoperability diagnostic path, not a SeeVar flight-control dependency.

For non-interactive read-only diagnostics, use SeeVar's PEM probe:

```bash
python3 dev/tools/telescope/seestar_pem_diagnostics.py
python3 dev/tools/telescope/seestar_pem_diagnostics.py --host 192.168.178.252 --json
```

The probe authenticates on port `4700`, then calls `get_device_state` and
`pi_get_info` only.

## Rules

- Prefer read-only SSH operations.
- Do not run package upgrades on the scope.
- Do not change ZWO system services unless recovery is understood.
- Remount root read-write only for deliberate account/key maintenance.
- Keep firmware payload changes small and reversible.
