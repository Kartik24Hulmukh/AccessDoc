# Delivery, upload deadlines, and release-gate integrity

October 2026 launch continuation on `harden/accessdoc-v1-launch`. Final source candidate: `42758c9c0c0706dc263283e3adf74f93bd705594`. Earlier complete engineering/live receipts are scoped to `4270da84dc8f89a99b2e354a62c92543fe639edb` and explicitly distinguished below. Frozen baseline: `1f21edeb064e0d01b8932f707c80eedaa8c9f00f`. Evidence under `docs/evidence/delivery-hardening-2026-09-30/` includes failed reproductions, not only passing runs.

**Release decision: HOLD.** All hosted CI checks passed on repaired source `42758c9`; earlier failures and passes are recorded separately. The final four-model live gate failed; exact-preview functional verification and required human approvals remain incomplete. Engineering progress is not evidence of 100x capacity, traction, or 100 real-human evaluations.

## Delivery and implemented fixes

The preceding ten local hardening commits were pushed through authorized credentials, then the following nine atomic commits were also pushed to PR #95:

| Commit | Change | Reproduced failure / verification |
|---|---|---|
| `f931f20` | Strict, bounded CSV error translation | Oversized fields previously escaped as 500; malformed quotes were silently accepted. Field limits now return 413, malformed CSV 422, in both real-socket adapters before rendering. |
| `cbc20c0` | Shared absolute upload/drain deadline | Continuous small writes bypassed inactivity timeouts and held all generation slots. Incremental `read1` reads rearm remaining monotonic budget; normal expiry returns 408. Oversized input retains 413 even when draining expires. Socket settings are restored. |
| `8971726` | Complete test collection, exact-SHA smoke, and dependency audit | Release verifier now runs pytest, including function-based regressions. Smoke requires the complete SHA both before and after functionality, checks actual negative-response bodies, and runs the shipped bundle verifier. CI freezes dependencies before installing pinned audit tooling. |
| `f18c95d` | Portable RSS fallback regression | Actual Windows CI failed because the test tried patching a nonexistent POSIX `resource` module. Injected test interface covers the behavior on every platform; missing-resource graceful degradation is also tested. |
| `16efa29` | Protected-preview smoke support with credential confinement | Workflow accepts an exact preview origin; automation-bypass headers are restricted to verified project origins and redirects to another origin are rejected. No deployment protection was disabled. |
| `4270da8` | Fail on ignored exceptions and close fixtures | Seven unclosed JSON fixtures generated ignored `ResourceWarning` exceptions. Fixtures now close, and ignored exceptions, resource leaks, and unhandled test threads are fatal pytest failures. |
| `d3620af` | Bounded manual node counts and generic adapter validation | Superscript digits triggered raw Python conversion errors; huge decimal cells hit interpreter limits. Optional counts now accept only nonnegative integer/ASCII decimal values up to 5,000, check length before conversion, and never expose arbitrary parser exception details. |
| `446e172` | Council-driven gate integrity | Explicit bash preserves failing validator exits through `tee`; decoded JSON error keys are scanned as well as values. Regressions reproduce both false-positive gates. |
| `42758c9` | Typed truncated-body transport contract | Full-suite cancellation evidence caught a regression in the generic-error change. Dedicated safe transport exception preserves exact partial-body coverage without echoing parser errors. |

Release statuses are bound to the exact local commit and checked against the remote branch ref. A lagging PR-head API response initially attached a new local-verifier receipt to the older head; attribution was corrected explicitly (the old status is marked superseded/error, not left as a false pass). Historical local-only delivery notes in earlier receipts are superseded by this successful push. They remain historical records, not current access claims.

## Parallel AI release council

Three independent, read-only AI reviews covered architecture/SRE, adversarial gate integrity, and product/founder launch value. They are not human evaluators or independent release signatories. The red-team review identified three concrete gaps: masked validator exit status, exception text hidden in JSON keys, and Unicode manual node-count conversion leakage. New tests were frozen failing before changes (**17 failed, 5 passed, 7 subtests**); after remediation, the broader focused suite passed **39 tests and 42 subtests**. Findings, raw failures, and fixes are retained. No reviewer mutated repository code or called the provider.

All reviewers recommended HOLD. Product priorities remain authorized exact-target evidence, genuine ten-session practitioner handoff/second-use measurement, and named approval/claims clearance—not adding speculative frameworks. Their 401 protection descriptions came from earlier supplied context; fresh direct probes in this receipt observed 302 sign-in redirects. A completed hosted CI receipt here supersedes earlier running-CI uncertainty, but not the human or live-provider holds.

The first complete verifier after those council fixes failed one chaos-coverage test: making all `ValueError` messages generic also hid the transport-specific truncation evidence. This failure is retained. The body reader now raises a dedicated `TruncatedBodyError`; its fixed safe public message preserves the existing exact half-close contract, while arbitrary parser errors remain generic. No chaos assertion was weakened.

