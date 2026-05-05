#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/stage_reports_from_summary.py
Objective: Stage AAVSO/BAA submission files from the latest real-night
           postflight summary JSON written by accountant.py.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from datetime import datetime, timedelta, timezone

from astropy.time import Time
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAIA_CACHE_DIR = PROJECT_ROOT / "data" / "gaia_cache"
VSP_CACHE_DIRS = [
    PROJECT_ROOT / "catalogs" / "reference_stars",
    PROJECT_ROOT / "data" / "reference_stars",
    PROJECT_ROOT / "data" / "comp_stars",
]
INSTRUMENTAL_MAG_ZEROPOINT = 25.0

import sys
sys.path.insert(0, str(PROJECT_ROOT))

from core.postflight.aavso_reporter import (
    AAVSOReporter,
    BAACCDReporter,
    BAAModifiedExtendedReporter,
)
from core.postflight.gaia_resolver import _cache_path
from core.utils.env_loader import load_config


# Choose the newest postflight summary unless the caller pins one explicitly.
def _latest_summary(report_dir: Path) -> Path:
    candidates = sorted(report_dir.glob("postflight_summary_*.json"))
    if not candidates:
        raise FileNotFoundError(f"No postflight summary JSON found in {report_dir}")
    return candidates[-1]


# Parse a stored UTC timestamp into an aware datetime for ledger fallback.
def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# Convert a stamped UTC string into the JD format required by report exporters.
def _to_jd(obs_utc: str) -> float:
    return float(Time(obs_utc).jd)


# Compute target airmass from solved sky position and configured site location.
def _compute_airmass(row: dict) -> str:
    ra_deg = row.get("solved_ra_deg")
    dec_deg = row.get("solved_dec_deg")
    obs_utc = row.get("last_obs_utc")
    if ra_deg in (None, "") or dec_deg in (None, "") or not obs_utc:
        return "na"

    cfg = load_config()
    loc = cfg.get("location", {}) if isinstance(cfg, dict) else {}
    lat = loc.get("lat")
    lon = loc.get("lon")
    elev = loc.get("elevation", 0.0)
    if lat in (None, "") or lon in (None, ""):
        return "na"

    try:
        location = EarthLocation(lat=float(lat) * u.deg, lon=float(lon) * u.deg, height=float(elev) * u.m)
        when = Time(obs_utc)
        target = SkyCoord(ra=float(ra_deg) * u.deg, dec=float(dec_deg) * u.deg, frame="icrs")
        altaz = target.transform_to(AltAz(obstime=when, location=location))
        secz = getattr(altaz, "secz", None)
        if secz is None:
            return "na"
        value = float(secz.value if hasattr(secz, "value") else secz)
        if not (1.0 <= value <= 40.0):
            return "na"
        return round(value, 3)
    except Exception:
        return "na"


# Reuse the same target-name normalization as the chart fetcher cache.
def _clean_target_name(name: str) -> str:
    return str(name or "").lower().replace(" ", "_").replace("-", "_")


