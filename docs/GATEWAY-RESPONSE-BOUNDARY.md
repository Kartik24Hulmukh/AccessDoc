# Provider response boundary and September launch gates

The gateway streams provider completions using the existing pooled requests session.
`GATEWAY_MAX_RESPONSE_BYTES` defaults to 1,048,576 decoded bytes and must be a positive integer. The limit applies after HTTP decompression; do not raise it without measuring memory under concurrent completions. A response exactly at the limit is accepted. Invalid/non-object JSON is treated as an empty completion. Every response closes on success, overflow, parse failure or stream exception. Non-200 bodies are not consumed; status and headers (including Retry-After) drive routing. Usage from discarded error bodies is unavailable.

A decoded overflow is a 502-class **internal gateway attempt failure**, feeding existing circuit breaking and fallback. An elapsed deadline observed between chunks is a 504-class attempt failure. These are not promises that all API calls return 200: missing deployment credentials still produce a deliberate 503.

## Explicit limits

- Requests connect/read timeouts are inactivity bounds, not strict total cancellation. DNS, slow headers, or a slow-drip stream within one decoded chunk can exceed the admission deadline. Strict cancellation remains a release gate; moving blocking I/O into a thread alone would not cancel the work.
- Decoded bytes are bounded, but JSON object allocation and decompressor buffers add overhead. This is not an RSS ceiling for the process.
- Existing token admission uses reported usage. Prompt/reasoning tokens, missing usage, and timed-out provider work prevent a guaranteed billing ceiling. Enforce provider/account quotas and alarms independently.
- Transport is synchronous pooled HTTP, not an async connection-pool refactor. No untested architectural rewrite is claimed.
- Actual ingestion is bounded axe-core JSON; generated artifacts span PDF/HTML/OpenACR/SARIF/VPAT. OCR and arbitrary document upload are not supported product claims.

## Reproduction

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p 'test_gateway*.py'
python scripts/concurrent_bench.py
python scripts/hosted_soak.py --seconds 30 --workers 16
# Only with an operator-approved provider budget and a secret in the environment:
python scripts/gateway_bench.py
```

Nine new tests cover exact boundary, chunk overflow, decoded gzip expansion, ignored 429 bodies, invalid/deep non-object JSON, stream failure cleanup, deadline observation, invalid configuration, and real-socket gzip expansion followed by successful recovery.

## Five-point premortem

| Failure | Control/evidence | Remaining gate |
|---|---|---|
| Oversized JSON, ZIP bomb or provider gzip response exhausts RAM | Existing ingress/ZIP limits; new decoded provider cap; real gzip regression | Same-process RSS plateau and deployed peak-memory soak |
| Worker saturation or slow-drip provider stalls pool | Admission control, queue bounds, timeouts, circuit breakers, overload/recovery tests | Strict cancellation and connection/DNS/slow-drip chaos |
| OCR/parser scope misrepresented | Only axe JSON is accepted; hostile/oversized JSON rejected | Do not sell arbitrary PDF/DOCX/OCR ingestion |
| Provider 429/5xx cascade or bill shock | Shared breakers, Retry-After/backoff, fallback, usage admission | Provider token-accounting reconciliation, account quotas and alerts |
| Green health masks unusable AI or no market traction | Health discloses gateway.configured; browser bundle journey verified | Owner secret install, authenticated remediation, collector/alerts, three design-partner handoffs |

## Product release posture

Keep September 16–17 scoped to a bounded accessibility-evidence beta. Activation metric: time from first valid scan upload to a successfully verified bundle. Record accepted-bundle rate, fallback rate, cost per successful remediation, and seven-day repeat usage. Obtain three actual design-partner handoffs; no numeric traction improvement is asserted without users and a baseline.

Both credentials supplied in the conversation should be rotated after this delivery. Do not place them in source, PR text, benchmark artifacts or command examples. The deployment owner must install the rotated Melious secret in the production environment, redeploy, and run authenticated remediation before enabling the AI feature.