## Frozen baseline and measured results

Baseline suite before edits: **884 passed, 1 skipped, 159 subtests, 3 warnings**, 72.15 seconds. Earlier strict release verifier on `4270da8`: **10/10 local gates**, **900 passed, 1 skipped, 178 subtests, 3 intentional duplicate-ZIP warnings**, 81.58 seconds. Final repaired source `42758c9` passed **10/10 strict local gates: 906 tests, 1 deployed-target skip, 201 subtests, 3 intentional duplicate-ZIP warnings**, 75.61 seconds. Additional test coverage is not a latency improvement. The remaining skip needs a deployed target.

### Slow-upload reproduction: matched fixture, three samples per adapter

Two clients continuously wrote one byte every 20 ms. Inactivity timeout was 150 ms; configured absolute budget was 200 ms; capacity was two generation slots. Probe observation occurred at 350 ms while clients had **not** voluntarily stopped. These small-sample percentiles are descriptive order statistics, not an SLO; production's default absolute body budget remains 15 seconds.

| Adapter | Baseline probe status, 3/3 | After probe status, 3/3 | After slow-client results | Probe p50 / p95 / p99 before, ms | After, ms |
|---|---|---|---|---|---|
| Hosted handler | 503, all capacity occupied | 400, input validation reached | 6/6 HTTP 408 | 51.379 / 51.571 / 51.571 | 1.150 / 1.153 / 1.153 |
| Self-hosted handler | 503, all capacity occupied | 422, input validation reached | 6/6 HTTP 408 | 51.488 / 51.537 / 51.537 | 1.332 / 1.429 / 1.429 |

Different status classes mean the timing is **not** a successful-request speedup. The verified gain is capacity release despite ongoing malicious drip clients. Oversized drain behavior is separately covered by paired real-socket regressions.

### Local load, memory, and chaos

Eight workers, 100 requests: **100 HTTP 200**, one deterministic bundle digest; **163.33 requests/s**, p50/p95/p99 **47.3 / 66.6 / 71.2 ms**, max 79.5 ms. Idle RSS **35,196 KiB**, observed process-lifetime peak **45,032 KiB**, post-load RSS **45,032 KiB**. This final run followed full-suite completion on `42758c9`; the earlier `4270da8` run (165.51 requests/s, 47.0/65.1/66.3 ms, idle/peak/post-load 34,720/45,440/45,304 KiB) is retained separately. These are observations, not enforced memory ceilings.

The preceding source's loopback run measured 82.54 requests/s, p50/p95/p99 46.7/72.3/81.3 ms, idle/peak/post-load RSS 34,580/42,032/41,984 KiB while overlapping full-suite validation. The schedules differ; **no controlled throughput gain is claimed**.

**100 synthetic socket workflows, 40 disconnects** passed with zero captured unhandled thread exceptions, server errors, surviving new threads, or live server runner after shutdown. Recovery probes: `/healthz` 1.43 ms, `/readyz` 0.72 ms on `42758c9`. Earlier source recovery observations remain in their own receipt. Adversarial stress: **15 checks, zero failures**. These results do not establish 100 real people, global coroutine-leak absence, deployed 100x load capacity, or universally sub-200-ms recovery.

### Live Melious gate: failed final candidate

The canonical IDs were verified in the live provider catalog. Credentials stayed outside source, evidence, and PR text. Twelve bounded real calls were made per run, with existing token/wall-clock budgets unchanged.

| Model | Final successes | p50 / p95 / p99 ms, all attempts including failure |
|---|---|---|
| GLM-5.3 | 3/3 | 4675.77 / 4942.03 / 4942.03 |
| GLM-5.3 Flash | 3/3 | 6054.91 / 8008.00 / 8008.00 |
| Qwen 3.8 27B | 3/3 | 10836.25 / 11051.37 / 11051.37 |
| Kimi K3 | **2/3** | 21630.57 / 40026.15 / 40026.15 |

One Kimi attempt produced a timeout mapped to **HTTP 504 after 40,026.15 ms**. The gate exited **1**, **11/12** successful. The earlier `1f21ede` run passed 12/12, but does not override this final failure. No retry-until-green selection, widened budget, or static-answer substitution was used to claim four-model availability. Offline 429 failover, outage fail-fast (0.1 ms), and static-KB probes passed; they do not certify live outage latency or model availability. The provider/model gate remains failed.

### Dependency and hosted CI evidence

Local pinned `pip-audit 2.10.1` scanned a 24-package installed Python dependency snapshot: **zero known advisories**, exit 0. CycloneDX 1.4 SBOM contains 24 components. Scope excludes OS/container packages, frontend/transitive npm tooling, and independent security clearance.

