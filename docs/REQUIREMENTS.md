# Requirements and delivery map

The product is a reusable research-and-control system. The owner supplies a written strategy; the agent and owner clarify its rules and data requirements. The output is evidence and operational decision support, rather than an automatic assertion that a strategy is good.

Sources supplied by the owner: **Research Agent Task.pdf** (12 pages), **Research Agent Task 2.pdf** (1 page), and **Active Trading Track _ eToro Pro Investor Hub.pdf** (7 pages). These are reference documents, not authorization for brokerage access. Existing VXX research was not integrated or changed. Course dates and intermediate milestones are replaced by one integrated delivery as requested.

| Requirement | Implementation / evidence |
|---|---|
| Written idea first; reusable system | Preserved original description, questions, assumptions and owner acceptance; independent cases; expression and reviewed Python interfaces |
| Falsifiable economic hypothesis | Intake plus frozen configuration and signed specification |
| Baseline and one-change comparisons | Named baseline, exactly one strategy parameter leaf; fixed costs, universe, data, policy and source |
| Per-instrument costs; missing fees fail | Required spread, commission, slippage, fixed fees, financing/borrow, source/date, cash/CFD and shortability |
| Every attempt logged | Durable start before evaluation, completed/failed/interrupted statuses, trials.csv and declared external prior attempts |
| Separate validation and robustness | Chronological validation, fixed-rule expanding-history folds, descriptive block bootstrap, halt/delisting continuation |
| Trial count, effective trials, DSR | Raw disclosed attempts, correlation participation-ratio heuristic, documented IID DSR; unavailable values stay unavailable |
| Machine-readable specification before holdout | Hypothesis, universe, signal, holding, costs, ranges, kill criterion, trials and source/data hashes, named timestamped attestation |
| Holdout gate | Hash/copy without parsing at registration; one permit after signing; failed access does not restore innocence |
| Report-last / reproducibility | Numerical rerun before report, signed trial-statistic comparison, event/artifact verification, separate clean-copy check |
| Continue beyond project dates | Extra synthetic year through the real CSV loader, halt and delisting; no mocked cutoff; explicitly not financial forward evidence |
| Risk plan before selected history review | Dated commitment, chosen measures/ranges/reasons and adverse-performance template; gated history import/review |
| Hard limits independent of AI | Order/exposure checks, group limits, drawdown, volatility, turnover, shortability, missing inputs and explicit statistical warmup policy |
| Simulated blocked order | Oversized entry, drawdown, missing data, unavailable short and permitted reduction tests |
| Reviewer explains; owner decides | Factual review, optional evidence-referenced AI interpretation with no order tools, keep/adjust/pause/manual record |
| Controlled operations | Durable proposals, decisions, kill switch, interrupted-commit recovery, cash/units reconciliation and incidents |
| Reporting and attribution | HTML tear sheet, evidence JSON, trials CSV, daily HTML/JSON, descriptive benchmark/instrument attribution, costs, performance note and adverse-performance template |
| Five actual forward trading days | Fresh opening proposal, timely decision, later close, daily report and reconciliation workflow; elapsed observed days remain to be collected |

The overview describes research, risk, operation and reporting. Detailed additional operation/reporting task sheets were not supplied. Their scope follows the overview and agreed definition; undisclosed marking criteria cannot be certified.

## Remaining acceptance activities

- Agree an actual strategy/mandate and acquire authorized point-in-time data with verified costs. Profitability is not a software acceptance result.
- Test the optional AI provider with the user's chosen model/key.
- Verify actual eToro permissions, instrument identifiers, field semantics and costs. Transport was tested with fixtures, without account access.
- Observe five actual exchange trading days, verifying the feed/calendar and retaining approvals, daily reports and independent reconciliations. Timestamp checks alone cannot prove feed authenticity or calendar correctness.
- Add and validate capabilities outside the daily engine when a future strategy requires them. Reusability is an extension contract, not a claim that every conceivable strategy is already implemented.

Broker-demo and real-money execution are outside this release. The agreed operational demonstration is shadow operation; an order connector would need separate implementation and acceptance.
