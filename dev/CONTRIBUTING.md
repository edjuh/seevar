# Contributing to SeeVar

Objective: Defines the technical standards, workflow rules, and header requirements for SeeVar contributors.

Version: 1.3.0

## 1. Garmt Header Standard
Every Python file (`.py`) must begin with a PEP 257 docstring.

Required fields:
- Filename
- Version
- Objective

## 2. Architectural Pillars
All new logic must fall into one of these pillars:
1. PREFLIGHT: data harvesting, vetting, horizon logic, scheduling
2. FLIGHT: hardware orchestration and acquisition via Alpaca-native control
3. POSTFLIGHT: solved astrometry, dark-calibrated photometry, and reporting

## 3. Protocol Reality
SeeVar’s current hardware control path is:

- primary control: Alpaca HTTP on port `32323`
- discovery: Alpaca UDP beacon on port `32227`
- legacy/event paths may still exist in old notes, but are not the primary control doctrine

Do not write new code against the old “TCP 4700 as main control path” assumption.

## 4. Core Logic Constraints
- Never hardcode install-specific paths when a project-root-relative or config-based path will do.
- Current production photometry is raw Bayer-green, untransformed `TG`.
- Production photometry should not depend on naive debayering.
- If a frame is not proven by calibration/WCS/QC, it must not be accepted.

## 5. Pull Request Protocol
Before merging:
1. Verify the logic docs still reflect the real architecture.
2. Run the regression tests in `dev/test_*.py`.
3. Keep changes scoped and scientifically honest.