Actual hosted CI on both `4270da8` and final repaired source `42758c9` passed Ubuntu tests (including browser self-audit, OpenACR validation, container build/smoke), macOS and Windows portability, lint, evidence, dependency security, GitGuardian, and Vercel preview checks. The earlier Windows failure, the council-fix intermediate failed local verifier, and final hosted success are all retained. Final repaired-source checks completed successfully on both push and pull-request runs. An evidence-only successor commit does not change tested application code; its checks must still be observed, not assumed. Vercel deployment success means deploy completed, not functional authorization or launch approval.

## Five-point premortem disposition

1. **Memory exhaustion:** native row streaming from the preceding hardening work remains; CSV field-limit exceptions now translate before rendering. Absolute body deadlines prevent tiny uploads occupying generation slots forever. Sustained hosted memory/100x load and arbitrary OCR ingestion are not certified.
2. **Worker deadlock / capacity starvation:** drip-client reproduction no longer holds every generation permit; real-socket pool recovery passes on both adapters. Existing epoch-scoped gateway admissions and shutdown checks remain. This is not proof about every external asynchronous worker lifecycle.
3. **OCR/parsing/provider timeouts:** strict CSV decoding and absolute reads replace cosmetic timeouts. General OCR is not an implemented product promise. Final Kimi live timeout remains unresolved; preserve the failed gate rather than claiming an application fix can ensure vendor availability.
4. **429/5xx cascades / spend:** bounded pooled gateway reads, token ceilings, generation-bound breakers, and injected outage probes remain covered. No arbitrary sleeps were added to production. Actual response generation takes seconds; sub-200-ms decision overhead must not be confused with complete live answers.
5. **False readiness / credential leakage / traction:** complete test collection, fatal ignored exceptions, full-SHA smoke, error-body assertions, advisory audit, and verified-origin bypass restrictions now guard release evidence. Named practitioner, accessibility, security, editorial, and legal approvals remain required; no adoption/revenue result is asserted.

## `repos.md` integrations and product scope

The supplied catalog was reviewed in preceding continuations. Existing **Playwright + axe-core** remains the selected integration for real scan → evidence bundle → shipped verifier and agency handoff. It closes the actual user workflow without replacing deterministic evidence generation with a cosmetic mock. The current fixes require native standard-library streaming, deadlines, resource ownership, and gate correctness; **no new catalog parser, OCR/RAG stack, connector, or agent framework** was added without a demonstrated functional gap. See `docs/HARDENING-REMEDIATION-HANDOFF-2026-09-29.md` and `examples/agency-handoff/README.md` for prior integration rationale. `pip-audit` is CI-only validation tooling, not a runtime feature.

## Exact-target and human blockers

Earlier preview `https://access-r54bu998p-atlas16.vercel.app` belongs to `4270da8`. Repaired-source preview `https://access-7skcw76j9-atlas16.vercel.app` belongs to `42758c9`; fresh `/`, `/healthz`, and `/readyz` probes again returned 302 sign-in redirects with zero functional checks. Direct probes of `/`, `/healthz`, `/readyz`, and `/api/version` returned **302 to vercel.com sign-in**. The same-origin smoke correctly refused that redirect, exited 1 in readiness, and ran **zero functional checks**. Earlier inspection reported protection as 401; the retained latest observation is 302. Neither establishes application behavior.

Repository Actions secret metadata contained no secrets. No Vercel automation bypass was available; protection was not disabled. Configure `VERCEL_AUTOMATION_BYPASS_SECRET` through the authorized secret manager/Actions UI, then dispatch the protected-preview workflow on this branch with the exact final SHA and preview origin. Never substitute the Git or model token for Vercel authorization. Rotate the credentials already disclosed in chat before production persistence.

Remain draft and **do not auto-merge** until the live model gate, exact-SHA deployed contract/rollback verification, and `docs/RELEASE_GATES.md` human tracks pass. Practitioner acceptance, second-use intent, independent accessibility review, security/contact ownership, public-copy review, and name/legal clearance cannot be invented by synthetic or AI evaluators.

## Reproduction

```bash
python -m pytest tests -q
python scripts/verify_release.py
python scripts/hardening_load.py --output load.json
python scripts/disconnect_chaos.py --output chaos.json
python scripts/stress_test.py
python scripts/gateway_bench.py --probes-only --output gateway-probes.json
# Live bounded provider gate: MELIOUS_API_KEY injected privately, never on argv.
python scripts/gateway_bench.py --output gateway-live.json
python docs/evidence/delivery-hardening-2026-09-30/upload_deadline_bench.py /path/to/checkout
```

Run upload measurement against separate baseline and candidate source checkouts; it uses only loopback sockets. Exact-preview smoke requires `PRODUCTION_URL`, `EXPECTED_VERSION`, and complete `TARGET_COMMIT`; the optional bypass is an environment secret. No schema migration was introduced. Reverting HTTP/CSV hardening would restore reproduced vulnerabilities and is not a launch strategy.
