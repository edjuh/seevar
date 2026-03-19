# 🤝 Contributing to SeeVar

> **SeeVar — Asthonising Automated Variable Star Observatory**
> *AAVSO compliant. Obviously.*

SeeVar is currently in beta. The most valuable contribution right now
is testing on real hardware and reporting what breaks.

---

## 🐛 Reporting a bug

Open an issue and include:

| Item | Command |
|------|---------|
| Pi model and OS | `uname -a` |
| Bootstrap version | `head -5 ~/seevar/bootstrap.sh` |
| Python environment | `~/seevar/.venv/bin/python3 --version` |
| Which step failed | e.g. "bootstrap aborted at pip install" |
| Relevant log output | `tail -50 ~/seevar/logs/orchestrator.log` |

The more detail the better. Silent failures are the hardest to debug
from 1000km away.

---

## 💡 Suggesting a feature

Open an issue with the label `enhancement`. Describe what you want
the observatory to do, not how to implement it. The ROADMAP is mapped
to the characters of Marten Toonder's Rommeldam — if your idea fits
a character, bonus points.

---

## 🔭 Hardware testing

If you have a ZWO Seestar S30, S30-Pro, or S50 and are willing to
test SeeVar at first light, please open an issue with the label
`hardware-test` and your location (Maidenhead grid is sufficient).

Priority testing regions: 40°–60°N (the seed catalog is optimised
for this declination band).

---

## 📋 Pull requests

SeeVar follows strict architectural conventions documented in
`dev/CONTRIBUTING.md`. Please read that before submitting code.

All Python files require the Garmt header standard:
- `Filename` — relative path from repo root
- `Version` — current milestone version
- `Objective` — one complete sentence describing the file's purpose

---

## 📡 AAVSO observer code

SeeVar submits photometry under the observer's own AAVSO code.
REDA (Ed de la Rie, Haarlem NL) is the development observer.
Your observations will be submitted under your own code — configured
during bootstrap.

---

*"Wij handelen hier volgens de regelen van het fatsoen!"*
