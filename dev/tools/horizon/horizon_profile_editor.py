#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/horizon/horizon_profile_editor.py
Version: 1.0.0
Objective: Run a local Flask editor for manual SeeVar horizon profile cleanup.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR, load_config


DEFAULT_MASK = DATA_DIR / "horizon_mask.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5060
DEFAULT_FLOOR_DEG = 15.0
MIN_ALT_DEG = -5.0
MAX_ALT_DEG = 80.0


# Return a compact UTC timestamp for backup filenames.
def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# Keep edited horizon altitudes inside the supported profile range.
def _clamp_alt(value: float) -> float:
    return max(MIN_ALT_DEG, min(MAX_ALT_DEG, float(value)))


# Expand an azimuth sector, including wrap-around sectors crossing north.
def _az_range(start_az: int, end_az: int) -> list[int]:
    start = int(round(start_az)) % 360
    end = int(round(end_az)) % 360
    if start <= end:
        return list(range(start, end + 1))
    return list(range(start, 360)) + list(range(0, end + 1))


# Resolve the configured safety floor used for a new blank profile.
def _default_floor() -> float:
    try:
        cfg = load_config()
        candidates = [
            cfg.get("location", {}).get("horizon_limit"),
            cfg.get("horizon", {}).get("floor_deg"),
            cfg.get("horizon", {}).get("safety_floor_deg"),
            DEFAULT_FLOOR_DEG,
        ]
        values = []
        for item in candidates:
            if item is None:
                continue
            try:
                values.append(float(item))
            except (TypeError, ValueError):
                continue
        return max(values) if values else DEFAULT_FLOOR_DEG
    except Exception:
        return DEFAULT_FLOOR_DEG


# Build a full per-degree profile when no horizon mask exists yet.
def _blank_payload(mask_path: Path) -> dict:
    floor = round(_default_floor(), 1)
    profile = {str(az): floor for az in range(360)}
    confidence = {
        str(az): {"mean": floor, "var": 0.0, "n": 0, "source": "manual:editor_default"}
        for az in range(360)
    }
    return {
        "#objective": "Manual SeeVar horizon profile edited with dev/tools/horizon/horizon_profile_editor.py.",
        "source": "manual_editor",
        "method": "operator_canvas_edit",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_points": 360,
        "measured_points": 0,
        "interpolated_points": 0,
        "manual_points": 360,
        "manual_overrides": [],
        "profile": profile,
        "confidence": confidence,
        "editor": {"created_from": str(mask_path), "version": "1.0.0"},
    }


# Load an existing horizon mask and normalize missing or malformed entries.
def _load_payload(mask_path: Path) -> dict:
    if not mask_path.exists():
        return _blank_payload(mask_path)

    payload = json.loads(mask_path.read_text(encoding="utf-8"))
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        raise ValueError(f"{mask_path} has no usable profile object")

    fixed_profile = {}
    for az in range(360):
        try:
            fixed_profile[str(az)] = round(_clamp_alt(float(profile.get(str(az), _default_floor()))), 2)
        except (TypeError, ValueError):
            fixed_profile[str(az)] = round(_default_floor(), 2)
    payload["profile"] = fixed_profile

    confidence = payload.get("confidence")
    if not isinstance(confidence, dict):
        confidence = {}
    for az in range(360):
        key = str(az)
        if not isinstance(confidence.get(key), dict):
            confidence[key] = {
                "mean": fixed_profile[key],
                "var": 0.0,
                "n": 0,
                "source": "manual:editor_loaded",
            }
    payload["confidence"] = confidence
    return payload


# Produce small status numbers for the editor header and API responses.
def _summarize(payload: dict) -> dict:
    profile = {int(k): float(v) for k, v in payload["profile"].items()}
    values = list(profile.values())
    confidence = payload.get("confidence") or {}
    measured = sum(1 for entry in confidence.values() if isinstance(entry, dict) and entry.get("source") == "measured")
    manual = sum(1 for entry in confidence.values() if isinstance(entry, dict) and str(entry.get("source", "")).startswith("manual:"))
    return {
        "points": len(profile),
        "min_alt": round(min(values), 2),
        "max_alt": round(max(values), 2),
        "mean_alt": round(sum(values) / len(values), 2),
        "measured_points": measured,
        "manual_points": manual,
        "timestamp": payload.get("timestamp"),
        "source": payload.get("source", "unknown"),
    }


