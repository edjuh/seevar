#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/utils/generate_manifest.py
Version: 1.6.2
Objective: Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS while excluding transient runtime data, generated science products, backups, helper artifacts, and virtual environments.
"""

import os
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FALLBACK_TARGET_DIRECTORIES = [
    "core",
    "dev",
    "docs",
    "scripts",
    "systemd",
    "catalogs",
]

FALLBACK_ROOT_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "ROADMAP.md",
    "UPGRADE.MD",
    "requirements.txt",
    "config.toml.example",
    "bootstrap.sh",
    "upgrade.sh",
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
    ".gitkeep",
    "SeeVar.jpg",
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
    ".jpg",
    ".jpeg",
    ".png",
    ".zip",
    ".bsp",
    ".xyls",
    ".axy",
    ".corr",
    ".match",
    ".rdls",
    ".solved",
    ".wcs",
    ".new",
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
    ".json",
    ".html",
    ".yml",
    ".yaml",
    ".toml",
    ".example",
    "",
}

MANIFEST_FILE = PROJECT_ROOT / "dev/logic" / "FILE_MANIFEST.md"
NAS_MANIFEST = Path("/mnt/astronas/SEE_VAR_MANIFEST.md")


# Return true when a directory should never be included in the source manifest.
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


# Return true when a file is transient, generated, private, binary, or otherwise not manifest-worthy.
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


# Collapse multiline metadata into a Markdown table-safe single line.
def sanitize_text(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("|", "/")
    text = text.replace("||", "/")
    return text.strip()


# Shorten long metadata fields so the manifest remains readable.
def truncate_text(text: str, limit: int = 120) -> str:
    text = sanitize_text(text)
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


# Extract Version/Objective fields from script-style header blocks.
def extract_python_style(content: str):
    version = None
    objective_parts = []
    active_key = None

    meta_re = re.compile(r"^\s*(?:(?:#|;|//)\s*)?(Version|Objective):\s*(.+?)\s*$", re.IGNORECASE)
    continuation_re = re.compile(r"^\s*(?:(?:#|;|//)\s*)?\s{2,}(.+?)\s*$")

    for line in content.splitlines():
        meta_match = meta_re.match(line)
        if meta_match:
            key = meta_match.group(1).lower()
            value = sanitize_text(meta_match.group(2))
            active_key = key
            if key == "version":
                version = value
            elif key == "objective":
                objective_parts = [value]
            continue

        if active_key == "objective":
            stripped = line.strip()
            if not stripped:
                active_key = None
                continue
            if stripped.startswith(("=", "-", '"""', "'''", "import ", "from ", "def ", "class ", "@")):
                active_key = None
                continue
            continuation_match = continuation_re.match(line)
            continuation = continuation_match.group(1) if continuation_match else stripped
            continuation = sanitize_text(continuation.lstrip("#; "))
            if not continuation or continuation.startswith(("=", "-", '"""', "'''")):
                active_key = None
                continue
            if re.match(r"(?i)^(filename|version|objective):", continuation):
                active_key = None
                continue
            objective_parts.append(continuation)

    objective = " ".join(objective_parts) if objective_parts else None

    return version, objective


# Extract Version/Objective fields from Markdown blockquote metadata.
def extract_markdown_style(content: str):
    version = None
    objective = None

    v_match = re.search(r"(?mi)^>\s*\*\*Version:\*\*\s*(.+?)\s*$", content)
    o_match = re.search(r"(?mi)^>\s*\*\*Objective:\*\*\s*(.+?)\s*$", content)
    if not v_match:
        v_match = re.search(r"(?mi)^#\s*Version:\s*(.+?)\s*$", content)
    if not o_match:
        o_match = re.search(r"(?mi)^\*\*Objective:\*\*\s*(.+?)\s*$", content)

    if v_match:
        version = sanitize_text(v_match.group(1))
    if o_match:
        objective = sanitize_text(o_match.group(1))

    return version, objective


# Extract objective text from systemd unit Description fields.
def extract_systemd_style(content: str):
    d_match = re.search(r"(?m)^Description\s*=\s*(.+?)\s*$", content)
    return None, sanitize_text(d_match.group(1)) if d_match else None


