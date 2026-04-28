#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/aavso_reporter.py
Version: 1.5.0
Objective: Generate and validate AAVSO Extended Format reports in data/reports/
           using SeeVar TG photometry defaults for OSC Bayer data. Also
           supports the BAA-modified AAVSO Extended variant.
"""

import logging
import math
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

try:
    from core.flight.vault_manager import VaultManager
except Exception:
    VaultManager = None

from core.utils.env_loader import load_config

log = logging.getLogger("AAVSOReporter")

DEFAULT_OBSTYPE = "DSLR"
DEFAULT_FILTER = "TG"
VALID_FLAGS = {"YES", "NO"}
VALID_MTYPES = {"STD", "DIF"}
VALID_FILTERS = {
    "U", "B", "V", "R", "I",
    "TG", "TB", "TR",
    "CV", "CR",
    "SG", "SR", "SI",
    "Z", "Y", "J", "H", "K",
    "C", "HA", "OIII", "SII",
}

DEFAULT_BAA_TELESCOPE = "ZWO Seestar S30-Pro"
DEFAULT_BAA_CAMERA = "Integrated CMOS"
DEFAULT_BAA_ANALYSIS = "SeeVar"


def _default_software_name() -> str:
    try:
        from core.flight.pilot import SWCREATE
        return str(SWCREATE)
    except Exception:
        return "SeeVar"


class AAVSOReporter:
    """
    Generates AAVSO Extended Format submission files.

    Defaults for current SeeVar output:
      - FILTER : TG
      - TRANS  : NO
      - MTYPE  : STD
      - OBSTYPE: DSLR
    """

    def __init__(self, observer_code: str | None = None, software_name: str | None = None, obstype: str = DEFAULT_OBSTYPE):
        self.report_dir = PROJECT_ROOT / "data" / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self.obs_code = (observer_code or self._load_observer_code()).strip().upper()
        if not self.obs_code or self.obs_code == "MISSING_ID":
            raise ValueError(
                "observer_code missing from config.toml - AAVSO submissions require a valid observer code."
            )

        self.software_name = (software_name or _default_software_name()).strip()
        self.obstype = obstype.strip().upper() if obstype else DEFAULT_OBSTYPE

    def _load_observer_code(self) -> str:
        if VaultManager is not None:
            try:
                vault = VaultManager()
                conf = vault.get_observer_config()
                code = str(conf.get("observer_id", "")).strip()
                if code and code != "MISSING_ID":
                    return code
            except Exception as e:
                log.warning("VaultManager observer lookup failed: %s", e)

        try:
            cfg = load_config()
            code = str(cfg.get("aavso", {}).get("observer_code", "")).strip()
            if code:
                return code
        except Exception as e:
            log.warning("Direct config observer lookup failed: %s", e)

        return ""

    def _load_config(self) -> dict:
        try:
            return load_config()
        except Exception as e:
            log.warning("Config load failed: %s", e)
            return {}

    def _normalize_flag(self, value, field: str, allowed: set[str]) -> str:
        val = str(value).strip().upper()
        if val not in allowed:
            raise ValueError(f"{field} must be one of {sorted(allowed)}, got {value!r}")
        return val

    def _normalize_filter(self, value) -> str:
        val = str(value or DEFAULT_FILTER).strip().upper()
        if not val:
            val = DEFAULT_FILTER
        if val not in VALID_FILTERS:
            raise ValueError(f"Unsupported AAVSO filter code: {value!r}")
        return val

    def _normalize_text(self, value, field: str, default: str | None = None) -> str:
        if value in (None, ""):
            if default is not None:
                return default
            raise ValueError(f"{field} is required")
        text = str(value).strip()
        if not text:
            if default is not None:
                return default
            raise ValueError(f"{field} is required")
        return text.replace(",", ";").replace("\n", " ").replace("\r", " ")

    def _build_location_string(self) -> str:
        cfg = self._load_config()
        loc = cfg.get("location", {}) if isinstance(cfg, dict) else {}
        lat = float(loc.get("lat", 0.0))
        lon = float(loc.get("lon", 0.0))
        elev = float(loc.get("elevation", 0.0))

        lat_suffix = "N" if lat >= 0 else "S"
        lon_suffix = "E" if lon >= 0 else "W"
        return f"{abs(lat):.6f}{lat_suffix} {abs(lon):.6f}{lon_suffix} H{int(round(elev))}m"

    def _build_telescope_string(self) -> str:
        cfg = self._load_config()
        baa = cfg.get("baa", {}) if isinstance(cfg, dict) else {}
        explicit = str(baa.get("telescope", "")).strip()
        if explicit:
            return explicit

        scopes = cfg.get("seestars", []) if isinstance(cfg, dict) else []
        if scopes:
            scope = scopes[0] or {}
            model = str(scope.get("model", "")).strip()
            mount = str(scope.get("mount", "")).strip()
            name = str(scope.get("name", "")).strip()
            parts = [part for part in [name, model, mount] if part]
            if parts:
                return " / ".join(parts)
        return DEFAULT_BAA_TELESCOPE

    def _build_camera_string(self) -> str:
        cfg = self._load_config()
        baa = cfg.get("baa", {}) if isinstance(cfg, dict) else {}
        explicit = str(baa.get("camera", "")).strip()
        if explicit:
            return explicit
        return DEFAULT_BAA_CAMERA

    def _fmt_num(self, value, places=3, field="value", allow_na=False) -> str:
        if value in (None, ""):
            raise ValueError(f"{field} is missing")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"{field} is not finite: {value!r}")
            return f"{numeric:.{places}f}"

        text = str(value).strip()
        if not text:
            raise ValueError(f"{field} is missing")

        if allow_na and text.lower() == "na":
            return "na"

        if text.startswith((">", "<")):
            suffix = text[1:].strip()
            try:
                float(suffix)
            except ValueError as exc:
                raise ValueError(f"{field} has invalid limit format: {value!r}") from exc
            return text

        try:
            numeric = float(text)
        except ValueError as exc:
            raise ValueError(f"{field} is not numeric: {value!r}") from exc

        if not math.isfinite(numeric):
            raise ValueError(f"{field} is not finite: {value!r}")
        return f"{numeric:.{places}f}"

    def _normalize_observation(self, obs: dict, idx: int) -> dict[str, str]:
        target = self._normalize_text(obs.get("target"), f"observations[{idx}].target")
        return {
            "target": target,
            "jd": self._fmt_num(obs.get("jd"), 5, f"{target}.jd"),
            "mag": self._fmt_num(obs.get("mag"), 3, f"{target}.mag"),
            "err": self._fmt_num(obs.get("err"), 3, f"{target}.err"),
            "filter": self._normalize_filter(obs.get("filter", DEFAULT_FILTER)),
            "trans": self._normalize_flag(obs.get("trans", "NO"), f"{target}.trans", VALID_FLAGS),
            "mtype": self._normalize_flag(obs.get("mtype", "STD"), f"{target}.mtype", VALID_MTYPES),
            "comp": self._normalize_text(obs.get("comp"), f"{target}.comp"),
            "cmag": self._fmt_num(obs.get("cmag"), 3, f"{target}.cmag"),
            "kname": self._normalize_text(obs.get("kname"), f"{target}.kname", default="na"),
            "kmag": self._fmt_num(obs.get("kmag", "na"), 3, f"{target}.kmag", allow_na=True),
            "amass": self._fmt_num(obs.get("amass", "na"), 3, f"{target}.amass", allow_na=True),
            "group": self._normalize_text(obs.get("group", "na"), f"{target}.group", default="na"),
            "chart": self._normalize_text(obs.get("chart", "na"), f"{target}.chart", default="na"),
            "notes": self._normalize_text(obs.get("notes", "na"), f"{target}.notes", default="na"),
        }

    def validate_observation(self, obs: dict, idx: int = 1) -> dict[str, str]:
        return self._normalize_observation(obs, idx)

    def validate_report(self, observations: list[dict]) -> list[dict[str, str]]:
        if not observations:
            raise ValueError("No observations supplied for AAVSO report")
        return [self._normalize_observation(obs, idx) for idx, obs in enumerate(observations, start=1)]

    def _header_lines(self) -> list[str]:
        return [
            "#TYPE=EXTENDED",
            f"#OBSCODE={self.obs_code}",
            f"#SOFTWARE={self.software_name}",
            "#DELIM=,",
            "#DATE=JD",
            f"#OBSTYPE={self.obstype}",
            "#NAME,DATE,MAG,MERR,FILT,TRANS,MTYPE,CNAME,CMAG,KNAME,KMAG,AMASS,GROUP,CHART,NOTES",
        ]

    def render_report_text(self, observations: list[dict], validate: bool = True) -> str:
        rows = self.validate_report(observations) if validate else observations

        lines = list(self._header_lines())
        for row in rows:
            lines.append(",".join([
                row["target"],
                row["jd"],
                row["mag"],
                row["err"],
                row["filter"],
                row["trans"],
                row["mtype"],
                row["comp"],
                row["cmag"],
                row["kname"],
                row["kmag"],
                row["amass"],
                row["group"],
                row["chart"],
                row["notes"],
            ]))

        return "\n".join(lines) + "\n"

    def preview_report(self, observations: list[dict]) -> str:
        return self.render_report_text(observations, validate=True)

    def finalize_report(self, observations: list[dict], validate: bool = True) -> Path:
        text = self.render_report_text(observations, validate=validate)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"AAVSO_{self.obs_code}_{timestamp}.txt"
        save_path = self.report_dir / filename

        with open(save_path, "w") as f:
            f.write(text)

        log.info("AAVSO report written: %s", save_path)
        return save_path


class BAAModifiedExtendedReporter(AAVSOReporter):
    """
    Generates the BAA-supported modified AAVSO Extended format.

    Differences from stock AAVSO Extended:
      - #TYPE=AAVSO EXT BAA V1.00
      - adds #LOCATION / #TELESCOPE / #CAMERA
      - uses tab delimiters
    """

    def __init__(
        self,
        observer_code: str | None = None,
        software_name: str | None = None,
        obstype: str = DEFAULT_OBSTYPE,
        location: str | None = None,
        telescope: str | None = None,
        camera: str | None = None,
    ):
        super().__init__(observer_code=observer_code, software_name=software_name, obstype=obstype)
        self.location = self._normalize_text(location or self._build_location_string(), "baa.location")
        self.telescope = self._normalize_text(telescope or self._build_telescope_string(), "baa.telescope")
        self.camera = self._normalize_text(camera or self._build_camera_string(), "baa.camera")

    def _header_lines(self) -> list[str]:
        return [
            "#TYPE=AAVSO EXT BAA V1.00",
            f"#OBSCODE={self.obs_code}",
            f"#SOFTWARE={self.software_name}",
            "#DELIM=TAB",
            "#DATE=JD",
            f"#OBSTYPE={self.obstype}",
            f"#LOCATION={self.location}",
            f"#TELESCOPE={self.telescope}",
            f"#CAMERA={self.camera}",
            "#NAME\tDATE\tMAG\tMERR\tFILT\tTRANS\tMTYPE\tCNAME\tCMAG\tKNAME\tKMAG\tAMASS\tGROUP\tCHART\tNOTES",
        ]

    def render_report_text(self, observations: list[dict], validate: bool = True) -> str:
        rows = self.validate_report(observations) if validate else observations
        lines = list(self._header_lines())
        for row in rows:
            lines.append("\t".join([
                row["target"],
                row["jd"],
                row["mag"],
                row["err"],
                row["filter"],
                row["trans"],
                row["mtype"],
                row["comp"],
                row["cmag"],
                row["kname"],
                row["kmag"],
                row["amass"],
                row["group"],
                row["chart"],
                row["notes"],
            ]))
        return "\n".join(lines) + "\n"

    def finalize_report(self, observations: list[dict], validate: bool = True) -> Path:
        text = self.render_report_text(observations, validate=validate)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"BAA_AAVSO_EXT_{self.obs_code}_{timestamp}.txt"
        save_path = self.report_dir / filename
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(text)
        log.info("BAA-modified AAVSO report written: %s", save_path)
        return save_path


class BAACCDReporter(AAVSOReporter):
    """
    Generates the fuller BAA CCD/CMOS tabular layout with repeated comparison
    star columns. This is intended for one variable per file.
    """

    def __init__(
        self,
        observer_code: str | None = None,
        software_name: str | None = None,
        obstype: str = DEFAULT_OBSTYPE,
        location: str | None = None,
        telescope: str | None = None,
        camera: str | None = None,
        analysis_software: str | None = None,
        magnitude_type: str = "Instrumental",
        comment: str = "",
    ):
        super().__init__(observer_code=observer_code, software_name=software_name, obstype=obstype)
        self.location = self._normalize_text(location or self._build_location_string(), "baa.location")
        self.telescope = self._normalize_text(telescope or self._build_telescope_string(), "baa.telescope")
        self.camera = self._normalize_text(camera or self._build_camera_string(), "baa.camera")
        self.analysis_software = self._normalize_text(analysis_software or DEFAULT_BAA_ANALYSIS, "baa.analysis_software")
        self.magnitude_type = self._normalize_text(magnitude_type, "baa.magnitude_type")
        self.comment = self._normalize_text(comment or "", "baa.comment", default="")

    def _normalize_baa_observation(self, obs: dict, idx: int) -> dict:
        target = self._normalize_text(obs.get("target"), f"observations[{idx}].target")
        comp_rows = obs.get("comp_rows") or []
        if not isinstance(comp_rows, list):
            raise ValueError(f"{target}.comp_rows must be a list when using BAACCDReporter")

        norm_comp_rows = []
        for comp_idx, comp in enumerate(comp_rows, start=1):
            if not isinstance(comp, dict):
                continue
            norm_comp_rows.append({
                "source_id": self._normalize_text(comp.get("source_id", f"COMP{comp_idx}"), f"{target}.comp_rows[{comp_idx}].source_id"),
                "ref_mag": self._fmt_num(comp.get("v_mag"), 3, f"{target}.comp_rows[{comp_idx}].v_mag"),
                "ref_err": self._fmt_num(comp.get("v_mag_err", 0.0), 3, f"{target}.comp_rows[{comp_idx}].v_mag_err"),
                "inst_mag": self._fmt_num(comp.get("inst_mag"), 3, f"{target}.comp_rows[{comp_idx}].inst_mag"),
                "inst_err": self._fmt_num(comp.get("inst_err"), 3, f"{target}.comp_rows[{comp_idx}].inst_err"),
            })

        return {
            "target": target,
            "jd": self._fmt_num(obs.get("jd"), 5, f"{target}.jd"),
            "filter": self._normalize_filter(obs.get("filter", DEFAULT_FILTER)),
            "mag": self._fmt_num(obs.get("mag"), 3, f"{target}.mag"),
            "err": self._fmt_num(obs.get("err"), 3, f"{target}.err"),
            "target_inst_mag": self._fmt_num(obs.get("target_inst_mag"), 3, f"{target}.target_inst_mag"),
            "target_inst_err": self._fmt_num(obs.get("target_inst_err"), 3, f"{target}.target_inst_err"),
            "exp_len": self._fmt_num(obs.get("exp_len"), 0, f"{target}.exp_len"),
            "file_name": self._normalize_text(obs.get("file_name"), f"{target}.file_name"),
            "chart": self._normalize_text(obs.get("chart", "na"), f"{target}.chart", default="na"),
            "comp_rows": norm_comp_rows,
        }

    def render_report_text(self, observations: list[dict], validate: bool = True) -> str:
        if not observations:
            raise ValueError("No observations supplied for BAA CCD report")

        rows = [self._normalize_baa_observation(obs, idx) for idx, obs in enumerate(observations, start=1)]
        target_name = rows[0]["target"]
        chart_id = rows[0]["chart"]
        max_comps = max((len(row["comp_rows"]) for row in rows), default=0)

        lines = [
            "File Format\tCCD/CMOS v2.03",
            f"Observation Method\t{self.obstype}",
            f"Variable\t{target_name}",
            f"Chart ID\t{chart_id}",
            f"Observer code\t{self.obs_code}",
            f"Location\t{self.location}",
            f"Telescope\t{self.telescope}",
            f"Camera\t{self.camera}",
            f"Magnitude type\t{self.magnitude_type}",
            f"Photometry software\t{self.software_name}",
            f"Analysis software\t{self.analysis_software}",
            f"Comment\t{self.comment}",
            "",
        ]

        header = [
            "JulianDate", "Filter", "VarCalcMag", "VarCalcErr",
            "VarInstMag", "VarInstErr", "ExpLen", "FileName",
        ]
        for _ in range(max_comps):
            header.extend(["CmpStar", "CmpRefMag", "CmpRefErr", "CmpInstMag", "CmpInstErr"])
        lines.append("\t".join(header))

        for row in rows:
            fields = [
                row["jd"],
                row["filter"],
                row["mag"],
                row["err"],
                row["target_inst_mag"],
                row["target_inst_err"],
                row["exp_len"],
                row["file_name"],
            ]
            for comp in row["comp_rows"]:
                fields.extend([
                    comp["source_id"],
                    comp["ref_mag"],
                    comp["ref_err"],
                    comp["inst_mag"],
                    comp["inst_err"],
                ])
            missing = max_comps - len(row["comp_rows"])
            if missing > 0:
                fields.extend([""] * (missing * 5))
            lines.append("\t".join(fields))

        return "\n".join(lines) + "\n"

    def finalize_report(self, observations: list[dict], validate: bool = True) -> Path:
        text = self.render_report_text(observations, validate=validate)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        target = self._normalize_text(observations[0].get("target", "UNKNOWN"), "baa.target", default="UNKNOWN").replace(" ", "_")
        filename = f"BAA_CCD_{self.obs_code}_{target}_{timestamp}.txt"
        save_path = self.report_dir / filename
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(text)
        log.info("BAA CCD report written: %s", save_path)
        return save_path


if __name__ == "__main__":
    rep = AAVSOReporter()
    print("[OK] AAVSO Reporter initialised.")
    print(f"     Observer code : {rep.obs_code}")
    print(f"     Report dir    : {rep.report_dir}")
    print(f"     Software      : {rep.software_name}")
    print(f"     OBSTYPE       : {rep.obstype}")
