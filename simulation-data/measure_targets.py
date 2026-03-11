#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: ~/seevar/simulation-data/measure_targets.py
Version: 1.0.0
Objective: Simulates photometric reduction by extracting object metadata and calculating synthetic flux from FITS headers and pixel data.
"""

import os
import glob
import csv
from astropy.io import fits
import numpy as np

def extract_measurements(buffer_dir):
    fit_files = glob.glob(os.path.join(buffer_dir, "*.fit"))
    output_file = "simulation_measurements.csv"

    print(f"Reducing {len(fit_files)} images into {output_file}...")

    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Target', 'Filter', 'Exposure', 'Calculated_Mag', 'Status'])

        for fpath in fit_files:
            with fits.open(fpath) as hdul:
                header = hdul[0].header
                data = hdul[0].data
                
                # Mock photometry: "Measuring" flux in the center of the frame
                # Using a 10x10 box to get an average ADU
                mid_y, mid_x = data.shape[0] // 2, data.shape[1] // 2
                aperture = data[mid_y-5:mid_y+5, mid_x-5:mid_x+5]
                mean_flux = np.mean(aperture)
                
                # Convert flux back to magnitude for the measurement
                # This reverses the logic used in the generator
                mag = 15 - 2.5 * np.log10(mean_flux / 150)
                
                writer.writerow([
                    header.get('OBJECT', 'Unknown'),
                    header.get('FILTER', 'CV'),
                    header.get('EXPTIME', 60.0),
                    round(mag, 3),
                    "Measured"
                ])

    print("Photometric reduction complete.")

if __name__ == "__main__":
    target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'local_buffer')
    extract_measurements(target_dir)
