#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/accountant.py
Version: 2.5.0
Objective: Sweep local_buffer, build aligned stack-first science products from dark-calibrated frames, require real solved WCS,
run Bayer differential photometry, and stamp TG scientific results into the ledger.
"""

import json
import logging
import shutil
import fcntl
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.ndimage import shift as ndi_shift
from scipy.spatial import cKDTree
from skimage.registration import phase_cross_correlation

try:
    import astroalign
except ImportError:  # optional fallback; normal shift alignment remains available
    astroalign = None

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.postflight.calibration_engine import CalibrationEngine
from core.postflight.master_analyst import MasterAnalyst
from core.postflight.dark_calibrator import dark_calibrator
from core.postflight.calibration_assets import ensure_calibration_dirs, save_missing_calibrations
from core.utils.env_loader import load_config
from core.flight.star_quality import StarShapeMetrics, measure_star_shape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("Accountant")

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = DATA_DIR / "reports"
LOCAL_BUFFER = DATA_DIR / "local_buffer"
ARCHIVE_DIR = DATA_DIR / "archive"
PROCESS_DIR = DATA_DIR / "process"
CALIBRATED_BUFFER = DATA_DIR / "calibrated_buffer"
LEDGER_FILE = DATA_DIR / "ledger.json"
MISSING_DARKS_FILE = DATA_DIR / "missing_darks.json"
PLAN_FILE = DATA_DIR / "tonights_plan.json"
VSX_CATALOG_FILE = DATA_DIR / "vsx_catalog.json"
ACCOUNTANT_LOCK = DATA_DIR / "accountant.lock"

MIN_SNR = 5.0
STACK_GROUP_GAP_SEC = 900
MAX_STACK_FRAMES = 24


# Function: _postflight_cfg
def _postflight_cfg() -> dict:
    cfg = load_config()
    return cfg.get("postflight", {}) if isinstance(cfg, dict) else {}


# Function: _cfg_int
def _cfg_int(key: str, default: int) -> int:
    try:
        return int(round(float(_postflight_cfg().get(key, default))))
    except Exception:
        return default


# Function: _cfg_float
def _cfg_float(key: str, default: float) -> float:
    try:
        return float(_postflight_cfg().get(key, default))
    except Exception:
        return default


# Function: _cfg_bool
def _cfg_bool(key: str, default: bool) -> bool:
    value = _postflight_cfg().get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


MAX_PLATE_SOLVE_CANDIDATES = max(1, _cfg_int("max_plate_solve_candidates", 3))
STACK_SHAPE_QC_ENABLED = _cfg_bool("stack_shape_qc_enabled", True)
PUBLISH_SINGLE_FRAME_PREVIEWS = _cfg_bool("publish_single_frame_previews", False)
REQUIRE_STACKED_PRODUCTS = _cfg_bool("require_stacked_products", True)
MIN_STAR_SHAPE_SOURCES = max(3, _cfg_int("min_star_shape_sources", 8))
MAX_STAR_ELONGATION = max(1.5, _cfg_float("max_star_elongation", 6.0))
MAX_STAR_TRAIL_PX = max(4.0, _cfg_float("max_star_trail_px", 18.0))

_engine = CalibrationEngine()
_analyst = MasterAnalyst()


# Function: _install_accountant_log_handler
def _install_accountant_log_handler():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "accountant.log"
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger_names = [
        "Accountant",
        "MasterAnalyst",
        "seevar.dark_calibrator",
        "seevar.calibration_engine",
        "seevar.bayer_photometry",
        "seevar.gaia_resolver",
    ]
    for logger_name in logger_names:
        target_logger = logging.getLogger(logger_name)
        for handler in target_logger.handlers:
            if getattr(handler, "baseFilename", None) == str(log_path):
                break
        else:
            file_handler = logging.FileHandler(log_path, mode="a")
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            target_logger.addHandler(file_handler)


_install_accountant_log_handler()


# Collapse low-level calibration errors into stable morning-triage categories.
# Function: _classify_failure
def _classify_failure(error: str) -> str:
    err_l = str(error or "").lower()
    if "snr_too_low" in err_l:
        return "LOW_SNR"
    if "saturated" in err_l:
        return "SATURATED"
    if "target_flux_zero_or_negative" in err_l:
        return "NEGATIVE_FLUX"
    if "out_of_frame" in err_l:
        return "OUT_OF_FRAME"
    if "insufficient_valid_comps_after_clip" in err_l:
        return "INSUFFICIENT_COMPS_AFTER_CLIP"
    if "insufficient_valid_comps" in err_l or "insufficient_comp_stars" in err_l:
        return "INSUFFICIENT_COMPS"
    if "no_wcs" in err_l or "wcs" in err_l:
        return "NO_WCS"
    if "dark" in err_l:
        return "NO_DARK"
    if "failed_to_load_fits" in err_l:
        return "FAILED_TO_LOAD_FITS"
    if err_l:
        return "QC_OTHER"
    return "UNKNOWN"


# Render a compact text report and matching JSON artifact for morning triage.
# Function: _write_postflight_report
def _write_postflight_report(
    session_started_utc: str,
    processed: int,
    successes: int,
    session_rows: list[dict],
) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"postflight_summary_{stamp}"
    json_path = REPORT_DIR / f"{base_name}.json"
    txt_path = REPORT_DIR / f"{base_name}.txt"

    status_counts = Counter(str(row.get("ledger_status", "UNKNOWN")) for row in session_rows)
    failure_counts = Counter(
        str(row.get("failure_category"))
        for row in session_rows
        if row.get("failure_category")
    )
    accepted_rows = [row for row in session_rows if row.get("observation_success")]
    failed_rows = [row for row in session_rows if not row.get("observation_success")]

    payload = {
        "metadata": {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "session_started_utc": session_started_utc,
            "schema_version": "2026.7",
        },
        "counts": {
            "raw_frames_processed": processed,
            "successful_observations": successes,
            "groups": len(session_rows),
            "status": dict(sorted(status_counts.items())),
            "failure_category": dict(sorted(failure_counts.items())),
        },
        "accepted_observations": accepted_rows,
        "failed_groups": failed_rows,
    }

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    lines = [
        "SeeVar Postflight Summary",
        f"generated UTC : {payload['metadata']['generated_utc']}",
        f"session UTC   : {session_started_utc}",
        f"raw processed : {processed}",
        f"accepted      : {successes}",
        f"groups        : {len(session_rows)}",
        "",
        "Status counts",
    ]
    if status_counts:
        for status, count in sorted(status_counts.items()):
            lines.append(f"  {status:24} {count}")
    else:
        lines.append("  none")

    lines.extend(["", "Failure categories"])
    if failure_counts:
        for category, count in sorted(failure_counts.items()):
            lines.append(f"  {category:24} {count}")
    else:
        lines.append("  none")

    lines.extend(["", "Accepted observations"])
    if accepted_rows:
        for row in accepted_rows:
            lines.append(
                "  {target:20} TG={mag:.3f} +/- {err:.3f} SNR={snr:.1f} comps={comps}/{comps_raw} "
                "rej={rej} mode={mode}".format(
                    target=row["target_name"],
                    mag=float(row.get("mag", 0.0)),
                    err=float(row.get("err", 0.0)),
                    snr=float(row.get("target_snr", 0.0)),
                    comps=int(row.get("n_comps", 0)),
                    comps_raw=int(row.get("n_comps_raw", row.get("n_comps", 0))),
                    rej=int(row.get("n_comps_rejected", 0)),
                    mode=row.get("calibration_state", "UNKNOWN"),
                )
            )
    else:
        lines.append("  none")

    lines.extend(["", "Failed groups"])
    if failed_rows:
        for row in failed_rows:
            lines.append(
                f"  {row['target_name']:20} status={row.get('ledger_status','UNKNOWN'):18} "
                f"category={row.get('failure_category','UNKNOWN'):24} detail={row.get('failure_detail','')}"
            )
    else:
        lines.append("  none")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Postflight summary written: %s", txt_path.name)
    log.info("Postflight summary written: %s", json_path.name)
    return txt_path, json_path


@contextmanager
# Function: _process_lock
def _process_lock():
    ACCOUNTANT_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNTANT_LOCK, "w") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return

        try:
            lock_handle.write(str(datetime.now(timezone.utc).isoformat()))
            lock_handle.flush()
            yield True
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


# Function: load_ledger
def load_ledger() -> dict:
    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE, "r") as f:
                data = json.load(f)
                return data.get("entries", {}) if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            log.warning("Ledger unreadable, starting fresh.")
    return {}


# Function: save_ledger
def save_ledger(entries: dict):
    output = {
        "#objective": "Master Observational Register and Status Ledger",
        "metadata": {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "schema_version": "2026.6",
        },
        "entries": entries,
    }
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_FILE, "w") as f:
        json.dump(output, f, indent=4)



# Function: _temp_bin_for_requirement
def _temp_bin_for_requirement(temp_c):
    if temp_c in (None, "", "UNKNOWN"):
        return None
    try:
        return int(round(float(temp_c) / 2.0) * 2.0)
    except Exception:
        return None


# Function: save_missing_darks
def save_missing_darks(entries: dict):
    requirements = {}

    for target_name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "FAILED_NO_DARK":
            continue

        exp_ms = entry.get("required_dark_exp_ms")
        gain = entry.get("required_dark_gain")
        temp_c = entry.get("required_dark_temp_c")
        if exp_ms in (None, "") or gain in (None, ""):
            continue

        exp_ms = int(exp_ms)
        gain = int(gain)
        temp_bin = _temp_bin_for_requirement(temp_c)
        req_key = f"e{exp_ms}_g{gain}_tb{temp_bin if temp_bin is not None else 'na'}"

        bucket = requirements.setdefault(req_key, {
            "exp_ms": exp_ms,
            "gain": gain,
            "temp_bin": temp_bin,
            "targets": [],
            "capture_paths": [],
            "latest_capture_utc": None,
        })

        bucket["targets"].append(target_name)
        if entry.get("last_capture_path"):
            bucket["capture_paths"].append(entry["last_capture_path"])

        last_capture = entry.get("last_capture_utc")
        if last_capture and (bucket["latest_capture_utc"] is None or last_capture > bucket["latest_capture_utc"]):
            bucket["latest_capture_utc"] = last_capture

    payload = {
        "metadata": {
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "requirement_count": len(requirements),
            "target_count": sum(len(v["targets"]) for v in requirements.values()),
        },
        "requirements": sorted(
            requirements.values(),
            key=lambda x: (x["exp_ms"], x["gain"], x["temp_bin"] if x["temp_bin"] is not None else 9999),
        ),
    }

    MISSING_DARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MISSING_DARKS_FILE, "w") as f:
        json.dump(payload, f, indent=4)


# Function: _blank_entry
def _blank_entry() -> dict:
    return {
        "status": "PENDING",
        "last_success": None,
        "last_capture_utc": None,
        "last_capture_path": None,
        "attempts": 0,
        "priority": "NORMAL",
        "last_mag": None,
        "last_err": None,
        "last_snr": None,
        "last_filter": None,
        "last_photometric_system": None,
        "last_measurement_kind": None,
        "last_comps": None,
        "last_comps_raw": None,
        "last_comps_rejected": None,
        "last_comp_rows": None,
        "last_zp": None,
        "last_zp_std": None,
        "last_target_inst_mag": None,
        "last_target_inst_err": None,
        "last_obs_utc": None,
        "last_peak_adu": None,
        "last_solved_ra": None,
        "last_solved_dec": None,
        "last_dark_key": None,
        "required_dark_exp_ms": None,
        "required_dark_gain": None,
        "required_dark_temp_c": None,
        "required_bias_gain": None,
        "required_flat_filter": None,
        "required_flat_scope_id": None,
        "required_flat_scope_name": None,
        "last_scope_id": None,
        "last_scope_name": None,
        "last_calibration_state": None,
        "last_accepted_product": None,
        "last_accepted_preview": None,
    }


# Function: _parse_header
def _parse_header(fpath: Path, header: dict) -> tuple:
    target_name = header.get("OBJECT", "")
    if not str(target_name).strip():
        target_name = fpath.stem.split("_")[0]
    target_name = str(target_name).strip()

    date_obs = header.get("DATE-OBS")
    if not date_obs:
        date_obs = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).isoformat()

    ra_deg = dec_deg = None

    ra_val = header.get("RA")
    dec_val = header.get("DEC")
    if ra_val is not None and dec_val is not None:
        try:
            ra_deg = float(ra_val)
            dec_deg = float(dec_val)
            return target_name, date_obs, ra_deg, dec_deg
        except Exception:
            pass

    ra_str = header.get("OBJCTRA")
    dec_str = header.get("OBJCTDEC")
    if ra_str and dec_str:
        try:
            coord = SkyCoord(f"{ra_str} {dec_str}", unit=(u.hourangle, u.deg))
            ra_deg = float(coord.ra.deg)
            dec_deg = float(coord.dec.deg)
            return target_name, date_obs, ra_deg, dec_deg
        except Exception:
            pass

    if header.get("CRVAL1") is not None and header.get("CRVAL2") is not None:
        try:
            ra_deg = float(header["CRVAL1"])
            dec_deg = float(header["CRVAL2"])
        except Exception:
            pass

    return target_name, date_obs, ra_deg, dec_deg


# Function: _archive_frame
def _archive_frame(fpath: Path):
    _archive_paths([fpath])


# Function: _parse_iso_utc
def _parse_iso_utc(value: str | None):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# Function: _safe_name
def _safe_name(name: str) -> str:
    return str(name or "UNKNOWN").replace(" ", "_").replace("/", "-")


# Function: _accepted_products_dir
def _accepted_products_dir(session_started_utc: str) -> Path:
    cfg = load_config()
    postflight_cfg = cfg.get("postflight", {}) if isinstance(cfg, dict) else {}
    configured = str(postflight_cfg.get("accepted_products_dir") or "").strip()
    if configured:
        return Path(configured).expanduser()

    storage_cfg = cfg.get("storage", {}) if isinstance(cfg, dict) else {}
    primary = str(storage_cfg.get("primary_dir") or "").strip()
    if primary:
        root = Path(primary).expanduser()
        return root / "Astrophoto" / "Variables" / f"SeeVar_{session_started_utc[:10].replace('-', '')}_accepted_solved"

    return ARCHIVE_DIR / "accepted_solved"


# Function: _copy_wcs_sidecar
def _copy_wcs_sidecar(source_wcs: Path | None, product_path: Path) -> Path | None:
    if not source_wcs or not Path(source_wcs).exists():
        return None
    dest_wcs = product_path.with_suffix(".wcs")
    if Path(source_wcs) != dest_wcs:
        shutil.copy2(source_wcs, dest_wcs)
    return dest_wcs


# Function: _copy_accepted_fits
def _copy_accepted_fits(source: Path, dest: Path, result: dict, row: dict) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with fits.open(source) as hdul:
        header = hdul[0].header
        header["ACCEPTED"] = (True, "SeeVar postflight accepted")
        header["ACCMAG"] = (float(result.get("mag", 0.0)), "Accepted TG magnitude")
        header["ACCERR"] = (float(result.get("err", 0.0)), "Accepted TG uncertainty")
        header["ACCSNR"] = (float(result.get("target_snr", 0.0)), "Accepted target SNR")
        header["ACCSTATE"] = (str(row.get("calibration_state", ""))[:68], "Accepted product state")
        header["ACCUTC"] = (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "Acceptance UTC")
        hdul.writeto(dest, overwrite=True)
    return dest


# Function: _is_stacked_product
def _is_stacked_product(product_path: Path, row: dict) -> bool:
    state = str(row.get("calibration_state") or "").upper()
    if "STACK" in state or "STACK" in product_path.name.upper():
        return True
    try:
        header = fits.getheader(product_path, 0)
        return bool(header.get("STACKED") or int(header.get("NCOMBINE", 1)) > 1)
    except Exception:
        return False


# Function: _scale_preview
def _scale_preview(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim > 2:
        arr = np.squeeze(arr)
    if arr.ndim != 2:
        raise ValueError("preview data is not 2-D")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError("preview data has no finite pixels")
    lo, hi = np.nanpercentile(finite, [5.0, 99.85])
    if not np.isfinite(hi - lo) or hi <= lo:
        lo, hi = float(np.nanmin(finite)), float(np.nanmax(finite))
    scaled = np.clip((arr - lo) / max(1e-6, hi - lo), 0.0, 1.0)
    scaled = np.arcsinh(scaled * 8.0) / np.arcsinh(8.0)
    return (scaled * 255.0).astype(np.uint8)


# Function: _write_accepted_preview
def _write_accepted_preview(fits_path: Path, jpg_path: Path, wcs_path: Path | None, ra_deg: float, dec_deg: float, label: str) -> Path:
    data = fits.getdata(fits_path)
    gray = _scale_preview(data)
    image = Image.fromarray(gray).convert("RGB")
    draw = ImageDraw.Draw(image)

    try:
        if wcs_path and Path(wcs_path).exists():
            wcs = WCS(fits.getheader(wcs_path, 0))
            x, y = [float(v) for v in wcs.all_world2pix([[ra_deg, dec_deg]], 0)[0]]
            if 0 <= x < image.width and 0 <= y < image.height:
                r = 22
                draw.line((x - r, y, x + r, y), fill=(255, 210, 80), width=2)
                draw.line((x, y - r, x, y + r), fill=(255, 210, 80), width=2)
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=(255, 210, 80), width=2)
    except Exception as e:
        log.debug("  accepted preview WCS overlay skipped for %s: %s", fits_path.name, e)

    draw.text((18, 18), label, fill=(255, 255, 255))
    jpg_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(jpg_path, quality=92)
    return jpg_path


# Function: _publish_accepted_products
def _publish_accepted_products(
    product_path: Path,
    wcs_path: Path | None,
    target_name: str,
    ra_deg: float,
    dec_deg: float,
    result: dict,
    row: dict,
    session_started_utc: str,
) -> tuple[Path | None, Path | None]:
    dest_dir = _accepted_products_dir(session_started_utc)
    safe = _safe_name(target_name)
    is_stack = _is_stacked_product(product_path, row)
    suffix = "stack" if is_stack else "single"
    stamp = _parse_iso_utc(row.get("last_obs_utc")) or datetime.now(timezone.utc)
    base = f"{safe}_{stamp.strftime('%Y%m%dT%H%M%S')}_accepted_solved_{suffix}"
    dest_fits = dest_dir / f"{base}.fits"
    dest_jpg = dest_dir / f"{base}.jpg"

    try:
        copied_fits = _copy_accepted_fits(product_path, dest_fits, result, row)
        copied_wcs = _copy_wcs_sidecar(wcs_path, copied_fits)
        if not is_stack and not PUBLISH_SINGLE_FRAME_PREVIEWS:
            log.info("  accepted single-frame FITS written for %s; JPEG preview skipped", target_name)
            return copied_fits, None
        label = f"{target_name} TG={float(result.get('mag', 0.0)):.3f} SNR={float(result.get('target_snr', 0.0)):.1f}"
        copied_jpg = _write_accepted_preview(copied_fits, dest_jpg, copied_wcs, ra_deg, dec_deg, label)
        log.info("  accepted products written for %s: %s / %s", target_name, copied_fits.name, copied_jpg.name)
        return copied_fits, copied_jpg
    except Exception as e:
        log.warning("  accepted product publish failed for %s: %s", target_name, e)
        return None, None


# Function: _load_frame_meta
def _load_frame_meta(fpath: Path) -> dict | None:
    try:
        header = fits.getheader(fpath, 0)
    except Exception as e:
        log.error("  Corrupt or invalid FITS: %s (%s)", fpath.name, e)
        return None

    target_name, date_obs, ra_deg, dec_deg = _parse_header(fpath, header)
    obs_dt = _parse_iso_utc(date_obs)
    if obs_dt is None:
        try:
            obs_dt = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc)
        except Exception:
            obs_dt = datetime.now(timezone.utc)
        date_obs = obs_dt.isoformat().replace("+00:00", "Z")

    return {
        "path": fpath,
        "target_name": target_name,
        "date_obs": date_obs,
        "obs_dt": obs_dt,
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
    }


# Function: _build_target_groups
def _build_target_groups(fits_files: list[Path]) -> list[dict]:
    metas = []
    for fpath in sorted(fits_files):
        meta = _load_frame_meta(fpath)
        if meta:
            metas.append(meta)

    metas.sort(key=lambda m: (m["obs_dt"], m["path"].name))

    groups = []
    current = None
    for meta in metas:
        if current:
            same_target = meta["target_name"] == current["target_name"]
            gap_s = (meta["obs_dt"] - current["last_obs_dt"]).total_seconds()
            if same_target and gap_s <= STACK_GROUP_GAP_SEC:
                current["items"].append(meta)
                current["last_obs_dt"] = meta["obs_dt"]
                continue

        current = {
            "target_name": meta["target_name"],
            "items": [meta],
            "last_obs_dt": meta["obs_dt"],
        }
        groups.append(current)

    return groups


# Function: _stack_output_path
def _stack_output_path(target_name: str, obs_dt: datetime, n_frames: int) -> Path:
    PROCESS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = obs_dt.strftime("%Y%m%dT%H%M%S")
    safe_name = _safe_name(target_name)
    return PROCESS_DIR / f"{safe_name}_{stamp}_STACK_{n_frames}x.fits"


# Function: _stack_subset
def _stack_subset(paths: list[Path], limit: int = MAX_STACK_FRAMES) -> list[Path]:
    if len(paths) <= limit:
        return list(paths)
    if limit <= 1:
        return [paths[-1]]

    step = (len(paths) - 1) / float(limit - 1)
    picks = []
    seen = set()
    for idx in range(limit):
        chosen = paths[int(round(idx * step))]
        key = str(chosen)
        if key in seen:
            continue
        seen.add(key)
        picks.append(chosen)
    return picks


# Estimate a robust background level and sigma from finite image pixels.
# Function: _background_stats
def _background_stats(data: np.ndarray) -> tuple[float, float]:
    finite = np.isfinite(data)
    vals = data[finite]
    if vals.size == 0:
        return 0.0, 1.0
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    sigma = 1.4826 * mad if mad > 0 else float(np.std(vals))
    return med, max(sigma, 1e-6)


# Detect compact bright-source centroids for stack alignment.
# Function: _source_centroids
def _source_centroids(data: np.ndarray, max_sources: int = 200) -> np.ndarray:
    med, sigma = _background_stats(data)
    finite = np.isfinite(data)
    vals = data[finite]
    if vals.size == 0:
        return np.empty((0, 2), dtype=np.float32)

    threshold = max(med + 6.0 * sigma, float(np.percentile(vals, 99.85)))
    maxima = ndimage.maximum_filter(data, size=9)
    peaks = np.argwhere(finite & (data == maxima) & (data > threshold))
    peaks = sorted(peaks, key=lambda yx: data[tuple(yx)], reverse=True)

    height, width = data.shape
    centroids: list[tuple[float, float]] = []
    used: list[tuple[int, int]] = []

    for y, x in peaks:
        if y < 8 or x < 8 or y >= height - 8 or x >= width - 8:
            continue
        if any(abs(y - uy) < 10 and abs(x - ux) < 10 for uy, ux in used):
            continue

        cutout = np.clip(data[y - 4 : y + 5, x - 4 : x + 5] - med, 0.0, None)
        flux = float(cutout.sum())
        if flux <= 0:
            continue

        yy, xx = np.indices(cutout.shape)
        cy = float((yy * cutout).sum() / flux + y - 4)
        cx = float((xx * cutout).sum() / flux + x - 4)
        centroids.append((cy, cx))
        used.append((int(y), int(x)))

        if len(centroids) >= max_sources:
            break

    return np.array(centroids, dtype=np.float32)


# Function: _shape_metrics_from_header
def _shape_metrics_from_header(header) -> StarShapeMetrics | None:
    try:
        sources = int(header.get("STARSRC"))
    except Exception:
        return None
    try:
        median_elongation = header.get("STARELON")
        median_major = header.get("STARMED")
        p90_major = header.get("STARLEN")
        return StarShapeMetrics(
            sources=sources,
            median_elongation=float(median_elongation) if median_elongation is not None else None,
            median_major_axis_px=float(median_major) if median_major is not None else None,
            p90_major_axis_px=float(p90_major) if p90_major is not None else None,
            error=str(header.get("STARQERR", "")).strip(),
        )
    except Exception:
        return None


# Function: _shape_qc_failure
def _shape_qc_failure(path: Path) -> str | None:
    if not STACK_SHAPE_QC_ENABLED:
        return None
    try:
        with fits.open(path, mode="update") as hdul:
            header = hdul[0].header
            metrics = _shape_metrics_from_header(header)
            if metrics is None:
                metrics = measure_star_shape(hdul[0].data)
                metrics.write_header(header)
                hdul.flush()
            return metrics.acceptance_error(
                max_elongation=MAX_STAR_ELONGATION,
                max_major_axis_px=MAX_STAR_TRAIL_PX,
                min_sources=MIN_STAR_SHAPE_SOURCES,
            )
    except Exception as exc:
        return f"star_shape_qc_error:{exc}"


# Estimate image shift from matched star centroids and reject noisy matches.
# Function: _star_shift
def _star_shift(reference: np.ndarray, moving: np.ndarray, max_shift_px: float = 250.0) -> tuple[float, float] | None:
    ref_points = _source_centroids(reference)
    mov_points = _source_centroids(moving)
    if len(ref_points) < 8 or len(mov_points) < 8:
        return None

    tree = cKDTree(ref_points)
    distances, indices = tree.query(mov_points, distance_upper_bound=max_shift_px)
    ok = np.isfinite(distances) & (indices < len(ref_points))
    if int(np.count_nonzero(ok)) < 8:
        return None

    shifts = ref_points[indices[ok]] - mov_points[ok]
    median_shift = np.median(shifts, axis=0)
    residual = np.hypot(*(shifts - median_shift).T)
    if float(np.median(residual)) > 2.0:
        return None

    shift_y, shift_x = float(median_shift[0]), float(median_shift[1])
    if abs(shift_y) > max_shift_px or abs(shift_x) > max_shift_px:
        return None

    return shift_y, shift_x


# Use astroalign's asterism matching when translational shift alignment is not enough.
# Function: _astroalign_frame
def _astroalign_frame(reference: np.ndarray, moving: np.ndarray) -> tuple[np.ndarray, dict] | None:
    if astroalign is None:
        return None

    try:
        fill = float(np.median(moving[np.isfinite(moving)]))
        registered, footprint = astroalign.register(
            moving.astype(np.float32, copy=False),
            reference.astype(np.float32, copy=False),
            fill_value=fill,
        )
    except Exception as exc:
        log.debug("  astroalign fallback unavailable for frame: %s", exc)
        return None

    invalid_fraction = 0.0
    if footprint is not None:
        invalid_fraction = float(np.count_nonzero(footprint)) / float(footprint.size)
    if invalid_fraction > 0.60:
        log.warning("  astroalign fallback rejected: %.0f%% invalid footprint", invalid_fraction * 100.0)
        return None

    return registered.astype(np.float32), {
        "method": "ASTROALIGN",
        "invalid_fraction": invalid_fraction,
    }


# Prefer cheap shift alignment, but fall back to astroalign for rotated/doubled fields.
# Function: _align_stack_frame
def _align_stack_frame(
    reference: np.ndarray,
    ref_work: np.ndarray,
    moving: np.ndarray,
    name: str,
) -> tuple[np.ndarray, tuple[float, float], str] | None:
    work = moving - np.median(moving)
    star_shift = _star_shift(reference, moving)
    shift_y = shift_x = None

    try:
        shift_yx, _, _ = phase_cross_correlation(ref_work, work, upsample_factor=10)
        shift_y, shift_x = float(shift_yx[0]), float(shift_yx[1])
    except Exception as exc:
        if star_shift is None:
            astro = _astroalign_frame(reference, moving)
            if astro:
                return astro[0], (0.0, 0.0), astro[1]["method"]
            log.warning("  stack align failed for %s: %s", name, exc)
            return None
        shift_y, shift_x = star_shift

    if star_shift is not None:
        star_y, star_x = star_shift
        if shift_y is not None and shift_x is not None and max(abs(star_y - shift_y), abs(star_x - shift_x)) > 5.0:
            log.warning(
                "  stack phase shift overridden for %s: phase dy=%.1f dx=%.1f, stars dy=%.1f dx=%.1f",
                name,
                shift_y,
                shift_x,
                star_y,
                star_x,
            )
        shift_y, shift_x = star_y, star_x

    if abs(shift_y) > 250 or abs(shift_x) > 250:
        astro = _astroalign_frame(reference, moving)
        if astro:
            log.info(
                "  astroalign fallback accepted for %s after excessive shift dy=%.1f dx=%.1f",
                name,
                shift_y,
                shift_x,
            )
            return astro[0], (0.0, 0.0), astro[1]["method"]
        log.warning("  stack align rejected for %s: excessive shift dy=%.1f dx=%.1f", name, shift_y, shift_x)
        return None

    fill = float(np.median(moving))
    aligned_arr = ndi_shift(moving, shift=(shift_y, shift_x), order=1, mode="constant", cval=fill)
    return aligned_arr.astype(np.float32), (shift_y, shift_x), "SHIFT"


# Function: _median_stack
def _median_stack(calibrated_paths: list[Path], target_name: str, obs_dt: datetime) -> Path | None:
    if len(calibrated_paths) < 2:
        return None

    stack_paths = _stack_subset(calibrated_paths, MAX_STACK_FRAMES)
    if len(stack_paths) < len(calibrated_paths):
        log.info(
            "  stack input capped for %s: using %d/%d frame(s) to control memory",
            target_name,
            len(stack_paths),
            len(calibrated_paths),
        )

    arrays = []
    header = None
    exptimes = []
    source_names = []
    for path in stack_paths:
        try:
            with fits.open(path) as hdul:
                arrays.append(hdul[0].data.astype(np.float32))
                source_names.append(path.name)
                if header is None:
                    header = hdul[0].header.copy()
                exptime = hdul[0].header.get("EXPTIME")
                if exptime is not None:
                    exptimes.append(float(exptime))
        except Exception as e:
            log.warning("  stack load failed for %s: %s", path.name, e)

    if len(arrays) < 2 or header is None:
        return None

    kept = [(arr, name) for arr, name in zip(arrays, source_names) if arr.shape == arrays[0].shape]
    if len(kept) < 2:
        return None

    reference = kept[0][0]
    ref_work = reference - np.median(reference)

    aligned = [reference]
    aligned_names = [kept[0][1]]
    shifts = [(0.0, 0.0)]
    align_methods = Counter({"REF": 1})

    for arr, name in kept[1:]:
        aligned_result = _align_stack_frame(reference, ref_work, arr, name)
        if aligned_result is None:
            continue
        aligned_arr, shift_yx, method = aligned_result
        aligned.append(aligned_arr)
        aligned_names.append(name)
        shifts.append(shift_yx)
        align_methods[method] += 1

    if len(aligned) < 2:
        log.warning("  stack alignment kept fewer than 2 usable frames for %s", target_name)
        return None

    # A plain median suppresses drifting stars in sparse alt/az bursts; mean preserves the signal better.
    # Preserve signed float data; clipping here destroys the calibrated background model.
    stacked = np.mean(np.stack(aligned, axis=0), axis=0)
    stacked = stacked.astype(np.float32)

    header["OBJECT"] = target_name
    header["NCOMBINE"] = len(aligned)
    header["STACKED"] = True
    header["ALIGNMTH"] = "+".join(f"{k}:{v}" for k, v in sorted(align_methods.items()))[:68]
    header["ALIGNSUC"] = len(aligned)
    header["ALIGNREF"] = aligned_names[0][:68]
    header["BUNIT"] = "ADU-DARKSUB"
    if exptimes:
        usable_exptimes = exptimes[:len(aligned)]
        header["TOTEXP"] = round(sum(usable_exptimes), 3)
        header["EXPTIME"] = round(sum(usable_exptimes), 3)
    if STACK_SHAPE_QC_ENABLED:
        measure_star_shape(stacked).write_header(header)

    out_path = _stack_output_path(target_name, obs_dt, len(aligned))
    fits.PrimaryHDU(data=stacked, header=header).writeto(out_path, overwrite=True)

    median_abs_shift = float(np.median([max(abs(dy), abs(dx)) for dy, dx in shifts])) if shifts else 0.0
    log.info("  aligned stack for %s: %d/%d frame(s) kept, median |shift|=%.2f px -> %s", target_name, len(aligned), len(kept), median_abs_shift, out_path.name)
    return out_path
# Function: _archive_group
def _archive_group(group_items: list[dict]):
    for item in group_items:
        _archive_frame(item["path"])


# Function: _related_products
def _related_products(path: Path) -> list[Path]:
    path = Path(path)
    stem = path.stem
    products = [path]
    products.extend(path.with_suffix(suffix) for suffix in (
        ".wcs",
        ".axy",
        ".corr",
        ".match",
        ".rdls",
        ".solved",
        ".new",
    ))
    products.append(path.with_name(f"{stem}-indx.xyls"))
    return products


# Function: _archive_paths
def _archive_paths(paths: list[Path]):
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    seen = set()
    for path in paths:
        if not path:
            continue
        for candidate in _related_products(Path(path)):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                if candidate.exists():
                    shutil.move(str(candidate), str(ARCHIVE_DIR / candidate.name))
            except Exception as e:
                log.warning("  Archive failed for %s: %s", candidate.name, e)


# Function: _archive_failed_group
def _archive_failed_group(group_items: list[dict], calibrated_paths: list[Path], stack_path: Path | None):
    raw_paths = [item["path"] for item in group_items]
    transient_paths = raw_paths + list(calibrated_paths)
    if stack_path:
        transient_paths.append(stack_path)
    _archive_paths(transient_paths)


# Function: _purge_paths
def _purge_paths(paths: list[Path]):
    seen = set()
    for path in paths:
        if not path:
            continue
        path = Path(path)
        for candidate in _related_products(path):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                if candidate.exists():
                    candidate.unlink()
            except Exception as e:
                log.warning("  Cleanup failed for %s: %s", candidate.name, e)


# Function: _cleanup_completed_group
def _cleanup_completed_group(group_items: list[dict], calibrated_paths: list[Path], stack_path: Path | None):
    raw_paths = [item["path"] for item in group_items]
    transient_paths = raw_paths + list(calibrated_paths)
    if stack_path:
        transient_paths.append(stack_path)
    _purge_paths(transient_paths)


# Function: _cleanup_intermediates
def _cleanup_intermediates(calibrated_paths: list[Path], stack_path: Path | None):
    transient_paths = list(calibrated_paths)
    if stack_path:
        transient_paths.append(stack_path)
    _purge_paths(transient_paths)


# Function: _clear_unclosed_success
def _clear_unclosed_success(entry: dict):
    if not entry.get("last_obs_utc"):
        entry["last_success"] = None


# Function: process_buffer
def process_buffer():
    with _process_lock() as lock_acquired:
        if not lock_acquired:
            log.info("Accountant already running; skipping duplicate postflight sweep.")
            return

        session_started_utc = datetime.now(timezone.utc).isoformat()
        log.info("Accountant: auditing local buffer...")

        if not LOCAL_BUFFER.exists():
            log.info("Local buffer empty or missing, nothing to do.")
            return

        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        ensure_calibration_dirs()
        CALIBRATED_BUFFER.mkdir(parents=True, exist_ok=True)
        PROCESS_DIR.mkdir(parents=True, exist_ok=True)
        ledger = load_ledger()
        fits_files = sorted(LOCAL_BUFFER.glob("*.fit")) + sorted(LOCAL_BUFFER.glob("*.fits"))

        if not fits_files:
            log.info("No FITS files in buffer.")
            return

        processed = successes = 0
        session_rows = []
        mag_lookup = {}

        if VSX_CATALOG_FILE.exists():
            try:
                vsx_data = json.load(open(VSX_CATALOG_FILE))
                vsx_stars = vsx_data.get("stars", {})
                for name, star in vsx_stars.items():
                    mid = star.get("mag_mid")
                    if mid is not None:
                        try:
                            mag_lookup[name] = float(mid)
                        except (TypeError, ValueError):
                            pass
                log.info("VSX mag_mid loaded: %d targets", len(mag_lookup))
            except Exception as e:
                log.warning("VSX mag lookup failed: %s", e)

        if PLAN_FILE.exists():
            try:
                plan_data = json.load(open(PLAN_FILE))
                added = 0
                for t in plan_data.get("targets", []):
                    name = t.get("name", "")
                    if name and name not in mag_lookup:
                        mag = t.get("mag_max")
                        if mag is not None:
                            try:
                                mag_lookup[name] = float(mag)
                                added += 1
                            except (TypeError, ValueError):
                                pass
                log.info("Plan mag_max added: %d additional targets", added)
            except Exception as e:
                log.warning("Plan mag lookup failed: %s", e)

        for name, entry in ledger.items():
            if name not in mag_lookup:
                last = entry.get("last_mag")
                if last is not None:
                    try:
                        mag_lookup[name] = float(last)
                    except (TypeError, ValueError):
                        pass

        groups = _build_target_groups(fits_files)

        for group in groups:
            key = group["target_name"]
            items = group["items"]
            raw_count = len(items)
            log.info("Processing group: %s (%d raw frame(s))", key, raw_count)
            row = {
                "target_name": key,
                "raw_frames": raw_count,
                "group_started_utc": datetime.now(timezone.utc).isoformat(),
                "observation_success": False,
                "failure_category": None,
                "failure_detail": None,
            }

            if key not in ledger:
                ledger[key] = _blank_entry()

            ref = next((item for item in items if item["ra_deg"] is not None and item["dec_deg"] is not None), items[0])
            date_obs = ref["date_obs"]
            ra_deg = ref["ra_deg"]
            dec_deg = ref["dec_deg"]
            ref_header = fits.getheader(ref["path"], 0)
            req_exp_ms = ref_header.get("EXPMS")
            if req_exp_ms in (None, "", "UNKNOWN"):
                exptime = ref_header.get("EXPTIME")
                if exptime not in (None, "", "UNKNOWN"):
                    req_exp_ms = int(round(float(exptime) * 1000.0))
            else:
                req_exp_ms = int(round(float(req_exp_ms)))
            req_gain = ref_header.get("GAIN")
            if req_gain not in (None, "", "UNKNOWN"):
                req_gain = int(round(float(req_gain)))
            req_temp_c = ref_header.get("CCD-TEMP")
            if req_temp_c not in (None, "", "UNKNOWN"):
                req_temp_c = float(req_temp_c)
            req_filter = str(ref_header.get("FILTER", "TG")).strip() or "TG"
            req_scope_id = str(ref_header.get("SCOPEID", "")).strip() or None
            req_scope_name = str(ref_header.get("SCOPENAM", "")).strip() or req_scope_id
            row["exp_ms"] = req_exp_ms
            row["gain"] = req_gain
            row["ccd_temp_c"] = req_temp_c
            row["filter"] = req_filter
            row["scope_id"] = req_scope_id
            row["scope_name"] = req_scope_name
            row["capture_file"] = items[-1]["path"].name

            if date_obs and not str(date_obs).endswith("Z"):
                date_obs = str(date_obs) + "Z"

            ledger[key]["last_capture_utc"] = date_obs
            ledger[key]["last_capture_path"] = items[-1]["path"].name
            ledger[key]["required_bias_gain"] = req_gain
            ledger[key]["required_flat_filter"] = req_filter
            ledger[key]["required_flat_scope_id"] = req_scope_id
            ledger[key]["required_flat_scope_name"] = req_scope_name
            ledger[key]["last_scope_id"] = req_scope_id
            ledger[key]["last_scope_name"] = req_scope_name

            if ra_deg is None or dec_deg is None:
                log.error("  %s group has no usable coordinate hints, cannot solve.", key)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "FAILED_NO_WCS"
                _clear_unclosed_success(ledger[key])
                row["failure_category"] = "NO_COORD_HINTS"
                row["failure_detail"] = "group has no usable coordinate hints"
                row["ledger_status"] = ledger[key].get("status")
                session_rows.append(row)
                _archive_group(items)
                save_ledger(ledger)
                save_missing_calibrations(ledger)
                processed += raw_count
                continue

            calibrated_paths = []
            dark_keys = []
            for item in items:
                dark = dark_calibrator.calibrate(item["path"])
                if dark.get("status") == "ok":
                    calibrated_paths.append(Path(dark["calibrated_path"]))
                    dark_key = dark.get("dark_key")
                    if dark_key:
                        dark_keys.append(dark_key)
                else:
                    log.warning("  %s dark calibration failed for %s: %s", key, item["path"].name, dark.get("error"))

            if not calibrated_paths:
                log.warning("  %s has no dark-calibrated science frames in this group", key)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "FAILED_NO_DARK"
                ledger[key]["required_dark_exp_ms"] = req_exp_ms
                ledger[key]["required_dark_gain"] = req_gain
                ledger[key]["required_dark_temp_c"] = req_temp_c
                ledger[key]["last_calibration_state"] = "NO_USABLE_DARK"
                _clear_unclosed_success(ledger[key])
                row["failure_category"] = "NO_DARK"
                row["failure_detail"] = "no dark-calibrated science frames in this group"
                row["ledger_status"] = ledger[key].get("status")
                row["required_dark_exp_ms"] = req_exp_ms
                row["required_dark_gain"] = req_gain
                row["required_dark_temp_c"] = req_temp_c
                session_rows.append(row)
                _archive_group(items)
                save_ledger(ledger)
                save_missing_calibrations(ledger)
                processed += raw_count
                continue

            raw_candidate_paths = []
            stack_path = _median_stack(calibrated_paths, key, ref["obs_dt"])
            if REQUIRE_STACKED_PRODUCTS and len(calibrated_paths) >= 2 and not stack_path:
                log.error("  %s rejected: stacked product required but stack creation failed", key)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "FAILED_STACK_REQUIRED"
                ledger[key]["last_calibration_state"] = "STACK_REQUIRED_FAILED"
                _clear_unclosed_success(ledger[key])
                row["failure_category"] = "STACK_REQUIRED"
                row["failure_detail"] = "stacked product required but stack creation failed"
                row["ledger_status"] = ledger[key].get("status")
                row["calibration_state"] = ledger[key].get("last_calibration_state")
                session_rows.append(row)
                _archive_failed_group(items, calibrated_paths, stack_path)
                save_ledger(ledger)
                save_missing_calibrations(ledger)
                processed += raw_count
                continue
            if stack_path:
                raw_candidate_paths.append((stack_path, f"DARKSUB_STACK_{len(calibrated_paths)}"))
            if not REQUIRE_STACKED_PRODUCTS or len(calibrated_paths) < 2:
                raw_candidate_paths.extend((path, "DARKSUB_SINGLE") for path in reversed(calibrated_paths))

            candidate_paths = []
            shape_rejects = []
            for candidate_path, candidate_state in raw_candidate_paths:
                shape_error = _shape_qc_failure(candidate_path)
                if shape_error:
                    shape_rejects.append(f"{candidate_path.name}:{shape_error}")
                    log.warning("  %s shape QC rejected %s: %s", key, candidate_path.name, shape_error)
                    continue
                candidate_paths.append((candidate_path, candidate_state))

            if not candidate_paths:
                detail = "; ".join(shape_rejects[:4]) or "no shape-usable candidates"
                log.error("  %s rejected: no untrailed stack/single candidates", key)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "FAILED_QC_TRAILED"
                ledger[key]["last_calibration_state"] = "FAILED_STAR_SHAPE_QC"
                _clear_unclosed_success(ledger[key])
                row["failure_category"] = "TRAILING"
                row["failure_detail"] = detail
                row["ledger_status"] = ledger[key].get("status")
                row["calibration_state"] = ledger[key].get("last_calibration_state")
                session_rows.append(row)
                _archive_failed_group(items, calibrated_paths, stack_path)
                save_ledger(ledger)
                save_missing_calibrations(ledger)
                processed += raw_count
                continue

            total_solve_candidates = len(candidate_paths)
            if total_solve_candidates > MAX_PLATE_SOLVE_CANDIDATES:
                candidate_paths = candidate_paths[:MAX_PLATE_SOLVE_CANDIDATES]
                log.warning(
                    "  %s plate-solve candidates capped: using %d/%d candidate(s)",
                    key,
                    len(candidate_paths),
                    total_solve_candidates,
                )

            solve = None
            solve_path = None
            solve_wcs_path = None
            cal_state = "DARKSUB_SINGLE"
            for candidate_path, candidate_state in candidate_paths:
                log.info("  %s plate-solve candidate: %s", key, candidate_path.name)
                solve = _analyst.solve_frame(str(candidate_path))
                if solve.get("ok"):
                    solve_path = candidate_path
                    solve_wcs_path = Path(solve["wcs_path"])
                    cal_state = candidate_state
                    break

            if not solve or not solve.get("ok"):
                log.error("  %s solve failed for stacked/single candidates", key)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "FAILED_NO_WCS"
                ledger[key]["last_calibration_state"] = "STACK_FAILED_NO_WCS"
                _clear_unclosed_success(ledger[key])
                row["failure_category"] = "NO_WCS"
                row["failure_detail"] = "solve failed for stacked/single candidates"
                row["ledger_status"] = ledger[key].get("status")
                row["calibration_state"] = ledger[key].get("last_calibration_state")
                session_rows.append(row)
                _archive_failed_group(items, calibrated_paths, stack_path)
                save_ledger(ledger)
                save_missing_calibrations(ledger)
                processed += raw_count
                continue

            # If the aligned stack would not solve but an individual frame did, reuse the
            # single-frame WCS on the stack for photometry. This preserves the stacked SNR
            # when the field geometry is stable but the stack confuses solve-field.
            if (
                stack_path
                and solve_path
                and solve_wcs_path
                and solve_path != stack_path
                and solve_wcs_path.exists()
            ):
                log.info(
                    "  stack solve fallback for %s: reusing WCS from %s on %s",
                    key,
                    solve_path.name,
                    stack_path.name,
                )
                copied_wcs = _copy_wcs_sidecar(solve_wcs_path, stack_path)
                solve_path = stack_path
                if copied_wcs:
                    solve_wcs_path = copied_wcs
                cal_state = f"{cal_state}+STACK_WCS_FALLBACK"

            target_mag = mag_lookup.get(key)
            result = _engine.calibrate(
                Path(solve_path),
                ra_deg,
                dec_deg,
                key,
                target_mag=target_mag,
                wcs_path=solve_wcs_path,
                solve_result=solve,
            )

            status = result.get("status", "error")
            error = result.get("error", "")
            observation_success = False

            if status == "ok":
                snr = result.get("target_snr", 0.0)

                if snr >= MIN_SNR:
                    log.info(
                        "  OK %s  TG=%.3f +/- %.3f  SNR=%.1f  comps=%d/%d  rej=%d  mode=%s",
                        key,
                        result.get("mag", 0),
                        result.get("err", 0),
                        snr,
                        result.get("n_comps", 0),
                        result.get("n_comps_raw", result.get("n_comps", 0)),
                        result.get("n_comps_rejected", 0),
                        cal_state,
                    )

                    dark_key_value = dark_keys[0] if len(set(dark_keys)) == 1 else f"{len(set(dark_keys))}_dark_keys"
                    ledger[key].update({
                        "status": "OBSERVED",
                        "last_success": date_obs,
                        "last_capture_utc": date_obs,
                        "last_capture_path": items[-1]["path"].name,
                        "last_mag": result.get("mag"),
                        "last_err": result.get("err"),
                        "last_snr": round(snr, 1),
                        "last_filter": result.get("filter"),
                        "last_photometric_system": result.get("photometric_system", "TG"),
                        "last_measurement_kind": result.get("measurement_kind", "raw_bayer_green_untransformed"),
                        "last_comps": result.get("n_comps"),
                        "last_comps_raw": result.get("n_comps_raw", result.get("n_comps")),
                        "last_comps_rejected": result.get("n_comps_rejected", 0),
                        "last_comp_rows": result.get("comp_rows"),
                        "last_zp": result.get("zero_point"),
                        "last_zp_std": result.get("zp_std"),
                        "last_target_inst_mag": result.get("target_inst_mag"),
                        "last_target_inst_err": result.get("target_inst_err"),
                        "last_obs_utc": date_obs,
                        "last_peak_adu": result.get("peak_adu"),
                        "last_solved_ra": result.get("solved_ra_deg"),
                        "last_solved_dec": result.get("solved_dec_deg"),
                        "last_dark_key": dark_key_value,
                        "last_calibration_state": cal_state,
                    })
                    successes += 1
                    observation_success = True
                    row.update({
                        "observation_success": True,
                        "ledger_status": ledger[key].get("status"),
                        "calibration_state": cal_state,
                        "mag": result.get("mag"),
                        "err": result.get("err"),
                        "target_snr": result.get("target_snr"),
                        "n_comps": result.get("n_comps"),
                        "n_comps_raw": result.get("n_comps_raw", result.get("n_comps")),
                        "n_comps_rejected": result.get("n_comps_rejected", 0),
                        "filter": result.get("filter"),
                        "photometric_system": result.get("photometric_system", "TG"),
                        "measurement_kind": result.get("measurement_kind", "raw_bayer_green_untransformed"),
                        "target_inst_mag": result.get("target_inst_mag"),
                        "target_inst_err": result.get("target_inst_err"),
                        "zero_point": result.get("zero_point"),
                        "zp_std": result.get("zp_std"),
                        "peak_adu": result.get("peak_adu"),
                        "last_obs_utc": date_obs,
                        "comp_rows": result.get("comp_rows"),
                        "solved_ra_deg": result.get("solved_ra_deg"),
                        "solved_dec_deg": result.get("solved_dec_deg"),
                    })
                    accepted_fits, accepted_jpg = _publish_accepted_products(
                        Path(solve_path),
                        solve_wcs_path,
                        key,
                        ra_deg,
                        dec_deg,
                        result,
                        row,
                        session_started_utc,
                    )
                    if accepted_fits:
                        ledger[key]["last_accepted_product"] = str(accepted_fits)
                        row["accepted_product"] = str(accepted_fits)
                    if accepted_jpg:
                        ledger[key]["last_accepted_preview"] = str(accepted_jpg)
                        row["accepted_preview"] = str(accepted_jpg)
                else:
                    log.warning("  %s poor SNR=%.1f (min %.1f)", key, snr, MIN_SNR)
                    if ledger[key].get("status") != "OBSERVED":
                        ledger[key]["status"] = "FAILED_QC_LOW_SNR"
                    ledger[key]["last_calibration_state"] = cal_state
                    _clear_unclosed_success(ledger[key])
                    row["failure_category"] = "LOW_SNR"
                    row["failure_detail"] = f"poor SNR={snr:.1f} (min {MIN_SNR:.1f})"

            elif status == "fail":
                err_l = error.lower()

                if "snr_too_low" in err_l:
                    log.warning("  %s rejected for low SNR", key)
                    if ledger[key].get("status") != "OBSERVED":
                        ledger[key]["status"] = "FAILED_QC_LOW_SNR"
                elif "saturated" in err_l:
                    log.warning("  %s saturated (peak_adu=%s)", key, result.get("peak_adu"))
                    if ledger[key].get("status") != "OBSERVED":
                        ledger[key]["status"] = "FAILED_SATURATED"
                elif "no_wcs" in err_l or "wcs" in err_l:
                    log.error("  %s has no solved WCS", key)
                    if ledger[key].get("status") != "OBSERVED":
                        ledger[key]["status"] = "FAILED_NO_WCS"
                elif "flux" in err_l or "out_of_frame" in err_l or "insufficient_" in err_l:
                    log.warning("  %s failed QC: %s", key, error)
                    if ledger[key].get("status") != "OBSERVED":
                        ledger[key]["status"] = "FAILED_QC"
                else:
                    log.warning("  %s failed: %s", key, error)
                    if ledger[key].get("status") != "OBSERVED":
                        ledger[key]["status"] = "FAILED_QC"

                ledger[key]["last_comps_raw"] = result.get("n_comps_raw")
                ledger[key]["last_comps_rejected"] = result.get("n_comps_rejected")
                ledger[key]["last_photometric_system"] = result.get("photometric_system", "TG")
                ledger[key]["last_measurement_kind"] = result.get("measurement_kind", "raw_bayer_green_untransformed")
                ledger[key]["last_calibration_state"] = cal_state
                _clear_unclosed_success(ledger[key])
                row["failure_category"] = _classify_failure(error)
                row["failure_detail"] = error
                row["target_snr"] = result.get("target_snr")
                row["n_comps_raw"] = result.get("n_comps_raw")
                row["n_comps_rejected"] = result.get("n_comps_rejected")
                target_measurement = result.get("target_measurement") or {}
                row["target_measurement"] = target_measurement or None

            else:
                log.error("  %s calibration error: %s", key, error)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "ERROR"
                ledger[key]["last_calibration_state"] = cal_state
                _clear_unclosed_success(ledger[key])
                row["failure_category"] = "CALIBRATION_ERROR"
                row["failure_detail"] = error or "unknown calibration error"

            if observation_success:
                _cleanup_completed_group(items, calibrated_paths, stack_path)
            else:
                log.info("  Archiving failed reduction artifacts for %s", key)
                _archive_failed_group(items, calibrated_paths, stack_path)
            row["ledger_status"] = ledger[key].get("status")
            row["calibration_state"] = ledger[key].get("last_calibration_state")
            session_rows.append(row)
            save_ledger(ledger)
            save_missing_darks(ledger)
            save_missing_calibrations(ledger)
            processed += raw_count

        save_missing_darks(ledger)
        save_missing_calibrations(ledger)
        _write_postflight_report(session_started_utc, processed, successes, session_rows)

        log.info(
            "Audit complete. %d raw frames processed, %d successful observations stamped.",
            processed,
            successes,
        )


if __name__ == "__main__":
    process_buffer()
