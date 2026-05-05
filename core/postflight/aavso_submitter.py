#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/aavso_submitter.py
Version: 1.0.0
Objective: Submit staged AAVSO Extended report files to the authenticated
           apps.aavso.org WebObs photometry upload form and capture the
           server's validation/warning feedback as durable artifacts.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

from core.utils.env_loader import PROJECT_ROOT, load_config

LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "data" / "reports"
SUBMIT_URL = "https://apps.aavso.org/v2/data/submit/photometry/"
LOGIN_MARKER = "/accounts/auth0/login/"
USER_AGENT = "SeeVar-AAVSO-Submitter/1.0"

log = logging.getLogger("AAVSOSubmitter")


# Install a dedicated submitter log so WebObs interactions can be audited later.
def _install_log_handler() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "aavso_submitter.log"
    for handler in log.handlers:
        if getattr(handler, "baseFilename", None) == str(log_path):
            return

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, mode="a")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    log.setLevel(logging.INFO)


_install_log_handler()


# Reduce HTML to readable lines for success/error/warning extraction.
def _html_lines(html: str) -> list[str]:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text)
    lines = []
    seen = set()
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


# Extract CSRF token, form action, hidden inputs, and the upload field from the
# live submit page so the client follows whatever the current server renders.
def _parse_form(html: str, base_url: str) -> dict:
    form_match = re.search(r"<form\b([^>]*)>(.*?)</form>", html, re.I | re.S)
    if not form_match:
        raise RuntimeError("Could not find AAVSO submit form on page")

    attrs = form_match.group(1)
    body = form_match.group(2)
    action_match = re.search(r'action=["\']([^"\']*)["\']', attrs, re.I)
    action = urljoin(base_url, action_match.group(1)) if action_match and action_match.group(1) else base_url

    fields: dict[str, str] = {}
    file_field = None

    for input_match in re.finditer(r"<input\b([^>]*)>", body, re.I | re.S):
        raw_attrs = input_match.group(1)
        name_match = re.search(r'name=["\']([^"\']+)["\']', raw_attrs, re.I)
        if not name_match:
            continue
        name = name_match.group(1)
        type_match = re.search(r'type=["\']([^"\']+)["\']', raw_attrs, re.I)
        field_type = (type_match.group(1).strip().lower() if type_match else "text")
        value_match = re.search(r'value=["\']([^"\']*)["\']', raw_attrs, re.I | re.S)
        value = unescape(value_match.group(1)) if value_match else ""

        if field_type == "file":
            file_field = name
            continue

        if field_type in {"submit", "button", "image", "reset"}:
            if value:
                fields[name] = value
            continue

        fields[name] = value

    if not file_field:
        raise RuntimeError("Could not find file upload field on AAVSO submit form")

    return {
        "action": action,
        "fields": fields,
        "file_field": file_field,
    }


