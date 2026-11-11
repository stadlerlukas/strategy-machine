# Accounting and statistical methods

## Accounting

Signals use completed sessions and rebalance at the next supplied opening mark. Signed target fractions become units using opening NAV. Reductions are considered first; costs reduce equity and after-fee exposure is checked per order. Blocking can make the realized portfolio differ from ideal targets. The same rules operate in research and shadow mode.

Cost per fill is absolute notional × (half the declared full spread + commission bps + slippage bps) / 10,000 + fixed fee. Financing/borrow apply to held notional for actual elapsed calendar days / 365. Annual inputs are assumptions, not fetched broker terms. Idle cash earns no interest. Splits adjust units; dividends affect cash; delistings use explicit settlement including zero. Halted instruments use supplied marks and cannot fill. Final positions remain marked rather than forcibly closed.

Gross performance adds costs back along the same position path. It is not a separately rebalanced cost-free strategy. Dollar attribution is reconciled independently to NAV changes. Margin liquidation, liquidity/volume, partial fills, FX, intraday price paths and eToro ticket accounting are not inferred.

## Statistics

Sharpe uses sample standard deviation of session excess returns and the configured periods/year. The annual risk-free rate is converted to a session rate. Undefined results remain null. Annualization assumes the declared session cadence; irregular data needs review.

Turnover counts absolute traded notional / prior NAV on both buys and sells separately, annualized without halving. Break-even transaction bps describe fixed-path capacity after financing divided by traded exposure; negative values are possible. Return, CAGR, volatility, drawdown and average trades/session are also calculated.

The Sharpe interval uses a fixed-seed moving-block bootstrap with five-observation blocks and 160 resamples. It is a coarse descriptive diagnostic, especially weak for short histories, not a precise claim about changing regimes.

DSR follows [Bailey and Lopez de Prado, The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf). This implementation uses comparable local training-Sharpe dispersion and all declared development/validation attempts, including failures, repeats and prior external attempts, in an IID moment approximation. Serial dependence is not corrected. Inadequate sample/dispersion produces null and blocks sign-off. More experiments are not automatically better evidence.

Effective trials use the participation ratio of aligned local return correlations. This is a heuristic, not a measured true independent search count; it does not lower the raw count used for DSR. The system cannot reconstruct undisclosed external searches or their dependence/dispersion. Declare previous searches. DSR is not a guaranteed probability of future profit.

Draft expected ranges are observed min/max Sharpe, turnover and break-even bps across recorded development/validation runs. They describe sensitivity, not predictive intervals. Signing preserves those generated ranges; independently calibrated predictive ranges would need their own method and evidence. Holdout/shadow observations are compared without editing the ranges.

Beta and annual arithmetic residual use the equal-weight configured universe. This is descriptive attribution, not a multi-factor model or proof of alpha. Another benchmark requires a validated adapter. Instrument P&L, transaction costs and financing are shown separately.

## Evidence boundaries

Inputs, costs, policy and Python engine source hashes are frozen. Holdout is protected by application gates, not OS access restrictions: the owner or trusted Python code could read it outside the workflow. Signatures are local named timestamps, not verified digital identity.

Runs have durable starts before evaluation. Failed/interrupted attempts remain in trials.csv. Reports rerun numerical calculations, compare signed statistics and verify the event/artifact chain. Reproduction is logged separately from experiments. Continuation uses the real loader with an extra synthetic year; repeated future features are operational scaffolding, not forecasts.

The manifest covers Python files under `machine/`. UI/documentation changes are not numerical dependencies. Preserve the runtime version for exact reproduction. Changed engine code deliberately requires a documented migration, not modified historical results. Clean-copy reproduction tests portability/determinism, not the truth of financial assumptions.
