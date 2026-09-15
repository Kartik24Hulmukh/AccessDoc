# Serverless /api/remediate evidence - 2026-09-15

Produced by PR #41 (harden/accessdoc-prod). Live calls against the Melious gateway with MELIOUS_API_KEY supplied from the environment only (never committed, never logged).

serverless_remediate_e2e.json
- 5 contract cases through api/handler.py (the Vercel adapter, not the self-hosted server): default chain, explicit model alias, unknown model, empty violations, missing credential.
- 20x concurrency burst on the dedicated remediation pool (8 slots, 30 s admission queue in this run; ships defaulting to 10 s).

Headline: 20/20 HTTP 200, 0 unexpected 5xx, 0 shed requests, 0 static-KB fallbacks, p50 12.4 s / p95 21.2 s / p99 21.3 s wall for a 3-rule plan under a 2.5x oversubscribed pool. Single request: 8.8 s (primary model, 1,177 tokens, 3,067-char plan); 10.8 s on the aliased 27B model.
