#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/utils/observer_math.py
Version: 1.0.2
Objective: Mathematical utilities for observational astronomy, including Maidenhead grid calculations dynamically tested against config.toml.
"""

import os
import tomllib

def get_maidenhead_6char(lat: float, lon: float) -> str:
    """
    Converts decimal latitude and longitude into a 6-character Maidenhead grid locator.
    """
    lon += 180.0
    lat += 90.0

    field_lon = int(lon / 20)
    field_lat = int(lat / 10)
    char1 = chr(ord('A') + field_lon)
    char2 = chr(ord('A') + field_lat)

    lon_rem = lon % 20
    lat_rem = lat % 10
    char3 = str(int(lon_rem / 2))
    char4 = str(int(lat_rem / 1))

    lon_min = (lon_rem % 2) * 60
    lat_min = (lat_rem % 1) * 60
    char5 = chr(ord('a') + int(lon_min / 5))
    char6 = chr(ord('a') + int(lat_min / 2.5))

    return f"{char1}{char2}{char3}{char4}{char5}{char6}"

if __name__ == "__main__":
    config_path = os.path.expanduser("~/seevar/config.toml")
    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        
        test_lat = config.get("location", {}).get("lat", 0.0)
        test_lon = config.get("location", {}).get("lon", 0.0)
        
        if test_lat and test_lon:
            print(f"Test Configuration Coordinates ({test_lat}, {test_lon}): {get_maidenhead_6char(test_lat, test_lon)}")
        else:
            print("Location data not found in config.toml.")
            
    except Exception as e:
        print(f"❌ Config Read Error: {e}")
