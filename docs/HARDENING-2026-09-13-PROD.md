# AccessDoc Production Hardening Receipt - 2026-09-13

Branch: harden/accessdoc-prod - base d09f7739edbb60d31c07380b4d1e6c05dc361366 (main)
Credentials: $GIT_AUTH_TOKEN and $MELIOUS_API_KEY via environment only; zero secrets in tracked files.

## Baseline vs hardened

| Gate | base d09f773 | hardened branch |
|---|---|---|
| unittest discover -s tests | 639 run, 0 fail, 0 err, 12 skip | 650 run, 0 fail, 0 err, 12 skip |
| scripts/concurrent_bench.py (100 workers x 2 rounds) | FAIL: 32 contract violations (oversize -> 422), p50 12711 / p95 18592 / p99 20612 ms, RSS 37.3/323.0 MB | PASS: 0 violations, 0 unexpected 5xx, 0 transport errors, p50 8416 / p95 12740 / p99 14603 ms, RSS 37.0/253.5 MB |
| Melious gateway (live, 3 calls/model) | n/a (no gateway layer) | glm-5.3 1370/1399/1399 ms; glm-5.3-flash 4225/4452/4452; qwen3.8-27b 3116/3182/3182; kimi-k3 4631/4919/4919; all 3/3 ok |
| 429-storm / outage probes | n/a | fallback to glm-5.3-flash PASS; fail-fast 234 ms PASS; static-KB last resort PASS |

## Failure modes remediated
1. Oversize body contract drift -> LimitExceeded => 413 INPUT_TOO_LARGE (app/main.py::_read).
2. Missing /healthz liveness alias on self-hosted daemon (app/main.py).
3. Gateway cascade deadlock -> app/gateway.py circuit breakers + pooled session + Retry-After-aware jittered backoff + ordered fallback + static KB.

## Reproduce
    python3 scripts/concurrent_bench.py <repo_root>
    MELIOUS_API_KEY=*** python3 scripts/gateway_bench.py <repo_root>
    python3 -m unittest discover -s tests
Raw JSON: docs/evidence/2026-09-13-prod/{bench_results.json,bench_base_vs_hardened.json,gateway_bench.json}
