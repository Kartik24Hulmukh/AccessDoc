# Local stress testing

These scripts create bounded loopback servers where needed. They do not stress a public endpoint.

```bash
python scripts/stress_test.py
python scripts/hardening_load.py --output hardening-load.json
python scripts/hosted_soak.py --seconds 5 --workers 8 --output hosted-soak.json
python scripts/disconnect_chaos.py --output disconnect-chaos.json
python scripts/gateway_bench.py --probes-only --output gateway-probes.json
```

`stress_test.py` is an in-process malformed-input/scale/determinism check; it does not implement `--workers` or `--requests`. `hardening_load.py` measures the serverless adapter with 8 workers/100 requests. `hosted_soak.py` tests both adapters and records valid successful bundles separately from explicit 503 refusals. `disconnect_chaos.py` checks interrupted-body recovery. Gateway probes are synthetic/offline, not real-provider acceptance.

Admitted bundles must verify; overload refusals must be explicit. HTTP 500, unexpected transport resets, report cross-contamination, unbounded counters, failed TTL reclamation or inability to recover after a slow client remain blockers. Browser cancellation stops browser waiting/retries; it does not promise accepted-job server cancellation. A pilot API key is not a multi-tenant identity model.

The supported ingestion boundary is supplied axe-core JSON plus structured manual findings. Arbitrary PDF/OCR/multi-format ingestion is not implemented and must not be advertised.

Local measurements are machine/workload-specific. A 1-to-100 offered-concurrency burst or finding-instance expansion is not a 100-fold successful-throughput result. Refusals remain in the denominator. Production, sustained-load, real-provider and consenting human/assistive-technology gates require separate evidence.