# Extract a readable title from basic HTML templates.
def extract_html_style(content: str):
    t_match = re.search(r"(?is)<title>\s*(.+?)\s*</title>", content)
    return None, sanitize_text(t_match.group(1)) if t_match else None


# Provide objective text for known structured files that do not carry headers.
def inferred_objective(filepath: Path) -> str | None:
    rel = filepath.relative_to(PROJECT_ROOT).as_posix()
    known = {
        "README.md": "Primary project overview and operator entry point for SeeVar.",
        "CONTRIBUTING.md": "Repository contribution rules and expectations for SeeVar changes.",
        "INSTALL.md": "Installation guide for deploying SeeVar onto supported systems.",
        "LICENSE": "Project license terms.",
        "UPGRADE.MD": "Upgrade procedure and compatibility notes for existing SeeVar installations.",
        "bootstrap.sh": "Fresh-install bootstrap for SeeVar runtime, dependencies, config, and user services.",
        "upgrade.sh": "Upgrade helper for existing SeeVar deployments.",
        "scripts/update_seevar.sh": "Repository update helper for deployed SeeVar systems.",
        "core/fed-mission": "Legacy/operator shell entry point for launching SeeVar mission flow.",
        "core/hardware/ladies.txt": "Human-readable naming notes for configured Seestar telescopes.",
        "dev/utils/nas_backup.sh": "NAS snapshot helper for SeeVar source and durable data while excluding transient FITS/WCS products.",
        "docs/PRESENTATION.md": "Presentation notes and visual walkthrough material for SeeVar.",
        "dev/logic/SEEVAR_SKILL/SKILL.md": "Codex skill instructions for SeeVar-aware development assistance.",
        "dev/logic/ALPACA_BRIDGE.MD": "Canonical doctrine for controlling Seestar telescopes through the official ZWO ASCOM Alpaca REST API.",
        "dev/logic/COMMUNICATION.MD": "Historical protocol record for retired JSON-RPC control paths and their Alpaca replacements.",
        "dev/logic/DATALOGIC.MD": "Data ownership and transformation rules for SeeVar runtime JSON artifacts.",
        "dev/logic/FLIGHT.MD": "Operational doctrine for executing target acquisition during the science flight phase.",
        "dev/logic/PHOTOMETRICS.MD": "Scientific standards and roadmap for SeeVar differential photometry.",
        "dev/logic/PICKERING_PROTOCOL.MD": "Historical and cultural reference explaining SeeVar naming and observatory design inspiration.",
        "dev/logic/PREFLIGHT.MD": "Operational doctrine for preflight data preparation, planning, and go/no-go gates.",
        "dev/tools/clean_postflight_remnants.py": "Dry-run-first cleanup tool for transient astrometry solver products in SeeVar data directories.",
        "dev/logic/SEEVAR_DICT.PSV": "Pipe-separated data dictionary for SeeVar runtime files, fields, owners, and lifecycle notes.",
    }
    if rel in known:
        return known[rel]
    if rel == "requirements.txt":
        return "Python dependency list for SeeVar runtime and development environments."
    if rel == "config.toml.example":
        return "Example SeeVar runtime configuration copied and customized by bootstrap.sh."
    if rel == ".github/workflows/basic-checks.yml":
        return "GitHub Actions workflow for baseline repository checks."
    if rel == ".github/pull_request_template.md":
        return "Pull request template for SeeVar repository changes."
    if rel == ".gitignore":
        return "Repository ignore rules for runtime artifacts, caches, and local secrets."
    if filepath.suffix.lower() == ".json":
        return "Structured configuration or seed data used by SeeVar."
    if filepath.name.startswith("test_") and filepath.suffix == ".py":
        return "Development smoke test for SeeVar pipeline behavior."
    return None


# Read tracked paths from Git so local runtime data cannot pollute the manifest.
def tracked_files() -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception:
        return None

    paths = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        paths.append(PROJECT_ROOT / line.strip())
    return paths


