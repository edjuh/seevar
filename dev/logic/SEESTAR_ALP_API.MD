# Seestar ALP API Notes

Objective: record the confirmed `seestar_alp` API workbench path for diagnostics and future SeeVar integration.

## Role

`seestar_alp` talks to the native Seestar API and exposes it through an Alpaca-style action wrapper. It is not the same as using the limited firmware Alpaca implementation directly.

Decision: `seestar_alp` is diagnostics/API workbench by default. It may become controlled tooling only when `[seestar_alp].enabled = true` and `[seestar_alp].mode = "controlled"` are set in `config.toml`. Normal photometry flight stays on firmware Alpaca.

Use it as an API workbench and controlled integration candidate. Do not make it the primary flight path until the relevant calls have been tested under a real run.

## Bruno Collection

The DEV RPI has the Bruno collection here:

```bash
/home/ed/seestar_alp/bruno/Seestar Alpaca API
```

Open it with Bruno or run it with the `bru` CLI. Use the collection to inspect request bodies and export known-good calls to `curl` or Python.

The collection uses Alpaca action requests:

```bash
curl -X PUT "http://127.0.0.1:5555/api/v1/telescope/1/action" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "Action=start_mosaic" \
  --data-urlencode 'Parameters={"target_name":"M 3","ra":"13h42m11.8s","dec":"+28d22m38s","is_j2000":true,"is_use_lp_filter":false,"gain":80}' \
  --data-urlencode "ClientID=1" \
  --data-urlencode "ClientTransactionID=999"
```

JSON request bodies may work through helper tools, but the Bruno ground truth is form-url-encoded Alpaca action wrapping.

## Confirmed Useful Calls

| Area | Action |
| --- | --- |
| Scheduler | `create_schedule`, `add_schedule_item`, `get_schedule`, `start_scheduler`, `stop_scheduler` |
| Imaging | `start_mosaic`, `capture_target`, exposure/gain setting actions |
| Pointing | `goto_target`, `start_solve`, `get_solve_result`, `get_last_solve_result`, `sync_scope` |
| Startup/shutdown | `start_up_sequence`, `pi_shutdown`, `pi_reboot` |
| Environment | dew heater via `pi_output_set2` with level value |
| Files/status | `get_last_image`, `get_device_state`, `get_setting`, disk volume and stack state calls |

## Authentication

Newer Seestar firmware uses challenge-response authentication for the native API. `seestar_alp` can use the extracted app PEM when configured for it.

The PEM is a runtime secret and must never be committed:

```bash
/home/ed/.config/seestar/seestar_3.1.2.pem
```

## Notes

- `seestar_alp` can do features not exposed cleanly by pure Alpaca, including Seestar mosaics and heater level control.
- Dithering behavior may differ from native app imaging.
- Keep SeeVar production control on confirmed paths only.
- Prefer Bruno for discovery, then implement the smallest tested call in SeeVar.
