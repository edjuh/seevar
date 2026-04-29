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
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
import numpy as np
from scipy.ndimage import shift as ndi_shift
from skimage.registration import phase_cross_correlation

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.postflight.calibration_engine import CalibrationEngine
from core.postflight.master_analyst import MasterAnalyst
from core.postflight.dark_calibrator import dark_calibrator
from core.postflight.calibration_assets import ensure_calibration_dirs, save_missing_calibrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("Accountant")

DATA_DIR = PROJECT_ROOT / "data"
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

_engine = CalibrationEngine()
_analyst = MasterAnalyst()


@contextmanager
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


def load_ledger() -> dict:
    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE, "r") as f:
                data = json.load(f)
                return data.get("entries", {}) if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            log.warning("Ledger unreadable, starting fresh.")
    return {}


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



def _temp_bin_for_requirement(temp_c):
    if temp_c in (None, "", "UNKNOWN"):
        return None
    try:
        return int(round(float(temp_c) / 2.0) * 2.0)
    except Exception:
        return None


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
    }


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


def _archive_frame(fpath: Path):
    try:
        shutil.move(str(fpath), str(ARCHIVE_DIR / fpath.name))
        sidecar = fpath.with_suffix(".wcs")
        if sidecar.exists():
            shutil.move(str(sidecar), str(ARCHIVE_DIR / sidecar.name))
    except Exception as e:
        log.error("  Archive failed for %s: %s", fpath.name, e)


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


def _safe_name(name: str) -> str:
    return str(name or "UNKNOWN").replace(" ", "_").replace("/", "-")


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


def _stack_output_path(target_name: str, obs_dt: datetime, n_frames: int) -> Path:
    PROCESS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = obs_dt.strftime("%Y%m%dT%H%M%S")
    safe_name = _safe_name(target_name)
    return PROCESS_DIR / f"{safe_name}_{stamp}_STACK_{n_frames}x.fits"


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

    for arr, name in kept[1:]:
        work = arr - np.median(arr)
        try:
            shift_yx, _, _ = phase_cross_correlation(ref_work, work, upsample_factor=10)
            shift_y, shift_x = float(shift_yx[0]), float(shift_yx[1])
        except Exception as e:
            log.warning("  stack align failed for %s: %s", name, e)
            continue

        if abs(shift_y) > 250 or abs(shift_x) > 250:
            log.warning("  stack align rejected for %s: excessive shift dy=%.1f dx=%.1f", name, shift_y, shift_x)
            continue

        aligned_arr = ndi_shift(arr, shift=(shift_y, shift_x), order=1, mode="constant", cval=float(np.median(arr)))
        aligned.append(aligned_arr.astype(np.float32))
        aligned_names.append(name)
        shifts.append((shift_y, shift_x))

    if len(aligned) < 2:
        log.warning("  stack alignment kept fewer than 2 usable frames for %s", target_name)
        return None

    # A plain median suppresses drifting stars in sparse alt/az bursts; mean preserves the signal better.
    stacked = np.mean(np.stack(aligned, axis=0), axis=0)
    stacked = np.clip(stacked, 0, 65535).astype(np.uint16)

    header["OBJECT"] = target_name
    header["NCOMBINE"] = len(aligned)
    header["STACKED"] = True
    header["ALIGNMTH"] = "SHIFTMEAN"
    header["ALIGNSUC"] = len(aligned)
    header["ALIGNREF"] = aligned_names[0][:68]
    if exptimes:
        usable_exptimes = exptimes[:len(aligned)]
        header["TOTEXP"] = round(sum(usable_exptimes), 3)
        header["EXPTIME"] = round(sum(usable_exptimes), 3)

    out_path = _stack_output_path(target_name, obs_dt, len(aligned))
    fits.PrimaryHDU(data=stacked, header=header).writeto(out_path, overwrite=True)

    median_abs_shift = float(np.median([max(abs(dy), abs(dx)) for dy, dx in shifts])) if shifts else 0.0
    log.info("  aligned stack for %s: %d/%d frame(s) kept, median |shift|=%.2f px -> %s", target_name, len(aligned), len(kept), median_abs_shift, out_path.name)
    return out_path
