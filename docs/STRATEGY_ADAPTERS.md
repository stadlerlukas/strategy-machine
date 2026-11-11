# Strategy interfaces

A strategy receives completed daily history and a parameter dictionary, and returns signed target NAV fractions. The engine calculates quantities at the next opening mark, applies costs and independently checks the policy. Today's closing price is never supplied to its opening decision.

## Restricted expressions

An expression runs once per `symbol`; `n_assets` is the universe size. Calls: `price(symbol, lag)`, `sma(symbol, window)`, `std(symbol, window)`, `momentum(symbol, lag)`, `zscore(symbol, window)`, `feature(name, symbol, lag)`, `param(name)`, `abs`, `min`, `max`. Arguments are positional. Lag zero means the latest completed observation.

Example software-only rule:

```json
{"kind":"expression", "expression":"param('allocation') / n_assets if price(symbol) > sma(symbol, param('lookback')) else 0", "params":{"allocation":0.4,"lookback":20}}
```

Arithmetic, comparisons, boolean operations and conditional expressions are supported by a manually interpreted AST. Imports, attributes, indexing, comprehensions and statements are rejected. This is not Python eval. Insufficient lookback yields zero exposure; a missing required feature fails. Statistical windows crossing splits require a suitable signal adapter; accounting prices stay unadjusted.

The bundled momentum and reversal rules are demonstrations. They reset their signal windows around splits and inactive instruments. Neither is an investment recommendation.

## Reviewed Python

A daily strategy module exposes:

```python
def targets(history, params):
    # history: [(date_string, {symbol: validated_bar}), ...]
    return {symbol: 0.0 for symbol in history[-1][1]}
```

Configuration specifies `kind: python`, source `path`, SHA-256 of its UTF-8 text, and `params`. The UI requires explicit code review. Registration embeds that source into the immutable configuration for portable reproduction.

These modules execute with the process's permissions; they are **not sandboxed**. They could access files/network/credentials if written to do so. Run reviewed code only. A reproducible adapter must use supplied past data, be deterministic, avoid external I/O and avoid mutable module state. It is instantiated afresh for each target calculation. External packages or imports require an explicitly versioned runtime and validation.

## Capability gaps

Ticket-specific stops/holding periods, intraday bars, options expiry/exercise, futures roll/margin, order-book execution, FX, incomplete dynamic panels and learned-model fitting need additional interfaces. A signal module cannot supply missing accounting semantics. Extend the relevant data, execution or fitting interface, add hand-checkable tests, and create a documented successor case carrying prior trial exposure.

Chronological validation uses expanding completed history for signals and resets to flat capital per validation block. It does not re-fit a predictive model. A learned strategy needs an adapter that fits only past data and freezes its model artifact per fold.

## Revisions

Signing freezes a case. Preserve it; create a successor with the changed hypothesis/configuration/source, explain the change and include past searches in `prior_trials`. Previously inspected holdout becomes development evidence. New folders do not make old data unseen; obtain genuinely untouched data or future observations for a new out-of-sample assessment.
