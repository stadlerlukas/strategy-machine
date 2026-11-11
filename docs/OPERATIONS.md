# Operating routine

## Historical replay

After sign-off, select a normalized CSV in Operate. Each proposal uses only the next session. The owner approves or rejects the saved proposal. Rejection retains existing positions while prices, corporate actions and financing are still accounted for; it does not flatten the portfolio.

Recording pause or manual activates the kill switch. Keep does not silently release it; release requires its own named decision in Operate.

The kill switch blocks proposals/approvals; it sends no liquidation orders. Exposure-reducing orders can pass binding risk limits when proposed and approved. Market moves can breach a limit after a fill; the close review records this and later orders are checked again. Daily checks are not intraday guaranteed stops.

Each committed session writes factual HTML and JSON. Reconcile against independently observed cash and signed units. Mismatches create incidents. Copying the same book is not independent reconciliation; demo matching snapshots are labelled synthetic fixtures.

After an interruption between decision and book commit, use the idempotent `recover` action. For a saved forward close, use `forward_recover`. Do not submit duplicate approvals. Restarting restores state from disk.

## Forward observation

Use a separately signed, non-synthetic case with real historical evidence; do not mix replay into it. Before the first opening observation, optionally **Seed signal history** from a completed historical CSV ending before today. This starts a flat book at the configured capital and imports no old positions or P&L. Portfolio statistical-risk measures still follow the declared warmup policy.

Example opening snapshot (replace every illustrative value with verified current data):

```json
{
  "stage":"open", "observed_at":"2026-11-03T09:00:00+00:00",
  "session_date":"2026-11-03", "source":"your verified feed and mapping",
  "provenance":"forward_observed",
  "rows":[{"date":"2026-11-03","symbol":"EXAMPLE","open":100,"close":100,"status":"active","split":1,"dividend":0,"settlement":null}]
}
```

Include all configured instruments. Opening close marks must equal their opens. The timestamp must be timezone-aware and within ten minutes of real host time, with at most thirty seconds of future clock skew. The session date must equal the current UTC date.

Approve within ten minutes of the opening timestamp or reject the stale proposal. The paper fill convention uses the original observed opening marks plus configured costs; it makes no claim that a later real order could obtain them. At the later close, supply `stage: close`, a fresh later timestamp and actual closing marks. Date, symbol, open, split and dividend must match the opening facts. Changed facts stop processing for investigation rather than silently rewriting earlier evidence.

The close replays the saved decision and checks that closing information did not alter opening orders. Recover interrupted commits using the saved proposal ID. Only completed and committed forward dates count. Feed authenticity and exchange holidays need independent verification. Sessions crossing UTC midnight, other session conventions or missed closing imports require a calendar/feed extension; never falsify timestamps.

Daily routine: opening observation → proposal → decision → later close → daily report → independent reconciliation → regenerated report → owner decision. Observe at least five actual trading days and retain all daily evidence, including no-trade sessions. The counter alone is not the full course acceptance package.

## Statistical warmup

Missing prices, fees or required features stop evaluation. In the mandate explicitly choose:

- `block_increases`: block new exposure while rolling volatility/full correlation history is unavailable; reductions can continue.
- `static_limits`: explicitly permit warmup under static exposure, position, group, drawdown and turnover limits while statistical gaps are reported.

Volatility uses up to thirty completed portfolio returns and needs twenty. Correlation needs thirty-one valid completed price observations. Flat initial portfolio returns do not establish the risk of a new position. Declare shared economic-driver groups; correlations are descriptive. Neither mode claims full statistical coverage before enough data exists.

## CLI

UI and CLI share the same service:

```powershell
python -m machine action --root workspaces --case my-case forward_open --args open-args.json
```

The file contains `{"snapshot": <full snapshot>}`. Other actions:

| Action | Argument keys |
|---|---|
| forward_seed | path (completed historical CSV) |
| forward_decide | proposal_id, approve (boolean), actor, reason |
| forward_close | proposal_id, snapshot |
| forward_recover / recover | proposal_id |
| shadow | path (normalized replay CSV) |
| decide | proposal_id, approve, actor, reason, synthetic |
| reconcile | snapshot: date, cash, units, provenance |
| kill | active, actor, reason |
| review | optional history_path; committed plan required |
| human_decision | decision: keep/adjust/pause/manual, actor, reason |
| report / audit | no arguments |

Run one local server/process per case. The UI serializes actions; SQLite unique claims and head checks protect duplicate decisions. Competing CLI writers are outside the intended single-owner model.
