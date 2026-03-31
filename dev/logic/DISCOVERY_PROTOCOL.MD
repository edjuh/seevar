# 🛰️ DISCOVERY PROTOCOL

> **Objective:** Network discovery and hardware identification for Seestar telescopes.
> **Version:** 2.0.0 (Alpaca)
> **Path:** `dev/logic/DISCOVERY_PROTOCOL.MD`

## 1. Network Discovery

Two methods, in priority order:

### Method A — Direct HTTP probe (preferred)

The S30-Pro does not respond to Alpaca UDP discovery on port 32227.
Use direct HTTP to the known IP on port 32323:

```bash
curl http://<telescope_ip>:32323/management/v1/configureddevices
```

A 200 response with 7 devices confirms the telescope is alive and Alpaca is operational.
The IP is read from `config.toml [[seestars]] ip`.

### Method B — UDP broadcast (fallback for other models)

Standard Alpaca discovery on UDP port 32227. Works on S50, may work
on future firmware. See `core/hardware/hardware_loader.py`.

## 2. Hardware Fingerprinting

After discovery, identify the model via the Alpaca camera endpoint:

```bash
curl http://<ip>:32323/api/v1/camera/0/cameraxsize?ClientID=42&ClientTransactionID=1
```

| cameraxsize | Model | Instrument |
|-------------|-------|-----------|
| 3840 | S30-Pro | IMX585 |
| 1920 | S30 or S50 | IMX662 or IMX462 |

For 1920px models, disambiguate via camera/0/description.

## 3. Grid Detection

* **Home Grid**: Check for IP in `192.168.178.0/24`. Mount NAS to `/mnt/astronas/`.
* **Field Mode**: Fallback to NVMe `lifeboat_dir` if NAS is unreachable.

## 4. Temporal Alignment

Pre-flight fails if system clock offset > 0.5s from GPS PPS.
