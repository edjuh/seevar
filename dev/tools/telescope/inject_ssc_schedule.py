#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/inject_ssc_schedule.py
Objective: Inject a SeeVar SSC payload into a seestar_alp scheduler through
           the Alpaca action wrapper.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PAYLOAD = PROJECT_ROOT / "data" / "ssc_payload.json"
DEFAULT_BASE_URL = "http://127.0.0.1:5555"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
        raise ValueError(f"{path} is not an SSC scheduler payload")
    return payload


def _request_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _action(base_url: str, device: int, action: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/telescope/{device}/action"
    return _request_json(
        url,
        {
            "Action": action,
            "Parameters": json.dumps(params),
            "ClientID": 1,
            "ClientTransactionID": 999,
        },
        timeout,
    )


def _ensure_ok(response: dict[str, Any], label: str) -> None:
    if int(response.get("ErrorNumber", 0)) != 0:
        raise RuntimeError(f"{label}: {response.get('ErrorMessage', response)}")


def _schedule_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    action = item.get("action")
    if not action:
        raise ValueError(f"schedule item without action: {item}")
    params = item.get("params") or {}
    return {"action": action, "params": params}


def inject_schedule(
    *,
    payload_path: Path,
    base_url: str,
    device: int,
    clear: bool,
    start: bool,
    dry_run: bool,
    timeout: float,
) -> int:
    payload = _load_json(payload_path)
    items = payload["list"]

    print(f"payload: {payload_path}")
    print(f"device : {device}")
    print(f"items  : {len(items)}")

    for index, item in enumerate(items, start=1):
        params = item.get("params") or {}
        print(f"{index:02d}. {item.get('action')} {params.get('target_name', '')}".rstrip())

    if dry_run:
        print("dry-run: no scheduler changes sent")
        return 0

    try:
        _ensure_ok(_action(base_url, device, "get_schedule", {}, timeout), "get_schedule")
        if clear:
            _ensure_ok(_action(base_url, device, "create_schedule", {}, timeout), "create_schedule")

        for index, item in enumerate(items, start=1):
            response = _action(base_url, device, "add_schedule_item", _schedule_item_payload(item), timeout)
            _ensure_ok(response, f"add_schedule_item #{index}")

        if start:
            _ensure_ok(_action(base_url, device, "start_scheduler", {}, timeout), "start_scheduler")

    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach seestar_alp at {base_url}: {exc}") from exc

    print("injected")
    if start:
        print("started")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--device", type=int, required=True, help="seestar_alp device number")
    parser.add_argument("--no-clear", action="store_true", help="append instead of replacing scheduler")
    parser.add_argument("--start", action="store_true", help="start scheduler after injection")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    return inject_schedule(
        payload_path=args.payload.expanduser().resolve(),
        base_url=args.base_url,
        device=args.device,
        clear=not args.no_clear,
        start=args.start,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
