# AccessDoc — launch hardening checkpoint (15 September 2026)

## Decision: NO-GO for the full launch definition of done

This is an incremental hardening PR, not a launch certification. Baseline `main` is `0e5bd1b` (merged #45, beta.7). The previously reported Vercel crash is resolved: `/`, `/healthz`, `/readyz` return 200 and report that exact commit. Existing main `production-smoke` is green. The older attachment's unconditional launch-ready conclusion is superseded by these measured qualifications.

## Baseline audit

- Clean clone, 24 remote branches; no open PRs at audit start. Older feature/fix branches exist; no evidence they are all current outstanding work.
- Product: axe JSON → tamper-evident PDF/HTML/OpenACR/optional SARIF/VPAT/EAA evidence bundles. This is not an arbitrary PDF/DOCX/OCR ingestion product. Do not promise unsupported file formats.
- Runtime: Python >=3.10, ReportLab >=4 and Requests >=2.32; dev pypdf 6.18.1, PyYAML, jsonschema; optional Playwright. Broad ranges are not a production lockfile. Fresh dependency audit resolved 14 packages with no known vulnerabilities; snapshot attached, not a supply-chain guarantee.
- Initial suite: 695 tests, no failures, 2 skips while browser prerequisites installed. Baseline ResourceWarnings were real HTTPError handle leaks, despite exit code zero. Playwright Chromium and axe-core were then installed.
- Branch protection requires strict `test`, `lint`, `accessdoc-evidence`. No protection was weakened. Production smoke remains a post-deploy gate, not proof from a green deployment status.
- Statement coverage percentage was not measured; test count is not coverage percentage.

## Five-point premortem

| Failure mode | Evidence / work delivered | Residual launch gate |
|---|---|---|
| Retry cascade exceeds budget and pins workers | Reproduced four calls after one-call token budget; retry after deadline; minimum completion allowance 64 despite 10 remaining; sub-second timeout rounded to 1s. Fixed per-retry checks, allowance clipping, nonnegative usage and timeout clamping. | Requests connect/read inactivity limits are not strict wall-clock cancellation. Provider-reported usage cannot bound unreported billable retries or input tokens. Introduce bounded cancellable I/O plus provider/tokenizer-backed accounting before asserting hard guarantees. |
| Malformed upstream success crashes remediation | Reproduced TypeError for non-string multipart text and AttributeError for list-valued usage. Normalize these fields and close responses. | Bound decoded upstream response size and verify adversarial slow-drip behavior in isolated workers. |
| Memory retention or parser overload after hostile inputs | 100 workers / 200 balanced JSON requests: no transport errors, no contract violations, no unexpected 5xx. Fresh health and bundle requests succeed after load. | RSS 42.0 → peak 318.5 → post-run 191.6 MiB; did NOT return to startup floor. Need multi-round RSS plateau and deployed soak, not forced allocator trimming. |
| False-green measurement hides recovery/runtime failure | Seeded balanced benchmark, explicit recovery probes, retry accounting, truthful per-model sample counts. Fixed orphaned cold-start runner and added import/execution regression. Production health test now opt-in executable instead of unconditional skip. | 100 workers is not a measured 100x production baseline; kernel/process limits and deployed provider quotas must be tested. |
| Public product appears healthy while AI disabled | Production `gateway.configured=false`; `/limits` has two concurrent requests/process, no API key required, and rate limit null. | Owner must configure rotated Melious secret in deployment, validate authenticated remediation, enforce WAF/provider quotas, and set OTel collector/alerts. No deployment administration credential was supplied. |

## Failure logs resolved

New gateway regression suite on baseline: **5 failures + 2 errors / 7 tests**. These are not speculative risks. Focused gateway tests passed after one remediation loop. Added response-close, expired-call, and 100-worker shared-gateway 429/503/timeout → static fallback → recovered provider tests.

Cold-start stress initially failed importing removed `generate_bundle`, then failed reading obsolete `submitted_text_sha256`. Migrated to `build_artifacts` + `build_bundle`, current receipt identity/count assertions and `validate_bundle`; one-request regression prevents recurrence. Two loops used for this component, below five. Test-handle hygiene required one pass.

## Measured results

### HTTP ingestion: local self-hosted adapter

| Metric | Baseline original runner | Current deterministic runner | Delta |
|---|---:|---:|---:|
| Requests / workers | 200 / 100 | 200 / 100 | — |
| P50 ms | 10574.70 | 12869.89 | +21.7% |
| P95 ms | 18525.08 | 23164.06 | +25.0% |
| P99 ms | 19268.13 | 25025.72 | +29.9% |
| Throughput req/s | 7.65 | 6.26 | -18.2% |
| Initial / peak RSS MiB | 42.0 / 337.5 | 42.0 / 318.5 | peak -5.6% |
| Post-run RSS MiB | not measured | 191.6 | no floor-return claim |
| Unexpected 5xx / contract / transport errors | 0 / 0 / 0 | 0 / 0 / 0 | unchanged |
| Explicit post-load health / bundle | not measured | 200 / 200 | verified |

CPU shared with test runners and input mix changed (baseline unseeded vs balanced seeded), so these are observations, **not comparable performance improvements or regressions**. Current statuses: 134×200, 33×413, 33×422; admission retries zero. Supports oversized/corrupt/hostile axe JSON only.

### Live Melious: current code, three independent samples/model

| Model | Success | P50 ms | P95 / P99 ms | Outcome |
|---|---:|---:|---:|---|
| GLM-5.3 | 3/3 | 4504.24 | 4715.20 | healthy in sample |
| GLM-5.3 Flash | 3/3 | 12370.79 | 17273.99 | initial earlier probe timed out; variable provider |
| Qwen 3.8 27B | 3/3 | 10802.89 | 11009.60 | healthy in sample |
| Kimi K3 | 2/3 | 28149.70 | 30031.42 | one 504 at 30s; not fully green |

Percentiles include failures and with N=3 P95/P99 are just the observed maximum, not tail confidence. Shared session/breaker is reused per model. 429 storm fallback PASS; full 5xx outage fail-fast 218.6ms PASS; static KB PASS. Local synthetic concurrency test also recovers after 200 outage calls across 100 workers. This is not a live 100-concurrent paid gateway benchmark.

### Other validation

- Adversarial stress: 15/15 (XSS, YAML injection, 5,000 findings, tamper, determinism).
- Boundary load: 9/9 contracts; 100 requests / 8 workers all 200; 178.66 req/s, deterministic digest. Loopback only.
- Repaired in-process bundle stress: 200 requests / 100 workers, 0 errors; P50/P95/P99 123.89/340.21/389.54ms; 111.59 req/s; peak RSS high-water counters 36,612 → 69,636 KiB. Ten subprocess cold starts produced identical hashes. These are not deployed serverless cold starts.
- Release verifier at the previous test snapshot: 705 tests, no failures/skips; all verifier gates PASS. Final suite includes one additional stress-entrypoint test; final result recorded in PR before checkpoint.
- Config/version/BOM lint PASS, beta.7 unchanged. No tag was moved or minted.

## Startup product / traction launch gates (proposed, not achieved)

1. **Founder:** select one paid design-partner workflow: accessibility agencies producing buyer-verifiable procurement evidence. Ship the already-working JSON → evidence → independent verifier loop, not an unbuilt OCR roadmap.
2. **Activation:** instrument opt-in events `sample_loaded`, `bundle_generated`, `bundle_verified`, `remediation_used`; never log source documents or prompts. Track median time-to-first-verified-bundle, not visits alone.
3. **Value validation:** before September 16, obtain three design-partner sessions completing a real evidence handoff and independently verify their bundles. Record time saved and willingness to pay. This run did not contact users or fabricate traction.
4. **Launch cut:** September 16 limited cohort only after deployment secrets/quotas and functional remediation pass. September 17 expand only after a sustained representative soak, RSS plateau, explicit rollback rehearsal and monitored SLO pass. Otherwise remain bounded beta.
5. **Ownership:** Founder owns demand baseline and activation; SRE owns deployed soak/alerts/rollback; Red Team owns malformed/slow-drip provider and parser adversarial fixtures. Replace these roles with named operators before cutover.

## Merge and security policy

PR #46 is on `harden/accessdoc-prod`; no unrelated branches or main edited directly. Merge only after all required checks and validation gates pass. Because Kimi live sampling is not entirely green, production AI is disabled, and deployed 100x proof is absent, **full-release merge is withheld**. This checkpoint does not authorize silently downgrading the definition of done. Operators may separately review an incremental fix merge under their normal policy.

Credentials were used only for authorized GitHub operations and bounded Melious probes, never committed. Both credentials appeared in the task conversation and must be rotated. Production secret installation needs deployment-owner access. No rollback or credential revocation was performed without deployment credentials.

Raw measured evidence is in `docs/launch-evidence-2026-09-15/`. Latest remote checks/PR state are authoritative; historical attachment numbers are not current results.
