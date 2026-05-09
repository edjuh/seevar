#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/catalogs/build_deepsky_catalogs.py
Objective: Build normalized SeeVar secondary imaging catalogs from master NGC/IC/Messier data.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
from pathlib import Path
from urllib.request import Request, urlopen

from lxml import html

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CATALOG_DIR = PROJECT_ROOT / "catalogs"
DEFAULT_MASTER = CATALOG_DIR / "ngc-ic-messier-catalog.json"

CALDWELL_URL = "https://astropixels.com/caldwell/caldwellcat.html"
HERSCHEL_URL = "https://en.wikipedia.org/wiki/Herschel_400_Catalogue"
SHARPLESS_URL = "https://www.reinervogel.net/Sharpless/Sharpless_data_e.html"


def _fetch_doc(url: str) -> html.HtmlElement:
    req = Request(url, headers={"User-Agent": "SeeVarCatalogBuilder/1.0"})
    data = urlopen(req, timeout=30, context=ssl._create_unverified_context()).read()
    return html.fromstring(data)


def _hms_to_deg(value: str) -> float:
    parts = [float(part) for part in re.split(r"[:\s]+", value.strip()) if part]
    while len(parts) < 3:
        parts.append(0.0)
    return round((parts[0] + parts[1] / 60.0 + parts[2] / 3600.0) * 15.0, 6)


def _dms_to_deg(value: str) -> float:
    text = value.strip().replace("+", "")
    sign = -1.0 if text.startswith("-") else 1.0
    text = text.lstrip("-")
    parts = [float(part) for part in re.split(r"[:\s]+", text) if part]
    while len(parts) < 3:
        parts.append(0.0)
    return round(sign * (parts[0] + parts[1] / 60.0 + parts[2] / 3600.0), 6)


def _clean_name(value: str | None) -> str:
    return " ".join(str(value or "").replace("_", " ").split())


def _ngc_key(value: str | int | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).upper().replace(" ", "")
    match = re.search(r"(NGC|IC)(\d+[A-Z]?)", text)
    if not match and re.fullmatch(r"\d+[A-Z]?", text):
        return f"NGC{text}"
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}"


def _m_key(value: str | None) -> str | None:
    match = re.search(r"M\s*(\d+)", str(value or ""), re.IGNORECASE)
    return f"M{int(match.group(1))}" if match else None


