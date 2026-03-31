#!/usr/bin/env python3
"""
test_alpaca_official.py — Test ZWO's built-in Alpaca server on Wilhelmina
==========================================================================
Run on Dev Pi (192.168.178.15).  Wilhelmina must be in Station Mode on
the same LAN (192.168.178.251).

Install first:
    pip install alpyca --break-system-packages

This script does 4 things:
  1. UDP discovery — finds Alpaca servers on the LAN
  2. Management API — lists all devices Wilhelmina exposes
  3. Telescope READ test — reads RA, Dec, tracking state
  4. Telescope WRITE test — attempts a slew (only if you say yes)

Based on ZWO forum findings:
  - Alpaca v1.1.2-1 had a bug requiring app connection before slew
  - Alpaca v1.1.3-1+ fixed this — NINA can slew without the app
  - Your fw 7.18 might already have this fix
"""

import sys
import json
import time
import socket
import struct
import requests

WILHELMINA_IP = "192.168.178.251"
DISCOVERY_PORT = 32227
KNOWN_ALPACA_PORTS = [80, 8080, 11111]  # common defaults; discovery will tell us

# ─── Step 1: Alpaca UDP Discovery ───────────────────────────────────────────

def discover_alpaca(timeout=3):
    """Send Alpaca discovery broadcast, listen for responses."""
    print("=" * 60)
    print("STEP 1: Alpaca UDP Discovery (port 32227)")
    print("=" * 60)

    msg = json.dumps({"alpacadiscovery": 1, "alpacaport": 0}).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    # Try broadcast first
    servers = []
    try:
        sock.sendto(msg, ("255.255.255.255", DISCOVERY_PORT))
        print(f"  Sent discovery broadcast on UDP {DISCOVERY_PORT}")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                resp = json.loads(data.decode())
                port = resp.get("AlpacaPort", resp.get("alpacaport"))
                print(f"  ✓ Response from {addr[0]}: Alpaca port = {port}")
                servers.append((addr[0], port))
            except socket.timeout:
                break
    except Exception as e:
        print(f"  Broadcast failed: {e}")
    finally:
        sock.close()

    # Also try direct unicast to Wilhelmina
    if not any(s[0] == WILHELMINA_IP for s in servers):
        print(f"\n  Trying direct unicast to {WILHELMINA_IP}...")
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2.settimeout(timeout)
        try:
            sock2.sendto(msg, (WILHELMINA_IP, DISCOVERY_PORT))
            data, addr = sock2.recvfrom(1024)
            resp = json.loads(data.decode())
            port = resp.get("AlpacaPort", resp.get("alpacaport"))
            print(f"  ✓ Direct response: Alpaca port = {port}")
            servers.append((WILHELMINA_IP, port))
        except socket.timeout:
            print(f"  ✗ No response from {WILHELMINA_IP} on UDP {DISCOVERY_PORT}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
        finally:
            sock2.close()

    if not servers:
        print("\n  No Alpaca servers found via discovery.")
        print("  Will try known ports directly...")
    return servers


# ─── Step 2: Management API ────────────────────────────────────────────────

def probe_management(ip, port):
    """Query the Alpaca management API for device list."""
    print(f"\n{'=' * 60}")
    print(f"STEP 2: Management API — http://{ip}:{port}")
    print("=" * 60)

    base = f"http://{ip}:{port}"

    # Server description
    try:
        r = requests.get(f"{base}/management/v1/description", timeout=5)
        desc = r.json()
        print(f"  Server: {json.dumps(desc, indent=2)}")
    except Exception as e:
        print(f"  Description failed: {e}")

    # Configured devices
    devices = []
    try:
        r = requests.get(f"{base}/management/v1/configureddevices", timeout=5)
        data = r.json()
        devices = data.get("Value", [])
        print(f"\n  Configured devices ({len(devices)}):")
        for d in devices:
            print(f"    - {d.get('DeviceType','?')} #{d.get('DeviceNumber',0)}: "
                  f"{d.get('DeviceName','unnamed')}")
    except Exception as e:
        print(f"  Device list failed: {e}")

    # Alpaca API versions
    try:
        r = requests.get(f"{base}/management/apiversions", timeout=5)
        print(f"\n  API versions: {r.json()}")
    except Exception as e:
        print(f"  API versions failed: {e}")

    return devices


# ─── Step 3: Telescope READ test ───────────────────────────────────────────

def test_telescope_reads(ip, port, device_number=0):
    """Read telescope properties via Alpaca REST."""
    print(f"\n{'=' * 60}")
    print(f"STEP 3: Telescope READ test (device #{device_number})")
    print("=" * 60)

    base = f"http://{ip}:{port}/api/v1/telescope/{device_number}"

    # Connect first
    print("\n  Connecting...")
    try:
        r = requests.put(f"{base}/connected",
                         data={"Connected": "true", "ClientID": 1,
                               "ClientTransactionID": 1},
                         timeout=10)
        resp = r.json()
        err = resp.get("ErrorNumber", 0)
        if err:
            print(f"  ✗ Connect error {err}: {resp.get('ErrorMessage')}")
        else:
            print(f"  ✓ Connected")
    except Exception as e:
        print(f"  ✗ Connect failed: {e}")
        return False

    # Read properties
    properties = [
        ("name", "Name"),
        ("description", "Description"),
        ("driverversion", "Driver version"),
        ("interfaceversion", "Interface version"),
        ("canslew", "Can slew"),
        ("canslewasync", "Can slew async"),
        ("canpark", "Can park"),
        ("canunpark", "Can unpark"),
        ("canpulseguide", "Can pulse guide"),
        ("tracking", "Tracking"),
        ("atpark", "At park"),
        ("rightascension", "RA (hours)"),
        ("declination", "Dec (degrees)"),
        ("altitude", "Altitude (degrees)"),
        ("azimuth", "Azimuth (degrees)"),
        ("siderealtime", "Sidereal time"),
        ("siteelevation", "Site elevation"),
        ("sitelatitude", "Site latitude"),
        ("sitelongitude", "Site longitude"),
    ]

    results = {}
    for prop, label in properties:
        try:
            r = requests.get(f"{base}/{prop}",
                             params={"ClientID": 1, "ClientTransactionID": 1},
                             timeout=5)
            data = r.json()
            err = data.get("ErrorNumber", 0)
            val = data.get("Value")
            if err:
                print(f"  {label}: ERROR {err} — {data.get('ErrorMessage','')}")
            else:
                if isinstance(val, float):
                    print(f"  {label}: {val:.6f}")
                else:
                    print(f"  {label}: {val}")
                results[prop] = val
        except Exception as e:
            print(f"  {label}: FAILED — {e}")

    # Check supported actions (might reveal plan upload!)
    print("\n  Supported actions:")
    try:
        r = requests.get(f"{base}/supportedactions",
                         params={"ClientID": 1, "ClientTransactionID": 1},
                         timeout=5)
        data = r.json()
        actions = data.get("Value", [])
        if actions:
            for a in actions:
                print(f"    - {a}")
        else:
            print("    (none)")
    except Exception as e:
        print(f"    FAILED: {e}")

    return results


# ─── Step 4: Telescope WRITE test (slew) ──────────────────────────────────

def test_telescope_slew(ip, port, device_number=0):
    """Attempt a small slew to test write commands."""
    print(f"\n{'=' * 60}")
    print("STEP 4: Telescope WRITE test (slew)")
    print("=" * 60)

    base = f"http://{ip}:{port}/api/v1/telescope/{device_number}"

    # Read current position
    try:
        r = requests.get(f"{base}/rightascension",
                         params={"ClientID": 1, "ClientTransactionID": 1},
                         timeout=5)
        current_ra = r.json().get("Value")
        r = requests.get(f"{base}/declination",
                         params={"ClientID": 1, "ClientTransactionID": 1},
                         timeout=5)
        current_dec = r.json().get("Value")
        print(f"  Current position: RA={current_ra:.4f}h, Dec={current_dec:.4f}°")
    except Exception as e:
        print(f"  ✗ Can't read position: {e}")
        return

    # Try Unpark first
    print("\n  Attempting Unpark...")
    try:
        r = requests.put(f"{base}/unpark",
                         data={"ClientID": 1, "ClientTransactionID": 1},
                         timeout=10)
        resp = r.json()
        err = resp.get("ErrorNumber", 0)
        if err:
            print(f"  ✗ Unpark error {err}: {resp.get('ErrorMessage')}")
        else:
            print(f"  ✓ Unpark OK")
    except Exception as e:
        print(f"  ✗ Unpark failed: {e}")

    # Enable tracking
    print("  Enabling tracking...")
    try:
        r = requests.put(f"{base}/tracking",
                         data={"Tracking": "true", "ClientID": 1,
                               "ClientTransactionID": 1},
                         timeout=10)
        resp = r.json()
        err = resp.get("ErrorNumber", 0)
        if err:
            print(f"  ✗ Tracking error {err}: {resp.get('ErrorMessage')}")
        else:
            print(f"  ✓ Tracking enabled")
    except Exception as e:
        print(f"  ✗ Tracking failed: {e}")

    # Small slew: +0.01h in RA (about 0.15°)
    target_ra = current_ra + 0.01
    target_dec = current_dec
    print(f"\n  Attempting SlewToCoordinatesAsync:")
    print(f"    Target: RA={target_ra:.4f}h, Dec={target_dec:.4f}°")
    print(f"    (tiny slew: +0.01h ≈ 0.15° east)")

    try:
        r = requests.put(f"{base}/slewtocoordinatesasync",
                         data={"RightAscension": str(target_ra),
                               "Declination": str(target_dec),
                               "ClientID": 1,
                               "ClientTransactionID": 1},
                         timeout=15)
        resp = r.json()
        err = resp.get("ErrorNumber", 0)
        msg = resp.get("ErrorMessage", "")

        if err:
            print(f"\n  ✗ SLEW REJECTED — Error {err}: {msg}")
            print(f"    HTTP status: {r.status_code}")
            print(f"    Full response: {json.dumps(resp, indent=2)}")
            return False
        else:
            print(f"  ✓ SLEW COMMAND ACCEPTED!")
            # Poll slewing status
            for i in range(20):
                time.sleep(1)
                r2 = requests.get(f"{base}/slewing",
                                  params={"ClientID": 1,
                                          "ClientTransactionID": 1},
                                  timeout=5)
                slewing = r2.json().get("Value")
                if slewing:
                    print(f"    ... slewing ({i+1}s)")
                else:
                    print(f"  ✓ SLEW COMPLETE after {i+1}s")
                    # Read new position
                    r3 = requests.get(f"{base}/rightascension",
                                      params={"ClientID": 1,
                                              "ClientTransactionID": 1},
                                      timeout=5)
                    new_ra = r3.json().get("Value")
                    r4 = requests.get(f"{base}/declination",
                                      params={"ClientID": 1,
                                              "ClientTransactionID": 1},
                                      timeout=5)
                    new_dec = r4.json().get("Value")
                    print(f"  New position: RA={new_ra:.4f}h, Dec={new_dec:.4f}°")
                    return True
            print("  ⚠ Slew still in progress after 20s")
            return True
    except Exception as e:
        print(f"\n  ✗ SLEW FAILED: {e}")
        return False


# ─── Step 0: Port scan fallback ───────────────────────────────────────────

def find_alpaca_port(ip):
    """If discovery fails, try known ports for Alpaca management API."""
    print(f"\n  Scanning {ip} for Alpaca HTTP server...")
    for port in KNOWN_ALPACA_PORTS:
        try:
            r = requests.get(f"http://{ip}:{port}/management/apiversions",
                             timeout=3)
            if r.status_code == 200:
                print(f"  ✓ Found Alpaca on port {port}")
                return port
        except:
            pass

    # Also try the Seestar's known ports
    for port in [4700, 4800, 4801, 4900, 5555, 9090, 32323]:
        try:
            r = requests.get(f"http://{ip}:{port}/management/apiversions",
                             timeout=2)
            if r.status_code == 200:
                print(f"  ✓ Found Alpaca on port {port}")
                return port
        except:
            pass

    print("  ✗ No Alpaca HTTP server found")
    return None


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Wilhelmina Alpaca Test — Official ZWO Firmware Driver  ║")
    print("║  Target: 192.168.178.251 (S30-Pro, fw 7.18)            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Step 1: Discovery
    servers = discover_alpaca()

    # Find Wilhelmina's port
    alpaca_port = None
    for ip, port in servers:
        if ip == WILHELMINA_IP:
            alpaca_port = port
            break

    if not alpaca_port:
        alpaca_port = find_alpaca_port(WILHELMINA_IP)

    if not alpaca_port:
        print("\n✗ Cannot find Alpaca server on Wilhelmina.")
        print("  Possible causes:")
        print("  - Wilhelmina not in Station Mode (check Seestar app)")
        print("  - Firmware too old (needs Alpaca-capable firmware)")
        print("  - Alpaca not enabled in firmware")
        sys.exit(1)

    # Step 2: Management
    devices = probe_management(WILHELMINA_IP, alpaca_port)

    # Find telescope device number
    telescope_num = 0
    for d in devices:
        if d.get("DeviceType", "").lower() == "telescope":
            telescope_num = d.get("DeviceNumber", 0)
            break

    # Step 3: Reads
    results = test_telescope_reads(WILHELMINA_IP, alpaca_port, telescope_num)

    # Step 4: Writes (only with confirmation)
    if not results:
        print("\n✗ Read test failed — skipping write test")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print("READY FOR WRITE TEST")
    print("=" * 60)
    print()
    print("  This will attempt a tiny slew (+0.15° east).")
    print("  Wilhelmina's arm must be open and tracking.")
    print()

    if "--auto" in sys.argv:
        do_slew = True
    else:
        ans = input("  Proceed with slew test? [y/N] ").strip().lower()
        do_slew = ans in ("y", "yes")

    if do_slew:
        success = test_telescope_slew(WILHELMINA_IP, alpaca_port, telescope_num)
        if success:
            print("\n" + "🎉" * 20)
            print("  ALPACA WRITE COMMANDS WORK!")
            print("  The firmware lockout does NOT apply to the official")
            print("  Alpaca driver — SeeVar can control Wilhelmina!")
            print("🎉" * 20)
        else:
            print("\n  Slew failed. The lockout may apply to Alpaca writes too.")
            print("  Check the error messages above for clues.")
    else:
        print("\n  Skipped write test. Run again with --auto to auto-confirm.")

    print("\n  Done.")


if __name__ == "__main__":
    main()