# Load VSP chart metadata from local cache first, then the live API.
def _load_vsp_chart(target_name: str) -> dict:
    clean_name = _clean_target_name(target_name)
    for base in VSP_CACHE_DIRS:
        path = base / f"{clean_name}.json"
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict) and data.get("chartid"):
                return data

    import requests

    response = requests.get(
        "https://apps.aavso.org/vsp/api/chart/",
        params={"format": "json", "star": target_name, "fov": 180, "maglimit": 15.0},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# Load the Gaia cache near the solved field center so source_id can be mapped
# back to sky coordinates for VSP crossmatching.
def _load_gaia_cache(row: dict) -> dict:
    ra_deg = row.get("solved_ra_deg")
    dec_deg = row.get("solved_dec_deg")
    if ra_deg in (None, "") or dec_deg in (None, ""):
        return {}
    path = _cache_path(float(ra_deg), float(dec_deg))
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# Convert VSP and Gaia rows into a shared ICRS coordinate space.
def _star_coord(ra_value, dec_value, *, hourangle: bool = False) -> SkyCoord:
    if hourangle:
        return SkyCoord(str(ra_value), str(dec_value), unit=(u.hourangle, u.deg), frame="icrs")
    return SkyCoord(float(ra_value) * u.deg, float(dec_value) * u.deg, frame="icrs")


def _safe_float(value, default: float) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


# Recover chart id and a plausible check-star row by crossmatching retained
# Gaia comparison stars back onto the VSP chart sequence.
def _chart_context(row: dict) -> dict:
    try:
        chart = _load_vsp_chart(row["target_name"])
        chart_id = str(chart.get("chartid", "na")).strip() or "na"
        photometry = chart.get("photometry") or chart.get("comparison_stars") or []
        gaia_cache = _load_gaia_cache(row)
        gaia_rows = {str(star.get("source_id")): star for star in (gaia_cache.get("stars") or []) if isinstance(star, dict)}

        matches = []
        for comp in row.get("comp_rows") or []:
            gaia_row = gaia_rows.get(str(comp.get("source_id")))
            if not gaia_row:
                continue
            try:
                gaia_coord = _star_coord(gaia_row.get("ra"), gaia_row.get("dec"))
            except Exception:
                continue

            best = None
            best_sep = None
            for vsp_star in photometry:
                try:
                    vsp_coord = _star_coord(vsp_star.get("ra"), vsp_star.get("dec"), hourangle=True)
                except Exception:
                    continue
                sep = gaia_coord.separation(vsp_coord).arcsec
                if best_sep is None or sep < best_sep:
                    best_sep = sep
                    best = vsp_star

            if best is not None and best_sep is not None and best_sep <= 5.0:
                matches.append({
                    "comp_row": comp,
                    "vsp_star": best,
                    "sep_arcsec": best_sep,
                    "inst_err": _safe_float(comp.get("inst_err"), 9.99),
                    "snr": _safe_float(comp.get("snr"), 0.0),
                    "v_mag": _safe_float(comp.get("v_mag"), 99.0),
                })

        matches.sort(key=lambda item: (item["inst_err"], -item["snr"], item["v_mag"], item["sep_arcsec"]))
        check = matches[0]["vsp_star"] if matches else None
        check_comp = matches[0]["comp_row"] if matches else None
        return {
            "chart_id": chart_id,
            "check_source_id": str(check_comp.get("source_id")) if isinstance(check_comp, dict) else None,
            "check_name": (check.get("auid") or check.get("label")) if isinstance(check, dict) else "na",
            "check_ref_mag": next((band.get("mag") for band in (check.get("bands") or []) if band.get("band") == "V"), "na") if isinstance(check, dict) else "na",
        }
    except Exception:
        return {"chart_id": "na", "check_source_id": None, "check_name": "na", "check_ref_mag": "na"}


# Compute the reported check-star magnitude against the ensemble excluding the
# check star itself, so KMAG is a real calculated check and not circular.
def _compute_check_mag(comp_rows: list[dict], source_id: str | None) -> str | float:
    if not source_id:
        return "na"

    target_row = None
    others = []
    for row in comp_rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("source_id")) == str(source_id):
            target_row = row
        else:
            others.append(row)

    if target_row is None or len(others) < 2:
        return "na"

    weighted = []
    for row in others:
        try:
            zp = float(row.get("zp"))
            weight = float(row.get("weight"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(zp) or not math.isfinite(weight) or weight <= 0:
            continue
        weighted.append((zp, weight))

    if len(weighted) < 2:
        return "na"

    try:
        inst_mag = float(target_row.get("inst_mag"))
    except (TypeError, ValueError):
        return "na"

    weight_sum = sum(weight for _, weight in weighted)
    if weight_sum <= 0:
        return "na"

    avg_zp = sum(zp * weight for zp, weight in weighted) / weight_sum
    calc_mag = avg_zp + inst_mag - INSTRUMENTAL_MAG_ZEROPOINT
    return round(calc_mag, 3) if math.isfinite(calc_mag) else "na"


# Turn one accepted summary row into the normalized observation payload used by
# the AAVSO and BAA report formatters.
def _observation_from_summary(row: dict) -> dict:
    chart_ctx = _chart_context(row)
    check_mag = _compute_check_mag(row.get("comp_rows") or [], chart_ctx.get("check_source_id"))
    notes = [
        f"MODE={row.get('calibration_state', 'UNKNOWN')}",
        f"COMPS={row.get('n_comps', 0)}/{row.get('n_comps_raw', row.get('n_comps', 0))}",
    ]
    rejected = int(row.get("n_comps_rejected", 0) or 0)
    if rejected:
        notes.append(f"REJ={rejected}")

    return {
        "target": row["target_name"],
        "jd": _to_jd(row["last_obs_utc"]),
        "mag": row["mag"],
        "err": row["err"],
        "filter": row.get("filter", "TG"),
        "trans": "NO",
        "mtype": "STD",
        "comp": "ENSEMBLE",
        "cmag": "na",
        "kname": chart_ctx["check_name"],
        "kmag": check_mag,
        "amass": _compute_airmass(row),
        "group": "na",
        "chart": chart_ctx["chart_id"],
        "notes": " ".join(notes),
        "peak_adu": row.get("peak_adu"),
        "saturation_checked": True,
        "saturated": False,
        "target_inst_mag": row.get("target_inst_mag"),
        "target_inst_err": row.get("target_inst_err"),
        "exp_len": (float(row["exp_ms"]) / 1000.0) if row.get("exp_ms") not in (None, "") else None,
        "file_name": row.get("capture_file") or f"{row['target_name'].replace(' ', '_')}.fits",
        "comp_rows": row.get("comp_rows") or [],
    }


# Pull the latest coherent set of accepted observations from ledger.json when a
# postflight summary is not yet available on the host.
def _accepted_from_ledger(ledger_path: Path) -> list[dict]:
    payload = json.loads(ledger_path.read_text())
    entries = payload.get("entries", payload) if isinstance(payload, dict) else {}

    observed = []
    for target_name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status")) != "OBSERVED":
            continue
        obs_dt = _parse_dt(entry.get("last_obs_utc"))
        if obs_dt is None:
            continue
        observed.append((obs_dt, str(target_name), entry))

    if not observed:
        raise ValueError(f"No OBSERVED ledger rows with last_obs_utc found in {ledger_path}")

    newest_dt = max(item[0] for item in observed)
    cutoff = newest_dt - timedelta(hours=12)
    rows = []
    for obs_dt, target_name, entry in sorted(observed):
        if obs_dt < cutoff:
            continue
        rows.append({
            "target_name": target_name,
            "last_obs_utc": obs_dt.isoformat().replace("+00:00", "Z"),
            "mag": entry.get("last_mag"),
            "err": entry.get("last_err"),
            "filter": entry.get("last_filter", "TG"),
            "calibration_state": entry.get("last_calibration_state", "UNKNOWN"),
            "n_comps": entry.get("last_comps", 0),
            "n_comps_raw": entry.get("last_comps_raw", entry.get("last_comps", 0)),
            "n_comps_rejected": entry.get("last_comps_rejected", 0),
            "peak_adu": entry.get("last_peak_adu"),
            "target_inst_mag": entry.get("last_target_inst_mag"),
            "target_inst_err": entry.get("last_target_inst_err"),
            "scope_name": entry.get("last_scope_name"),
            "capture_file": entry.get("last_capture_path"),
            "comp_rows": entry.get("last_comp_rows") or [],
            "photometric_system": entry.get("last_photometric_system", "TG"),
            "measurement_kind": entry.get("last_measurement_kind", "raw_bayer_green_untransformed"),
            "solved_ra_deg": entry.get("last_solved_ra"),
            "solved_dec_deg": entry.get("last_solved_dec"),
        })
    return rows


# Render the requested submission files from one accepted-observation list.
def stage_reports(
    summary_path: Path | None,
    include_baa_ccd: bool = True,
    observer_code: str | None = None,
) -> list[Path]:
    ledger_fallback = False
    if summary_path is not None:
        payload = json.loads(summary_path.read_text())
        accepted = payload.get("accepted_observations") or []
        if not accepted:
            raise ValueError(f"No accepted observations found in {summary_path.name}")
    else:
        accepted = _accepted_from_ledger(PROJECT_ROOT / "data" / "ledger.json")
        ledger_fallback = True

    observations = [_observation_from_summary(row) for row in accepted]
    aavso = AAVSOReporter(observer_code=observer_code)
    baa_ext = BAAModifiedExtendedReporter(observer_code=observer_code)
    outputs = [
        aavso.finalize_report(observations),
        baa_ext.finalize_report(observations),
    ]

    if include_baa_ccd and not ledger_fallback:
        for obs in observations:
            outputs.append(BAACCDReporter(observer_code=observer_code).finalize_report([obs]))

    return outputs


# Parse CLI arguments for a read-mostly staging command.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage AAVSO/BAA reports from a postflight summary JSON.")
    parser.add_argument(
        "--summary",
        type=Path,
        help="Explicit postflight summary JSON. Defaults to the newest postflight_summary_*.json in data/reports.",
    )
    parser.add_argument(
        "--no-baa-ccd",
        action="store_true",
        help="Skip per-target BAA CCD/CMOS export files.",
    )
    parser.add_argument(
        "--observer-code",
        help="Override observer code when local config.toml is absent or incomplete.",
    )
    return parser.parse_args()


# Run the staging command and print every generated report path.
def main() -> None:
    args = parse_args()
    report_dir = PROJECT_ROOT / "data" / "reports"
    summary_path = args.summary.expanduser().resolve() if args.summary else None
    if summary_path is None:
        try:
            summary_path = _latest_summary(report_dir)
        except FileNotFoundError:
            summary_path = None
    outputs = stage_reports(
        summary_path,
        include_baa_ccd=not args.no_baa_ccd,
        observer_code=args.observer_code,
    )
    if summary_path is not None:
        print(f"Summary: {summary_path}")
    else:
        print(f"Summary: ledger fallback ({PROJECT_ROOT / 'data' / 'ledger.json'})")
        if not args.no_baa_ccd:
            print("Note: BAA CCD/CMOS export skipped in ledger fallback mode (exp_len not retained in ledger).")
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