def _float_or_none(value) -> float | None:
    try:
        if value in (None, "", "-", "–"):
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _master_indexes(rows: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_name: dict[str, dict] = {}
    by_messier: dict[str, dict] = {}
    for row in rows:
        key = _ngc_key(row.get("name"))
        if key:
            by_name[key] = row
        for messier in row.get("m") or []:
            mkey = _m_key(messier)
            if mkey:
                by_messier[mkey] = row
    return by_name, by_messier


def _target_from_master(
    row: dict,
    *,
    name: str,
    catalog: str,
    common_name: str = "",
    source_id: str = "",
    priority: int = -5,
    duration: int = 900,
) -> dict:
    aliases = []
    for item in row.get("m") or []:
        if item:
            aliases.append(str(item))
    if row.get("name") and row.get("name") != name:
        aliases.append(str(row["name"]))

    return {
        "name": name,
        "common_name": common_name or _clean_name(row.get("common_names")),
        "source_id": source_id or name,
        "aliases": sorted(set(aliases)),
        "ra": _hms_to_deg(str(row["ra"])),
        "dec": _dms_to_deg(str(row["dec"])),
        "type": str(row.get("type") or catalog.upper()),
        "object_definition": _clean_name(row.get("object_definition")),
        "catalog": catalog,
        "science_mode": "imaging",
        "max_mag": _float_or_none(row.get("v_mag") or row.get("b_mag")),
        "b_mag": _float_or_none(row.get("b_mag")),
        "v_mag": _float_or_none(row.get("v_mag")),
        "constellation": row.get("const"),
        "major_axis_arcmin": _float_or_none(row.get("majax")),
        "minor_axis_arcmin": _float_or_none(row.get("minax")),
        "priority": priority,
        "duration": duration,
    }


def build_messier(master_rows: list[dict]) -> list[dict]:
    _, by_messier = _master_indexes(master_rows)
    targets = []
    for idx in range(1, 111):
        key = f"M{idx}"
        row = by_messier.get(key)
        if row:
            targets.append(_target_from_master(row, name=key, catalog="messier", source_id=key))
    return targets


def build_caldwell(master_rows: list[dict]) -> list[dict]:
    by_name, _ = _master_indexes(master_rows)
    doc = _fetch_doc(CALDWELL_URL)
    tables = sorted(doc.xpath("//table"), key=lambda table: len(table.xpath(".//tr")), reverse=True)
    rows = tables[0].xpath(".//tr")[3:] if tables else []
    targets = []
    for tr in rows:
        cells = [" ".join(cell.text_content().split()) for cell in tr.xpath("./td")]
        if len(cells) < 8 or not cells[0].isdigit():
            continue
        caldwell = f"C{int(cells[0])}"
        ngc = _ngc_key(cells[1])
        row = by_name.get(ngc or "")
        if row:
            targets.append(
                _target_from_master(
                    row,
                    name=caldwell,
                    catalog="caldwell",
                    common_name=cells[10] if len(cells) > 10 else "",
                    source_id=ngc or caldwell,
                )
            )
    return targets


def build_herschel400(master_rows: list[dict]) -> list[dict]:
    by_name, _ = _master_indexes(master_rows)
    doc = _fetch_doc(HERSCHEL_URL)
    targets = []
    seen = set()
    for table in doc.xpath("//table")[9:13]:
        for tr in table.xpath(".//tr")[1:]:
            cells = [" ".join(cell.text_content().split()) for cell in tr.xpath("./td")]
            if len(cells) < 2:
                continue
            key = _ngc_key(cells[1])
            if not key or key in seen or key not in by_name:
                continue
            seen.add(key)
            targets.append(
                _target_from_master(
                    by_name[key],
                    name=key,
                    catalog="herschel400",
                    common_name=cells[2] if len(cells) > 2 else "",
                    source_id=key,
                    priority=-6,
                    duration=900,
                )
            )
    return targets


def build_sharpless() -> list[dict]:
    doc = _fetch_doc(SHARPLESS_URL)
    targets = []
    tables = sorted(doc.xpath("//table"), key=lambda table: len(table.xpath(".//tr")), reverse=True)
    rows = tables[0].xpath(".//tr")[1:] if tables else []
    for tr in rows:
        cells = [" ".join(cell.text_content().split()) for cell in tr.xpath("./td")]
        if len(cells) < 4 or not cells[0].startswith("Sh"):
            continue
        targets.append(
            {
                "name": cells[0].replace("Sh 2-", "Sh2-"),
                "common_name": cells[4] if len(cells) > 4 else "",
                "source_id": cells[0],
                "aliases": [],
                "ra": _hms_to_deg(cells[1]),
                "dec": _dms_to_deg(cells[2]),
                "type": "SHARPLESS",
                "object_definition": "Emission nebula",
                "catalog": "sharpless",
                "science_mode": "imaging",
                "max_mag": None,
                "constellation": None,
                "major_axis_arcmin": _float_or_none(cells[3]),
                "minor_axis_arcmin": None,
                "priority": -7,
                "duration": 1200,
            }
        )
    return targets


def write_catalog(name: str, targets: list[dict], source: str) -> Path:
    payload = {
        "#objective": f"Normalized {name} secondary imaging catalog for SeeVar filler targets.",
        "schema": "seevar-secondary-catalog-v1",
        "source": source,
        "target_count": len(targets),
        "targets": targets,
    }
    path = CATALOG_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build normalized deep-sky secondary catalogs.")
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--only", nargs="*", choices=["messier", "caldwell", "herschel400", "sharpless"])
    args = parser.parse_args()

    master_rows = json.loads(args.master.read_text(encoding="utf-8"))
    builders = {
        "messier": lambda: build_messier(master_rows),
        "caldwell": lambda: build_caldwell(master_rows),
        "herschel400": lambda: build_herschel400(master_rows),
        "sharpless": build_sharpless,
    }
    wanted = args.only or list(builders)
    for name in wanted:
        targets = builders[name]()
        path = write_catalog(name, targets, str(args.master if name != "sharpless" else SHARPLESS_URL))
        print(f"{name}: {len(targets)} -> {path}")


if __name__ == "__main__":
    main()
