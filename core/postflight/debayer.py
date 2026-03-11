#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/postflight/debayer.py
Version: 1.0.0
Objective: Reference Siril script for fotometrie (Master-Flat -> Green extraction -> Stacking).
"""
# This is a Siril command file. 
# It is stored as .py to remain compatible with the Federation manifest scanner.

# requires 1.2.0
# cd flats
# convert flat_ -out=../process
# cd ../process
# stack flat_ rej 3 3 -nonorm -out=master-flat
# cd ../lights
# convert light_ -out=../process
# cd ../process
# calibrate light_ -flat=master-flat -cfa
# extract pp_light_ -green
# register g_pp_light_
# stack r_g_pp_light_ rej 3 3 -norm=none -out=photometry_final_G
