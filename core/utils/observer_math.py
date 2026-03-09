#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/utils/observer_math.py
Version: 1.0.0
Objective: Mathematical utilities for observational astronomy, including Maidenhead grid calculations.
"""

def get_maidenhead_6char(lat: float, lon: float) -> str:
    """
    Converts decimal latitude and longitude into a 6-character Maidenhead grid locator.
    """
    # Offset by 180 and 90 to eliminate negative coordinates
    lon += 180.0
    lat += 90.0

    # Field (1st pair - Letters)
    field_lon = int(lon / 20)
    field_lat = int(lat / 10)
    char1 = chr(ord('A') + field_lon)
    char2 = chr(ord('A') + field_lat)

    # Square (2nd pair - Digits)
    lon_rem = lon % 20
    lat_rem = lat % 10
    char3 = str(int(lon_rem / 2))
    char4 = str(int(lat_rem / 1))

    # Subsquare (3rd pair - Lowercase letters)
    # Convert remaining degrees to minutes (* 60)
    lon_min = (lon_rem % 2) * 60
    lat_min = (lat_rem % 1) * 60
    char5 = chr(ord('a') + int(lon_min / 5))
    char6 = chr(ord('a') + int(lat_min / 2.5))

    return f"{char1}{char2}{char3}{char4}{char5}{char6}"

if __name__ == "__main__":
    # Test for Haarlem
    print(f"Test Haarlem (52.382, 4.601): {get_maidenhead_6char(52.382, 4.601)}")