# Pull human-meaningful outcome lines out of the server response.
def _classify_response_lines(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    success = []
    warnings = []
    errors = []
    success_patterns = [
        r"\bsuccess\b",
        r"\bsuccessfully submitted\b",
        r"\bsubmission complete\b",
        r"\bobservations?\s+(?:were\s+)?submitted\b",
        r"\baccepted\b",
    ]
    for line in lines:
        low = line.lower()
        if any(re.search(pattern, low) for pattern in success_patterns):
            success.append(line)
        if any(token in low for token in ("warning", "out of limit", "out-of-limit", "outside limit", "outside limits", "outside range", "duplicate", "non-fatal")):
            warnings.append(line)
        if any(token in low for token in ("error", "failed", "invalid", "rejected", "must", "required", "unable")):
            errors.append(line)
    if success:
        errors = [line for line in errors if "login session" in line.lower()]
    return success, warnings, errors


# Normalize a stored cookie string into a requests cookie jar.
def _apply_cookie_string(session: requests.Session, cookie_string: str) -> None:
    raw = str(cookie_string or "").strip()
    if not raw:
        return

    if "=" not in raw:
        session.cookies.set("app2_session", raw, domain="apps.aavso.org", path="/")
        session.cookies.set("canary", "false", domain="apps.aavso.org", path="/")
        return

    for chunk in raw.split(";"):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        session.cookies.set(name.strip(), value.strip(), domain="apps.aavso.org", path="/")

    if "canary" not in session.cookies:
        session.cookies.set("canary", "false", domain="apps.aavso.org", path="/")


# Build a session from config or explicit override. Existing webobs_token is
# retained as a legacy fallback and treated as the app2_session value.
def _build_session(cookie_override: str | None = None) -> requests.Session:
    cfg = load_config()
    aavso_cfg = cfg.get("aavso", {}) if isinstance(cfg, dict) else {}
    cookie_string = (
        cookie_override
        or os.environ.get("AAVSO_WEBOBS_SESSION_COOKIE", "")
        or str(aavso_cfg.get("webobs_session_cookie", "")).strip()
        or str(aavso_cfg.get("webobs_token", "")).strip()
    )
    if not cookie_string:
        raise ValueError(
            "No AAVSO WebObs session cookie configured. Set [aavso].webobs_session_cookie "
            "or export AAVSO_WEBOBS_SESSION_COOKIE."
        )

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    _apply_cookie_string(session, cookie_string)
    return session


class AAVSOWebObsSubmitter:
    """
    Session-based WebObs uploader for the new apps.aavso.org photometry submit page.
    """

    def __init__(self, cookie_override: str | None = None, timeout: float = 30.0):
        self.timeout = float(timeout)
        self.session = _build_session(cookie_override)

    # Fetch the live submit page and ensure we are authenticated.
    def probe(self) -> dict:
        response = self.session.get(SUBMIT_URL, timeout=self.timeout, allow_redirects=True)
        authenticated = LOGIN_MARKER not in response.url
        payload = {
            "checked_utc": datetime.now(timezone.utc).isoformat(),
            "submit_url": SUBMIT_URL,
            "final_url": response.url,
            "status_code": response.status_code,
            "authenticated": authenticated,
            "cookies": sorted(self.session.cookies.keys()),
        }
        if authenticated:
            form = _parse_form(response.text, response.url)
            payload["form_action"] = form["action"]
            payload["file_field"] = form["file_field"]
            payload["form_fields"] = sorted(form["fields"].keys())
        else:
            payload["error"] = "AAVSO login session is missing or expired"
        return payload

    # Submit one staged AAVSO report file and capture the server feedback.
    def submit(self, report_path: Path) -> dict:
        report_path = Path(report_path).expanduser().resolve()
        if not report_path.exists():
            raise FileNotFoundError(report_path)

        probe = self.probe()
        if not probe.get("authenticated"):
            raise RuntimeError(probe.get("error", "AAVSO login session is missing or expired"))

        page = self.session.get(SUBMIT_URL, timeout=self.timeout, allow_redirects=True)
        form = _parse_form(page.text, page.url)
        files = {
            form["file_field"]: (
                report_path.name,
                report_path.read_bytes(),
                "text/plain",
            )
        }
        response = self.session.post(
            form["action"],
            data=form["fields"],
            files=files,
            timeout=self.timeout,
            allow_redirects=True,
            headers={"Referer": page.url},
        )

        lines = _html_lines(response.text)
        success_lines, warning_lines, error_lines = _classify_response_lines(lines)
        accepted = bool(success_lines) and not any("login session" in line.lower() for line in error_lines)
        out_of_limit = [line for line in warning_lines if "limit" in line.lower() or "range" in line.lower()]

        result = {
            "submitted_utc": datetime.now(timezone.utc).isoformat(),
            "report_path": str(report_path),
            "submit_url": SUBMIT_URL,
            "final_url": response.url,
            "status_code": response.status_code,
            "accepted": accepted,
            "authenticated": LOGIN_MARKER not in response.url,
            "success_lines": success_lines,
            "warning_lines": warning_lines,
            "error_lines": error_lines,
            "out_of_limit_lines": out_of_limit,
        }

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_path = REPORT_DIR / f"aavso_submit_result_{stamp}.json"
        html_path = REPORT_DIR / f"aavso_submit_result_{stamp}.html"
        json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        html_path.write_text(response.text, encoding="utf-8")
        result["result_json"] = str(json_path)
        result["result_html"] = str(html_path)

        if accepted:
            log.info("AAVSO submission accepted for %s", report_path.name)
        else:
            log.warning("AAVSO submission not confirmed for %s", report_path.name)
        if out_of_limit:
            log.warning("AAVSO submission returned out-of-limit warnings for %s", report_path.name)

        return result
