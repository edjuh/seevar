#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/utils/generate_manifest.py
Version: 1.6.2
Objective: Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS while excluding transient runtime data, generated science products, backups, helper artifacts, and virtual environments.
"""

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TARGET_DIRECTORIES = [
    "core",
    "dev",
    "data",
    "systemd",
    "catalogs",
]

ROOT_FILES = [
    "requirements.txt",
    "config.toml",
]

IGNORE_DIRS = {
    "__pycache__",
    ".git",
    ".github",
    ".venv",
    "venv",
    "env",
    "site-packages",
    "dist-info",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "local_buffer",
    "gaia_cache",
    "reports",
    "raw",
    "archive",
    "reference_stars",
    "horizon_frames",
    "test_frames",
}

IGNORE_FILE_NAMES = {
    "__init__.py",
    "FILE_MANIFEST.md",
    "SEE_VAR_MANIFEST.md",
}

IGNORE_FILE_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".swp",
    ".swo",
    ".tmp",
    ".temp",
    ".orig",
    ".rej",
    ".log",
    ".npy",
    ".npz",
    ".fits",
    ".fit",
    ".fts",
)

TEXT_METADATA_SUFFIXES = {
    ".py",
    ".md",
    ".MD",
    ".txt",
    ".psv",
    ".service",
    ".timer",
    ".sh",
    "",
}

MANIFEST_FILE = PROJECT_ROOT / "dev/logic" / "FILE_MANIFEST.md"
NAS_MANIFEST = Path("/mnt/astronas/SEE_VAR_MANIFEST.md")


def should_ignore_dir(dirname: str) -> bool:
    if dirname in IGNORE_DIRS:
        return True
    if dirname.startswith("."):
        return True
    if dirname.endswith(".egg-info"):
        return True
    if dirname.endswith(".dist-info"):
        return True
    return False


def should_ignore_file(filename: str) -> bool:
    lower = filename.lower()

    if filename in IGNORE_FILE_NAMES:
        return True
    if filename.startswith("."):
        return True
    if lower.endswith(IGNORE_FILE_SUFFIXES):
        return True
    if lower.endswith(".bak"):
        return True
    if ".bak." in lower:
        return True
    if ".hdrbak." in lower:
        return True
    return False


def sanitize_text(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("|", "/")
    text = text.replace("||", "/")
    return text.strip()


def truncate_text(text: str, limit: int = 120) -> str:
    text = sanitize_text(text)
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def extract_python_style(content: str):
    version = None
    objective = None

    v_match = re.search(r"(?m)^Version:\s*(.+?)\s*$", content)
    o_match = re.search(r"(?m)^Objective:\s*(.+?)\s*$", content)

    if v_match:
        version = sanitize_text(v_match.group(1))
    if o_match:
        objective = sanitize_text(o_match.group(1))

    return version, objective


def extract_markdown_style(content: str):
    version = None
    objective = None

    v_match = re.search(r"(?mi)^>\s*\*\*Version:\*\*\s*(.+?)\s*$", content)
    o_match = re.search(r"(?mi)^>\s*\*\*Objective:\*\*\s*(.+?)\s*$", content)

    if v_match:
        version = sanitize_text(v_match.group(1))
    if o_match:
        objective = sanitize_text(o_match.group(1))

    return version, objective


def get_file_info(filepath: Path):
    version, objective = "N/A", "No objective defined."

    if filepath.suffix.lower() == ".json":
        return "JSON", "Data/Configuration file."

    if filepath.suffix not in TEXT_METADATA_SUFFIXES and filepath.name not in ROOT_FILES:
        return version, objective

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(4000)

        py_ver, py_obj = extract_python_style(content)
        md_ver, md_obj = extract_markdown_style(content)

        if py_ver:
            version = py_ver
        elif md_ver:
            version = md_ver

        if py_obj:
            objective = py_obj
        elif md_obj:
            objective = md_obj

        version = truncate_text(version, 60)
        objective = truncate_text(objective, 120)

    except Exception:
        pass

    return version, objective


def collect_manifest_rows():
    rows = []

    for filename in ROOT_FILES:
        full_path = PROJECT_ROOT / filename
        if full_path.exists():
            ver, obj = get_file_info(full_path)
            rows.append((filename, ver, obj))

    for directory in TARGET_DIRECTORIES:
        dir_path = PROJECT_ROOT / directory
        if not dir_path.exists():
            continue

        for root, dirs, files in os.walk(dir_path):
            dirs[:] = sorted(d for d in dirs if not should_ignore_dir(d))

            for filename in sorted(files):
                if should_ignore_file(filename):
                    continue

                full_path = Path(root) / filename
                rel_path = full_path.relative_to(PROJECT_ROOT)

                rel_parts = set(rel_path.parts)
                if rel_parts & IGNORE_DIRS:
                    continue

                ver, obj = get_file_info(full_path)
                rows.append((str(rel_path), ver, obj))

    rows.sort(key=lambda row: row[0].lower())
    return rows


def generate_manifest_text():
    rows = collect_manifest_rows()

    lines = [
        "# 🔭 SeeVar: File Manifest",
        "",
        "> **System State**: Diamond Revision (Sovereign)",
        "",
        "| Path | Version | Objective |",
        "| :--- | :--- | :--- |",
    ]

    for rel_path, ver, obj in rows:
        lines.append(f"| {rel_path} | {ver} | {obj} |")

    lines.append("")
    return "\n".join(lines)


def write_manifest():
    manifest_content = generate_manifest_text()

    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        f.write(manifest_content)

    try:
        NAS_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with open(NAS_MANIFEST, "w", encoding="utf-8") as f:
            f.write(manifest_content)
        print(f"✅ NAS Manifest mirrored to {NAS_MANIFEST}")
    except Exception as e:
        print(f"⚠️ Could not mirror to NAS: {e}")

    print(f"✅ Local manifest updated at {MANIFEST_FILE}")


if __name__ == "__main__":
    write_manifest()
