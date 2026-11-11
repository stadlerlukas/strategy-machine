# Optional integrations

## OpenAI

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in the process environment before starting. Choose a model supporting Responses API structured JSON outputs. The integration calls `https://api.openai.com/v1/responses` with `store: false`; provider retention policies still apply, so this is not a blanket no-retention guarantee. Requests provide no tools to the model. Authenticated requests refuse redirects.

Intake advice labels assumptions and proposes data requirements/sources. Implementation either proposes a restricted expression or identifies an adapter gap. Setup proposals leave unresolved values empty. Bounded research receives explicit parameter bounds and a trial budget, and each candidate goes through the same deterministic research runner. It cannot change data, fees or policy, sign a document, approve a proposal or place an order. Risk interpretation references computed fact IDs and still needs human verification.

Prompts live in `machine/intake.py`, `machine/agents.py` and `machine/application.py`. The user-mediated alternative is described in `agent_prompts/WORKING_CONTRACT.md`. No hidden autonomous background agent is required. Provider payloads and responses were tested using fixtures; authenticated model acceptance requires the user's selected model/key.

Primary reference checked 2026-11-03: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## eToro read-only transport

Set `ETORO_API_KEY` and an environment-specific `ETORO_USER_KEY` before launch. Use read-scoped keys for the intended demo/real account. Real reading is explicitly selected.

| Resource | Demo route | Real route |
|---|---|---|
| portfolio | /api/v1/trading/info/demo/portfolio | /api/v1/trading/info/portfolio |
| history | /api/v1/trading/info/trade/demo/history | /api/v1/trading/info/trade/history |
| quotes | /api/v1/market-data/instruments/rates | same market-data route |

Only GET is implemented. Headers are x-api-key, x-user-key and a fresh x-request-id. Transient errors retry at most three times. Credentials/response bodies are not included in transport error messages. Raw account data is saved locally and may be private; protect the workspace and backups. No secret should be placed in case settings or reports.

Portfolio fetching is in the UI; history and quotes use the CLI `etoro` action. Before fetching history, commit the risk mandate. Supply `minDate`, optionally `page` and `pageSize`, in `params`. The adapter rejects lookbacks older than 364 days. Each call fetches one explicitly requested page: iterate and verify completeness yourself or add a provider-specific acquisition adapter. A single page is not declared complete account history. Use authorized exports for older periods. Closed trades are not automatically converted into daily NAV.

Example arguments, with date/environment to be reviewed:

```json
{"mode":"demo","resource":"history","params":{"minDate":"2026-11-01","page":1,"pageSize":100}}
```

```powershell
python -m machine action --root workspaces --case my-case etoro --args broker-read.json
```

Use `normalize_snapshot(raw, mapping)` only after verifying actual fields and units. Supply dotted paths for cash, positions, instrument ID and signed units plus an ID-to-symbol map. Multiple positions are summed only after signed-unit semantics are established. Copying, margin, FX, financing and cash conventions must match the reference model; otherwise a suitable accounting adapter is needed.

Primary documentation checked 2026-11-03: [API index](https://api-portal.etoro.com/llms.txt), [authentication](https://api-portal.etoro.com/core/getting-started/authentication), [demo portfolio breakdown](https://api-portal.etoro.com/api-reference/trading--demo/get-demo-portfolio-breakdown), [real portfolio breakdown](https://api-portal.etoro.com/api-reference/trading--real/get-portfolio-breakdown), [demo history](https://api-portal.etoro.com/api-reference/trading--demo/list-trading-history), [real history](https://api-portal.etoro.com/api-reference/trading--real/list-trading-history), [instrument rates](https://api-portal.etoro.com/api-reference/market-data/get-instrument-market-rates). Routes were checked against documentation; live credentials and actual account schema validation remain outstanding.