# Write a horizon mask with a timestamped backup of the previous file.
def _write_payload(mask_path: Path, payload: dict) -> Path | None:
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if mask_path.exists():
        backup = mask_path.with_name(f"{mask_path.stem}.{_now_stamp()}.bak{mask_path.suffix}")
        shutil.copy2(mask_path, backup)

    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    payload["n_points"] = 360
    payload["manual_points"] = sum(
        1
        for entry in (payload.get("confidence") or {}).values()
        if isinstance(entry, dict) and str(entry.get("source", "")).startswith("manual:")
    )
    mask_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return backup


# Apply individual edited azimuth/altitude points to the profile.
def _apply_points(payload: dict, points: list[dict], label: str) -> None:
    profile = payload["profile"]
    confidence = payload["confidence"]
    source = f"manual:{label or 'editor'}"
    for point in points:
        az = int(round(float(point["az"]))) % 360
        alt = round(_clamp_alt(float(point["alt"])), 2)
        profile[str(az)] = alt
        confidence[str(az)] = {"mean": alt, "var": 0.0, "n": 1, "source": source}


# Apply one constant-altitude obstruction sector to the profile.
def _apply_segment(payload: dict, start_az: int, end_az: int, altitude_deg: float, label: str) -> None:
    points = [{"az": az, "alt": altitude_deg} for az in _az_range(start_az, end_az)]
    _apply_points(payload, points, label or "segment")
    overrides = payload.setdefault("manual_overrides", [])
    overrides.append({
        "start_az": int(round(start_az)) % 360,
        "end_az": int(round(end_az)) % 360,
        "altitude_deg": round(_clamp_alt(altitude_deg), 2),
        "label": label or "editor_segment",
    })


# Render a Stellarium-style azimuth/altitude text profile for inspection.
def _horizon_txt(profile: dict) -> str:
    lines = []
    for az in range(360):
        lines.append(f"{az:.1f} {float(profile[str(az)]):.2f}\r\n")
    return "".join(lines)


# Create the Flask application and bind editor/API routes to one mask path.
def create_app(mask_path: Path) -> Flask:
    app = Flask(__name__)

    # Serve the single-page editor interface.
    @app.get("/")
    def index() -> Response:
        return Response(INDEX_HTML, mimetype="text/html")

    # Return the current profile, metadata, and summary statistics.
    @app.get("/api/profile")
    def get_profile() -> Response:
        payload = _load_payload(mask_path)
        return jsonify({"path": str(mask_path), "summary": _summarize(payload), "payload": payload})

    # Persist edited per-degree points from the canvas.
    @app.post("/api/points")
    def post_points() -> Response:
        body = request.get_json(force=True)
        points = body.get("points") or []
        if not isinstance(points, list) or not points:
            return jsonify({"error": "points must be a non-empty list"}), 400
        payload = _load_payload(mask_path)
        _apply_points(payload, points, str(body.get("label") or "editor"))
        backup = _write_payload(mask_path, payload)
        return jsonify({"summary": _summarize(payload), "backup": str(backup) if backup else None})

    # Persist one constant-altitude azimuth sector.
    @app.post("/api/segment")
    def post_segment() -> Response:
        body = request.get_json(force=True)
        payload = _load_payload(mask_path)
        _apply_segment(
            payload,
            int(float(body["start_az"])),
            int(float(body["end_az"])),
            float(body["altitude_deg"]),
            str(body.get("label") or "segment"),
        )
        backup = _write_payload(mask_path, payload)
        return jsonify({"summary": _summarize(payload), "backup": str(backup) if backup else None})

    # Export the current profile as azimuth/altitude text.
    @app.get("/api/horizon.txt")
    def get_horizon_txt() -> Response:
        payload = _load_payload(mask_path)
        return Response(_horizon_txt(payload["profile"]), mimetype="text/plain")

    return app