def _archive_group(group_items: list[dict]):
    for item in group_items:
        _archive_frame(item["path"])


def _purge_paths(paths: list[Path]):
    seen = set()
    for path in paths:
        if not path:
            continue
        path = Path(path)
        for candidate in (path, path.with_suffix(".wcs")):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                if candidate.exists():
                    candidate.unlink()
            except Exception as e:
                log.warning("  Cleanup failed for %s: %s", candidate.name, e)


def _cleanup_completed_group(group_items: list[dict], calibrated_paths: list[Path], stack_path: Path | None):
    raw_paths = [item["path"] for item in group_items]
    transient_paths = raw_paths + list(calibrated_paths)
    if stack_path:
        transient_paths.append(stack_path)
    _purge_paths(transient_paths)


def _cleanup_intermediates(calibrated_paths: list[Path], stack_path: Path | None):
    transient_paths = list(calibrated_paths)
    if stack_path:
        transient_paths.append(stack_path)
    _purge_paths(transient_paths)


def _clear_unclosed_success(entry: dict):
    if not entry.get("last_obs_utc"):
        entry["last_success"] = None


def process_buffer():
    with _process_lock() as lock_acquired:
        if not lock_acquired:
            log.info("Accountant already running; skipping duplicate postflight sweep.")
            return

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
                _archive_group(items)
                save_ledger(ledger)
                save_missing_calibrations(ledger)
                processed += raw_count
                continue

            candidate_paths = []
            stack_path = _median_stack(calibrated_paths, key, ref["obs_dt"])
            if stack_path:
                candidate_paths.append((stack_path, f"DARKSUB_STACK_{len(calibrated_paths)}"))
            candidate_paths.extend((path, "DARKSUB_SINGLE") for path in reversed(calibrated_paths))

            solve = None
            solve_path = None
            cal_state = "DARKSUB_SINGLE"
            for candidate_path, candidate_state in candidate_paths:
                solve = _analyst.solve_frame(str(candidate_path))
                if solve.get("ok"):
                    solve_path = candidate_path
                    cal_state = candidate_state
                    break

            if not solve or not solve.get("ok"):
                log.error("  %s solve failed for stacked/single candidates", key)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "FAILED_NO_WCS"
                ledger[key]["last_calibration_state"] = "STACK_FAILED_NO_WCS"
                _clear_unclosed_success(ledger[key])
                _cleanup_intermediates(calibrated_paths, stack_path)
                _archive_group(items)
                save_ledger(ledger)
                save_missing_calibrations(ledger)
                processed += raw_count
                continue

            target_mag = mag_lookup.get(key)
            result = _engine.calibrate(
                Path(solve_path),
                ra_deg,
                dec_deg,
                key,
                target_mag=target_mag,
                wcs_path=Path(solve["wcs_path"]),
                solve_result=solve,
            )

            status = result.get("status", "error")
            error = result.get("error", "")

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
                else:
                    log.warning("  %s poor SNR=%.1f (min %.1f)", key, snr, MIN_SNR)
                    if ledger[key].get("status") != "OBSERVED":
                        ledger[key]["status"] = "FAILED_QC_LOW_SNR"
                    ledger[key]["last_calibration_state"] = cal_state
                    _clear_unclosed_success(ledger[key])

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

            else:
                log.error("  %s calibration error: %s", key, error)
                if ledger[key].get("status") != "OBSERVED":
                    ledger[key]["status"] = "ERROR"
                ledger[key]["last_calibration_state"] = cal_state
                _clear_unclosed_success(ledger[key])

            _cleanup_completed_group(items, calibrated_paths, stack_path)
            save_ledger(ledger)
            save_missing_darks(ledger)
            save_missing_calibrations(ledger)
            processed += raw_count

        save_missing_darks(ledger)
        save_missing_calibrations(ledger)

        log.info(
            "Audit complete. %d raw frames processed, %d successful observations stamped.",
            processed,
            successes,
        )


if __name__ == "__main__":
    process_buffer()
