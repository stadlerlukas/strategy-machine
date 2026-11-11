# Delivery validation — 2026-11-03

This is the historical validation record for the original local delivery. The GitHub source distribution excludes saved workspaces and the original packaging checksum manifest. Generate demonstration cases using the README commands before running case reproduction. References below to supplied cases and `SHA256SUMS.json` describe the original delivery, not files included in this repository.

**39 automated tests passed** on CPython 3.12.14 / Windows. The final suite completed in 36.681 seconds. No third-party Python runtime packages are required.

Checks cover hand-calculated accounting, next-open timing, same-session look-ahead prevention, fees, weekend financing, splits/dividends, halts, zero-settlement delisting, shorts, incremental replay, missing/invalid data, risk blocking/reductions, explicit warmup, pause controls, append-only storage, undefined Sharpe and trial statistics.

Integration checks cover intake agreement, restricted expressions, bounded model-proposed research, chronological fold reproduction, hidden holdout access and one-use gate, frozen source/data, signing and continuation, approvals/duplicate prevention, independent reconciliation incidents, interrupted forward-close recovery, stale/future observations, normalization, read-only broker requests, refusal of authenticated redirects and local Host/Origin/CSRF checks. Provider/network payloads use named fixtures, not live credentials.

A real Chromium browser exercised all six stages, created a case from written text, checked missing-owner validation, verified report download links and rendered desktop (1440 px) and mobile (390 px) layouts. No JavaScript errors or mobile page overflow were found. Screenshots were inspected.

Both supplied cases completed baseline/two variations, full validation plus three chronological folds, continuation, synthetic sign-off, one holdout evaluation, 18 shadow replay sessions with daily HTML/JSON, fixture reconciliation and an owner pause. The fixtures declare their invented prices, fees and approvals. They each report **zero actual forward sessions**.

A separate copy of the final source and evidence recalculated both complete case reports. Their numerical metrics and signed trial statistics exactly matched the supplied originals. This was a clean filesystem-copy reproduction, not a Git checkout; the delivery is a source folder/archive rather than a hosted repository.

Re-run from this folder:

```powershell
python -m machine test
python -m machine reproduce --workspace workspaces/demo-trend
python -m machine reproduce --workspace workspaces/demo-reversal
```

Reproduction appends audit events; copy the case if preserving its original ledger head matters. `validation.json` contains the compact machine-readable results. `SHA256SUMS.json` fingerprints delivered files; it is a packaging checksum, not external notarization.

Not established by these tests: live model behaviour, eToro credential/schema compatibility, accurate real instrument fees, data suitability/point-in-time validity, exchange-calendar/feed authenticity, five elapsed forward trading days or profitability. The daily reference engine's capabilities and extensions are documented in the guide. No real or brokerage-demo orders were sent.