# Parse command-line options for the local editor server.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Flask editor for data/horizon_mask.json.")
    parser.add_argument("--mask", type=Path, default=DEFAULT_MASK, help="Horizon mask JSON to edit.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    return parser.parse_args()


# Start the Flask development server for operator use on a trusted local network.
def main() -> int:
    args = parse_args()
    mask_path = args.mask.expanduser().resolve()
    app = create_app(mask_path)
    print(f"Horizon editor: http://{args.host}:{args.port}/")
    print(f"Editing       : {mask_path}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SeeVar Horizon Editor</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101214;
      --panel: #181b1f;
      --line: #313842;
      --text: #e9eef2;
      --muted: #9aa7b3;
      --accent: #7ed957;
      --warn: #ffbe55;
      --danger: #ff6868;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    header, main { max-width: 1280px; margin: 0 auto; padding: 16px; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
    h1 { margin: 0; font-size: 20px; letter-spacing: .08em; text-transform: uppercase; }
    .meta { color: var(--muted); font-size: 12px; }
    .toolbar {
      display: grid;
      grid-template-columns: repeat(6, minmax(90px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 12px;
    }
    label { display: grid; gap: 4px; color: var(--muted); font-size: 11px; text-transform: uppercase; }
    input, button, a.button {
      min-height: 34px;
      border: 1px solid var(--line);
      background: #0d0f11;
      color: var(--text);
      padding: 7px 9px;
      font: inherit;
      text-decoration: none;
    }
    button, a.button { cursor: pointer; text-align: center; }
    button.primary { border-color: var(--accent); color: var(--accent); }
    button.warn { border-color: var(--warn); color: var(--warn); }
    canvas {
      width: 100%;
      height: 560px;
      display: block;
      background: #0b0d0f;
      border: 1px solid var(--line);
    }
    .status {
      margin-top: 10px;
      color: var(--muted);
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
    }
    .status strong { color: var(--text); font-weight: 600; }
    @media (max-width: 820px) {
      header { display: block; }
      .toolbar { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      canvas { height: 440px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>SeeVar Horizon Editor</h1>
      <div class="meta" id="path">loading...</div>
    </div>
    <div class="meta">drag the green profile; segment boxes write fixed azimuth ranges</div>
  </header>
  <main>
    <section class="toolbar">
      <label>Start Az<input id="startAz" type="number" min="0" max="359" value="245"></label>
      <label>End Az<input id="endAz" type="number" min="0" max="359" value="324"></label>
      <label>Altitude<input id="altitude" type="number" min="-5" max="80" step="0.5" value="32"></label>
      <label>Label<input id="label" type="text" value="manual_block"></label>
      <button class="primary" id="applySegment">Apply Segment</button>
      <a class="button" href="/api/horizon.txt" target="_blank">horizon.txt</a>
      <button id="reload">Reload</button>
      <button class="warn" id="saveVisible">Save Visible Profile</button>
    </section>
    <canvas id="plot" width="1200" height="560"></canvas>
    <div class="status">
      <span>Az <strong id="azRead">--</strong></span>
      <span>Alt <strong id="altRead">--</strong></span>
      <span>Min <strong id="minRead">--</strong></span>
      <span>Max <strong id="maxRead">--</strong></span>
      <span>Manual <strong id="manualRead">--</strong></span>
      <span id="message"></span>
    </div>
  </main>
  <script>
    const canvas = document.getElementById('plot');
    const ctx = canvas.getContext('2d');
    const profile = new Array(360).fill(15);
    const margin = {left: 48, right: 18, top: 18, bottom: 38};
    let dragging = false;

    function xForAz(az) {
      return margin.left + (az / 359) * (canvas.width - margin.left - margin.right);
    }
    function yForAlt(alt) {
      const min = -5, max = 80;
      return margin.top + ((max - alt) / (max - min)) * (canvas.height - margin.top - margin.bottom);
    }
    function azForX(x) {
      return Math.max(0, Math.min(359, Math.round(((x - margin.left) / (canvas.width - margin.left - margin.right)) * 359)));
    }
    function altForY(y) {
      const min = -5, max = 80;
      return Math.max(min, Math.min(max, max - ((y - margin.top) / (canvas.height - margin.top - margin.bottom)) * (max - min)));
    }
    function setMessage(text, bad=false) {
      const el = document.getElementById('message');
      el.textContent = text;
      el.style.color = bad ? 'var(--danger)' : 'var(--muted)';
    }
    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#0b0d0f';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = '#27303a';
      ctx.lineWidth = 1;
      ctx.fillStyle = '#89939e';
      ctx.font = '12px ui-monospace, monospace';
      for (let alt = 0; alt <= 80; alt += 10) {
        const y = yForAlt(alt);
        ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(canvas.width - margin.right, y); ctx.stroke();
        ctx.fillText(String(alt), 10, y + 4);
      }
      for (let az = 0; az < 360; az += 30) {
        const x = xForAz(az);
        ctx.beginPath(); ctx.moveTo(x, margin.top); ctx.lineTo(x, canvas.height - margin.bottom); ctx.stroke();
        ctx.fillText(String(az), x - 10, canvas.height - 12);
      }
      ctx.fillStyle = 'rgba(126,217,87,.18)';
      ctx.beginPath();
      ctx.moveTo(xForAz(0), canvas.height - margin.bottom);
      for (let az = 0; az < 360; az++) ctx.lineTo(xForAz(az), yForAlt(profile[az]));
      ctx.lineTo(xForAz(359), canvas.height - margin.bottom);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = '#7ed957';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let az = 0; az < 360; az++) {
        const x = xForAz(az), y = yForAlt(profile[az]);
        if (az === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    function pointer(ev) {
      const rect = canvas.getBoundingClientRect();
      const sx = canvas.width / rect.width, sy = canvas.height / rect.height;
      return {x: (ev.clientX - rect.left) * sx, y: (ev.clientY - rect.top) * sy};
    }
    function editAt(ev) {
      const p = pointer(ev);
      const az = azForX(p.x);
      const alt = Math.round(altForY(p.y) * 10) / 10;
      profile[az] = alt;
      document.getElementById('azRead').textContent = az;
      document.getElementById('altRead').textContent = alt.toFixed(1);
      draw();
    }
    async function loadProfile() {
      const res = await fetch('/api/profile');
      const data = await res.json();
      for (let az = 0; az < 360; az++) profile[az] = Number(data.payload.profile[String(az)] ?? 15);
      document.getElementById('path').textContent = data.path;
      document.getElementById('minRead').textContent = data.summary.min_alt;
      document.getElementById('maxRead').textContent = data.summary.max_alt;
      document.getElementById('manualRead').textContent = data.summary.manual_points;
      setMessage('loaded');
      draw();
    }
    async function postJson(url, body) {
      const res = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    canvas.addEventListener('mousedown', ev => { dragging = true; editAt(ev); });
    window.addEventListener('mouseup', () => { dragging = false; });
    canvas.addEventListener('mousemove', ev => { if (dragging) editAt(ev); });
    document.getElementById('reload').onclick = loadProfile;
    document.getElementById('saveVisible').onclick = async () => {
      const points = profile.map((alt, az) => ({az, alt}));
      try {
        const data = await postJson('/api/points', {label: 'canvas', points});
        setMessage(`saved; backup=${data.backup || 'none'}`);
      } catch (err) { setMessage(err.message, true); }
    };
    document.getElementById('applySegment').onclick = async () => {
      try {
        await postJson('/api/segment', {
          start_az: Number(document.getElementById('startAz').value),
          end_az: Number(document.getElementById('endAz').value),
          altitude_deg: Number(document.getElementById('altitude').value),
          label: document.getElementById('label').value || 'segment'
        });
        await loadProfile();
      } catch (err) { setMessage(err.message, true); }
    };
    loadProfile();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
