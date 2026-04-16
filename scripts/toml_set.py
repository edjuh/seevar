#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: scripts/toml_set.py
Version: 1.1.0
Objective: Safely update a TOML file by dotted key path for bootstrap and upgrade workflows.
"""

import sys
from pathlib import Path

import tomllib
import tomli_w


def _coerce_value(raw_value: str, value_type: str):
    if value_type == "float":
        return float(raw_value)
    if value_type == "int":
        return int(raw_value)
    if value_type == "bool":
        return raw_value.lower() in ("1", "true", "yes", "on")
    return raw_value


def _ensure_list_size(lst, index: int, next_is_index: bool):
    while len(lst) <= index:
        lst.append([] if next_is_index else {})


def _set_by_path(node, parts, value):
    cur = node

    for i, part in enumerate(parts[:-1]):
        next_part = parts[i + 1]
        next_is_index = next_part.isdigit()

        if part.isdigit():
            index = int(part)
            if not isinstance(cur, list):
                raise TypeError(f"Expected list at path segment '{part}', found {type(cur).__name__}")
            _ensure_list_size(cur, index, next_is_index)
            cur = cur[index]
        else:
            if not isinstance(cur, dict):
                raise TypeError(f"Expected dict at path segment '{part}', found {type(cur).__name__}")
            if part not in cur:
                cur[part] = [] if next_is_index else {}
            cur = cur[part]

    last = parts[-1]
    if last.isdigit():
        index = int(last)
        if not isinstance(cur, list):
            raise TypeError(f"Expected list at final segment '{last}', found {type(cur).__name__}")
        _ensure_list_size(cur, index, next_is_index=False)
        cur[index] = value
    else:
        if not isinstance(cur, dict):
            raise TypeError(f"Expected dict at final segment '{last}', found {type(cur).__name__}")
        cur[last] = value


def main():
    if len(sys.argv) != 5:
        print("Usage: toml_set.py <toml_file> <key.path> <value> <type>", file=sys.stderr)
        raise SystemExit(1)

    toml_path = Path(sys.argv[1])
    key_path = sys.argv[2].split(".")
    raw_value = sys.argv[3]
    value_type = sys.argv[4]

    with toml_path.open("rb") as f:
        data = tomllib.load(f)

    value = _coerce_value(raw_value, value_type)
    _set_by_path(data, key_path, value)

    with toml_path.open("wb") as f:
        tomli_w.dump(data, f)


if __name__ == "__main__":
    main()
