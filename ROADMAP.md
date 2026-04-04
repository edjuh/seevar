# 🗺️ S30-PRO Development Roadmap: The Rommeldam Epic

> **Objective:** Tracks the architectural journey and future versioning milestones of the Seestar Federation, mapped to the characters of Marten Toonder's universe.
> **Version:** 1.9.0 (Snotolf)

# 🗺️ SeeVar Development Roadmap: The Rommeldam Epic

> **Objective:** Track the architectural journey, scientific hardening, and future versioning milestones of the SeeVar observatory.
> **Version:** 3.1.0 (Fliep)

This roadmap records where SeeVar has been, where it is now, and what must
be hardened next.

SeeVar began as a helper around existing Seestar tooling and evolved into a
sovereign observatory pipeline. That evolution was not linear. Some parts
matured faster than others. The current roadmap reflects a shift from
discovery and control toward scientific trust.

---

## ✅ Past Milestones (The Foundation)

* **v0.0 Beunhaas:** Environment validation.
* **v0.1 Brigadier Snuf:** The state engine.
* **v0.2 Zedekia Zwederkoorn:** The Alpaca bridge patch.
* **v0.3 Joris Goedbloed:** Target acquisition.
* **v0.4 Zachtzalver:** Command translation.
* **v0.5 Hiep Hieper:** The orchestrator.
* **v0.6 Insp. Priembickel:** Hardening and git strictness.
* **v0.7 Argus:** The autonomous observer.
* **v0.8 Lieven Brekel:** Weather aborts and WCS bridge hardening.
* **v0.9 Terpen Tijn:** Westward priority, centroiding, and stable control handshake.
* **v1.0 Kwetal:** Orchestrator as a daemon.
* **v1.1 Pee Pastinakel:** Dynamic aperture scaling and saturation detection.
* **v1.2 Garmt:** Standardization and header discipline.
* **v1.3 Monkel:** Discovery phase and subnet awareness.
* **v1.4 Kriel:** gpsd integration and control centralization.
* **v1.5 Humpie:** Storage and wear strategy.
* **v1.6 Jochem:** Cadence filtering, ledger authority, and full simulation confirmation.
* **v1.7 Oene:** Clean-slate reinstall milestone and installability restoration.

---

## 🌲 Epoch 1: Het Kleine Volkje (v1.x)

*The invisible, tireless workers in the background. Focuses on resilience, control, and scientific hardening.*

### v1.8 Snotolf — The Hardware Whisperer
**Status:** largely completed

Delivered in this era:
- weather veto integration
- cloud logic redesign
- field rotation model
- exposure planner hardening
- Alpaca breakthrough on port `32323`
- `pilot.py` Alpaca rewrite
- dark library moved onto Alpaca path
- dashboard and telemetry improvements
- simulator and CI groundwork

This was the control-plane breakthrough.
It proved that the hardware could be driven cleanly and directly.

---

### v1.9 Fliep — The Scientific Hardening Release
**Status:** current epoch

This is the present chapter.

The focus of `v1.9.x` is not discovering more control features.
It is making the science chain defensible end-to-end.

#### ✅ Already established in 1.9
- `tonights_plan.json` restored as the canonical nightly handoff
- planner/orchestrator contract cleaned up
- simulator aligned to `A1-A12`
- flight doctrine frozen around `A1-A12`
- postflight doctrine frozen around `P1-P8`
- photometry doctrine rewritten around Bayer-aware measurement rather than naive debayering
- docs now reflect that flight and postflight have separate responsibilities

#### 1.9.0 — Doctrine Freeze
- freeze sovereign `A1-A12`
- freeze sovereign `P1-P8`
- align logic docs with actual architectural ownership
- make the scientific boundary explicit:
  - flight proves raw capture
  - postflight proves scientific trust

#### 1.9.2 — Detector Truth
Completed:
- match darks by exposure, gain, and temperature bin
- subtract darks before science photometry
- preserve raw custody and calibrated working custody separately
- validate the dark-calibration path with synthetic regression tests

#### 1.9.3 — Ensemble Robustness
Completed:
- add sigma clipping to the comparison-star ensemble
- record rejected comparison stars and final survivor count
- tighten quality verdicts around ensemble stability and zero-point scatter

#### 1.9.4 — Deterministic Reporting
Next:
- wire accepted postflight TG results into AAVSO report staging
- make report generation a true `P8` output
- stop treating the reporter as a side utility

#### 1.9.5 — Astropy Review Pass
- replace custom code with `astropy` components where that improves correctness and maintainability
- keep custom implementations only where the problem is genuinely SeeVar-specific:
  - Bayer-aware photometry
  - Seestar-specific hardware control
  - custody/state workflow
- perform a helicopter-view audit of places where Astropy is the better answer

#### 1.9.x also includes
- rewrite `WORKFLOW.MD` to match current Alpaca-era reality
- remove stale TCP-era doctrine from remaining docs
- validate first-light postflight on real frames before widening scope again

---

## ☕ Epoch 2: The Women of Rommeldam (v2.x)

*The caretakers and organizers. Focuses on bringing order, calibration, and scientific polish to the raw data.*

### v2.0 Anne Marie Doddel — The Hardened Observatory
**Target theme:** first fully defensible end-to-end science release

Planned:
- flat-field pipeline fully operational
- detector-calibrated photometry as standard
- robust postflight archive products
- comparison-star reconciliation: Gaia DR3 vs AAVSO VSP
- production-ready AAVSO output path
- first validated first-light science release on Wilhelmina

### v2.1 Anne-Miebetje
- sub-version stabilization after first-light lessons

### v2.2 Wobbe
- stable technical build and operational polish

### v2.3 Wolle
- stronger plotting, light curves, and result visualization