# Walk selected source directories when Git metadata is unavailable.
def fallback_files() -> list[Path]:
    paths = []
    for filename in FALLBACK_ROOT_FILES:
        full_path = PROJECT_ROOT / filename
        if full_path.exists():
            paths.append(full_path)

    for directory in FALLBACK_TARGET_DIRECTORIES:
        dir_path = PROJECT_ROOT / directory
        if not dir_path.exists():
            continue

        for root, dirs, files in os.walk(dir_path):
            dirs[:] = sorted(d for d in dirs if not should_ignore_dir(d))
            for filename in sorted(files):
                paths.append(Path(root) / filename)

    return paths


# Decide whether a tracked/fallback path belongs in the human source manifest.
def manifest_path_allowed(filepath: Path) -> bool:
    if not filepath.exists() or not filepath.is_file():
        return False

    rel_path = filepath.relative_to(PROJECT_ROOT)
    if any(should_ignore_dir(part) for part in rel_path.parts[:-1]):
        return False
    if should_ignore_file(filepath.name):
        return False
    if filepath.suffix.lower() not in TEXT_METADATA_SUFFIXES and filepath.name not in FALLBACK_ROOT_FILES:
        return False
    return True


# Extract version and objective metadata for a single manifest row.
def get_file_info(filepath: Path):
    version, objective = "N/A", "No objective defined."

    if filepath.suffix.lower() == ".json":
        return "JSON", inferred_objective(filepath) or "Structured configuration or seed data used by SeeVar."

    if filepath.suffix.lower() not in TEXT_METADATA_SUFFIXES and filepath.name not in FALLBACK_ROOT_FILES:
        return version, objective

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(4000)

        py_ver, py_obj = extract_python_style(content)
        md_ver, md_obj = extract_markdown_style(content)
        systemd_ver, systemd_obj = extract_systemd_style(content)
        html_ver, html_obj = extract_html_style(content)

        if py_ver:
            version = py_ver
        elif md_ver:
            version = md_ver
        elif systemd_ver:
            version = systemd_ver
        elif html_ver:
            version = html_ver

        if py_obj:
            objective = py_obj
        elif md_obj:
            objective = md_obj
        elif systemd_obj:
            objective = systemd_obj
        elif html_obj:
            objective = html_obj
        else:
            inferred = inferred_objective(filepath)
            if inferred:
                objective = inferred

        version = truncate_text(version, 60)
        objective = truncate_text(objective, 120)

    except Exception:
        pass

    return version, objective


# Collect sorted manifest rows from tracked source files only.
def collect_manifest_rows():
    rows = []
    files = tracked_files() or fallback_files()

    for full_path in files:
        if not manifest_path_allowed(full_path):
            continue
        rel_path = full_path.relative_to(PROJECT_ROOT)
        ver, obj = get_file_info(full_path)
        rows.append((str(rel_path), ver, obj))

    rows.sort(key=lambda row: row[0].lower())
    return rows


# Render the full Markdown manifest including a missing-objective audit section.
def generate_manifest_text(rows: list[tuple[str, str, str]] | None = None):
    rows = rows if rows is not None else collect_manifest_rows()
    missing = [row for row in rows if row[2] == "No objective defined."]

    lines = [
        "# 🔭 SeeVar: File Manifest",
        "",
        "> **System State**: Diamond Revision (Sovereign)",
        "> **Scope**: Tracked source, config templates, service units, tests, and logic docs only. Runtime data and generated science products are excluded.",
        "",
        "| Path | Version | Objective |",
        "| :--- | :--- | :--- |",
    ]

    for rel_path, ver, obj in rows:
        lines.append(f"| {rel_path} | {ver} | {obj} |")

    if missing:
        lines.extend([
            "",
            "## Missing Objectives",
            "",
            "These tracked files are valid manifest entries but still need an explicit Objective header or documented inference:",
            "",
        ])
        for rel_path, _, _ in missing:
            lines.append(f"- {rel_path}")

    lines.append("")
    return "\n".join(lines)


# Write the manifest locally and mirror it to the NAS when available.
def write_manifest():
    rows = collect_manifest_rows()
    missing = [row for row in rows if row[2] == "No objective defined."]
    manifest_content = generate_manifest_text(rows)

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
    print(f"✅ Manifest rows: {len(rows)} | missing objectives: {len(missing)}")


if __name__ == "__main__":
    write_manifest()
