# 🌉 ALPACA BRIDGE (seestar.service)

> **Version:** 2026.03.12
> **Path:** `logic/ALPACA_BRIDGE.MD`

## Role (Post-Diamond Revision)

The Alpaca bridge is **not** the capture path. Sovereign TCP (port 4700
control, port 4801 frame stream) handles all science acquisition directly.

The bridge remains useful for two things only:
- Service health-check: `systemctl is-active seestar.service`
- Scheduler toggle and mosaic JSON injection (Path A, optional)

## Service Reality

The bridge runs as an independent systemd service, outside the SeeVar
virtualenv.

```
Service:   seestar.service  (PPID 1, systemd-managed)
Execution: ~/.pyenv/versions/ssc-3.13.5/bin/python3
```

Before any Alpaca call, verify the service is alive:
```bash
systemctl is-active seestar.service
```

## Port Architecture

| Port | Purpose | Use |
|------|---------|-----|
| `127.0.0.1:5432` | Alpaca bridge (HTTP) | Health-check, scheduler only |
| `192.168.178.55:4700` | S30-Pro JSON-RPC (TCP) | All sovereign control |
| `192.168.178.55:4801` | Binary frame stream (TCP) | Science capture |
| `192.168.178.55:4800` | Stack stream (TCP) | ZIP stacks (not used for science) |

**Never use port 5555. It was wrong. The correct Alpaca port is 5432.**

## Alpaca Call Rules (when used)

- Device index: `/0/` (not `/1/`)
- `ClientID`: integer `42` — never a string
- `ClientTransactionID`: auto-incrementing integer per session
- All action calls use **PUT** method
- Endpoint base: `http://127.0.0.1:5432/api/v1/telescope/0/`

## What Alpaca Does NOT Do

- Does not trigger science capture (`iscope_start_view` goes to port 4700)
- Does not receive frame data (frames come from port 4801)
- `method_sync` does not exist — removed from seestar_alp
- `start_exposure` is not a confirmed method — do not use
