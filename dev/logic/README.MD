# 🧠 SeeVar: Logic & Protocols

> **Objective:** Definitive entry point and table of contents for the architectural law, scientific standards, and roadmap governing the SeeVar observatory pipeline.
> **Version:** 1.9.0
> **Path:** `dev/logic/README.MD`

---

## Purpose

This directory is the doctrinal core of SeeVar.

It defines:
- how the observatory is allowed to behave
- which artifacts are authoritative
- where science truth is established
- what is currently implemented
- what is still being hardened

SeeVar is no longer just a helper around `seestar_alp`.
It has evolved into a sovereign pipeline with its own preflight, flight,
postflight, oversight, and science rules.

---

## Core Documentation

| Document | Purpose |
|----------|---------|
| `CORE.MD` | Chain of command and system doctrine |
| `ARCHITECTURE_OVERVIEW.MD` | High-level structural map of the software stack |
| `STATE_MACHINE.MD` | Canonical `A1-A12` flight chain and state ownership |
| `FLIGHT.MD` | Per-target sovereign flight execution doctrine |
| `POSTFLIGHT.MD` | Canonical `P1-P8` postflight science chain |
| `PHOTOMETRICS.MD` | Differential photometry standards, assumptions, and hardening roadmap |
| `PREFLIGHT.MD` | Go/No-Go pillars and nightly planning doctrine |
| `CADENCE.MD` | Scientific cadence policy |
| `AAVSO_LOGIC.MD` | AAVSO targeting, identifiers, reporting conventions |
| `API_PROTOCOL.MD` | Confirmed hardware/API behavior and protocol detail |
| `ALPACA_BRIDGE.MD` | Alpaca role, device map, and transport notes |
| `SIMULATORLOGIC.MD` | Simulation obligations and flight mirroring rules |
| `WORKFLOW.MD` | Narrative system walkthrough — currently due for rewrite |
| `FILE_MANIFEST.md` | Generated manifest — do not edit manually |

---

## Current Architectural Law

### Canonical nightly handoff

`data/tonights_plan.json` is the authoritative preflight handoff into flight.

Flight must not silently replace planner logic with local ad-hoc scoring.

### Canonical flight chain

Flight now follows the sovereign `A1-A12` chain:

- `A1` Target Lock
- `A2` Safety Gate
- `A3` Session Init
- `A4` Slew Command
- `A5` Slew Verify
- `A6` Settle
- `A7` Pointing Verify
- `A8` Corrective Nudge
- `A9` Exposure Plan
- `A10` Acquire
- `A11` Quality Gate
- `A12` Commit

### Canonical postflight chain

Postflight now follows the sovereign `P1-P8` chain:

- `P1` Ingest
- `P2` Calibration Match
- `P3` Calibration Apply
- `P4` Astrometric Solve
- `P5` Source Measurement
- `P6` Ensemble Calibration
- `P7` Quality Verdict
- `P8` Commit And Report

### Scientific boundary

Flight proves:
- a trustworthy raw frame was captured

Postflight proves:
- that the frame supports trustworthy science

That boundary must remain clean.

---

## Current Version Story

### 1.7.x — Restoration
This phase restored the core nightly contract:
- `tonights_plan.json` as canonical handoff
- dashboard funnel visibility
- cadence reintegration
- planner/orchestrator alignment

### 1.8.x — Flight Hardening
This phase aligned the execution side:
- sovereign `A1-A12`
- simulator vocabulary
- clearer orchestrator ownership
- explicit pointing-verification placeholders

### 1.9.x — Postflight Hardening
This is the current phase.

Focus:
- real astrometric truth in postflight
- real detector calibration in postflight
- more defensible ensemble photometry
- deterministic report staging

---

## Roadmap 1.9.x

### 1.9.0 — Doctrine freeze
- freeze `P1-P8`
- align `POSTFLIGHT.MD`, `PHOTOMETRICS.MD`, and entry docs
- make postflight ownership explicit

### 1.9.1 — Astrometric truth
- require a real solved WCS in postflight
- stop treating header-only geometry as scientific truth
- make unsolved frames fail honestly

### 1.9.2 — Detector truth
- match darks by exposure, gain, and temperature bin
- subtract darks before photometry
- preserve raw custody and derived-calibrated custody separately

### 1.9.3 — Ensemble robustness
- add sigma clipping to the comparison-star ensemble
- record rejected comparison stars
- tighten postflight quality verdicts around survivor count and scatter

### 1.9.4 — Deterministic reporting
- wire accepted postflight results into AAVSO report staging
- make report generation a proper `P8` output, not a side utility

### Later
- flat-field support
- color transformation only where scientifically justified
- optional multi-band reporting once standards and workflow are ready

---

## Astropy Direction

SeeVar contains custom implementations that were written before the full
breadth of `astropy` was appreciated.

Current doctrine:
- prefer established `astropy` solutions where they improve correctness,
  maintainability, and scientific trust
- keep custom code where the problem is genuinely SeeVar-specific:
  Bayer-aware photometry, custody rules, Seestar-specific control flow,
  and mission-state orchestration

This is not a rejection of `astropy`.
It is an ongoing migration toward using it more intelligently.

---

## Documents Needing Attention

### High priority
- `WORKFLOW.MD`
  It still reflects an older pipeline shape and transport layer.
  It should be rewritten to match:
  - Alpaca-era control
  - `A1-A12`
  - `P1-P8`
  - current postflight ownership

### Medium priority
- any module header/objective text that still describes deprecated behavior
- any remaining docs that still describe old direct-TCP flight as current law

---

## Operating Principle

Truth beats elegance.
Scientific honesty beats optimistic automation.
If a frame is not proven, it is not accepted.

That principle governs both code and documentation.
