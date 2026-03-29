#!/usr/bin/env python3
# ==============================================================================
# 🔭 SeeVar: Sovereign Heartbeat Monitor
# Path: dev/tools/seestar_heartbeat.py
# Objective: Maintain persistent TCP connection to Seestar via 5-second polling
#            Dynamically parses configuration from ~/seevar/config.toml
# ==============================================================================

import socket
import json
import time
import sys
from pathlib import Path

# Safe import for TOML parsing depending on Python version
try:
    import tomllib  # Built-in for Python 3.11+
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("❌ Error: tomllib or tomli is required to parse config.toml.")
        sys.exit(1)

CONFIG_PATH = Path.home() / "seevar" / "config.toml"
POLL_INTERVAL = 5.0  # 5 seconds easily beats the 15-second idle timeout
TIMEOUT = 10.0       # Aggressive timeout to fail fast on dead sockets

def load_network_config():
    """Extract Seestar IP and Port dynamically from config.toml."""
    if not CONFIG_PATH.exists():
        print(f"⚠️ Config not found at {CONFIG_PATH}. Using fallback: 192.168.178.251:4700")
        return "192.168.178.251", 4700

    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
            # Adjust these dict keys if your config.toml structure differs
            host = config.get("network", {}).get("seestar_ip", "192.168.178.251")
            port = config.get("network", {}).get("seestar_port", 4700)
            return host, port
    except Exception as e:
        print(f"⚠️ Failed to parse {CONFIG_PATH}: {e}. Using fallbacks.")
        return "192.168.178.251", 4700

def start_heartbeat():
    host, port = load_network_config()
    print(f"🚀 Initiating Sovereign Heartbeat to {host}:{port}")

    # The optimal lightweight payload to keep the connection alive safely
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "get_app_state",
        "id": 1000
    }) + "\r\n"
    
    cmd_bytes = payload.encode('utf-8')

    # OUTER LOOP: Handles infinite reconnection attempts
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        
        try:
            print(f"🔌 Connecting to {host}:{port}...")
            s.connect((host, port))
            print("✅ Connection established. Starting 5-second polling loop.")

            # INNER LOOP: Handles the active heartbeat protocol
            while True:
                loop_start = time.monotonic()

                # 1. Send the heartbeat ping
                s.sendall(cmd_bytes)

                # 2. Await and parse the response
                buf = b''
                deadline = time.monotonic() + TIMEOUT
                response_received = False

                while time.monotonic() < deadline:
                    try:
                        chunk = s.recv(4096)
                        if not chunk:
                            raise BrokenPipeError("Empty byte returned (socket closed by remote).")

                        buf += chunk
                        if b'\r\n' in buf:
                            line, _ = buf.split(b'\r\n', 1)
                            response = json.loads(line.decode('utf-8', errors='ignore'))
                            
                            if "result" in response or "error" in response:
                                # Successfully pinged and parsed
                                print(f"💓 Heartbeat OK | App State: {response.get('result', 'Error/Unknown')}")
                                response_received = True
                                break
                    except socket.timeout:
                        break # Let outer deadline handling catch the timeout

                if not response_received:
                    print("⚠️ No valid JSON-RPC response received. Tearing down socket.")
                    break # Break inner loop to force a fresh connection

                # 3. Sleep precisely until the next 5-second interval
                elapsed = time.monotonic() - loop_start
                sleep_time = max(0.0, POLL_INTERVAL - elapsed)
                time.sleep(sleep_time)

        except (socket.timeout, ConnectionError, BrokenPipeError) as e:
            print(f"🛑 Connection lost ({type(e).__name__}): {e}. Reconnecting in 3 seconds...")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n🛑 Heartbeat manually terminated by user.")
            break
        except Exception as e:
            print(f"❌ Unexpected exception: {e}. Reconnecting in 3 seconds...")
            time.sleep(3)
        finally:
            s.close()

if __name__ == "__main__":
    start_heartbeat()
