# DECISIONS.md

Rationale log for design choices in income-portfolio-guardian. Append new
entries at the bottom with a date. Do not delete superseded entries —
strike through or annotate instead, so the history of why stays intact.

---

## 2026-08-14 — Repo created; tier model and decay rule established

**Tier placement of GOF / PDI:** Initially proposed as Tier 1 "capital
preservation" holdings alongside O and VOO. Rejected. Both are leveraged
(PDI ~44% effective leverage) multi-sector credit CEFs whose distribution
rates have exceeded actual earned/NAV total return for multiple years
running — GOF has shown NAV erosion since 2021 (payouts > earnings), PDI's
5-yr NAV total return (~3%/yr) has badly lagged its ~15% NAV distribution
rate. Both also carry premium/discount risk on top of the credit risk.
**Decision:** track both under Tier 2 (diversified income), not Tier 1.
VOO is the closest thing to a true long-horizon compounder in the taxable/
Roth mix and is Tier 1 by default; O is Tier 1 on the strength of its
IG-real-estate profile, understanding it is still equity-beta and rate-
sensitive, not risk-free.

**Decay warning rule (drives `decay_tracker.py` alerts):** A fund is
flagged when return-of-capital % on its distribution stays above 90% for
3+ consecutive distribution periods *while* price/NAV is simultaneously
declining over the same window. Yield alone is not a signal — YMAX's
~60% headline yield against ~17.5% total return since inception is the
reference case for why. Rationale for the 3-period threshold: single-month
ROC spikes are common and often technical/tax-driven; a sustained trend
across a quarter is what indicates the fund is structurally liquidating
itself to fund the distribution.

**Manual-entry-first for ROC data:** No sponsor (YieldMax, Guggenheim,
PIMCO) exposes distribution composition via a stable API. A scraper
against sponsor IR pages is a real option later but will break on page
redesigns with no warning. Starting with manual CSV entry (5 minutes/month)
keeps the decay tracker reliable from day one; scraper is a v2 candidate
once the manual log has enough history to validate scraped values against.

**Tier drift monitor built first:** Requires only live position data
(already available via the existing Schwab API layer) and target %
arithmetic — no new data source, no manual entry, immediately useful for
the $37k Roth rollover deployment decision. Decay tracker requires the
manual ROC log to exist first, so it's sequenced second.

---