### v2.4 Irma
- narrow, annoying bug-fix release

### v2.5 Prettig
- usability and operator comfort improvements

### v2.6 Zonnetje
- optimistic feature release after scientific baseline is trusted

### v2.7 Agatha
- more official and business-grade observatory behavior

### v2.8 Georgette
- second telescope integration and broader federation capability

### v2.9 Tante Pollewop
- final polish across calibration, reporting, and user experience

---

## 🧠 Epoch 3: De Medici & Analisten (v3.x)

Focus:
- deep analytics
- long-term quality monitoring
- observing performance feedback
- multi-night ensemble reasoning

Possible themes:
- solve statistics over time
- photometric drift tracking
- nightly quality scoring
- automatic campaign feedback into planning

* **v3.0 Zielknijper:** The basis for the psychological stability of the code.
* **v3.1 Galzalver:** Plasters for the small wounds (hotfixes).
* **v3.2 Dr. Plus:** Added value and positive data-processing results.
* **v3.3 Alexander Pieps:** Refined data analysis down to the square millimeter.
* **v3.4 Sickbock:** Boundary-pushing (and risky) experimental features.
* **v3.5 Okke Zielzoeker:** Deep-diving into user analytics.
* **v3.6 Dr. Baboen:** Solid medical support under the hood.

---

## 🏛️ Epoch 4: De Bureaucratie & Middenstand (v4.x)

Focus:
- strict compliance
- immutable auditability
- stronger submission administration
- official reproducibility and provenance

This is where SeeVar becomes not only scientifically effective, but administratively impeccable.

* **v4.0 Ambtenaar Dorknoper:** *"Dat is buiten de voorschriften."* Strict AAVSO compliance, immutable audit logs, and official submissions.
* **v4.1 Bulle Bas:** Enforcement of security and protocols.
* **v4.2 Notaris Canteclaer:** The fine print and legally correct handling.
* **v4.3 Dickerdack:** The mayor keeping the entire pipeline running smoothly.
* **v4.4 Grootgrut:** Inventory management and database handling.
* **v4.5 Pastuiven Verkwansel:** The secretary keeping the file systems ordered.
* **v4.6 Ambtenaar Plof:** Heavy lifting for massive datasets.
* **v4.7 Referendaris Lapsnuut:** The administrative finishing touch.

---

## 🍷 Epoch 5: De Adel & De Kleine Club (v5.x)
*Focuses on high-society UI/UX and elite processing. "Een release voor luyden van stand."*
* **v5.0 Markies de Canteclaer:** The place of honor. A GUI so refined the rabble won't understand it.
* **v5.1 Graaf van Zandbergen:** A solid, noble UI foundation.
* **v5.2 Baron de l'Esprit:** Refined, intellectual algorithms.
* **v5.3 Jonker Wip:** A light-footed, snappy UI update.
* **v5.4 Oud-majoor Buitenzorg:** Background discipline and memory management.
* **v5.6 De heer Steinhacker:** Industrial-grade optimizations for heavy capital logic.
* **v5.8 Notaris Fijn van Draad:** The perfect aristocratic administrative closure.

---

## 🔮 Epoch 6: Het Magische Bos (v6.x)
*Focuses on complex, inexplicable, and esoteric software forces.*
* **v6.0 Hocus Pas:** Where the true magic happens (machine learning/AI integration).
* **v6.1 Zwarte Zwadderneel:** Edge-cases and error handling. *Log requirement: System must state "Deze update is gedoemd te mislukken" on startup.*
* **v6.2 De Zwarte Raaf:** Mysterious, lightning-fast data transfer protocols.
* **v6.3 Oene de Reus:** Brute-forcing massive chunks of unstructured data.
* **v6.4 Argus de Draak:** Guarding the treasure room (advanced encryption/security).
* **v6.5 De Gnoom:** Deep, hidden underground scripts.
* **v6.6 De Heks van de Nevelvallei:** Advanced image filters peering through fog/clouds.
* **v6.7 Magister Morya:** Esoteric and highly abstract functions.

---

## 🔬 Epoch 7: De Wetenschappers & Fenomenologen (v7.x)
*Focuses on heavy mathematics, deep astrophysics, and phenomena.*
* **v7.0 Professor Prlwytzkofsky:** Phenomenological consistency of the night sky. *Log requirement: All fatal exceptions must be rendered in phonetic Polish ("Praw!").*
* **v7.4 Joachim Snerle:** Detecting "earthly" influences (atmospheric refraction compensation).

---

## 💰 Epoch 8: De Zware Jongens & De Handel (v8.x)
*Focuses on pure efficiency and data brokering. "Geld moet rollen!"*
* **v8.0 Bul Super:** The Boss. "Zaken zijn zaken." *Requirement: Bug reports only accepted if accompanied by a "commission."*
* **v8.1 Knol:** The muscle. Smashing through database bottlenecks.
* **v8.2 De Markelaar:** The broker. External API connections and data trading.
* **v8.3 De Lorreman:** Garbage collection and archiving. *Note: "Geen bug is te klein voor de handel."*
* **v8.5 O. Fanth Mzn:** The media magnate. Publishing and exporting final results to the web.
* **v8.6 Super-Hieper Transit:** Lightning-fast internal logistics and bus transfers.
* **v8.7 De Kassier:** The final financial and administrative wrap-up.


## Astropy Position

SeeVar contains some custom implementations that exist because the project
grew organically and not every useful Astropy capability was recognized at
the beginning.

Current roadmap position:
- use Astropy more where it is clearly the better scientific foundation
- avoid rewriting well-tested astronomy primitives just for sovereignty
- keep custom code where it captures genuine SeeVar-specific behavior

This is a maturity step, not a retreat
