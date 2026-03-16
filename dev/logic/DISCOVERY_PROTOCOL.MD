# 🛰️ DISCOVERY PROTOCOL (v1.4 Kriel)

** Objective: UDP broadcast protocol for locating the Seestar S30 on the local network.

## 1. Network Discovery
* **Home Grid**: Check for IP in `192.168.178.0/24`. Mount NAS to `/mnt/astronas/`.
* **Field Mode**: Fallback to NVMe `lifeboat_dir` if NAS is unreachable.

## 2. Temporal Alignment
* Pre-flight fails if system clock offset > 0.5s from GPS PPS Atomic Clock.
