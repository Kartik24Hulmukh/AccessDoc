# Optional gateway readiness contract

`GET /readyz` on both adapters exposes a passive `gateway` snapshot. Polling does not initialize the gateway, call a model, or spend credits.

| Field | Meaning |
|---|---|
| `configured` | Nonblank `MELIOUS_API_KEY` exists; not an authentication check. |
| `status` | `degraded` for a known missing key or billing hold; otherwise `unknown`, not an assertion that a live model is reachable. |
| `degraded_reasons` | `not_configured`, `billing_exhausted`, or an empty list. |
| `billing_exhausted` | The process-local account-wide billing hold is currently active. |
| `billing_retry_after_seconds` | Rounded-up remaining hold time, zero after expiry. This is a local retry hint, not proof of restored provider credits. |

AI is optional: the deterministic evidence-bundle service and static remediation remain usable during a billing hold. Therefore a hold does not change the core readiness HTTP code to 503. Self-hosted `READY=False` still returns 503; liveness semantics are unchanged. Operators should alert on `gateway.degraded_reasons`, not restart healthy core instances on account exhaustion.

The billing snapshot is consistent under one lock and monotonic-clock sample. Breaker snapshots retain their existing semantics. Holds are process-local, not a distributed provider-account health guarantee. Readiness does not certify model success, OCR availability, or production capacity.

## Recovery

1. Check account credits with the provider without exposing credentials in logs.
2. Wait for the configured `GATEWAY_BILLING_COOLDOWN_SECONDS` hold (default 300 seconds) to expire.
3. Run `python scripts/gateway_bench.py --output gateway-live.json` with a securely injected `MELIOUS_API_KEY`.
4. Require the benchmark exit code to be zero. A timeout or incomplete sample set keeps the live gate closed.

## Verification and rollback

`python -W error::ResourceWarning -m pytest tests/test_gateway_readiness.py tests/test_gateway_billing_exhaustion.py tests/test_healthz_alias.py tests/test_app_main_health.py -q`

Tests exercise actual local HTTP handlers, billing-window expiry with a controlled monotonic clock, missing credentials, no lazy gateway construction, and secret-free snapshots. Fault injection in tests is not a production mock.

Rollback: revert the readiness feature commit. Added fields are additive; no database, route, or top-level HTTP status migration is involved.
