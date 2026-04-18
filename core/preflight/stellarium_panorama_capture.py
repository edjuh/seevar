#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/stellarium_panorama_capture.py
Version: 1.6.0
Objective: Capture a real visual panorama while slewing around the horizon.
Supports either direct RTSP snapshots or pulling freshly saved JPEGs from a
mounted Seestar media share after switching the device into scenery mode.
"""

import argparse
import errno
import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from alpaca.camera import Camera
from alpaca.telescope import Telescope

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import core.preflight.horizon_scanner_v2 as hv2
from core.preflight.stellarium_panorama_from_media import build_panorama_zip
from core.preflight.horizon_stellarium_export import HORIZON_MASK, STELLARIUM_DIR, _slugify
from core.preflight.panorama_calibration import (
    PANORAMA_CALIBRATION,
    apply_calibration,
    load_calibration_points,
    merge_calibration_points,
    parse_reference_point,
    save_calibration_points,
)
from core.utils.env_loader import DATA_DIR, load_config

PANORAMA_DIR = DATA_DIR / "panorama_media"
RTSP_WIDE_PORT = 4555
RPC_PORT = 4700
DEFAULT_SHARE_ROOT = PROJECT_ROOT / "s30_storage"
_RPC_MSG_ID = 50000


def _is_uri_location(root) -> bool:
    return isinstance(root, str) and "://" in root


def _gio_bin() -> str:
    path = shutil.which("gio")
    if not path:
        raise RuntimeError("gio is required for direct smb:// share access")
    return path


def _resolve_share_watch_root(root):
    if root is None:
        return None
    if _is_uri_location(root):
        uri = str(root).rstrip("/")
        lower = uri.lower()
        if lower.endswith("/scenery_photo"):
            return uri
        if lower.endswith("/myworks"):
            return f"{uri}/Scenery_photo"
        return uri

    path = Path(root)
    candidates = [
        path / "Scenery_photo",
        path / "MyWorks" / "Scenery_photo",
        path / "EMMC Images" / "MyWorks" / "Scenery_photo",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path


def _primary_scope_ip() -> str:
    cfg = load_config()
    scopes = cfg.get("seestars", [])
    if scopes:
        ip = scopes[0].get("ip")
        if ip and ip != "TBD":
            return str(ip)
    return "192.168.8.11"


def _capture_rtsp_jpeg(ip: str, out_path: Path, timeout: float = 10.0) -> None:
    url = f"rtsp://{ip}:{RTSP_WIDE_PORT}/stream"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-frames:v", "1",
        "-q:v", "2",
        "-y",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, timeout=timeout)


def _capture_rtsp_mp4(ip: str, out_path: Path, seconds: float, timeout: float | None = None) -> None:
    url = f"rtsp://{ip}:{RTSP_WIDE_PORT}/stream"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-t", f"{seconds:.2f}",
        "-an",
        "-y",
        "-c:v", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, timeout=timeout or max(10.0, seconds + 8.0))


def _rpc_call(ip: str, method: str, params=None, port: int = RPC_PORT, timeout: float = 6.0) -> dict:
    global _RPC_MSG_ID
    payload = {
        "id": _RPC_MSG_ID,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    _RPC_MSG_ID += 1

    wire = (json.dumps(payload) + "\r\n").encode("utf-8")
    chunks: list[bytes] = []
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(wire)
        while True:
            block = sock.recv(65536)
            if not block:
                break
            chunks.append(block)
            if b"\r\n" in block:
                break

    if not chunks:
        raise RuntimeError(f"{method}: empty response from {ip}:{port}")

    raw = b"".join(chunks).splitlines()[0]
    data = json.loads(raw.decode("utf-8"))
    if "error" in data:
        raise RuntimeError(f"{method}: {data['error']}")
    return data


def _set_view_mode(ip: str, mode: str) -> None:
    hv2.log.info("Switching %s into %s mode via JSON-RPC", ip, mode)
    try:
        _rpc_call(ip, "iscope_stop_view")
    except Exception as exc:
        hv2.log.warning("iscope_stop_view failed before mode switch: %s", exc)
    time.sleep(1.0)
    _rpc_call(ip, "iscope_start_view", {"mode": mode})
    time.sleep(2.0)


def _slew_panorama_position(telescope: Telescope, location, az: float, alt: float) -> bool:
    ra_h, dec_d = hv2.altaz_to_radec(az, alt, location)
    for attempt in range(1, hv2.SLEW_RETRY_LIMIT + 1):
        try:
            telescope.SlewToCoordinatesAsync(ra_h, dec_d)
        except Exception as exc:
            hv2.log.warning(
                "Panorama slew command failed at Az=%.1f° attempt %d/%d: %s",
                az,
                attempt,
                hv2.SLEW_RETRY_LIMIT,
                exc,
            )
            if attempt >= hv2.SLEW_RETRY_LIMIT:
                return False
            time.sleep(hv2.POST_RECOVERY_PAUSE_SEC)
            continue

        if hv2.wait_for_slew(telescope, timeout=45):
            time.sleep(hv2.SETTLE_SEC)
            return True

        hv2.log.warning(
            "Panorama slew timeout at Az=%.1f° attempt %d/%d",
            az,
            attempt,
            hv2.SLEW_RETRY_LIMIT,
        )
        try:
            telescope.AbortSlew()
        except Exception:
            pass
        if attempt >= hv2.SLEW_RETRY_LIMIT:
            return False
        time.sleep(hv2.POST_RECOVERY_PAUSE_SEC)
    return False


def _build_output_dir(base_dir: Path | None) -> Path:
    if base_dir is not None:
        out = Path(base_dir)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = PANORAMA_DIR / f"capture_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _capture_positions(step_deg: float) -> list[float]:
    values = np.arange(0.0, 360.0, float(step_deg)).tolist()
    if not values:
        values = [0.0]
    return [round(v, 1) for v in values]


def _snapshot_media(root: Path, suffixes: tuple[str, ...]) -> dict[Path, tuple[int, int]]:
    if _is_uri_location(root):
        return _snapshot_media_uri(str(root), suffixes)
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"Media share root does not exist: {root_path}")
    files: dict[str, tuple[int, int]] = {}
    try:
        entries = list(root_path.rglob("*"))
    except OSError:
        raise
    for path in entries:
        try:
            if not path.is_file():
                continue
            if path.suffix.lower() not in suffixes:
                continue
            stat = path.stat()
        except OSError:
            continue
        files[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return files


def _is_stale_file_handle(exc: BaseException) -> bool:
    message = str(exc).lower()
    err_no = getattr(exc, "errno", None)
    return err_no == errno.ESTALE or "stale file handle" in message


def _snapshot_media_safe(root, suffixes: tuple[str, ...], retries: int = 3, retry_sleep: float = 1.0):
    last_exc: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            return _snapshot_media(root, suffixes)
        except OSError as exc:
            last_exc = exc
            if not _is_stale_file_handle(exc) or attempt >= retries:
                break
            hv2.log.warning(
                "Media share snapshot hit stale file handle at %s (attempt %d/%d); retrying...",
                root,
                attempt,
                retries,
            )
            time.sleep(retry_sleep)
        except subprocess.CalledProcessError as exc:
            last_exc = exc
            if attempt >= retries:
                break
            time.sleep(retry_sleep)
    if last_exc is not None:
        raise RuntimeError(
            f"Could not snapshot media share {root}: {last_exc}. "
            "If this is a mounted Samba path, remount it before continuing."
        ) from last_exc
    raise RuntimeError(f"Could not snapshot media share {root}")


def _parse_gio_list_line(line: str) -> dict | None:
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 3:
        return None
    uri = parts[0]
    try:
        size = int(parts[1])
    except ValueError:
        size = 0
    type_field = parts[2].strip().lower()
    attrs: dict[str, str] = {}
    for field in parts[3:]:
        if "=" in field:
            key, value = field.split("=", 1)
            attrs[key.strip()] = value.strip()
    return {
        "uri": uri,
        "size": size,
        "modified": int(attrs.get("time::modified", "0") or "0"),
        "is_dir": "directory" in type_field,
    }


def _snapshot_media_uri(root_uri: str, suffixes: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    gio = _gio_bin()
    todo = [root_uri.rstrip("/")]
    seen: set[str] = set()
    files: dict[str, tuple[int, int]] = {}

    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        result = subprocess.run(
            [gio, "list", "-u", "-a", "time::modified,size,standard::type", current],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            parsed = _parse_gio_list_line(line)
            if not parsed:
                continue
            uri = parsed["uri"]
            if parsed["is_dir"]:
                todo.append(uri)
                continue
            suffix = Path(urlparse(uri).path).suffix.lower()
            if suffix not in suffixes:
                continue
            files[uri] = (int(parsed["modified"]) * 1_000_000_000, int(parsed["size"]))
    return files


def _wait_for_new_media(
    share_root,
    baseline: dict[str, tuple[int, int]],
    suffixes: tuple[str, ...],
    timeout: float,
    min_mtime_ns: int,
    seen_paths: set[str] | None = None,
    poll_sec: float = 1.0,
) -> str:
    deadline = time.monotonic() + timeout
    candidate: str | None = None
    consumed = seen_paths or set()
    while time.monotonic() < deadline:
        current = _snapshot_media_safe(share_root, suffixes)
        updates: list[tuple[int, str]] = []
        for path, stamp in current.items():
            if path in consumed:
                continue
            if int(stamp[0]) < int(min_mtime_ns):
                continue
            prior = baseline.get(path)
            if prior is None or stamp != prior:
                updates.append((stamp[0], path))
        if updates:
            candidate = max(updates, key=lambda item: item[0])[1]
            break
        time.sleep(poll_sec)

    if candidate is None:
        raise TimeoutError(f"No new media appeared under {share_root} within {timeout:.0f}s")

    stable_deadline = time.monotonic() + 5.0
    last_size = -1
    while time.monotonic() < stable_deadline:
        current = _snapshot_media_safe(share_root, suffixes)
        stamp = current.get(candidate)
        if stamp is None:
            time.sleep(0.5)
            continue
        size = stamp[1]
        if size == last_size:
            return candidate
        last_size = size
        time.sleep(0.5)
    return candidate


def _capture_share_media(
    share_root,
    output_dir: Path,
    stem: str,
    timeout: float,
    prompt: bool,
    suffixes: tuple[str, ...],
    min_mtime_ns: int,
    seen_paths: set[str],
) -> tuple[Path, str]:
    baseline = _snapshot_media_safe(share_root, suffixes)
    if prompt:
        input(f"Ready for {stem}. Trigger the scenery photo now, then press Enter to start watching {share_root} ...")
    pulled = _wait_for_new_media(
        share_root,
        baseline,
        suffixes,
        timeout=timeout,
        min_mtime_ns=min_mtime_ns,
        seen_paths=seen_paths,
    )
    pulled_path = Path(urlparse(pulled).path) if _is_uri_location(pulled) else Path(pulled)
    out_path = output_dir / f"{stem}{pulled_path.suffix.lower()}"
    if _is_uri_location(pulled):
        subprocess.run([_gio_bin(), "copy", pulled, str(out_path)], check=True)
    else:
        shutil.copy2(pulled_path, out_path)
    seen_paths.add(pulled)
    hv2.log.info("Pulled media from share: %s -> %s", pulled, out_path)
    return out_path, pulled


def capture_visual_panorama(
    ip: str,
    port: int,
    telescope_num: int,
    camera_num: int,
    client_id: int,
    altitude_deg: float,
    az_step_deg: float,
    output_dir: Path,
    capture_source: str,
    share_root,
    share_timeout: float,
    prompt_capture: bool,
    view_mode: str,
    require_mode_switch: bool,
    azimuth_offset_deg: float,
    calibration_points: list[dict] | None,
    video_seconds: float,
    build_zip: bool,
    zip_path: Path | None,
    landscape_name: str | None,
    top_alt: float,
    bottom_alt: float,
    sun_visible: bool,
) -> tuple[list[Path], Path | None]:
    output_dir = _build_output_dir(output_dir)
    positions = _capture_positions(az_step_deg)
    share_root = _resolve_share_watch_root(share_root)
    source = capture_source.lower().strip()
    if source == "auto":
        source = "share" if share_root and (_is_uri_location(share_root) or Path(share_root).exists()) else "rtsp"
    if source not in {"rtsp", "share"}:
        raise ValueError(f"Unsupported capture source: {capture_source}")
    if source == "share" and share_root is None:
        raise ValueError("share_root is required when capture_source='share'")

    location, lat, lon, elev = hv2.get_location()
    sun_alt, sun_az = hv2.get_sun_altaz(lat, lon, elev)

    addr = f"{ip}:{port}"
    telescope = Telescope(addr, telescope_num)
    camera = Camera(addr, camera_num) if source == "rtsp" else None
    if camera is not None:
        hv2.ALPACA_CAMERA_BASE = f"http://{ip}:{port}/api/v1/camera/{camera_num}"

    telescope.Connected = True
    if camera is not None:
        camera.Connected = True
        hv2.configure_camera(camera)
    try:
        telescope.Unpark()
    except Exception:
        pass
    try:
        _set_view_mode(ip, view_mode)
    except Exception as exc:
        if require_mode_switch:
            raise RuntimeError(f"Could not switch {ip} into {view_mode} mode: {exc}") from exc
        hv2.log.warning(
            "View mode switch to %s failed: %s. Continue and set the mode manually in the app if needed.",
            view_mode,
            exc,
        )

    if camera is not None and not hv2.probe_wide_camera(camera, client_id):
        hv2.disconnect_safely(camera, telescope)
        raise RuntimeError("Wide camera probe failed before panorama capture")

    captured: list[Path] = []
    capture_manifest: list[dict] = []
    consumed_share_paths: set[str] = set()
    try:
        for idx, az in enumerate(positions, start=1):
            if sun_visible and hv2.az_distance(az, sun_az) < hv2.SUN_EXCLUSION_DEG:
                hv2.log.warning("[%02d/%02d] Skip Az=%.1f° — sun exclusion", idx, len(positions), az)
                continue

            hv2.log.info("[%02d/%02d] Panorama slew Az=%.1f° Alt=%.1f°", idx, len(positions), az, altitude_deg)
            if source == "rtsp":
                moved = hv2.slew_with_recovery(telescope, camera, location, az, altitude_deg, client_id)
            else:
                moved = _slew_panorama_position(telescope, location, az, altitude_deg)
            if not moved:
                hv2.log.warning("Skipping panorama stop at Az=%.1f°", az)
                continue
            step_ready_ns = time.time_ns()

            try:
                actual_az = float(telescope.Azimuth)
            except Exception:
                actual_az = az
            placed_az = apply_calibration(
                actual_az,
                calibration_points,
                fallback_offset_deg=azimuth_offset_deg,
            )
            commanded_tag = f"{az % 360.0:05.1f}".replace(".", "_")
            observed_tag = f"{actual_az % 360.0:05.1f}".replace(".", "_")
            placed_tag = f"{placed_az % 360.0:05.1f}".replace(".", "_")
            stem = f"panorama_cmd{commanded_tag}_obs{observed_tag}_true{placed_tag}"
            hv2.log.info(
                "Panorama azimuth commanded=%.1f° observed=%.1f° placed=%.1f°",
                az % 360.0,
                actual_az % 360.0,
                placed_az,
            )

            jpg_path = output_dir / f"{stem}.jpg"
            if source == "rtsp":
                _capture_rtsp_jpeg(ip, jpg_path)
                captured.append(jpg_path)
                source_path = None
            else:
                pulled_path, source_path = _capture_share_media(
                    share_root=share_root,
                    output_dir=output_dir,
                    stem=stem,
                    timeout=share_timeout,
                    prompt=prompt_capture,
                    suffixes=(".jpg", ".jpeg"),
                    min_mtime_ns=step_ready_ns,
                    seen_paths=consumed_share_paths,
                )
                captured.append(pulled_path)
            capture_manifest.append(
                {
                    "step_index": idx,
                    "commanded_az_deg": round(float(az % 360.0), 3),
                    "observed_az_deg": round(float(actual_az % 360.0), 3),
                    "placed_az_deg": round(float(placed_az % 360.0), 3),
                    "captured_file": str(captured[-1]),
                    "capture_source": source,
                    "share_source": source_path,
                    "step_ready_utc": datetime.fromtimestamp(step_ready_ns / 1_000_000_000, tz=timezone.utc).isoformat(),
                }
            )

            if video_seconds > 0 and source == "rtsp":
                mp4_path = output_dir / f"{stem}.mp4"
                try:
                    _capture_rtsp_mp4(ip, mp4_path, seconds=video_seconds)
                except Exception as exc:
                    hv2.log.warning("Short video capture failed at Az=%.1f°: %s", az, exc)
            elif video_seconds > 0 and source == "share":
                hv2.log.info("video_seconds ignored for share capture source; copy videos manually from the mounted share if needed")

        zip_out = None
        if build_zip and captured:
            if zip_path is None:
                STELLARIUM_DIR.mkdir(parents=True, exist_ok=True)
                zip_name = _slugify(landscape_name or "SeeVar Panorama")
                zip_out = STELLARIUM_DIR / f"{zip_name}.zip"
            else:
                zip_out = Path(zip_path)
            build_panorama_zip(
                media_paths=captured,
                output_zip=zip_out,
                name=landscape_name or "SeeVar Panorama",
                pano_width=4096,
                pano_height=1024,
                top_alt=top_alt,
                bottom_alt=bottom_alt,
                mask_path=HORIZON_MASK if HORIZON_MASK.exists() else None,
                azimuth_offset_deg=float(azimuth_offset_deg),
                calibration_points=calibration_points,
            )
        manifest_path = output_dir / "capture_manifest.json"
        manifest_path.write_text(json.dumps({"captures": capture_manifest}, indent=2) + "\n")
        return captured, zip_out
    finally:
        hv2.disconnect_safely(camera, telescope)


def main():
    parser = argparse.ArgumentParser(description="Capture a real visual panorama from Seestar via RTSP or mounted media share.")
    parser.add_argument("--ip", type=str, default=None)
    parser.add_argument("--port", type=int, default=32323)
    parser.add_argument("--camera-num", type=int, default=hv2.WIDE_CAMERA_NUM_DEFAULT)
    parser.add_argument("--telescope-num", type=int, default=hv2.TELESCOPE_NUM_DEFAULT)
    parser.add_argument("--client-id", type=int, default=hv2.CLIENT_ID_DEFAULT)
    parser.add_argument("--alt", type=float, default=20.0)
    parser.add_argument("--az-step", type=float, default=15.0)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--capture-source", choices=["auto", "rtsp", "share"], default="auto")
    parser.add_argument("--share-root", type=str, default=str(DEFAULT_SHARE_ROOT))
    parser.add_argument("--share-timeout", type=float, default=90.0, help="Seconds to wait for a new JPEG on the mounted Seestar share")
    parser.add_argument("--prompt", action="store_true", help="Pause for Enter before watching the share for a new file")
    parser.add_argument("--view-mode", type=str, default="scenery", help="JSON-RPC view mode to request before capture (default: scenery)")
    parser.add_argument("--require-mode-switch", action="store_true", help="Fail if the requested view-mode switch does not confirm")
    parser.add_argument("--azimuth-offset-deg", type=float, default=-30.0, help="Apply a fixed azimuth correction before naming/placing panorama frames")
    parser.add_argument("--calibration-file", type=str, default=str(PANORAMA_CALIBRATION), help="Optional compass calibration JSON")
    parser.add_argument(
        "--reference",
        action="append",
        default=[],
        help=(
            "Compass anchor. Examples: 210=180, 210=south, "
            "obs=210,true=180,label=south roofline, "
            "file=/path/panorama_obs210_3.jpg,true=135,label=SE railing"
        ),
    )
    parser.add_argument("--save-calibration", action="store_true", help="Write merged reference points back to the calibration JSON")
    parser.add_argument("--video-seconds", type=float, default=0.0, help="Optional short MP4 duration per azimuth stop")
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--zip-output", type=str, default=None)
    parser.add_argument("--name", type=str, default="SeeVar Visual Panorama")
    parser.add_argument("--top-alt", type=float, default=45.0)
    parser.add_argument("--bottom-alt", type=float, default=-15.0)
    parser.add_argument("--sun-visible", dest="sun_visible", action="store_true")
    parser.add_argument("--sun-blocked", dest="sun_visible", action="store_false")
    parser.set_defaults(sun_visible=None)
    args = parser.parse_args()

    effective_source = args.capture_source
    if effective_source == "auto":
        effective_source = "share" if (_is_uri_location(args.share_root) or Path(args.share_root).exists()) else "rtsp"
    if effective_source == "rtsp" and shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required for RTSP panorama capture")

    ip = args.ip or _primary_scope_ip()
    if args.sun_visible is None:
        answer = input("Can the sun be seen by the Seestar from this site right now? [y/N]: ").strip().lower()
        sun_visible = answer.startswith("y")
    else:
        sun_visible = bool(args.sun_visible)

    calibration_points = load_calibration_points(Path(args.calibration_file)) if args.calibration_file else []
    if args.reference:
        calibration_points = merge_calibration_points(
            calibration_points,
            [parse_reference_point(spec) for spec in args.reference],
        )
        if args.save_calibration and args.calibration_file:
            written = save_calibration_points(calibration_points, Path(args.calibration_file))
            hv2.log.info("Saved compass calibration to %s", written)

    captured, zip_out = capture_visual_panorama(
        ip=ip,
        port=args.port,
        telescope_num=args.telescope_num,
        camera_num=args.camera_num,
        client_id=args.client_id,
        altitude_deg=args.alt,
        az_step_deg=args.az_step,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        capture_source=args.capture_source,
        share_root=args.share_root if args.share_root else None,
        share_timeout=float(args.share_timeout),
        prompt_capture=bool(args.prompt),
        view_mode=str(args.view_mode).strip().lower(),
        require_mode_switch=bool(args.require_mode_switch),
        azimuth_offset_deg=float(args.azimuth_offset_deg),
        calibration_points=calibration_points,
        video_seconds=float(args.video_seconds),
        build_zip=not args.no_zip,
        zip_path=Path(args.zip_output) if args.zip_output else None,
        landscape_name=args.name,
        top_alt=float(args.top_alt),
        bottom_alt=float(args.bottom_alt),
        sun_visible=sun_visible,
    )

    print(f"Captured JPEGs : {len(captured)}")
    if captured:
        print(f"Media dir      : {captured[0].parent}")
        if args.prompt:
            print("Prompt mode    : enabled")
    if zip_out:
        print(f"Stellarium zip : {zip_out}")


if __name__ == "__main__":
    main()
