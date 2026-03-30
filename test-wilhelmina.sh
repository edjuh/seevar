#!/bin/bash
# =============================================================================
# test_wilhelmina.sh
# Interactive test suite for Wilhelmina hardware communication.
# Tests Alpaca, JSON-RPC handshake, and port 4801 frame stream.
# Run from ~/seevar with .venv active.
# =============================================================================

HOST="192.168.178.251"
ALPACA="http://${HOST}:32323/api/v1/telescope/0"

alpaca_get() {
    curl -s "${ALPACA}/${1}?ClientID=1&ClientTransactionID=1" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  {d.get(\"Value\",\"ERR\")}  err={d.get(\"ErrorNumber\",\"?\")} {d.get(\"ErrorMessage\",\"\")}')"
}

alpaca_put() {
    curl -s -X PUT "${ALPACA}/${1}" \
      -d "${2}&ClientID=1&ClientTransactionID=1" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); ok='OK' if d.get('ErrorNumber')==0 else f'ERR {d[\"ErrorNumber\"]}: {d[\"ErrorMessage\"]}'; print(f'  {ok}')"
}

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║       Wilhelmina Test Suite v1.0.0               ║"
echo "╚══════════════════════════════════════════════════╝"

echo ""
echo "[ 1/5 ] Alpaca — basic connectivity"
alpaca_put "connected" "Connected=true"
echo -n "  name:      "; alpaca_get "name"
echo -n "  connected: "; alpaca_get "connected"
echo -n "  RA:        "; alpaca_get "rightascension"
echo -n "  Dec:       "; alpaca_get "declination"
echo -n "  altitude:  "; alpaca_get "altitude"
echo -n "  atpark:    "; alpaca_get "atpark"
echo -n "  tracking:  "; alpaca_get "tracking"

echo ""
echo "[ 2/5 ] JSON-RPC — handshake + master claim"
.venv/bin/python3 << 'PYEOF'
import socket, json, time

HOST = "192.168.178.251"
PORT = 4700

def udp_handshake():
    import socket
    msg = json.dumps({"jsonrpc":"2.0","id":1,"method":"scan_iscope","verify":True}).encode()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
            u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            u.settimeout(2.0)
            u.sendto(msg, ("255.255.255.255", 4720))
            print("  UDP scan_iscope sent to port 4720")
    except Exception as e:
        print(f"  UDP failed (non-fatal): {e}")

udp_handshake()
time.sleep(0.5)

s = socket.socket()
s.settimeout(5)
try:
    s.connect((HOST, PORT))
    print("  TCP connect: OK")
except Exception as e:
    print(f"  TCP connect: FAILED — {e}")
    exit(1)

buf = b""
cmd_id = 10000

def send(method, params=None):
    global cmd_id
    msg = {"jsonrpc":"2.0","id":cmd_id,"method":method}
    if params is None:
        msg["verify"] = True
    elif isinstance(params, dict):
        msg["params"] = params
    elif isinstance(params, list):
        msg["params"] = list(params) + ["verify"]
    s.sendall((json.dumps(msg)+"\r\n").encode())
    cmd_id += 1
    time.sleep(0.3)

def drain(secs=3):
    deadline = time.monotonic() + secs
    lines = []
    buf2 = b""
    while time.monotonic() < deadline:
        try:
            chunk = s.recv(4096)
            if chunk:
                buf2 += chunk
                while b"\r\n" in buf2:
                    line, buf2 = buf2.split(b"\r\n",1)
                    try: lines.append(json.loads(line))
                    except: pass
        except socket.timeout: continue
    return lines

# Drain initial events
drain(2)

# Init sequence
send("pi_is_verified")
send("set_setting", {"master_cli": True})
send("set_setting", {"cli_name": "SeeVar"})
time.sleep(0.5)

# Test a command
send("get_device_state")
responses = drain(5)
if responses:
    for r in responses:
        if r.get("id") == cmd_id - 1 or ("result" in r and "Event" not in r):
            print(f"  get_device_state response: {r}")
            break
    else:
        events = [r.get("Event") for r in responses if "Event" in r]
        print(f"  No command response — events received: {events}")
else:
    print("  No response received (session lock or connection issue)")

# Watch for Client event (master status)
send("pi_is_verified")
responses = drain(5)
for r in responses:
    if r.get("Event") == "Client":
        print(f"  Client event: is_master={r.get('is_master')} master_index={r.get('master_index')}")
        break

s.close()
PYEOF

echo ""
echo "[ 3/5 ] Port 4801 — frame stream (10s listen)"
.venv/bin/python3 << 'PYEOF'
import socket, struct, time

HOST = "192.168.178.251"
try:
    s = socket.socket()
    s.settimeout(3)
    s.connect((HOST, 4801))
    print("  Connected to port 4801")
    deadline = time.monotonic() + 10
    frames = 0
    while time.monotonic() < deadline:
        try:
            header = s.recv(80, socket.MSG_WAITALL)
            if len(header) < 20:
                continue
            _s1,_s2,_s3,size,_s5,_s6,code,frame_id,w,h = struct.unpack(">HHHIHHBBHH", header[:20])
            if size < 1000:
                continue
            payload = s.recv(size)
            print(f"  frame_id={frame_id} {w}x{h} size={size} expected={w*h*2}")
            frames += 1
            if frames >= 2:
                break
        except socket.timeout:
            continue
    if frames == 0:
        print("  No frames received (ContinuousExposure not active?)")
    s.close()
except Exception as e:
    print(f"  Port 4801 error: {e}")
PYEOF

echo ""
echo "[ 4/5 ] Event stream — 10s vocabulary capture"
.venv/bin/python3 << 'PYEOF'
import socket, json, time

HOST = "192.168.178.251"
s = socket.socket()
s.settimeout(2)
try:
    s.connect((HOST, 4700))
    seen = {}
    deadline = time.monotonic() + 10
    buf = b""
    while time.monotonic() < deadline:
        try:
            chunk = s.recv(4096)
            if chunk:
                buf += chunk
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    try:
                        msg = json.loads(line)
                        ev = msg.get("Event")
                        if ev and ev not in seen:
                            seen[ev] = msg
                            print(f"  {ev}: {msg}")
                    except: pass
        except socket.timeout: continue
    s.close()
    if not seen:
        print("  No events received")
except Exception as e:
    print(f"  Error: {e}")
PYEOF

echo ""
echo "[ 5/5 ] WilhelminaMonitor state"
cat /dev/shm/wilhelmina_state.json 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'  link_status : {d.get(\"link_status\")}')
print(f'  battery_pct : {d.get(\"battery_pct\")}%')
print(f'  temp_c      : {d.get(\"temp_c\")}°C')
print(f'  tracking    : {d.get(\"tracking\")}')
print(f'  level_angle : {d.get(\"level_angle\")}°')
print(f'  level_ok    : {d.get(\"level_ok\")}')
print(f'  last_event  : {d.get(\"last_event\")}')
print(f'  event_counts: {len(d.get(\"event_counts\",{}))} types seen')
" 2>/dev/null || echo "  wilhelmina_state.json not found"

echo ""
echo "══════════════════════════════════════════════════"
echo "  Test complete."
echo "══════════════════════════════════════════════════"
